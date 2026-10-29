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
MAX_FLOOD_WAIT = 60  # секунд: дольше — ошибка уходит в конвейер
MAX_TOTAL_FLOOD_WAIT = 900  # суммарно на один файл
RAMP_UP_AFTER = 16  # удачных кусков подряд — и можно ещё один одновременный


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
    loop = asyncio.get_running_loop()
    # Telegram может попросить подождать пару секунд (FLOOD_WAIT, у аккаунтов без Premium — часто).
    # Тогда все соединения вместе ждут, кусок отправляется заново, а одновременных кусков становится вдвое меньше.
    # После серии удачных кусков их число снова понемногу растёт.
    pause_until = 0.0
    slots = len(senders) * max(1, in_flight)
    allowed = slots
    waited = 0
    streak = 0

    def read(index: int) -> bytes:
        with path.open("rb") as f:
            f.seek(index * PART_SIZE)
            return f.read(PART_SIZE)

    async def wait_pause() -> None:
        while (delay := pause_until - loop.time()) > 0:
            await asyncio.sleep(delay)

    async def worker(slot: int, sender: MTProtoSender) -> None:
        nonlocal sent, stop, pause_until, allowed, waited, streak
        while pending and stop is None:
            if slot >= allowed:  # полоса временно выключена — ждём, пока лимит снова вырастет
                await asyncio.sleep(0.5)
                continue
            await wait_pause()
            if not pending or stop is not None:
                return
            index = pending.pop()
            data = await asyncio.to_thread(read, index)
            attempt = 0
            while True:
                await wait_pause()
                if stop is not None:
                    return
                try:
                    await sender.send(SaveBigFilePartRequest(file_id, index, parts, data))
                    break
                except errors.FloodError as err:
                    seconds = int(getattr(err, "seconds", 0) or 0)
                    if seconds > MAX_FLOOD_WAIT or waited + seconds > MAX_TOTAL_FLOOD_WAIT:
                        raise  # долгое ожидание — пусть решает конвейер (покажет обратный отсчёт)
                    # Одна пауза часто приходит сразу на несколько кусков — урезаем только один раз.
                    if loop.time() + seconds > pause_until:
                        waited += seconds
                        pause_until = loop.time() + seconds + 0.5
                        streak = 0
                        if allowed > 1:
                            allowed = max(1, allowed // 2)
                        log.info("Telegram просит подождать %d с — одновременных кусков теперь %d", seconds, allowed)
                except Exception as err:  # noqa: BLE001
                    if stop is not None:
                        return
                    attempt += 1
                    if attempt >= PART_RETRIES:
                        raise
                    log.info("Кусок %d: %s, повтор", index, err)
                    await asyncio.sleep(attempt)
            sent += len(data)
            streak += 1
            if streak >= RAMP_UP_AFTER and allowed < slots:
                allowed += 1
                streak = 0
            if progress:
                try:
                    progress(min(sent, size), size)
                except BaseException as err:  # отмена из progress
                    stop = err
                    raise

    try:
        # Полосы по кругу через соединения: когда их становится меньше, нагрузка всё равно делится между всеми.
        tasks = [
            asyncio.ensure_future(worker(j * len(senders) + k, sender))
            for j in range(max(1, in_flight))
            for k, sender in enumerate(senders)
        ]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        failed = next((t for t in done if t.exception()), None)
        if failed:
            stop = stop or failed.exception()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise stop  # type: ignore[misc]
        if pending:  # все полосы вышли, а куски остались — так быть не должно
            raise RuntimeError(f"Не отправлено кусков: {len(pending)}")
    finally:
        for s in senders:
            try:
                await s.disconnect()
            except Exception:  # noqa: BLE001
                pass
    return InputFileBig(id=file_id, parts=parts, name=path.name)
