"""Фейковые Telegram и API для тестов конвейера."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

from videoarchive.core.api import ApiError
from videoarchive.core.telegram import Account, FloodWait, TelegramConnectionError


class FakeTelegram:
    def __init__(self, premium: bool = False):
        self.premium = premium
        self.sent: list[dict] = []
        self.captions: dict[int, str] = {}
        self.deleted: list[int] = []
        self.fail_next: list[Exception] = []  # исключения для следующих send_video
        self.lose_response_once = False  # пост создан, но «ответ потерян»
        self.next_id = 100
        self.lock = threading.Lock()

    def account(self, refresh: bool = False) -> Account:
        return Account(id=1, name="Тест", username="test", premium=self.premium)

    def send_video(self, channel, path: Path, caption, thumb, progress=None, cancel=None) -> int:
        if self.fail_next:
            raise self.fail_next.pop(0)
        size = path.stat().st_size
        if progress:
            for part in (size // 2, size):
                progress(part, size)
        with self.lock:
            self.next_id += 1
            msg = {"id": self.next_id, "channel": channel, "file_name": path.name, "size": size, "caption": caption, "thumb": thumb}
            self.sent.append(msg)
            self.captions[self.next_id] = caption
        if self.lose_response_once:
            self.lose_response_once = False
            raise TelegramConnectionError("Нет связи с Telegram. Проверьте интернет.")
        return self.next_id

    def find_recent_upload(self, channel, file_name, size, since):
        for m in reversed(self.sent):
            if m["file_name"] == file_name and m["size"] == size:
                return m["id"]
        return None

    def edit_caption(self, channel, message_id, caption):
        self.captions[message_id] = caption

    def delete_messages(self, channel, ids):
        self.deleted += ids
        for i in ids:
            self.captions.pop(i, None)

    def existing_message_ids(self, channel, ids):
        return {i for i in ids if i in self.captions}

    def close(self):
        pass


class FakeApi:
    def __init__(self):
        self.media: dict[str, bytes] = {}
        self.videos: dict[str, dict] = {}
        self.hashes: dict[str, list[dict]] = {}
        self.fail_create: list[Exception] = []
        self.calls: list[str] = []

    def check_hash(self, digest):
        self.calls.append("check_hash")
        return self.hashes.get(digest, [])

    def put_media(self, key, path: Path):
        self.calls.append(f"put {key}")
        self.media[key] = path.read_bytes()
        return {"key": key}

    def create_video(self, payload):
        self.calls.append("create")
        if self.fail_create:
            raise self.fail_create.pop(0)
        video = {**payload, "tags": payload.get("tags", [])}
        self.videos[payload["id"]] = video
        return video

    def tags(self):
        return []


def net_error() -> ApiError:
    return ApiError(0, "network", "Нет связи с сайтом")


def flood(seconds: int = 1) -> FloodWait:
    return FloodWait(seconds)


def new_id() -> str:
    return str(uuid.uuid4())
