"""Обработка одного файла (раздел 6.4 ТЗ).

Подготовка: ffprobe → хеш и дубликаты → превью → постер и миниатюра → кадры для ИИ → ИИ-теги.
У фото нет превью-ролика: постер — уменьшенная копия снимка, ИИ получает одну картинку.
Загрузка:   Telegram → превью и постер на сайт → запись на сайте.

Каждый шаг сохраняет результат в очереди. Если программа упала или пропала сеть, повтор
продолжит с того же места и не отправит видео в Telegram второй раз.
"""

from __future__ import annotations

import logging
import secrets
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from videoarchive.core import media
from videoarchive.core.api import ApiClient, ApiError
from videoarchive.core.media import MediaError, VideoInfo
from videoarchive.core.paths import work_dir
from videoarchive.core.queue import DONE, ERROR, PREPARING, QUEUED, READY, UPLOADING, QueueItem, QueueStore
from videoarchive.core.telegram import FloodWait, TelegramConnectionError, TelegramError, TelegramLike, UploadCancelled, wait_flood
from videoarchive.core.textutil import CAPTION_LIMIT, CAPTION_LIMIT_PREMIUM, TG_LIMIT, build_caption, file_hash, normalize_tags

log = logging.getLogger(__name__)


class PipelineError(Exception):
    """Ошибка шага с понятным сообщением для пользователя."""


@dataclass
class Suggestion:
    title: str
    description: str
    tags: list[str]
    provider: str
    model: str


class Tagger(Protocol):
    def suggest(self, frames: list[Path], file_name: str, existing_tags: list[str]) -> Suggestion: ...


Notify = Callable[[str], None]


def suggestion_fields(item: QueueItem, title: bool = True, description: bool = True, tags: bool = True) -> dict:
    """Поля, которые надо записать в элемент, чтобы применить предложение ИИ.

    Название и описание заменяются, теги добавляются к уже стоящим.
    """
    s = item.ai_suggestion or {}
    fields: dict[str, object] = {}
    if title and s.get("title"):
        fields["title"] = s["title"]
    if description and s.get("description"):
        fields["description"] = s["description"]
    if tags and s.get("tags"):
        fields["tags"] = normalize_tags(item.tags + list(s["tags"]))
    return fields


def format_size(n: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit in ("Б", "КБ") else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return str(n)


class Pipeline:
    def __init__(
        self,
        store: QueueStore,
        *,
        api: ApiClient | None,
        telegram: TelegramLike | None,
        channel: str,
        tagger: Tagger | None = None,
        ai_auto: bool = False,
        ai_auto_apply: bool = False,
        existing_tags: Callable[[], list[str]] = lambda: [],
        notify: Notify = lambda _id: None,
        telegram_retries: int = 3,
    ):
        self.store = store
        self.api = api
        self.telegram = telegram
        self.channel = channel
        self.tagger = tagger
        self.ai_auto = ai_auto
        self.ai_auto_apply = ai_auto_apply
        self.existing_tags = existing_tags
        self.notify = notify
        self.telegram_retries = telegram_retries

    # ------------------------------------------------------------------ helpers

    def _set(self, item: QueueItem, save: bool = True, **fields: object) -> None:
        self.store.update(item.id, save=save, **fields)
        self.notify(item.id)

    def file_limit(self) -> int:
        if self.telegram:
            try:
                return self.telegram.account().file_limit
            except TelegramError:
                pass
        return TG_LIMIT

    def caption_limit(self) -> int:
        if self.telegram:
            try:
                return CAPTION_LIMIT_PREMIUM if self.telegram.account().premium else CAPTION_LIMIT
            except TelegramError:
                pass
        return CAPTION_LIMIT

    def check_size(self, item: QueueItem) -> None:
        limit = self.file_limit()
        if item.file_size > limit:
            premium_hint = "" if limit > TG_LIMIT else " С Telegram Premium лимит 4 ГБ."
            raise PipelineError(
                f"Файл {format_size(item.file_size)} больше лимита Telegram {format_size(limit)}.{premium_hint} "
                "Сожмите видео или разделите его на части."
            )

    # ------------------------------------------------------------------ подготовка

    def prepare(self, item_id: str, cancel: threading.Event | None = None) -> None:
        item = self.store.get(item_id)
        if not item:
            return
        try:
            self._prepare(item, cancel)
        except (MediaError, PipelineError) as err:
            log.warning("Подготовка %s: %s", item.file_name, err)
            self._set(item, status=ERROR, upload_requested=False, stage="", error=str(err))
        except UploadCancelled:
            self._set(item, status=READY if item.prepared else ERROR, stage="", error=None if item.prepared else "Остановлено")
        except Exception as err:  # noqa: BLE001
            log.exception("Подготовка %s", item.file_name)
            self._set(item, status=ERROR, upload_requested=False, stage="", error=f"Непредвиденная ошибка: {err}")

    def _check_cancel(self, cancel: threading.Event | None) -> None:
        if cancel and cancel.is_set():
            raise UploadCancelled()

    def _prepare(self, item: QueueItem, cancel: threading.Event | None) -> None:
        src = item.path_obj
        if not src.exists():
            raise PipelineError("Файл не найден: его переместили или удалили")
        self._set(item, status=QUEUED if item.upload_requested else PREPARING, error=None, save=False)
        out = work_dir(item.id)

        # 1. ffprobe
        if not item.info:
            self._set(item, stage="probe", save=False)
            info = media.probe_photo(src) if item.is_photo else media.probe(src)
            self._set(item, info=info.to_dict(), file_size=info.size)
        info = VideoInfo.from_dict(item.info or {})
        self.check_size(item)
        self._check_cancel(cancel)

        # 2. Хеш и дубликаты
        if not item.file_hash:
            self._set(item, stage="hash", save=False)
            digest = file_hash(src)
            duplicates = self.find_duplicates(item.id, digest)
            self._set(item, file_hash=digest, duplicates=duplicates)
        self._check_cancel(cancel)

        # 3. Превью (только видео)
        if not item.is_photo and not (item.preview_path and Path(item.preview_path).exists()):
            self._set(item, stage="preview", save=False)
            preview = media.make_preview(src, out / "preview.mp4", info)
            self._set(item, preview_path=str(preview))
        self._check_cancel(cancel)

        # 4. Постер и миниатюра для Telegram
        if not (item.poster_path and Path(item.poster_path).exists()) or not (item.thumb_path and Path(item.thumb_path).exists()):
            self._set(item, stage="poster", save=False)
            make = media.make_photo_poster if item.is_photo else media.make_poster
            poster = make(src, out / "poster.jpg", info)
            thumb = media.make_thumb(poster, out / "thumb.jpg", info)
            self._set(item, poster_path=str(poster), thumb_path=str(thumb))
        self._check_cancel(cancel)

        # 5–6. Кадры и ИИ (результат — только предложение, пользователь решает сам)
        if self.tagger and self.ai_auto and not item.ai_suggestion:
            self.suggest_tags(item.id)

        self._set(item, status=QUEUED if item.upload_requested else READY, stage="")

    def find_duplicates(self, item_id: str, digest: str) -> list[dict]:
        found: list[dict] = []
        # Дубликаты на сайте
        if self.api:
            try:
                for v in self.api.check_hash(digest):
                    found.append({"id": v["id"], "title": v["title"], "where": "site"})
            except ApiError as err:
                log.warning("Проверка дубликатов на сайте не удалась: %s", err)
        # Тот же файл уже в очереди
        for other in self.store.all():
            if other.id != item_id and other.file_hash == digest and other.status != DONE:
                found.append({"id": other.id, "title": other.title or other.file_name, "where": "queue"})
        return found

    def ensure_frames(self, item: QueueItem) -> list[Path]:
        frames = [Path(f) for f in item.frames if Path(f).exists()]
        if frames:
            return frames
        if item.info:
            info = VideoInfo.from_dict(item.info)
        else:
            info = media.probe_photo(item.path_obj) if item.is_photo else media.probe(item.path_obj)
        extract = media.extract_photo_ai_frame if item.is_photo else media.extract_ai_frames
        frames = extract(item.path_obj, work_dir(item.id), info)
        self._set(item, frames=[str(f) for f in frames])
        return frames

    def suggest_tags(self, item_id: str) -> Suggestion | None:
        """Запрашивает у ИИ название, описание и теги. Ошибка не валит подготовку."""
        item = self.store.get(item_id)
        if not item or not self.tagger:
            return None
        prev_stage = item.stage
        self._set(item, stage="ai", ai_error=None, save=False)
        try:
            frames = self.ensure_frames(item)
            s = self.tagger.suggest(frames, item.file_name, self.existing_tags())
        except Exception as err:  # noqa: BLE001
            log.warning("ИИ-теги для %s: %s", item.file_name, err)
            self._set(item, stage=prev_stage if prev_stage != "ai" else "", ai_error=str(err))
            return None
        self._set(item, stage=prev_stage if prev_stage != "ai" else "", ai_suggestion={
            "title": s.title, "description": s.description, "tags": s.tags, "provider": s.provider, "model": s.model,
        })
        if self.ai_auto_apply:
            current = self.store.get(item_id)
            if current and current.status not in (UPLOADING, DONE) and not current.tg_message_id:
                self._set(current, **suggestion_fields(current))
        return s

    # ------------------------------------------------------------------ загрузка

    def upload(self, item_id: str, cancel: threading.Event | None = None) -> None:
        item = self.store.get(item_id)
        if not item:
            return
        try:
            self._upload(item, cancel)
        except UploadCancelled:
            self._set(item, status=READY, upload_requested=False, stage="", progress=0.0, note="Остановлено")
        except (PipelineError, MediaError, TelegramError, ApiError) as err:
            log.warning("Загрузка %s: %s", item.file_name, err)
            self._set(item, status=ERROR, upload_requested=False, stage="", error=str(err), note="")
        except Exception as err:  # noqa: BLE001
            log.exception("Загрузка %s", item.file_name)
            self._set(item, status=ERROR, upload_requested=False, stage="", error=f"Непредвиденная ошибка: {err}", note="")

    def _upload(self, item: QueueItem, cancel: threading.Event | None) -> None:
        if not item.prepared:
            self._prepare(item, cancel)
            item = self.store.get(item.id) or item
        if item.is_duplicate and not item.tg_message_id:
            what = "фото" if item.is_photo else "видео"
            raise PipelineError(f"Такое {what} уже есть. Отметьте «Загрузить всё равно» или удалите из очереди.")
        if not item.title.strip():
            raise PipelineError("Укажите название")
        if not self.telegram:
            raise PipelineError("Сначала войдите в Telegram (Настройки)")
        if not self.api:
            raise PipelineError("Не настроен сайт (Настройки)")
        self.check_size(item)
        self._set(item, status=UPLOADING, error=None, note="")

        # 7. Telegram — ровно один раз
        if not item.tg_message_id:
            self._send_to_telegram(item, cancel)
        self._check_cancel(cancel)

        # 8. Превью и постер на сайт
        if not item.media_uploaded:
            self._set(item, stage="site", progress=0.0, save=False)
            suffix = secrets.token_hex(4)
            preview_key = None if item.is_photo else (item.preview_key or f"previews/{item.id}-{suffix}.mp4")
            poster_key = item.poster_key or f"posters/{item.id}-{suffix}.jpg"
            self._set(item, preview_key=preview_key, poster_key=poster_key)
            if preview_key:
                self.api.put_media(preview_key, Path(item.preview_path or ""))
            self.api.put_media(poster_key, Path(item.poster_path or ""))
            self._set(item, media_uploaded=True)

        # 9. Запись на сайте (id = id элемента очереди, поэтому повтор безопасен)
        if not item.site_done:
            self._set(item, stage="site", save=False)
            info = item.info or {}
            self.api.create_video({
                "id": item.id,
                "tg_channel": item.tg_channel or self.channel,
                "tg_message_id": item.tg_message_id,
                "media_type": item.media_type,
                "title": item.title.strip(),
                "description": item.description.strip() or None,
                "file_name": item.file_name,
                "file_size": item.file_size,
                "file_hash": item.file_hash,
                "duration": info.get("duration"),
                "width": info.get("width"),
                "height": info.get("height"),
                "fps": info.get("fps"),
                "codec": info.get("codec"),
                "preview_key": item.preview_key,
                "poster_key": item.poster_key,
                "tags": item.tags,
                "collections": item.collections,
            })
            self._set(item, site_done=True)

        self._set(item, status=DONE, upload_requested=False, stage="", progress=1.0, note="")
        self.cleanup(item)

    def _send_to_telegram(self, item: QueueItem, cancel: threading.Event | None) -> None:
        assert self.telegram
        caption = build_caption(item.title, item.description, item.tags, self.caption_limit())
        attempt = 0
        while True:
            self._check_cancel(cancel)
            # Прошлая попытка могла дойти до Telegram, а ответ — потеряться: ищем пост, прежде чем слать снова.
            if item.tg_started_at:
                try:
                    found = self.telegram.find_recent_upload(self.channel, item.file_name, item.file_size, item.tg_started_at)
                except TelegramError as err:
                    log.warning("Поиск прошлой отправки: %s", err)
                    found = None
                if found:
                    log.info("%s уже в канале (пост %s), повторно не отправляем", item.file_name, found)
                    self._set(item, tg_message_id=found, tg_channel=self.channel)
                    return

            self._set(item, stage="telegram", progress=0.0, tg_started_at=time.time())
            tracker = _SpeedTracker()

            def on_progress(sent: int, total: int) -> None:
                speed, eta = tracker.update(sent, total)
                item.progress = sent / total if total else 0.0
                item.speed, item.eta = speed, eta
                if tracker.should_notify():
                    self.notify(item.id)

            try:
                message_id = self.telegram.send_video(
                    self.channel, item.path_obj, caption, Path(item.thumb_path) if item.thumb_path else None, on_progress, cancel
                )
            except FloodWait as err:
                log.warning("FloodWait %s с", err.seconds)
                wait_flood(err, cancel, lambda left: self._set(item, stage="wait", note=f"Telegram просит подождать: {left} с", save=False))
                continue
            except TelegramConnectionError as err:
                attempt += 1
                if attempt > self.telegram_retries:
                    raise
                delay = min(5 * 2**attempt, 120)
                log.warning("Telegram: %s, повтор через %d с", err, delay)
                self._set(item, note=f"Нет связи, повтор через {delay} с", save=False)
                for _ in range(delay):
                    self._check_cancel(cancel)
                    time.sleep(1)
                continue
            # Сохраняем сразу — дальше видео в Telegram уже не отправится.
            self._set(item, tg_message_id=message_id, tg_channel=self.channel, progress=1.0, note="")
            return

    def cleanup(self, item: QueueItem) -> None:
        """После загрузки удаляем тяжёлые временные файлы; постер оставляем для списка."""
        for path in [item.preview_path, item.thumb_path, *item.frames]:
            if path:
                Path(path).unlink(missing_ok=True)
        self.store.update(item.id, preview_path=None, thumb_path=None, frames=[])


class _SpeedTracker:
    """Скорость загрузки (сглаженная) и оставшееся время."""

    def __init__(self) -> None:
        self.start = time.monotonic()
        self.last_time = self.start
        self.last_sent = 0
        self.speed = 0.0
        self.last_notify = 0.0

    def update(self, sent: int, total: int) -> tuple[float, float | None]:
        now = time.monotonic()
        dt = now - self.last_time
        if dt >= 0.5:
            instant = (sent - self.last_sent) / dt
            self.speed = instant if self.speed == 0 else self.speed * 0.7 + instant * 0.3
            self.last_time, self.last_sent = now, sent
        eta = (total - sent) / self.speed if self.speed > 0 else None
        return self.speed, eta

    def should_notify(self) -> bool:
        now = time.monotonic()
        if now - self.last_notify >= 0.25:
            self.last_notify = now
            return True
        return False


def remove_work_dir(item_id: str) -> None:
    shutil.rmtree(work_dir(item_id), ignore_errors=True)
