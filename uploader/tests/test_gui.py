"""Проверка интерфейса без экрана (QT_QPA_PLATFORM=offscreen): фейковые Telegram и сайт."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.fakes import FakeApi, FakeTelegram  # noqa: E402
from videoarchive.core.config import Config  # noqa: E402
from videoarchive.core.queue import DONE, READY  # noqa: E402

SHOTS = Path(os.environ.get("VIDEOARCHIVE_SHOTS", "")) if os.environ.get("VIDEOARCHIVE_SHOTS") else None


def shot(widget, name: str) -> None:
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        widget.grab().save(str(SHOTS / f"{name}.png"))


@pytest.fixture
def ctx(qtbot):
    from videoarchive.ui.context import AppContext

    cfg = Config(api_id=1, api_hash="x" * 32, channel="my_archive", site_url="https://a.test", uploader_token="t", setup_done=True)
    c = AppContext(cfg)
    tg = FakeTelegram()
    api = FakeApi()
    api.tags = lambda: [{"id": 1, "name": "закат", "count": 3}, {"id": 2, "name": "море", "count": 1}]
    c.telegram, c.api, c.account = tg, api, tg.account()
    c.tags = api.tags()
    c.collections = [{"id": 1, "name": "Природа", "emoji": "🌲"}, {"id": 2, "name": "Город", "emoji": None}]
    c.uploader_name = "Анна"
    c.manager.set_pipeline(c._make_pipeline())
    yield c
    c.manager.shutdown()


def test_upload_flow(qtbot, ctx, videos, tmp_path):
    from PySide6.QtCore import QItemSelectionModel

    from videoarchive.app import dark_palette
    from videoarchive.ui.main_window import MainWindow
    from videoarchive.ui.widgets import STYLE
    from PySide6.QtWidgets import QApplication

    QApplication.instance().setPalette(dark_palette())
    QApplication.instance().setStyleSheet(STYLE)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.resize(1280, 760)
    win.show()
    shot(win, "1-empty")

    folder = tmp_path / "in"
    folder.mkdir()
    for key in ("long", "vertical", "short"):
        shutil.copy(videos[key], folder / videos[key].name)
    tab = win.upload_tab
    tab.add_paths([folder])
    qtbot.waitUntil(lambda: all(i.status == READY for i in ctx.store.all()), timeout=60_000)
    assert len(ctx.store.all()) == 3

    # редактирование одного файла
    view = tab.view
    view.selectionModel().select(tab.model.index(0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
    editor = tab.editor
    editor.title.setText("Новое имя")
    editor.title.textEdited.emit("Новое имя")
    editor.tags.setText("закат, #Море")
    editor.tags.editingFinished.emit()
    first = ctx.store.get(tab.model.ids[0])
    assert first.title == "Новое имя"
    assert first.tags == ["закат", "море"]
    shot(win, "2-queue-editor")

    # массовое действие
    sel = view.selectionModel()
    for row in range(3):
        sel.select(tab.model.index(row), QItemSelectionModel.SelectionFlag.Select)
    assert tab.editor_stack.currentIndex() == 2
    tab.bulk.tags.setText("дрон")
    tab.bulk._add_tags()
    assert all("дрон" in i.tags for i in ctx.store.all())
    shot(win, "3-bulk")

    tab.toggle_upload()
    qtbot.waitUntil(lambda: all(i.status == DONE for i in ctx.store.all()), timeout=60_000)
    assert len(ctx.telegram.sent) == 3
    assert "Новое имя" in ctx.telegram.sent[0]["caption"] or any("Новое имя" in m["caption"] for m in ctx.telegram.sent)
    view.selectionModel().clearSelection()
    shot(win, "4-done")


def test_wizard_pages(qtbot, ctx):
    from videoarchive.ui.wizard import SetupWizard

    wiz = SetupWizard(ctx)
    qtbot.addWidget(wiz)
    wiz.show()
    shot(wiz, "5-wizard-telegram")
    ai_page = wiz.page(3)
    ai_page._move(0, 1)
    assert ctx.config.ai_providers[1].id == "groq"
    wiz.setStartId(3)
    wiz.restart()
    shot(wiz, "6-wizard-ai")


def test_library_tab(qtbot, ctx, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from tests.test_library import FakeLibApi, video
    from videoarchive.app import dark_palette
    from videoarchive.ui.library_tab import DeleteDialog, LibraryTab
    from videoarchive.ui.widgets import STYLE

    QApplication.instance().setPalette(dark_palette())
    QApplication.instance().setStyleSheet(STYLE)
    vids = [video(i, created_at=1_760_000_000_000 + i, duration=10 * i, file_size=1000 * i, width=1920, height=1080,
                  resolution_label="FullHD", tags=["закат", f"тег{i}"], collections=[1] if i % 2 else [], uploaded_by="Анна")
            for i in range(1, 6)]
    vids[1]["caption_dirty"] = 1
    for v in vids:
        ctx.telegram.captions[v["tg_message_id"]] = "old"
    api = FakeLibApi(vids)
    api.library = lambda: {"videos": list(api.videos.values()), "tags": ctx.tags, "collections": ctx.collections}
    ctx.api = api

    tab = LibraryTab(ctx)
    qtbot.addWidget(tab)
    tab.resize(1200, 600)
    tab.show()
    # при загрузке устаревшая подпись сразу уходит в Telegram
    qtbot.waitUntil(lambda: tab.loaded and api.videos["v2"]["caption_dirty"] == 0, timeout=10_000)
    assert ctx.telegram.captions[102].startswith("Видео 2")
    qtbot.waitUntil(lambda: tab.model.rowCount() == 5, timeout=5000)

    tab.search.setText("тег3")
    assert tab.proxy.rowCount() == 1
    tab.search.setText("")
    idx = tab.collection_filter.findData(1)
    tab.collection_filter.setCurrentIndex(idx)
    assert tab.proxy.rowCount() == 3
    tab.collection_filter.setCurrentIndex(0)
    shot(tab, "7-library")

    # проверка синхронизации: один пост удалён в канале вручную
    del ctx.telegram.captions[104]
    from videoarchive.core.library import LibraryService

    missing = LibraryService(api, ctx.telegram).find_missing_posts(list(api.videos.values()))
    assert [v["id"] for v in missing] == ["v4"]

    dialog = DeleteDialog([vids[0]])
    qtbot.addWidget(dialog)
    assert not dialog.from_telegram
    dialog.with_tg.setChecked(True)
    assert dialog.from_telegram
