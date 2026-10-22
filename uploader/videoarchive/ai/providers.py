"""Бесплатные провайдеры ИИ со зрением. Все получают кадры-картинки, а не видео.

Модели не захардкожены: берутся из настроек, а если там пусто или модель пропала —
программа спрашивает у провайдера список доступных моделей (discover_models).
"""

from __future__ import annotations

import base64
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from videoarchive.core.config import AIProviderConfig

if TYPE_CHECKING:
    from videoarchive.core.api import ApiClient

log = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(90, connect=15)


class ProviderError(Exception):
    """Провайдер не справился — переходим к следующему."""


class RateLimited(ProviderError):
    """Лимит исчерпан: провайдер «остывает» до сброса."""

    def __init__(self, message: str, retry_after: float):
        super().__init__(message)
        self.retry_after = retry_after


class ModelUnavailable(ProviderError):
    """Модели нет или её отключили — пробуем следующую модель того же провайдера."""


@dataclass
class Answer:
    text: str
    model: str


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def seconds_until_utc_midnight() -> float:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    return (tomorrow - now).total_seconds()


def parse_retry_after(res: httpx.Response, default: float = 60) -> float:
    for header in ("retry-after", "x-ratelimit-reset-requests", "x-ratelimit-reset"):
        value = res.headers.get(header)
        if not value:
            continue
        try:
            return float(value)
        except ValueError:
            m = re.match(r"(?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?$", value)  # Groq: "2m59.56s"
            if m and any(m.groups()):
                h, mi, s = (float(x or 0) for x in m.groups())
                return h * 3600 + mi * 60 + s
            if value.isdigit() and int(value) > 1e12:  # миллисекунды unix
                return max(int(value) / 1000 - time.time(), 1)
    return default


def short_error(res: httpx.Response) -> str:
    try:
        data = res.json()
        err = data.get("error", data)
        msg = err.get("message") if isinstance(err, dict) else str(err)
    except ValueError:
        msg = res.text
    return f"HTTP {res.status_code}: {(msg or '')[:200]}"


class Provider:
    id = ""
    title = ""
    needs_key = True
    collage = False  # отправлять один коллаж вместо отдельных кадров
    default_rpm = 20  # запросов в минуту (ограничение на нашей стороне)

    def __init__(self, cfg: AIProviderConfig, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self.http = httpx.Client(timeout=TIMEOUT, transport=transport)
        self._discovered: tuple[float, list[str]] | None = None

    @property
    def configured(self) -> bool:
        return self.cfg.enabled and (bool(self.cfg.api_key) or not self.needs_key)

    def models(self) -> list[str]:
        models = list(self.cfg.models)
        if not models:
            try:
                models = self.discover_models()[:4]
            except ProviderError as err:
                log.warning("%s: не удалось получить список моделей: %s", self.id, err)
        return models

    def discover_models(self) -> list[str]:
        """Актуальные vision-модели у провайдера (кэш на 6 часов)."""
        if self._discovered and time.time() - self._discovered[0] < 6 * 3600:
            return self._discovered[1]
        found = self._discover()
        self._discovered = (time.time(), found)
        return found

    def _discover(self) -> list[str]:
        return []

    def ask(self, images: list[Path], prompt: str, system: str) -> Answer:
        """Пробует модели по очереди; лимит и сетевые ошибки поднимаются выше."""
        models = self.models()
        if not models:
            raise ProviderError("не задано ни одной модели")
        last: Exception | None = None
        for model in models:
            try:
                return self.call(model, images, prompt, system)
            except ModelUnavailable as err:
                log.info("%s/%s недоступна: %s", self.id, model, err)
                last = err
        raise ProviderError(f"ни одна модель не доступна ({last})")

    def call(self, model: str, images: list[Path], prompt: str, system: str) -> Answer:
        raise NotImplementedError

    def check(self) -> str:
        """Проверка из настроек: ключ работает, какие модели доступны."""
        found = self.discover_models()
        configured = self.cfg.models
        if not found:
            return "связь есть"
        missing = [m for m in configured if m not in found]
        text = f"доступно vision-моделей: {len(found)}"
        if missing:
            text += f"; нет у провайдера: {', '.join(missing)}"
        if not configured:
            text += f"; будут использованы: {', '.join(found[:3])}"
        return text

    # ---- общий разбор ответов ----

    def _raise_for(self, res: httpx.Response, model: str) -> None:
        if res.status_code == 429:
            body = res.text.lower()
            daily = any(w in body for w in ("per day", "daily", "rpd", "quota"))
            retry = parse_retry_after(res, seconds_until_utc_midnight() if daily else 60)
            raise RateLimited(f"лимит ({short_error(res)})", retry)
        if res.status_code in (400, 401, 403) and re.search(r"api[ _-]?key|unauthori[sz]ed|invalid.*key", res.text, re.I):
            raise ProviderError("ключ не принят — проверьте его в настройках")
        if res.status_code in (404,) or (res.status_code == 400 and re.search(r"model|decommission|not found|not exist|does not support image", res.text, re.I)):
            raise ModelUnavailable(short_error(res))
        if res.status_code in (401, 403):
            raise ProviderError("ключ не принят")
        if res.status_code >= 400:
            raise ProviderError(short_error(res))

    def _post(self, url: str, **kw) -> httpx.Response:
        try:
            return self.http.post(url, **kw)
        except httpx.TimeoutException as err:
            raise ProviderError("таймаут") from err
        except httpx.TransportError as err:
            raise ProviderError(f"нет связи ({err.__class__.__name__})") from err

    def _get(self, url: str, **kw) -> httpx.Response:
        try:
            return self.http.get(url, **kw)
        except httpx.TransportError as err:
            raise ProviderError(f"нет связи ({err.__class__.__name__})") from err


def openai_messages(images: list[Path], prompt: str, system: str) -> list[dict]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": [{"type": "text", "text": prompt}] + [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64(p)}"}} for p in images
        ]},
    ]


def openai_text(data: dict) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as err:
        raise ProviderError("пустой ответ") from err
    if isinstance(content, list):  # некоторые модели возвращают части
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


# ---------------------------------------------------------------------------


class Groq(Provider):
    id, title = "groq", "Groq"
    collage = True  # у Groq ограничение 3–5 картинок и 2048 токенов на каждую — шлём один коллаж
    default_rpm = 25
    URL = "https://api.groq.com/openai/v1"
    VISION_HINTS = ("vision", "scout", "maverick", "-vl", "vl-", "qwen3.6", "qwen3.8", "gemma-3", "gemma3", "llava")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.cfg.api_key}"}

    def call(self, model: str, images: list[Path], prompt: str, system: str) -> Answer:
        res = self._post(f"{self.URL}/chat/completions", headers=self._headers(), json={
            "model": model, "messages": openai_messages(images, prompt, system), "temperature": 0.2, "max_completion_tokens": 700,
        })
        self._raise_for(res, model)
        return Answer(openai_text(res.json()), model)

    def _discover(self) -> list[str]:
        res = self._get(f"{self.URL}/models", headers=self._headers())
        self._raise_for(res, "")
        ids = [m["id"] for m in res.json().get("data", []) if m.get("active", True)]
        return [i for i in ids if any(h in i.lower() for h in self.VISION_HINTS)]


class OpenRouter(Provider):
    id, title = "openrouter", "OpenRouter"
    default_rpm = 15  # бесплатные модели: до 20 запросов в минуту
    URL = "https://openrouter.ai/api/v1"
    ROUTER = "openrouter/free"  # встроенный роутер бесплатных моделей, сам выбирает модель с картинками

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.cfg.api_key}", "HTTP-Referer": "https://github.com/FallAnge1/DuneMedia",
                "X-Title": "VideoArchive Uploader"}

    def models(self) -> list[str]:
        models = super().models()
        if not self.cfg.models:
            models = models[:3] + [self.ROUTER]
        return models

    def ask(self, images: list[Path], prompt: str, system: str) -> Answer:
        # OpenRouter сам перебирает модели из массива models (до 3) — один запрос вместо нескольких.
        models = self.models()
        if not models:
            raise ProviderError("не задано ни одной модели")
        for i in range(0, len(models), 3):
            batch = models[i : i + 3]
            res = self._post(f"{self.URL}/chat/completions", headers=self._headers(), json={
                "model": batch[0], "models": batch, "messages": openai_messages(images, prompt, system),
                "temperature": 0.2, "max_tokens": 700,
            })
            try:
                self._raise_for(res, batch[0])
            except ModelUnavailable:
                continue
            data = res.json()
            if "error" in data and "choices" not in data:
                raise ProviderError(str(data["error"])[:200])
            return Answer(openai_text(data), data.get("model") or batch[0])
        raise ProviderError("ни одна модель не доступна")

    def _discover(self) -> list[str]:
        res = self._get(f"{self.URL}/models")
        self._raise_for(res, "")
        found = []
        for m in res.json().get("data", []):
            pricing = m.get("pricing") or {}
            free = m["id"].endswith(":free") or (str(pricing.get("prompt")) in ("0", "0.0") and str(pricing.get("completion")) in ("0", "0.0"))
            inputs = (m.get("architecture") or {}).get("input_modalities") or []
            if free and "image" in inputs and m["id"] != self.ROUTER:
                found.append((m.get("context_length") or 0, m["id"]))
        return [mid for _, mid in sorted(found, reverse=True)]


class WorkersAI(Provider):
    """Cloudflare Workers AI через наш сайт (POST /api/ai/tag): ключ не нужен."""

    id, title = "workers_ai", "Cloudflare Workers AI"
    needs_key = False
    collage = True  # часть моделей Workers AI принимает только одну картинку
    default_rpm = 30

    def __init__(self, cfg: AIProviderConfig, api: "ApiClient | None", transport: httpx.BaseTransport | None = None):
        super().__init__(cfg, transport)
        self.api = api

    @property
    def configured(self) -> bool:
        return self.cfg.enabled and self.api is not None

    def models(self) -> list[str]:
        return list(self.cfg.models) or [""]  # "" — модель по умолчанию на сайте

    def call(self, model: str, images: list[Path], prompt: str, system: str) -> Answer:
        from videoarchive.core.api import ApiError

        assert self.api
        payload: dict = {"images": [b64(p) for p in images], "prompt": prompt, "system": system, "max_tokens": 700}
        if model:
            payload["model"] = model
        try:
            data = self.api.ai_tag(payload)
        except ApiError as err:
            if err.status == 429:
                raise RateLimited("дневной лимит нейронов", seconds_until_utc_midnight()) from err
            if err.status == 0:
                raise ProviderError("нет связи с сайтом") from err
            if "модел" in str(err).lower() or "model" in str(err.details).lower():
                raise ModelUnavailable(str(err)) from err
            raise ProviderError(str(err)) from err
        return Answer(data.get("text") or "", data.get("model") or model)

    def check(self) -> str:
        return "работает через сайт" if self.api else "сайт не настроен"


class Gemini(Provider):
    id, title = "gemini", "Google Gemini"
    default_rpm = 8
    URL = "https://generativelanguage.googleapis.com/v1beta"

    def call(self, model: str, images: list[Path], prompt: str, system: str) -> Answer:
        name = model if model.startswith("models/") else f"models/{model}"
        res = self._post(f"{self.URL}/{name}:generateContent", headers={"x-goog-api-key": self.cfg.api_key}, json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}] + [
                {"inline_data": {"mime_type": "image/jpeg", "data": b64(p)}} for p in images
            ]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 800, "responseMimeType": "application/json"},
        })
        if res.status_code == 429:
            retry = 60.0
            m = re.search(r'"retryDelay":\s*"(\d+)s"', res.text)
            if m:
                retry = float(m.group(1))
            if "PerDay" in res.text or "per day" in res.text.lower():
                retry = max(retry, seconds_until_utc_midnight() / 3)  # дневная квота Gemini сбрасывается по тихоокеанскому времени
            raise RateLimited(f"лимит ({short_error(res)})", retry)
        self._raise_for(res, model)
        data = res.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError) as err:
            reason = (data.get("promptFeedback") or {}).get("blockReason") or "пустой ответ"
            raise ProviderError(f"ответа нет: {reason}") from err
        return Answer("".join(p.get("text", "") for p in parts), model)

    def _discover(self) -> list[str]:
        res = self._get(f"{self.URL}/models", headers={"x-goog-api-key": self.cfg.api_key}, params={"pageSize": 200})
        self._raise_for(res, "")
        found = []
        for m in res.json().get("models", []):
            name = m["name"].removeprefix("models/")
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            if "flash" in name and not re.search(r"image|tts|audio|live|embedding|thinking-exp", name):
                found.append(name)
        # «-latest»-алиасы и более новые версии — вперёд.
        return sorted(found, key=lambda n: ("latest" not in n, "lite" in n, n), reverse=False)


class Ollama(Provider):
    id, title = "ollama", "Ollama"
    needs_key = False
    default_rpm = 1000
    VISION_HINTS = ("vl", "llava", "gemma3", "vision", "minicpm-v", "moondream", "bakllava", "granite3.2-vision", "mistral-small3")

    def __init__(self, cfg: AIProviderConfig, transport: httpx.BaseTransport | None = None):
        super().__init__(cfg, transport)
        self.http = httpx.Client(timeout=httpx.Timeout(300, connect=5), transport=transport)

    @property
    def base(self) -> str:
        return (self.cfg.base_url or "http://localhost:11434").rstrip("/")

    def models(self) -> list[str]:
        try:
            installed = self.discover_models()
        except ProviderError:
            installed = []
        configured = [m for m in self.cfg.models if not installed or m in installed or m.split(":")[0] in {i.split(":")[0] for i in installed}]
        return configured or installed[:2]

    def call(self, model: str, images: list[Path], prompt: str, system: str) -> Answer:
        res = self._post(f"{self.base}/api/chat", json={
            "model": model, "stream": False, "format": "json", "options": {"temperature": 0.2},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt, "images": [b64(p) for p in images]}],
        })
        if res.status_code == 404:
            raise ModelUnavailable(f"модель {model} не установлена (ollama pull {model})")
        self._raise_for(res, model)
        return Answer((res.json().get("message") or {}).get("content", ""), model)

    def _discover(self) -> list[str]:
        try:
            res = self.http.get(f"{self.base}/api/tags", timeout=5)
        except httpx.TransportError as err:
            raise ProviderError("Ollama не запущена") from err
        self._raise_for(res, "")
        names = [m["name"] for m in res.json().get("models", [])]
        return [n for n in names if any(h in n.lower() for h in self.VISION_HINTS)]

    def check(self) -> str:
        found = self.discover_models()
        return f"установлены vision-модели: {', '.join(found)}" if found else "Ollama запущена, но vision-моделей нет (ollama pull qwen2.5vl:7b)"


def build_provider(cfg: AIProviderConfig, api: "ApiClient | None" = None, transport: httpx.BaseTransport | None = None) -> Provider | None:
    if cfg.id == "groq":
        return Groq(cfg, transport)
    if cfg.id == "openrouter":
        return OpenRouter(cfg, transport)
    if cfg.id == "workers_ai":
        return WorkersAI(cfg, api, transport)
    if cfg.id == "gemini":
        return Gemini(cfg, transport)
    if cfg.id == "ollama":
        return Ollama(cfg, transport)
    return None
