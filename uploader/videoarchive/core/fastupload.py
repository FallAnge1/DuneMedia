"""Быстрая загрузка файла в Telegram: куски идут параллельно по нескольким соединениям.

Telethon шлёт куски по одному и ждёт ответа на каждый, поэтому скорость упирается в задержку
до сервера, а не в канал (на практике ~0,5 МБ/с). Здесь открываются дополнительные соединения
к «своему» дата-центру с тем же ключом авторизации, и в каждом одновременно летит несколько
кусков. Если что-то пошло не так до начала загрузки, вызывающий код возвращается к обычной
загрузке Telethon.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
from collections.abc import Callable
from pathlib import Path

from telethon import TelegramClient, errors
from telethon.network import MTProtoSender
from telethon.tl.functions.upload import SaveBigFilePartRequest
from telethon.tl.types import InputFileBig

log = logging.getLogger(__name__)

PART_SIZE = 512 * 1024  # максимум, который принимает Telegram
BIG_FILE = 10 * 1024 * 1024  # меньшие файлы Telegram хочет получать обычным способом (с md5)
PART_RETRIES = 5


class FastUploadUnavailable(Exception):
    """Дополнительные соединения открыть не удалось — грузим обычным способом."""


async def _open_sender(client: TelegramClient) -> MTProtoSender:
    dc = await client._get_dc(client.session.dc_id)  # noqa: SLF001 — у Telethon нет публичного API для этого
    sender = MTProtoSender(client.session.auth_key, loggers=client._log)  # noqa: SLF001
    await sender.connect(client._connection(dc.ip_address, dc.port, dc.id, loggers=client._log, proxy=client._proxy))  # noqa: SLF001
    return sender


async def upload_big_file(
    client: TelegramClient,
    path: Path,
    *,
    connections: int,
    in_flight: int = 3,
    progress: Callable[[int, int], None] | None = None,
) -> InputFileBig:
    """Загружает файл кусками и возвращает InputFileBig для send_file.

    progress(sent, total) вызывается после каждого куска; исключение из него (отмена) прерывает загрузку.
    """
    size = path.stat().st_size
    parts = math.ceil(size / PART_SIZE)
    file_id = random.getrandbits(63)

    senders: list[MTProtoSender] = []
    try:
        for _ in range(max(1, connections)):
            senders.append(await _open_sender(client))
    except Exception as err:  # noqa: BLE001
        for s in senders:
            await s.disconnect()
        if not senders:
            raise FastUploadUnavailable(str(err)) from err
        log.info("Открыто соединений: %d из %d (%s)", len(senders), connections, err)

    pending = list(range(parts - 1, -1, -1))  # pop() отдаёт куски по порядку
    sent = 0
    stop: BaseException | None = None

    def read(index: int) -> bytes:
        with path.open("rb") as f:
            f.seek(index * PART_SIZE)
            return f.read(PART_SIZE)

    async def worker(sender: MTProtoSender) -> None:
        nonlocal sent, stop
        while pending and stop is None:
            index = pending.pop()
            data = await asyncio.to_thread(read, index)
            for attempt in range(PART_RETRIES):
                try:
                    await sender.send(SaveBigFilePartRequest(file_id, index, parts, data))
                    break
                except errors.FloodWaitError:
                    raise
                except Exception as err:  # noqa: BLE001
                    if stop is not None:
                        return
                    if attempt == PART_RETRIES - 1:
                        raise
                    log.info("Кусок %d: %s, повтор", index, err)
                    await asyncio.sleep(1 + attempt)
            sent += len(data)
            if progress:
                try:
                    progress(min(sent, size), size)
                except BaseException as err:  # отмена из progress
                    stop = err
                    raise

    try:
        tasks = [asyncio.ensure_future(worker(s)) for s in senders for _ in range(max(1, in_flight))]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        failed = next((t for t in done if t.exception()), None)
        if failed:
            stop = stop or failed.exception()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise stop  # type: ignore[misc]
    finally:
        for s in senders:
            try:
                await s.disconnect()
            except Exception:  # noqa: BLE001
                pass
    return InputFileBig(id=file_id, parts=parts, name=path.name)
