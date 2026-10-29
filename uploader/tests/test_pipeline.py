from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from tests.fakes import FakeApi, FakeTelegram, flood, net_error
from videoarchive.core.manager import UploadManager
from videoarchive.core.pipeline import Pipeline, Suggestion, suggestion_fields
from videoarchive.core.queue import DONE, ERROR, QUEUED, READY, QueueItem, QueueStore
from videoarchive.core.telegram import TelegramConnectionError
from videoarchive.core.textutil import clean_title


def make(store, tg=None, api=None, **kw) -> Pipeline:
    return Pipeline(store, api=api if api is not None else FakeApi(), telegram=tg if tg is not None else FakeTelegram(),
                    channel="my_archive", **kw)


def add(store: QueueStore, path: Path, **fields) -> QueueItem:
    fields.setdefault("title", clean_title(path.name))
    item = QueueItem(path=str(path), file_name=path.name, file_size=path.stat().st_size, **fields)
    store.add(item)
    return item


def test_full_upload(videos):
    store, tg, api = QueueStore(), FakeTelegram(), FakeApi()
    p = make(store, tg, api)
    item = add(store, videos["long"], tags=["закат", "море"], collections=[2])
    p.prepare(item.id)
    assert store.get(item.id).status == READY
    assert item.info["resolution_label"] == "FullHD"
    assert Path(item.preview_path).exists() and Path(item.poster_path).exists()

    p.upload(item.id)
    item = store.get(item.id)
    assert item.status == DONE, item.error
    assert len(tg.sent) == 1
    assert tg.sent[0]["caption"] == "Закат над морем\n\n#закат #море"
    assert tg.sent[0]["thumb"] is not None
    video = api.videos[item.id]
    assert video["tg_message_id"] == item.tg_message_id
    assert video["tg_channel"] == "my_archive"
    assert video["preview_key"].startswith(f"previews/{item.id}-") and video["preview_key"] in api.media
    assert video["poster_key"] in api.media
    assert video["width"] == 1920 and video["collections"] == [2]
    assert video["file_hash"] == item.file_hash
    # временные файлы убраны, постер оставлен для списка
    assert item.preview_path is None and Path(item.poster_path).exists()


def test_site_failure_does_not_resend_to_telegram(videos):
    """ТЗ 6.4 п.10: если сайт упал после Telegram, повтор не отправляет видео второй раз."""
    store, tg, api = QueueStore(), FakeTelegram(), FakeApi()
    api.fail_create = [net_error()]
    p = make(store, tg, api)
    item = add(store, videos["short"])
    p.prepare(item.id)
    p.upload(item.id)
    assert store.get(item.id).status == ERROR
    assert store.get(item.id).tg_message_id is not None

    # «Перезапуск программы»: читаем очередь с диска заново.
    store2 = QueueStore()
    p2 = make(store2, tg, api)
    p2.upload(item.id)
    assert store2.get(item.id).status == DONE
    assert len(tg.sent) == 1
    assert api.calls.count("create") == 2


def test_lost_telegram_response_is_detected(videos):
    """Пост дошёл, а ответ потерялся: при повторе находим пост и не дублируем."""
    store, tg = QueueStore(), FakeTelegram()
    tg.lose_response_once = True
    p = make(store, tg, telegram_retries=0)
    item = add(store, videos["short"])
    p.prepare(item.id)
    p.upload(item.id)
    assert store.get(item.id).status == ERROR
    p.upload(item.id)
    assert store.get(item.id).status == DONE
    assert len(tg.sent) == 1
    assert store.get(item.id).tg_message_id == tg.sent[0]["id"]


def test_connection_retry_and_flood_wait(videos, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    store, tg = QueueStore(), FakeTelegram()
    tg.fail_next = [flood(2), TelegramConnectionError("Нет связи с Telegram")]
    p = make(store, tg)
    item = add(store, videos["short"])
    p.prepare(item.id)
    p.upload(item.id)
    assert store.get(item.id).status == DONE
    assert len(tg.sent) == 1


def test_size_limit(videos):
    store = QueueStore()
    item = add(store, videos["short"])
    store.update(item.id, file_size=3 * 1024**3)
    p = make(store, FakeTelegram(premium=False))
    with pytest.raises(Exception, match="больше лимита Telegram 2,0 ГБ. С Telegram Premium лимит 4 ГБ"):
        p.check_size(store.get(item.id))
    make(store, FakeTelegram(premium=True)).check_size(store.get(item.id))  # 3 ГБ < 4 ГБ — можно


def test_duplicates(videos, tmp_path):
    store, api = QueueStore(), FakeApi()
    p = make(store, api=api)
    first = add(store, videos["short"])
    p.prepare(first.id)
    api.hashes[first.file_hash] = [{"id": "x", "title": "Уже на сайте"}]

    copy = tmp_path / "copy_of_short.mp4"
    shutil.copy(videos["short"], copy)
    second = add(store, copy)
    p.prepare(second.id)
    second = store.get(second.id)
    assert {d["where"] for d in second.duplicates} == {"site", "queue"}
    assert second.is_duplicate
    p.upload(second.id)
    assert "уже есть" in store.get(second.id).error

    store.update(second.id, allow_duplicate=True, status=READY)
    p.upload(second.id)
    assert store.get(second.id).status == DONE


def test_missing_file_and_empty_title(videos, tmp_path):
    store = QueueStore()
    p = make(store)
    ghost = add(store, videos["short"])
    store.update(ghost.id, path=str(tmp_path / "nope.mp4"))
    p.prepare(ghost.id)
    assert "не найден" in store.get(ghost.id).error

    item = add(store, videos["short"], title="  ")
    p.prepare(item.id)
    p.upload(item.id)
    assert store.get(item.id).error == "Укажите название"


class FakeTagger:
    def __init__(self):
        self.calls = 0

    def suggest(self, frames, file_name, existing_tags):
        self.calls += 1
        assert len(frames) == 5 and all(f.exists() for f in frames)
        return Suggestion(title="ИИ-название", description="Описание", tags=["закат"], provider="groq", model="m")


def test_ai_suggestion_is_not_applied_silently(videos):
    store, tagger = QueueStore(), FakeTagger()
    p = make(store, tagger=tagger, ai_auto=True)
    item = add(store, videos["vertical"])
    p.prepare(item.id)
    item = store.get(item.id)
    assert tagger.calls == 1
    assert item.ai_suggestion["provider"] == "groq"
    assert item.title == "Vertical" and item.tags == []  # пользователь применяет сам


def test_ai_auto_apply(videos):
    """Настройка «сразу применять»: название и описание заменяются, теги добавляются к стоящим."""
    store, tagger = QueueStore(), FakeTagger()
    p = make(store, tagger=tagger, ai_auto=True, ai_auto_apply=True)
    item = add(store, videos["vertical"], tags=["мой тег"])
    p.prepare(item.id)
    item = store.get(item.id)
    assert (item.title, item.description) == ("ИИ-название", "Описание")
    assert item.tags == ["мой тег", "закат"]


def test_suggestion_fields_partial():
    item = QueueItem(path="x.mp4", title="Старое", description="", tags=["а"],
                     ai_suggestion={"title": "Новое", "description": "Опис", "tags": ["б", "а"]})
    assert suggestion_fields(item) == {"title": "Новое", "description": "Опис", "tags": ["а", "б"]}
    assert suggestion_fields(item, title=False, description=False) == {"tags": ["а", "б"]}
    assert suggestion_fields(QueueItem(path="x.mp4")) == {}


def test_manager_end_to_end(videos, tmp_path):
    store, tg, api = QueueStore(), FakeTelegram(), FakeApi()
    p = make(store, tg, api)
    changed: list[str] = []
    m = UploadManager(store, p, notify=changed.append)
    folder = tmp_path / "folder"
    folder.mkdir()
    for name in ("long", "vertical"):
        shutil.copy(videos[name], folder / videos[name].name)
    (folder / "notes.txt").write_text("не видео")
    added, skipped = m.add_paths([folder, videos["short"]])
    assert len(added) == 3 and skipped == []
    again, skipped = m.add_paths([videos["short"]])
    assert again == [] and "уже в очереди" in skipped[0]

    # «Загрузить всё» сразу, пока превью ещё готовятся.
    assert m.start_upload() == 3
    deadline = time.time() + 120
    while time.time() < deadline and any(i.status != DONE for i in store.all()):
        time.sleep(0.2)
    assert [i.status for i in store.all()] == [DONE, DONE, DONE], [i.error for i in store.all()]
    assert len(tg.sent) == 3 and len(api.videos) == 3
    assert changed
    m.clear_done()
    assert store.all() == []
    m.shutdown()


def test_queue_survives_restart(videos):
    store = QueueStore()
    item = add(store, videos["short"], tags=["a"])
    store.update(item.id, status=QUEUED, upload_requested=True, tg_message_id=5)
    reloaded = QueueStore()
    r = reloaded.get(item.id)
    assert r.status == QUEUED and r.upload_requested and r.tg_message_id == 5 and r.tags == ["a"]
    assert [i.id for i in reloaded.unfinished_uploads()] == [item.id]
    # прогресс не сохраняется
    assert "progress" not in r.to_dict()


def test_photo_upload(photos):
    store, tg, api = QueueStore(), FakeTelegram(), FakeApi()
    tagger = FakePhotoTagger()
    p = make(store, tg, api, tagger=tagger, ai_auto=True)
    item = add(store, photos["rotated"])
    assert item.is_photo and item.media_type == "photo"
    p.prepare(item.id)
    item = store.get(item.id)
    assert item.status == READY and item.prepared and item.preview_path is None
    assert tagger.frames == 1
    p.upload(item.id)
    item = store.get(item.id)
    assert item.status == DONE, item.error
    video = api.videos[item.id]
    assert video["media_type"] == "photo" and video["preview_key"] is None and video["duration"] is None
    assert (video["width"], video["height"]) == (600, 800)
    assert [k.split("/")[0] for k in api.media] == ["posters"]
    assert tg.sent[0]["file_name"] == "IMG_1234.jpg"


class FakePhotoTagger:
    def __init__(self):
        self.frames = 0

    def suggest(self, frames, file_name, existing_tags):
        self.frames = len(frames)
        return Suggestion(title="Фото", description="", tags=["портрет"], provider="groq", model="m")


def test_manager_accepts_photos(photos, videos, tmp_path):
    store = QueueStore()
    manager = UploadManager(store, make(store))
    try:
        (tmp_path / "notes.txt").write_text("x")
        added, skipped = manager.add_paths([photos["png"], videos["short"], tmp_path / "notes.txt"])
        assert [i.file_name for i in added] == ["Скриншот_экрана.png", "short_clip.mp4"]
        assert skipped == ["notes.txt: не похоже на видео или фото"]
    finally:
        manager.shutdown()
