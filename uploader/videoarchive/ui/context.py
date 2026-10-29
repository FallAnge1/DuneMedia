"""Общее состояние программы: настройки, Telegram, сайт, очередь и кэш тегов/коллекций."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Signal

from videoarchive.core.api import ApiClient, ApiError
from videoarchive.core.config import Config
from videoarchive.core.manager import UploadManager
from videoarchive.core.paths import session_path
from videoarchive.core.pipeline import Pipeline, Tagger
from videoarchive.core.queue import QueueStore
from videoarchive.core.telegram import Account, TelegramError, TelegramService
from videoarchive.ui.tasks import run_async

log = logging.getLogger(__name__)


class AppContext(QObject):
    item_changed = Signal(str)
    queue_changed = Signal()
    account_changed = Signal()
    catalog_changed = Signal()  # теги или коллекции
    message = Signal(str)  # короткое сообщение в строку состояния

    def __init__(self, config: Config | None = None):
        super().__init__()
        self.config = config or Config.load()
        self.store = QueueStore()
        self.telegram: TelegramService | None = None
        self.api: ApiClient | None = None
        self.account: Account | None = None
        self.account_error: str | None = None
        self.uploader_name: str | None = None
        self.site_error: str | None = None
        self.tags: list[dict] = []
        self.collections: list[dict] = []
        self._tg_lock = threading.Lock()
        self.manager = UploadManager(self.store, self._make_pipeline(), notify=self.item_changed.emit,
                                     on_queue_changed=self.queue_changed.emit)

    # ---- сборка ----

    def tagger(self) -> Tagger | None:
        if not self.config.ai_enabled:
            return None
        try:
            from videoarchive.ai.chain import AIChain
        except ImportError:  # ИИ-модуль ещё не установлен
            return None
        return AIChain.from_config(self.config, api=self.api)

    def _make_pipeline(self) -> Pipeline:
        return Pipeline(
            self.store,
            api=self.api,
            telegram=self.telegram,
            channel=self.config.channel,
            tagger=self.tagger(),
            ai_auto=self.config.ai_auto,
            ai_auto_apply=self.config.ai_auto_apply,
            existing_tags=lambda: [t["name"] for t in self.tags],
            notify=self.item_changed.emit,
        )

    def apply_config(self) -> None:
        """После изменения настроек: пересоздаём клиентов и конвейер."""
        self.config.save()
        # Старый клиент не закрываем: им может пользоваться идущая загрузка.
        self.api = (ApiClient(self.config.site_url, self.config.uploader_token, extra_headers=self.config.access_headers())
                    if self.config.site_ready else None)
        self.manager.set_pipeline(self._make_pipeline())

    def ensure_telegram(self) -> TelegramService:
        """Создаёт клиента Telegram (вызывать не из главного потока: подключение занимает время)."""
        with self._tg_lock:
            if self.telegram is None:
                if not (self.config.api_id and self.config.api_hash):
                    raise TelegramError("Не указаны api_id и api_hash (Настройки)")
                self.telegram = TelegramService(session_path(), int(self.config.api_id), self.config.api_hash,
                                                upload_connections=self.config.upload_connections)
            return self.telegram

    def reset_telegram(self) -> None:
        """api_id/api_hash поменялись — нужен новый клиент."""
        with self._tg_lock:
            if self.telegram:
                self.telegram.close()
            self.telegram = None
            self.account = None

    # ---- обновление статуса ----

    def refresh(self) -> None:
        """Проверяет Telegram и сайт, подтягивает теги и коллекции (в фоне)."""
        self.apply_config()

        def check() -> None:
            if self.config.telegram_ready:
                try:
                    tg = self.ensure_telegram()
                    self.account = tg.account(refresh=True)
                    self.account_error = None
                except TelegramError as err:
                    self.account, self.account_error = None, str(err)
            else:
                self.account, self.account_error = None, "Telegram не настроен"
            if self.api:
                try:
                    self.uploader_name = self.api.me()["name"]
                    self.site_error = None
                    self.tags = self.api.tags()
                    self.collections = self.api.collections()
                except ApiError as err:
                    self.uploader_name, self.site_error = None, str(err)
            else:
                self.uploader_name, self.site_error = None, "Сайт не настроен"

        def done(_: object) -> None:
            self.manager.set_pipeline(self._make_pipeline())
            self.account_changed.emit()
            self.catalog_changed.emit()

        run_async(check, done, lambda err: (log.exception("refresh", exc_info=err), done(None)))

    def reload_catalog(self) -> None:
        if not self.api:
            return
        api = self.api

        def load() -> tuple[list[dict], list[dict]]:
            return api.tags(), api.collections()

        def done(result: tuple[list[dict], list[dict]]) -> None:
            self.tags, self.collections = result
            self.catalog_changed.emit()

        run_async(load, done, lambda err: self.message.emit(str(err)))

    def shutdown(self) -> None:
        self.manager.shutdown()
        self.store.save()
        if self.telegram:
            self.telegram.close()
