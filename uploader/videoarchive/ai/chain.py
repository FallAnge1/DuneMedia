"""Цепочка ИИ-провайдеров (раздел 7 ТЗ).

Порядок задаётся в настройках. При лимите (429), таймауте, ошибке или невалидном JSON
программа сразу переходит к следующему провайдеру. Провайдер, упёршийся в лимит,
«остывает» до сброса лимита — время запоминается и переживает перезапуск.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from videoarchive.ai.normalize import InvalidAnswer, extract_json, normalize_answer
from videoarchive.ai.providers import Provider, ProviderError, RateLimited, build_provider
from videoarchive.core.config import Config, write_json_atomic
from videoarchive.core.paths import data_dir, find_tool
from videoarchive.core.pipeline import Suggestion

if TYPE_CHECKING:
    from videoarchive.core.api import ApiClient

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Ты помогаешь вести каталог видеоархива. Тебе показывают кадры из одного видео. "
    "Отвечай ТОЛЬКО JSON-объектом без пояснений и без markdown."
)

PROMPT_TEMPLATE = """Кадры взяты из разных моментов одного видео (по порядку).
Имя файла: {file_name}

Верни JSON строго такого вида:
{{"title": "...", "description": "...", "tags": ["...", "..."]}}

Правила:
- title — короткое название на русском, 2–6 слов, без кавычек и без слова «видео».
- description — 1–2 предложения на русском: что происходит в кадре.
- tags — от 5 до 12 тегов на русском, в нижнем регистре, без #, по 1–3 слова:
  объекты, место, время суток, погода, тип съёмки (дрон, таймлапс, слоумо, крупный план, статика, ручная камера),
  настроение, преобладающие цвета.
- Если подходит тег из списка существующих — используй его в точности, а не синоним.
{existing_block}"""

MAX_EXISTING_TAGS = 200


class AIError(Exception):
    pass


def build_prompt(file_name: str, existing: list[str]) -> str:
    block = ""
    if existing:
        block = "\nСуществующие теги архива (самые частые): " + ", ".join(existing[:MAX_EXISTING_TAGS])
    return PROMPT_TEMPLATE.format(file_name=file_name, existing_block=block)


def make_collage(frames: list[Path], out: Path) -> Path:
    """Кадры в одну картинку 3×2 — для провайдеров с ограничением числа картинок."""
    if out.exists():
        return out
    tool = find_tool("ffmpeg")
    if not tool or len(frames) == 1:
        return frames[0]
    pattern_dir = out.parent / "collage_src"
    pattern_dir.mkdir(exist_ok=True)
    for i, f in enumerate(frames[:6]):
        target = pattern_dir / f"{i:02d}.jpg"
        if not target.exists():
            target.write_bytes(f.read_bytes())
    kwargs: dict = {"capture_output": True, "check": False}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    res = subprocess.run(
        [tool, "-hide_banner", "-loglevel", "error", "-y", "-start_number", "0", "-i", str(pattern_dir / "%02d.jpg"),
         "-vf", "scale=400:-2,tile=3x2:padding=4", "-frames:v", "1", "-q:v", "4", str(out)],
        **kwargs,
    )
    if res.returncode != 0 or not out.exists():
        log.warning("Коллаж не собран: %s", res.stderr.decode("utf-8", "replace")[-300:])
        return frames[0]
    return out


class Cooldowns:
    """Когда провайдер снова доступен (unix-время). Хранится в ai_cooldowns.json."""

    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "ai_cooldowns.json"
        self.lock = threading.Lock()
        try:
            self.until: dict[str, float] = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            self.until = {}

    def blocked(self, provider_id: str) -> float:
        """Сколько секунд ещё ждать (0 — можно)."""
        return max(0.0, self.until.get(provider_id, 0) - time.time())

    def block(self, provider_id: str, seconds: float) -> None:
        with self.lock:
            self.until[provider_id] = time.time() + seconds
            try:
                write_json_atomic(self.path, self.until)
            except OSError:
                pass


class RateLimiter:
    """Не чаще N запросов в минуту к одному провайдеру — чтобы не упираться в минутные лимиты при массовой загрузке."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.next_slot: dict[str, float] = {}

    def wait(self, provider_id: str, rpm: int, max_wait: float = 20) -> bool:
        """Ждёт своей очереди. False — ждать слишком долго, лучше взять другого провайдера."""
        interval = 60 / max(rpm, 1)
        with self.lock:
            now = time.monotonic()
            slot = max(now, self.next_slot.get(provider_id, 0))
            if slot - now > max_wait:
                return False
            self.next_slot[provider_id] = slot + interval
        delay = slot - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        return True


class AIChain:
    def __init__(self, providers: list[Provider], cooldowns: Cooldowns | None = None, rpm_override: int | None = None):
        self.providers = providers
        self.cooldowns = cooldowns or Cooldowns()
        self.limiter = RateLimiter()
        self.rpm_override = rpm_override

    @classmethod
    def from_config(cls, config: Config, api: "ApiClient | None" = None) -> "AIChain | None":
        providers = [p for p in (build_provider(c, api) for c in config.ai_providers) if p and p.configured]
        if not providers:
            return None
        return cls(providers, rpm_override=config.ai_requests_per_minute or None)

    def status(self) -> list[tuple[str, str]]:
        out = []
        for p in self.providers:
            left = self.cooldowns.blocked(p.id)
            out.append((p.title, f"остывает ещё {int(left // 60)} мин" if left else "готов"))
        return out

    def suggest(self, frames: list[Path], file_name: str, existing_tags: list[str]) -> Suggestion:
        if not frames:
            raise AIError("Нет кадров для ИИ")
        prompt = build_prompt(file_name, existing_tags)
        collage: Path | None = None
        failures: list[str] = []

        for p in self.providers:
            left = self.cooldowns.blocked(p.id)
            if left:
                failures.append(f"{p.title}: лимит, ещё {max(1, int(left // 60))} мин")
                continue
            rpm = min(p.default_rpm, self.rpm_override) if self.rpm_override else p.default_rpm
            if not self.limiter.wait(p.id, rpm):
                failures.append(f"{p.title}: очередь запросов")
                continue
            images = frames
            if p.collage:
                collage = collage or make_collage(frames, frames[0].parent / "ai_collage.jpg")
                images = [collage]
            started = time.monotonic()
            try:
                answer = p.ask(images, prompt, SYSTEM_PROMPT)
                title, description, tags = normalize_answer(extract_json(answer.text), existing_tags)
            except RateLimited as err:
                self.cooldowns.block(p.id, err.retry_after)
                log.warning("ИИ %s: %s, остывает %.0f с", p.id, err, err.retry_after)
                failures.append(f"{p.title}: {err}")
                continue
            except (ProviderError, InvalidAnswer) as err:
                log.warning("ИИ %s: %s", p.id, err)
                failures.append(f"{p.title}: {err}")
                continue
            except Exception as err:  # noqa: BLE001
                log.exception("ИИ %s", p.id)
                failures.append(f"{p.title}: {err}")
                continue
            log.info("ИИ %s/%s ответил за %.1f с: %s", p.id, answer.model, time.monotonic() - started, tags)
            return Suggestion(title=title, description=description, tags=tags, provider=p.title, model=answer.model)

        raise AIError("Ни один ИИ-провайдер не ответил. " + "; ".join(failures))
