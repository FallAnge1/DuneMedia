"""Очередь в работе: подготовка файлов (видео и фото) в фоне (2 потока) и последовательная загрузка.

Пока одно видео уходит в Telegram, превью и ИИ-теги для следующих уже готовятся.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from videoarchive.core.media import MEDIA_EXTENSIONS, PHOTO_EXTENSIONS, VIDEO_EXTENSIONS  # noqa: F401 — реэкспорт
from videoarchive.core.pipeline import Pipeline
from videoarchive.core.queue import DONE, ERROR, NEW, PREPARING, QUEUED, READY, SKIPPED, UPLOADING, QueueItem, QueueStore
from videoarchive.core.textutil import clean_title

log = logging.getLogger(__name__)

def expand_paths(paths: Iterable[Path]) -> list[Path]:
    """Файлы и папки → список видео и фото (папки обходятся рекурсивно, скрытые файлы пропускаются)."""
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS and not f.name.startswith("."):
                    out.append(f)
        elif p.is_file():
            out.append(p)
    return out


class UploadManager:
    def __init__(self, store: QueueStore, pipeline: Pipeline, notify: Callable[[str], None] = lambda _id: None,
                 on_queue_changed: Callable[[], None] = lambda: None, prepare_workers: int = 2):
        self.store = store
        self.pipeline = pipeline
        self.notify = notify
        self.on_queue_changed = on_queue_changed
        self._prepare_pool = ThreadPoolExecutor(max_workers=prepare_workers, thread_name_prefix="prepare")
        self._prepare_futures: dict[str, Future] = {}
        self._cancel_prepare = threading.Event()
        self._cancel_upload = threading.Event()
        self._upload_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.current_upload: str | None = None

    def set_pipeline(self, pipeline: Pipeline) -> None:
        """Новые настройки (вход в Telegram, токен) — новый конвейер."""
        self.pipeline = pipeline

    # ---- добавление ----

    def add_paths(self, paths: Iterable[Path]) -> tuple[list[QueueItem], list[str]]:
        """Добавляет файлы и папки. Возвращает (добавленные, пропущенные с причиной)."""
        added: list[QueueItem] = []
        skipped: list[str] = []
        for path in expand_paths(paths):
            resolved = str(path.resolve())
            if path.suffix.lower() not in MEDIA_EXTENSIONS:
                skipped.append(f"{path.name}: не похоже на видео или фото")
                continue
            if self.store.find_by_path(resolved):
                skipped.append(f"{path.name}: уже в очереди")
                continue
            item = QueueItem(path=resolved, file_name=path.name, file_size=path.stat().st_size, title=clean_title(path.name))
            self.store.add(item)
            added.append(item)
            self.prepare(item.id)
        if added:
            self.on_queue_changed()
        return added, skipped

    def prepare(self, item_id: str) -> Future:
        with self._lock:
            existing = self._prepare_futures.get(item_id)
            if existing and not existing.done():
                return existing
            self._cancel_prepare.clear()
            future = self._prepare_pool.submit(self.pipeline.prepare, item_id, self._cancel_prepare)
            self._prepare_futures[item_id] = future
            return future

    def resume_preparation(self) -> None:
        """После перезапуска — доделать подготовку файлов, которые её не закончили."""
        for item in self.store.all():
            if item.status == NEW:
                self.prepare(item.id)

    def suggest_tags(self, item_id: str) -> Future:
        return self._prepare_pool.submit(self.pipeline.suggest_tags, item_id)

    # ---- загрузка ----

    def start_upload(self, ids: Iterable[str] | None = None) -> int:
        """Ставит элементы в очередь загрузки. Дубликаты без подтверждения и ошибки чтения пропускаются."""
        chosen = list(ids) if ids is not None else [i.id for i in self.store.all()]
        count = 0
        for item_id in chosen:
            item = self.store.get(item_id)
            if not item or item.status in (DONE, UPLOADING, SKIPPED) or item.upload_requested:
                continue
            if item.is_duplicate and not item.tg_message_id:
                continue
            if item.status == ERROR and not item.info:
                continue  # файл не прочитался — сначала «Повторить»
            status = QUEUED if item.status in (READY, ERROR) else item.status
            self.store.update(item.id, upload_requested=True, status=status, error=None, note="")
            self.notify(item.id)
            count += 1
        if count:
            self._ensure_upload_thread()
        return count

    def resume_uploads(self) -> int:
        pending = self.store.unfinished_uploads()
        if pending:
            self._ensure_upload_thread()
        return len(pending)

    def _ensure_upload_thread(self) -> None:
        with self._lock:
            if self._upload_thread and self._upload_thread.is_alive():
                return
            self._cancel_upload.clear()
            self._upload_thread = threading.Thread(target=self._upload_loop, name="upload", daemon=True)
            self._upload_thread.start()

    def _next_requested(self) -> QueueItem | None:
        pending = [i for i in self.store.unfinished_uploads() if i.status != UPLOADING]
        return min(pending, key=lambda i: i.added_at) if pending else None

    def _upload_loop(self) -> None:
        while not self._cancel_upload.is_set():
            item = self._next_requested()
            if not item:
                break
            # Подготовка этого файла могла ещё идти в фоне — дождёмся её.
            future = self._prepare_futures.get(item.id)
            if future and not future.done():
                item.note = "ждёт подготовки"
                self.notify(item.id)
                try:
                    future.result()
                except Exception:  # noqa: BLE001
                    log.exception("Подготовка")
            if self._cancel_upload.is_set():
                break
            item = self.store.get(item.id)
            if not item or not item.upload_requested or item.status in (ERROR, DONE, SKIPPED):
                continue
            self.current_upload = item.id
            try:
                self.pipeline.upload(item.id, self._cancel_upload)
            finally:
                self.current_upload = None
                # На всякий случай: элемент не должен остаться в «запрошенных», иначе цикл зациклится.
                after = self.store.get(item.id)
                if after and after.upload_requested and after.status not in (QUEUED, NEW, PREPARING):
                    self.store.update(item.id, upload_requested=False)
        log.info("Очередь загрузки пуста")

    def stop(self) -> None:
        """Остановить загрузку: текущий файл прерывается, остальные возвращаются в «готово»."""
        self._cancel_upload.set()
        for item in self.store.all():
            if item.upload_requested and item.status != UPLOADING:
                self.store.update(item.id, upload_requested=False, status=READY if item.prepared else item.status, note="")
                self.notify(item.id)

    @property
    def uploading(self) -> bool:
        return bool(self._upload_thread and self._upload_thread.is_alive())

    # ---- прочее ----

    def retry(self, item_id: str) -> None:
        item = self.store.get(item_id)
        if not item:
            return
        if not item.prepared:
            self.store.update(item_id, status=NEW, error=None)
            self.prepare(item_id)
        else:
            self.store.update(item_id, status=READY, error=None, upload_requested=False)
        self.notify(item_id)

    def remove(self, item_ids: Iterable[str]) -> None:
        for item_id in item_ids:
            if item_id == self.current_upload:
                continue
            future = self._prepare_futures.pop(item_id, None)
            if future:
                future.cancel()
            self.store.remove(item_id)
        self.on_queue_changed()

    def clear_done(self) -> None:
        self.remove([i.id for i in self.store.all() if i.status in (DONE, SKIPPED)])

    def shutdown(self) -> None:
        self._cancel_prepare.set()
        self._cancel_upload.set()
        self._prepare_pool.shutdown(wait=False, cancel_futures=True)
