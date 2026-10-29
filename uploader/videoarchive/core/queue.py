"""Очередь загрузки: сохраняется в queue.json, поэтому переживает перезапуск программы."""

from __future__ import annotations

import logging
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from videoarchive.core.config import write_json_atomic
from videoarchive.core.media import is_photo
from videoarchive.core.paths import data_dir, work_dir

log = logging.getLogger(__name__)

# Статусы
NEW = "new"  # добавлен, ещё не обработан
PREPARING = "preparing"  # ffprobe, превью, ИИ
READY = "ready"  # готов к загрузке
QUEUED = "queued"  # ждёт своей очереди на загрузку
UPLOADING = "uploading"  # загрузка в Telegram и на сайт
DONE = "done"
ERROR = "error"
SKIPPED = "skipped"

# Этапы — для подписи под прогрессом
STAGE_LABELS = {
    "probe": "анализ файла",
    "hash": "проверка дубликатов",
    "preview": "превью",
    "poster": "постер",
    "ai": "ИИ-теги",
    "telegram": "Telegram",
    "site": "сайт",
    "wait": "ожидание",
}


@dataclass
class QueueItem:
    path: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))  # он же id видео на сайте
    file_name: str = ""
    file_size: int = 0
    added_at: float = field(default_factory=time.time)
    status: str = NEW
    upload_requested: bool = False  # пользователь нажал «Загрузить»; переживает перезапуск
    stage: str = ""
    error: str | None = None
    # редактируемое
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    collections: list[int] = field(default_factory=list)
    # результаты подготовки
    info: dict | None = None
    file_hash: str | None = None
    duplicates: list[dict] = field(default_factory=list)  # [{id, title}] уже на сайте
    allow_duplicate: bool = False
    preview_path: str | None = None
    poster_path: str | None = None
    thumb_path: str | None = None
    frames: list[str] = field(default_factory=list)
    ai_suggestion: dict | None = None  # {title, description, tags, provider, model}
    ai_error: str | None = None
    # результаты загрузки — сохраняются сразу, чтобы не загружать видео в Telegram второй раз
    tg_channel: str | None = None
    tg_message_id: int | None = None
    tg_started_at: float | None = None  # когда началась отправка в Telegram
    preview_key: str | None = None
    poster_key: str | None = None
    media_uploaded: bool = False
    site_done: bool = False
    # не сохраняются
    progress: float = 0.0
    speed: float = 0.0
    eta: float | None = None
    note: str = ""

    TRANSIENT = ("progress", "speed", "eta", "note")

    @property
    def path_obj(self) -> Path:
        return Path(self.path)

    @property
    def is_photo(self) -> bool:
        return is_photo(self.path)

    @property
    def media_type(self) -> str:
        return "photo" if self.is_photo else "video"

    @property
    def prepared(self) -> bool:
        has_preview = self.is_photo or bool(self.preview_path)  # у фото превью-ролика нет
        return bool(self.info and has_preview and self.poster_path and self.thumb_path)

    @property
    def is_duplicate(self) -> bool:
        return bool(self.duplicates) and not self.allow_duplicate

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for key in self.TRANSIENT:
            d.pop(key, None)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "QueueItem":
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in fields and k not in cls.TRANSIENT})


class QueueStore:
    """Потокобезопасный список элементов очереди с сохранением на диск."""

    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "queue.json"
        self._lock = threading.RLock()
        self._save_lock = threading.Lock()  # снимок и запись одним шагом: старый снимок не перетрёт новый
        self._items: dict[str, QueueItem] = {}
        self._load()

    def _load(self) -> None:
        import json

        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError) as err:
            log.error("Очередь повреждена (%s), начинаем с пустой", err)
            return
        for d in raw.get("items", []):
            try:
                item = QueueItem.from_dict(d)
            except TypeError:
                continue
            # Прерванные операции после перезапуска продолжатся с сохранённого места.
            if item.status in (PREPARING, NEW):
                item.status = NEW
            elif item.status in (UPLOADING, QUEUED):
                item.status = QUEUED
                item.upload_requested = True
            item.stage = ""
            self._items[item.id] = item

    def save(self) -> None:
        with self._save_lock:
            with self._lock:
                data = {"version": 1, "items": [i.to_dict() for i in self._items.values()]}
            write_json_atomic(self.path, data)

    # ---- доступ ----

    def all(self) -> list[QueueItem]:
        with self._lock:
            return list(self._items.values())

    def get(self, item_id: str) -> QueueItem | None:
        with self._lock:
            return self._items.get(item_id)

    def find_by_path(self, path: str) -> QueueItem | None:
        with self._lock:
            return next((i for i in self._items.values() if i.path == path and i.status != DONE), None)

    def add(self, item: QueueItem) -> None:
        with self._lock:
            self._items[item.id] = item
        self.save()

    def update(self, item_id: str, save: bool = True, **fields: Any) -> QueueItem | None:
        with self._lock:
            item = self._items.get(item_id)
            if not item:
                return None
            for k, v in fields.items():
                setattr(item, k, v)
        if save:
            self.save()
        return item

    def remove(self, item_id: str) -> None:
        with self._lock:
            item = self._items.pop(item_id, None)
        if item:
            shutil.rmtree(work_dir(item.id), ignore_errors=True)
            self.save()

    def unfinished_uploads(self) -> list[QueueItem]:
        """Загрузки, прерванные закрытием программы."""
        return [i for i in self.all() if i.upload_requested and i.status not in (DONE, ERROR, SKIPPED)]
