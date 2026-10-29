"""Быстрая загрузка: паузы FLOOD_WAIT от Telegram не обрывают файл."""

from __future__ import annotations

import asyncio

import pytest
from telethon import errors

from videoarchive.core import fastupload


class FakeSender:
    def __init__(self, server: "FakeServer"):
        self.server = server

    async def send(self, request):
        return await self.server.handle(request)

    async def disconnect(self):
        pass


class FakeServer:
    def __init__(self, floods: int = 0, seconds: int = 1):
        self.floods = floods  # сколько первых запросов получат «подождите»
        self.seconds = seconds
        self.parts: dict[int, bytes] = {}
        self.calls = 0

    async def handle(self, request):
        self.calls += 1
        await asyncio.sleep(0)
        if self.floods > 0:
            self.floods -= 1
            raise errors.FloodWaitError(request=None, capture=self.seconds)
        self.parts[request.file_part] = request.bytes
        return True


@pytest.fixture
def big_file(tmp_path, monkeypatch):
    monkeypatch.setattr(fastupload, "PART_SIZE", 1024)
    path = tmp_path / "clip.mp4"
    path.write_bytes(bytes(range(256)) * 40)  # 10 КБ → 10 кусков
    return path


@pytest.fixture(autouse=True)
def fake_senders(monkeypatch):
    holder = {}

    async def open_sender(_client):
        return FakeSender(holder["server"])

    monkeypatch.setattr(fastupload, "_open_sender", open_sender)
    return holder


def run(path, server, holder, **kw):
    holder["server"] = server
    return asyncio.run(fastupload.upload_big_file(None, path, connections=4, in_flight=3, **kw))  # type: ignore[arg-type]


def test_uploads_all_parts(big_file, fake_senders):
    server = FakeServer()
    sent = []
    result = run(big_file, server, fake_senders, progress=lambda s, t: sent.append(s))
    assert result.parts == 10 and result.name == "clip.mp4"
    assert b"".join(server.parts[i] for i in range(10)) == big_file.read_bytes()
    assert sent[-1] == big_file.stat().st_size


def test_short_flood_wait_is_waited_out(big_file, fake_senders):
    """Раньше FLOOD_WAIT 1–2 с обрывал файл, и загрузка начиналась заново — бесконечно."""
    server = FakeServer(floods=5, seconds=1)
    result = run(big_file, server, fake_senders)
    assert result.parts == 10
    assert sorted(server.parts) == list(range(10))
    assert server.calls == 15  # 5 отказов + 10 кусков: ни один кусок не потерян и не начат заново


def test_long_flood_wait_goes_to_pipeline(big_file, fake_senders):
    server = FakeServer(floods=1, seconds=3600)
    with pytest.raises(errors.FloodWaitError):
        run(big_file, server, fake_senders)


def test_premium_flood_is_translated():
    from videoarchive.core.telegram import FloodWait, translate

    err = translate(errors.FloodPremiumWaitError(request=None, capture=7))
    assert isinstance(err, FloodWait) and err.seconds == 7


def test_one_pause_halves_parallelism_once(big_file, fake_senders, caplog):
    """Одна пауза, пришедшая сразу на несколько кусков, урезает параллельность один раз, а не до 1."""
    import logging

    server = FakeServer(floods=4, seconds=1)  # четыре одновременных отказа = одна пауза
    with caplog.at_level(logging.INFO, logger="videoarchive.core.fastupload"):
        run(big_file, server, fake_senders)
    halvings = [r.getMessage() for r in caplog.records if "одновременных кусков" in r.getMessage()]
    assert halvings and halvings[0].endswith("теперь 6")
    assert sorted(server.parts) == list(range(10))
