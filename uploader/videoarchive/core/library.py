"""Редактирование архива из программы (раздел 6.5 ТЗ). Подписи постов в Telegram обновляются вместе с сайтом."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from videoarchive.core.api import ApiClient, ApiError
from videoarchive.core.telegram import FloodWait, TelegramConnectionError, TelegramError, TelegramLike, wait_flood
from videoarchive.core.textutil import CAPTION_LIMIT, CAPTION_LIMIT_PREMIUM, build_caption

log = logging.getLogger(__name__)

Progress = Callable[[int, int], None]


@dataclass
class SaveResult:
    video: dict
    caption_updated: bool
    warning: str | None = None


class LibraryService:
    def __init__(self, api: ApiClient, telegram: TelegramLike | None):
        self.api = api
        self.telegram = telegram

    def caption_limit(self) -> int:
        try:
            return CAPTION_LIMIT_PREMIUM if self.telegram and self.telegram.account().premium else CAPTION_LIMIT
        except TelegramError:
            return CAPTION_LIMIT

    def caption_for(self, video: dict) -> str:
        return build_caption(video["title"], video.get("description"), video.get("tags", []), self.caption_limit())

    def _edit_caption(self, video: dict, caption: str, cancel: threading.Event | None = None) -> None:
        if not self.telegram:
            raise TelegramError("Нет входа в Telegram")
        while True:
            try:
                self.telegram.edit_caption(video["tg_channel"], int(video["tg_message_id"]), caption)
                return
            except FloodWait as err:
                wait_flood(err, cancel)

    # ---- одно видео ----

    def save_video(self, video: dict, *, title: str, description: str, tags: list[str], collections: list[int]) -> SaveResult:
        """Сначала подпись в Telegram, потом сайт. Если Telegram не удался — сайт всё равно обновится,
        а подпись помечается устаревшей и обновится позже."""
        changes: dict = {}
        if title != video["title"]:
            changes["title"] = title
        if (description or None) != (video.get("description") or None):
            changes["description"] = description or None
        if tags != video.get("tags", []):
            changes["tags"] = tags
        if sorted(collections) != sorted(video.get("collections", [])):
            changes["collections"] = collections
        if not changes:
            return SaveResult(video, caption_updated=False)

        caption_fields = {"title", "description", "tags"} & changes.keys()
        warning = None
        caption_ok = False
        if caption_fields:
            new_video = {**video, **changes}
            try:
                self._edit_caption(video, self.caption_for(new_video))
                changes["caption_synced"] = True
                caption_ok = True
            except TelegramError as err:
                warning = f"Сайт обновлён, а подпись в Telegram — нет: {err}. Она обновится при следующей синхронизации."
                log.warning("Подпись %s: %s", video["id"], err)
        updated = self.api.patch_video(video["id"], changes)
        return SaveResult(updated, caption_updated=caption_ok, warning=warning)

    def delete_video(self, video: dict, *, from_telegram: bool) -> str | None:
        """Удаляет запись (и файлы превью). from_telegram — ещё и пост в канале. Возвращает предупреждение."""
        warning = None
        if from_telegram:
            if not self.telegram:
                raise TelegramError("Нет входа в Telegram — пост удалить нельзя")
            try:
                self.telegram.delete_messages(video["tg_channel"], [int(video["tg_message_id"])])
            except TelegramError as err:
                warning = f"Пост в Telegram не удалён: {err}"
        self.api.delete_video(video["id"])
        return warning

    # ---- массовые операции ----

    def sync_dirty_captions(self, videos: list[dict], progress: Progress | None = None,
                            cancel: threading.Event | None = None) -> tuple[int, list[str]]:
        """Обновляет подписи постов, которые поменяли на сайте (caption_dirty = 1)."""
        dirty = [v for v in videos if v.get("caption_dirty")]
        done, errors = 0, []
        for i, v in enumerate(dirty):
            if cancel and cancel.is_set():
                break
            try:
                self._edit_caption(v, self.caption_for(v), cancel)
                self.api.patch_video(v["id"], {"caption_synced": True})
                done += 1
            except (TelegramError, ApiError) as err:
                errors.append(f"«{v['title']}»: {err}")
                if isinstance(err, TelegramConnectionError):
                    break  # нет сети — нет смысла продолжать
            if progress:
                progress(i + 1, len(dirty))
        return done, errors

    def find_missing_posts(self, videos: list[dict], progress: Progress | None = None) -> list[dict]:
        """Записи на сайте, чьи посты в канале удалили вручную."""
        if not self.telegram:
            raise TelegramError("Нет входа в Telegram")
        missing: list[dict] = []
        by_channel: dict[str, list[dict]] = {}
        for v in videos:
            by_channel.setdefault(v["tg_channel"], []).append(v)
        checked = 0
        for channel, items in by_channel.items():
            existing = self.telegram.existing_message_ids(channel, [int(v["tg_message_id"]) for v in items])
            missing += [v for v in items if int(v["tg_message_id"]) not in existing]
            checked += len(items)
            if progress:
                progress(checked, len(videos))
        return missing

    def remove_from_site(self, videos: list[dict]) -> list[str]:
        errors = []
        for v in videos:
            try:
                self.api.delete_video(v["id"])
            except ApiError as err:
                errors.append(f"«{v['title']}»: {err}")
        return errors
