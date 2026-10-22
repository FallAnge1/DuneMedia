from __future__ import annotations

from tests.fakes import FakeTelegram
from videoarchive.core.api import ApiError
from videoarchive.core.library import LibraryService
from videoarchive.core.telegram import TelegramError


class FakeLibApi:
    def __init__(self, videos: list[dict]):
        self.videos = {v["id"]: dict(v) for v in videos}
        self.patches: list[tuple[str, dict]] = []
        self.deleted: list[str] = []

    def patch_video(self, vid, changes):
        self.patches.append((vid, changes))
        v = self.videos[vid]
        for k, val in changes.items():
            if k == "caption_synced":
                v["caption_dirty"] = 0
            else:
                v[k] = val
        if {"title", "description", "tags"} & changes.keys() and not changes.get("caption_synced"):
            v["caption_dirty"] = 1
        return dict(v)

    def delete_video(self, vid):
        self.deleted.append(vid)
        return self.videos.pop(vid)


def video(i: int, **kw) -> dict:
    return {"id": f"v{i}", "tg_channel": "ch", "tg_message_id": 100 + i, "title": f"Видео {i}", "description": None,
            "tags": ["a"], "collections": [], "caption_dirty": 0, **kw}


def setup(videos):
    tg = FakeTelegram()
    for v in videos:
        tg.captions[v["tg_message_id"]] = "old"
    api = FakeLibApi(videos)
    return LibraryService(api, tg), api, tg


def test_save_updates_caption_then_site():
    lib, api, tg = setup([video(1)])
    r = lib.save_video(api.videos["v1"], title="Новое", description="Описание", tags=["закат", "море"], collections=[3])
    assert r.caption_updated and r.warning is None
    assert tg.captions[101] == "Новое\nОписание\n\n#закат #море"
    vid, changes = api.patches[0]
    assert changes["caption_synced"] is True and changes["collections"] == [3]
    assert api.videos["v1"]["caption_dirty"] == 0


def test_collections_only_does_not_touch_telegram():
    lib, api, tg = setup([video(1)])
    lib.save_video(api.videos["v1"], title="Видео 1", description="", tags=["a"], collections=[2])
    assert tg.captions[101] == "old"
    assert api.patches == [("v1", {"collections": [2]})]


def test_telegram_failure_marks_caption_dirty():
    lib, api, tg = setup([video(1)])

    def broken(*a):
        raise TelegramError("Нет права редактировать")

    tg.edit_caption = broken
    r = lib.save_video(api.videos["v1"], title="X", description="", tags=["a"], collections=[])
    assert not r.caption_updated and "подпись в Telegram — нет" in r.warning
    assert api.videos["v1"]["title"] == "X" and api.videos["v1"]["caption_dirty"] == 1


def test_sync_dirty_captions():
    vids = [video(1, caption_dirty=1, title="Правка с сайта"), video(2), video(3, caption_dirty=1)]
    lib, api, tg = setup(vids)
    progress = []
    done, errors = lib.sync_dirty_captions(list(api.videos.values()), lambda a, b: progress.append((a, b)))
    assert done == 2 and errors == []
    assert tg.captions[101].startswith("Правка с сайта") and tg.captions[102] == "old"
    assert all(v["caption_dirty"] == 0 for v in api.videos.values())
    assert progress[-1] == (2, 2)


def test_delete_variants():
    lib, api, tg = setup([video(1), video(2)])
    lib.delete_video(api.videos["v1"], from_telegram=False)
    assert api.deleted == ["v1"] and tg.deleted == []
    lib.delete_video(api.videos["v2"], from_telegram=True)
    assert tg.deleted == [102] and "v2" in api.deleted


def test_find_missing_posts():
    vids = [video(1), video(2), video(3)]
    lib, api, tg = setup(vids)
    del tg.captions[102]  # пост удалили в канале вручную
    missing = lib.find_missing_posts(list(api.videos.values()))
    assert [v["id"] for v in missing] == ["v2"]
    assert lib.remove_from_site(missing) == []
    assert "v2" not in api.videos


def test_remove_errors_collected():
    lib, api, tg = setup([video(1)])

    def fail(vid):
        raise ApiError(500, "x", "Сбой")

    api.delete_video = fail
    assert lib.remove_from_site([api.videos["v1"]]) == ["«Видео 1»: Сбой"]
