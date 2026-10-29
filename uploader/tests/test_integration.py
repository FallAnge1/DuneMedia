"""Связка с настоящим сайтом (локальный `npm run dev`): реальный ApiClient + фейковый Telegram.

Запуск:  VIDEOARCHIVE_TEST_SITE=http://localhost:8787 VIDEOARCHIVE_TEST_TOKEN=va_... pytest tests/test_integration.py
Без переменных окружения тест пропускается.
"""

from __future__ import annotations

import os

import httpx
import pytest

from tests.fakes import FakeTelegram
from videoarchive.core.api import ApiClient
from videoarchive.core.pipeline import Pipeline
from videoarchive.core.queue import DONE, QueueItem, QueueStore
from videoarchive.core.textutil import clean_title

SITE = os.environ.get("VIDEOARCHIVE_TEST_SITE")
TOKEN = os.environ.get("VIDEOARCHIVE_TEST_TOKEN")
pytestmark = pytest.mark.skipif(not (SITE and TOKEN), reason="нужен локальный сайт: VIDEOARCHIVE_TEST_SITE и VIDEOARCHIVE_TEST_TOKEN")


def test_upload_to_real_site(videos):
    api = ApiClient(SITE, TOKEN)
    me = api.me()
    store, tg = QueueStore(), FakeTelegram()
    tg.next_id = 900_000 + os.getpid() % 10_000 * 10
    p = Pipeline(store, api=api, telegram=tg, channel="dune_media_test")
    item = QueueItem(path=str(videos["long"]), file_name=videos["long"].name, file_size=videos["long"].stat().st_size,
                     title=clean_title(videos["long"].name), tags=["Интеграция", "закат"], description="Проверка связки")
    store.add(item)
    p.prepare(item.id)
    p.upload(item.id)
    item = store.get(item.id)
    assert item.status == DONE, item.error

    video = api.get_video(item.id)
    assert video["title"] == "Закат над морем"
    assert video["tags"] == ["закат", "интеграция"]
    assert video["resolution_label"] == "FullHD"
    assert video["uploaded_by"] == me["name"]
    assert video["caption_dirty"] == 0
    # превью отдаётся сайтом
    res = httpx.get(f"{SITE}/media/{video['preview_key']}", headers={"Range": "bytes=0-99"})
    assert res.status_code == 206
    # дубликат теперь виден на сайте
    assert any(v["id"] == item.id for v in api.check_hash(item.file_hash))
    # уборка
    api.delete_video(item.id)


def test_photo_to_real_site(photos):
    api = ApiClient(SITE, TOKEN)
    store, tg = QueueStore(), FakeTelegram()
    tg.next_id = 950_000 + os.getpid() % 10_000 * 10
    p = Pipeline(store, api=api, telegram=tg, channel="dune_media_test")
    path = photos["rotated"]
    item = QueueItem(path=str(path), file_name=path.name, file_size=path.stat().st_size, title="Фото у окна")
    store.add(item)
    p.prepare(item.id)
    p.upload(item.id)
    item = store.get(item.id)
    assert item.status == DONE, item.error
    video = api.get_video(item.id)
    assert video["media_type"] == "photo"
    assert video["preview_key"] is None and video["duration"] is None
    assert video["orientation"] == "vertical"
    assert httpx.get(f"{SITE}/media/{video['poster_key']}").status_code == 200
    api.delete_video(item.id)
