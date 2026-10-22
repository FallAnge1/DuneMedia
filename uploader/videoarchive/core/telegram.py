"""Работа с Telegram через аккаунт пользователя (MTProto, Telethon).

Bot API не подходит: он не загружает файлы больше 50 МБ. Telethon живёт в отдельном потоке
со своим циклом asyncio; остальная программа вызывает синхронные методы этого класса.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeVar

from telethon import TelegramClient, errors

from videoarchive import __version__
from videoarchive.core.textutil import TG_LIMIT, TG_LIMIT_PREMIUM

log = logging.getLogger(__name__)
T = TypeVar("T")

ProgressCallback = Callable[[int, int], None]


class TelegramError(Exception):
    """Ошибка Telegram с понятным сообщением."""


class FloodWait(TelegramError):
    def __init__(self, seconds: int):
        super().__init__(f"Telegram просит подождать {seconds} с перед следующим действием")
        self.seconds = seconds


class NotAuthorized(TelegramError):
    pass


class TelegramConnectionError(TelegramError):
    """Обрыв связи — операцию имеет смысл повторить."""


@dataclass
class Account:
    id: int
    name: str
    username: str | None
    premium: bool

    @property
    def file_limit(self) -> int:
        return TG_LIMIT_PREMIUM if self.premium else TG_LIMIT


@dataclass
class ChannelInfo:
    username: str
    title: str
    can_post: bool
    can_edit: bool
    can_delete: bool


class TelegramLike(Protocol):
    """То, что нужно конвейеру. В тестах подменяется фейком."""

    def account(self) -> Account: ...
    def send_video(self, channel: str, path: Path, caption: str, thumb: Path | None, progress: ProgressCallback | None = None,
                   cancel: threading.Event | None = None) -> int: ...
    def find_recent_upload(self, channel: str, file_name: str, size: int, since: float) -> int | None: ...
    def edit_caption(self, channel: str, message_id: int, caption: str) -> None: ...
    def delete_messages(self, channel: str, ids: list[int]) -> None: ...
    def existing_message_ids(self, channel: str, ids: list[int]) -> set[int]: ...


class UploadCancelled(Exception):
    pass


def translate(err: BaseException) -> TelegramError:
    """Ошибки Telethon → сообщения на русском."""
    if isinstance(err, TelegramError):
        return err
    if isinstance(err, errors.FloodWaitError):
        return FloodWait(int(err.seconds))
    mapping: list[tuple[type[BaseException], str]] = [
        (errors.PhoneNumberInvalidError, "Неверный номер телефона. Укажите его в международном формате, например +79991234567."),
        (errors.PhoneNumberBannedError, "Этот номер заблокирован в Telegram."),
        (errors.PhoneNumberUnoccupiedError, "На этот номер не зарегистрирован аккаунт Telegram."),
        (errors.PhoneCodeInvalidError, "Неверный код подтверждения."),
        (errors.PhoneCodeExpiredError, "Код устарел. Запросите новый."),
        (errors.PasswordHashInvalidError, "Неверный пароль двухэтапной проверки."),
        (errors.ApiIdInvalidError, "Неверные api_id или api_hash. Проверьте их на my.telegram.org."),
        (errors.AuthKeyUnregisteredError, "Сессия Telegram завершена. Войдите заново в настройках."),
        (errors.UsernameNotOccupiedError, "Канал с таким username не найден."),
        (errors.UsernameInvalidError, "Некорректный username канала."),
        (errors.ChannelPrivateError, "Канал недоступен: он приватный или вас там нет."),
        (errors.ChatAdminRequiredError, "Нужны права администратора канала."),
        (errors.ChatWriteForbiddenError, "Нет права публиковать в этом канале."),
        (errors.MediaCaptionTooLongError, "Подпись слишком длинная для Telegram."),
        (errors.MessageIdInvalidError, "Пост не найден в канале (возможно, удалён)."),
        (errors.MessageEditTimeExpiredError, "Этот пост больше нельзя редактировать."),
    ]
    for cls, message in mapping:
        if isinstance(err, cls):
            return TelegramError(message)
    if isinstance(err, (ConnectionError, OSError, asyncio.TimeoutError)):
        return TelegramConnectionError("Нет связи с Telegram. Проверьте интернет.")
    if isinstance(err, errors.RPCError):
        return TelegramError(f"Telegram вернул ошибку: {err.__class__.__name__}")
    return TelegramError(f"Ошибка Telegram: {err}")


class TelegramService:
    def __init__(self, session: Path, api_id: int, api_hash: str):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="telegram", daemon=True)
        self._thread.start()
        self._client: TelegramClient = self._call(self._create(session, api_id, api_hash))
        self._phone_code_hash: str | None = None
        self._account: Account | None = None
        self._entities: dict[str, Any] = {}

    async def _create(self, session: Path, api_id: int, api_hash: str) -> TelegramClient:
        session.parent.mkdir(parents=True, exist_ok=True)
        return TelegramClient(
            str(session), api_id, api_hash,
            flood_sleep_threshold=120,  # короткие FloodWait Telethon переждёт сам
            request_retries=5, connection_retries=10, retry_delay=2, auto_reconnect=True,
            device_model="VideoArchive Uploader", app_version=__version__, lang_code="ru", system_lang_code="ru",
            receive_updates=False,
        )

    def _call(self, coro: Coroutine[Any, Any, T], timeout: float | None = 120) -> T:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout)
        except TimeoutError as err:
            future.cancel()
            raise TelegramConnectionError("Telegram не ответил вовремя. Проверьте интернет.") from err

    def _run(self, coro_fn: Callable[[], Coroutine[Any, Any, T]], timeout: float | None = 120) -> T:
        async def wrapped() -> T:
            if not self._client.is_connected():
                await self._client.connect()
            return await coro_fn()

        try:
            return self._call(wrapped(), timeout)
        except (TelegramError, UploadCancelled):
            raise
        except Exception as err:  # noqa: BLE001
            log.exception("Ошибка Telegram")
            raise translate(err) from err

    def close(self) -> None:
        try:
            self._call(self._client.disconnect(), timeout=10)
        except Exception:  # noqa: BLE001
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)

    # ---- Вход ----

    def is_authorized(self) -> bool:
        return self._run(self._client.is_user_authorized)

    def send_code(self, phone: str) -> None:
        async def go() -> None:
            sent = await self._client.send_code_request(phone)
            self._phone_code_hash = sent.phone_code_hash

        self._run(go)

    def sign_in(self, phone: str, code: str) -> bool:
        """Возвращает True, если нужен пароль двухэтапной проверки."""

        async def go() -> bool:
            try:
                await self._client.sign_in(phone=phone, code=code.strip(), phone_code_hash=self._phone_code_hash)
            except errors.SessionPasswordNeededError:
                return True
            return False

        return self._run(go)

    def sign_in_password(self, password: str) -> None:
        self._run(lambda: self._client.sign_in(password=password))

    def log_out(self) -> None:
        self._run(self._client.log_out)
        self._account = None

    def account(self, refresh: bool = False) -> Account:
        if self._account and not refresh:
            return self._account

        async def go() -> Account:
            if not await self._client.is_user_authorized():
                raise NotAuthorized("Вход в Telegram не выполнен. Откройте настройки.")
            me = await self._client.get_me()
            name = " ".join(x for x in (me.first_name, me.last_name) if x) or me.username or str(me.id)
            return Account(id=me.id, name=name, username=me.username, premium=bool(getattr(me, "premium", False)))

        self._account = self._run(go)
        return self._account

    # ---- Канал ----

    async def _entity(self, channel: str) -> Any:
        if channel not in self._entities:
            self._entities[channel] = await self._client.get_entity(channel)
        return self._entities[channel]

    def check_channel(self, channel: str) -> ChannelInfo:
        """Проверяет, что канал публичный и у пользователя есть право публикации."""

        async def go() -> ChannelInfo:
            entity = await self._client.get_entity(channel)
            if not getattr(entity, "broadcast", False):
                raise TelegramError("Это не канал. Укажите username публичного канала.")
            if not getattr(entity, "username", None):
                raise TelegramError("У канала нет публичного username — сайт не сможет вести на посты.")
            perms = await self._client.get_permissions(entity, "me")
            creator = bool(perms and perms.is_creator)
            info = ChannelInfo(
                username=entity.username,
                title=entity.title,
                can_post=creator or bool(perms and perms.post_messages),
                can_edit=creator or bool(perms and perms.edit_messages),
                can_delete=creator or bool(perms and perms.delete_messages),
            )
            self._entities[channel] = entity
            return info

        return self._run(go)

    # ---- Посты ----

    def send_video(self, channel: str, path: Path, caption: str, thumb: Path | None, progress: ProgressCallback | None = None,
                   cancel: threading.Event | None = None) -> int:
        """Отправляет файл документом (без сжатия). Возвращает id поста."""

        def on_progress(sent: int, total: int) -> None:
            if cancel and cancel.is_set():
                raise UploadCancelled()
            if progress:
                progress(sent, total)

        async def go() -> int:
            entity = await self._entity(channel)
            message = await self._client.send_file(
                entity,
                str(path),
                caption=caption,
                parse_mode=None,  # без Markdown: иначе _ в хештегах превратится в курсив
                force_document=True,
                thumb=str(thumb) if thumb else None,
                progress_callback=on_progress,
            )
            return int(message.id)

        return self._run(go, timeout=None)

    def find_recent_upload(self, channel: str, file_name: str, size: int, since: float) -> int | None:
        """Ищет среди последних постов файл с тем же именем и размером, отправленный после since.

        Нужно, если связь оборвалась сразу после отправки: пост мог появиться, а ответ — потеряться.
        """

        async def go() -> int | None:
            entity = await self._entity(channel)
            async for msg in self._client.iter_messages(entity, limit=40):
                if msg.date and msg.date.timestamp() < since - 120:
                    break
                f = msg.file
                if f and f.size == size and (f.name or "") == file_name:
                    return int(msg.id)
            return None

        return self._run(go)

    def edit_caption(self, channel: str, message_id: int, caption: str) -> None:
        async def go() -> None:
            entity = await self._entity(channel)
            try:
                await self._client.edit_message(entity, message_id, caption, parse_mode=None)
            except errors.MessageNotModifiedError:
                pass  # подпись уже такая

        self._run(go)

    def delete_messages(self, channel: str, ids: list[int]) -> None:
        async def go() -> None:
            entity = await self._entity(channel)
            await self._client.delete_messages(entity, ids)

        self._run(go)

    def existing_message_ids(self, channel: str, ids: list[int]) -> set[int]:
        """Какие из постов ещё существуют (для проверки синхронизации)."""

        async def go() -> set[int]:
            entity = await self._entity(channel)
            found: set[int] = set()
            for i in range(0, len(ids), 100):
                batch = ids[i : i + 100]
                messages = await self._client.get_messages(entity, ids=batch)
                for m in messages:
                    if m is not None and not getattr(m, "action", None):
                        found.add(int(m.id))
            return found

        return self._run(go, timeout=600)


def wait_flood(err: FloodWait, cancel: threading.Event | None = None, on_tick: Callable[[int], None] | None = None) -> None:
    """Ждёт столько, сколько просит Telegram, с возможностью отмены."""
    end = time.monotonic() + err.seconds + 1
    while (left := end - time.monotonic()) > 0:
        if cancel and cancel.is_set():
            raise UploadCancelled()
        if on_tick:
            on_tick(int(left))
        time.sleep(min(1.0, left))
