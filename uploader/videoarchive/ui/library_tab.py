"""Вкладка «Библиотека» (раздел 6.5 ТЗ): правка архива с обновлением подписей в Telegram."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressDialog,
    QPushButton, QRadioButton, QTableView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from videoarchive.core.library import LibraryService
from videoarchive.core.pipeline import format_size
from videoarchive.core.textutil import normalize_tag
from videoarchive.ui.context import AppContext
from videoarchive.ui.queue_view import format_duration
from videoarchive.ui.tasks import run_async
from videoarchive.ui.widgets import CollectionList, TagLineEdit

COLUMNS = ["Название", "Теги", "Коллекции", "Длит.", "Разрешение", "Размер", "Добавлено", "Загрузил", "Подпись"]


class LibraryModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self.videos: list[dict] = []
        self.collections: dict[int, str] = {}

    def set_data(self, videos: list[dict], collections: list[dict]) -> None:
        self.beginResetModel()
        self.videos = videos
        self.collections = {c["id"]: f"{c.get('emoji') or ''} {c['name']}".strip() for c in collections}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.videos)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        v = self.videos[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.UserRole:
            return v
        if role == Qt.ItemDataRole.UserRole + 1:  # ключ сортировки
            return [v["title"].lower(), " ".join(v["tags"]), "", v.get("duration") or 0,
                    (v.get("width") or 0) * (v.get("height") or 0), v.get("file_size") or 0, v["created_at"],
                    v.get("uploaded_by") or "", v.get("caption_dirty", 0)][col]
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return v["title"]
            if col == 1:
                return " ".join(f"#{t}" for t in v["tags"])
            if col == 2:
                return ", ".join(self.collections.get(c, "?") for c in v["collections"])
            if col == 3:
                return format_duration(v.get("duration"))
            if col == 4:
                return f"{v.get('resolution_label') or ''} {v.get('width')}×{v.get('height')}" if v.get("width") else "—"
            if col == 5:
                return format_size(v.get("file_size") or 0)
            if col == 6:
                return datetime.fromtimestamp(v["created_at"] / 1000).strftime("%d.%m.%Y")
            if col == 7:
                return v.get("uploaded_by") or ""
            if col == 8:
                return "⚠ устарела" if v.get("caption_dirty") else "✓"
        if role == Qt.ItemDataRole.ToolTipRole and col == 8 and v.get("caption_dirty"):
            return "Название, описание или теги поменяли на сайте — подпись поста обновится при синхронизации"
        return None


class LibraryFilter(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.query = ""
        self.setSortRole(Qt.ItemDataRole.UserRole + 1)

    def set_query(self, text: str) -> None:
        # Qt 6.10+: begin/endFilterChange; в старых версиях — invalidateFilter.
        if hasattr(self, "beginFilterChange"):
            self.beginFilterChange()
            self.query = text.strip().lower().lstrip("#")
            self.endFilterChange()
        else:
            self.query = text.strip().lower().lstrip("#")
            self.invalidateFilter()

    def filterAcceptsRow(self, row, parent) -> bool:  # noqa: N802
        if not self.query:
            return True
        v = self.sourceModel().videos[row]
        hay = " ".join([v["title"], v.get("description") or "", " ".join(v["tags"]), v.get("file_name") or ""]).lower()
        return all(word in hay for word in self.query.split())


# ---------------------------------------------------------------------------


class VideoEditDialog(QDialog):
    def __init__(self, ctx: AppContext, video: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.video = video
        self.setWindowTitle("Изменить видео")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.poster = QLabel("…")
        self.poster.setFixedSize(200, 120)
        self.poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.poster)
        info = QLabel(
            f"Пост: t.me/{video['tg_channel']}/{video['tg_message_id']}\n"
            f"{video.get('file_name') or ''}\n{format_duration(video.get('duration'))} · "
            f"{video.get('resolution_label') or ''} · {format_size(video.get('file_size') or 0)}"
        )
        info.setObjectName("muted")
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(info, 1)
        layout.addLayout(top)

        form = QFormLayout()
        self.title = QLineEdit(video["title"])
        self.description = QPlainTextEdit(video.get("description") or "")
        self.description.setMaximumHeight(90)
        self.tags = TagLineEdit()
        self.tags.set_tags(video["tags"])
        self.tags.set_suggestions([t["name"] for t in ctx.tags])
        self.collections = CollectionList()
        self.collections.set_collections(ctx.collections, video["collections"])
        form.addRow("Название", self.title)
        form.addRow("Описание", self.description)
        form.addRow("Теги", self.tags)
        form.addRow("Коллекции", self.collections)
        layout.addLayout(form)
        note = QLabel("Подпись поста в Telegram обновится вместе с сайтом.")
        note.setObjectName("muted")
        layout.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        self.buttons = buttons
        layout.addWidget(buttons)
        self._load_poster()

    def _load_poster(self) -> None:
        key = self.video.get("poster_key")
        api = self.ctx.api
        if not key or not api:
            self.poster.setText("нет постера")
            return

        def done(data: bytes) -> None:
            pm = QPixmap()
            if pm.loadFromData(data):
                self.poster.setPixmap(pm.scaled(self.poster.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

        run_async(lambda: api.get_bytes(f"/media/{key}"), done, lambda _e: self.poster.setText("нет постера"))

    def save(self) -> None:
        title = self.title.text().strip()
        if not title:
            self.status.setText("Название не может быть пустым")
            return
        lib = LibraryService(self.ctx.api, self.ctx.telegram)  # type: ignore[arg-type]
        args = dict(title=title, description=self.description.toPlainText().strip(), tags=self.tags.tags(),
                    collections=self.collections.checked_ids())
        self.buttons.setEnabled(False)
        self.status.setText("Сохраняю…")

        def done(result) -> None:
            if result.warning:
                QMessageBox.warning(self, "Сохранено частично", result.warning)
            self.accept()

        def fail(err: Exception) -> None:
            self.buttons.setEnabled(True)
            self.status.setText(f"Ошибка: {err}")

        run_async(lambda: lib.save_video(self.video, **args), done, fail)


class DeleteDialog(QDialog):
    def __init__(self, videos: list[dict], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Удаление")
        layout = QVBoxLayout(self)
        names = ", ".join(f"«{v['title']}»" for v in videos[:3]) + (f" и ещё {len(videos) - 3}" if len(videos) > 3 else "")
        label = QLabel(f"Удалить {names}?")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.site_only = QRadioButton("Только с сайта (пост в Telegram останется)")
        self.with_tg = QRadioButton("С сайта и из Telegram (файл удалится навсегда)")
        self.site_only.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.site_only)
        group.addButton(self.with_tg)
        layout.addWidget(self.site_only)
        layout.addWidget(self.with_tg)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Удалить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def from_telegram(self) -> bool:
        return self.with_tg.isChecked()


class CollectionsDialog(QDialog):
    """Создать, переименовать, упорядочить, удалить коллекции."""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Коллекции")
        self.setMinimumSize(460, 420)
        layout = QHBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        side = QVBoxLayout()
        for text, fn in (("Создать…", self.create), ("Переименовать…", self.rename), ("Эмодзи…", self.emoji),
                         ("Выше", lambda: self.move(-1)), ("Ниже", lambda: self.move(1)), ("Удалить", self.delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            side.addWidget(b)
        side.addStretch()
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        side.addWidget(close)
        layout.addLayout(side)
        ctx.catalog_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        current = self.current()
        self.list.clear()
        for c in self.ctx.collections:
            item = QListWidgetItem(f"{c.get('emoji') or ''} {c['name']}  ({c.get('count', 0)})".strip())
            item.setData(Qt.ItemDataRole.UserRole, c)
            self.list.addItem(item)
            if current and c["id"] == current["id"]:
                self.list.setCurrentItem(item)

    def current(self) -> dict | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _run(self, fn) -> None:
        run_async(fn, lambda _r: self.ctx.reload_catalog(), lambda e: QMessageBox.warning(self, "Коллекции", str(e)))

    def create(self) -> None:
        name, ok = QInputDialog.getText(self, "Новая коллекция", "Название:")
        if ok and name.strip():
            api = self.ctx.api
            self._run(lambda: api.create_collection(name.strip()))

    def rename(self) -> None:
        c = self.current()
        if not c:
            return
        name, ok = QInputDialog.getText(self, "Переименовать", "Название:", text=c["name"])
        if ok and name.strip():
            api = self.ctx.api
            self._run(lambda: api.patch_collection(c["id"], name=name.strip()))

    def emoji(self) -> None:
        c = self.current()
        if not c:
            return
        emoji, ok = QInputDialog.getText(self, "Эмодзи", "Эмодзи (можно оставить пустым):", text=c.get("emoji") or "")
        if ok:
            api = self.ctx.api
            self._run(lambda: api.patch_collection(c["id"], emoji=emoji.strip() or None))

    def move(self, delta: int) -> None:
        c = self.current()
        if not c:
            return
        ids = [x["id"] for x in self.ctx.collections]
        i = ids.index(c["id"])
        j = i + delta
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            api = self.ctx.api
            self._run(lambda: api.order_collections(ids))

    def delete(self) -> None:
        c = self.current()
        if c and QMessageBox.question(self, "Коллекции", f"Удалить коллекцию «{c['name']}»? Видео останутся в архиве.") == QMessageBox.StandardButton.Yes:
            api = self.ctx.api
            self._run(lambda: api.delete_collection(c["id"]))


class TagsDialog(QDialog):
    """Переименовать, слить, удалить теги. Подписи затронутых постов затем обновляются."""

    def __init__(self, ctx: AppContext, on_changed, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.on_changed = on_changed
        self.setWindowTitle("Теги")
        self.setMinimumSize(560, 520)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти тег")
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Тег", "Видео"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, fn in (("Переименовать…", self.rename), ("Слить выбранные…", self.merge), ("Удалить", self.delete),
                         ("Удалить неиспользуемые", self.delete_unused)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        layout.addLayout(row)
        hint = QLabel("Выделите несколько тегов (Ctrl/Shift), чтобы слить их в один. Подписи постов с этими тегами обновятся.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        ctx.catalog_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        q = self.search.text().strip().lower().lstrip("#")
        tags = [t for t in self.ctx.tags if not q or q in t["name"]]
        self.table.setRowCount(len(tags))
        for r, t in enumerate(tags):
            name = QTableWidgetItem(f"#{t['name']}")
            name.setData(Qt.ItemDataRole.UserRole, t)
            self.table.setItem(r, 0, name)
            count = QTableWidgetItem(str(t["count"]))
            count.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 1, count)

    def selected(self) -> list[dict]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in rows]

    def _run(self, fn) -> None:
        def done(_r) -> None:
            self.ctx.reload_catalog()
            self.on_changed()

        run_async(fn, done, lambda e: QMessageBox.warning(self, "Теги", str(e)))

    def rename(self) -> None:
        sel = self.selected()
        if len(sel) != 1:
            QMessageBox.information(self, "Теги", "Выберите один тег")
            return
        t = sel[0]
        name, ok = QInputDialog.getText(self, "Переименовать тег", "Новое имя:", text=t["name"])
        new = normalize_tag(name) if ok else None
        if not new or new == t["name"]:
            return
        existing = next((x for x in self.ctx.tags if x["name"] == new), None)
        api = self.ctx.api
        if existing:
            if QMessageBox.question(self, "Теги", f"Тег «{new}» уже есть. Слить «{t['name']}» с ним?") == QMessageBox.StandardButton.Yes:
                self._run(lambda: api.merge_tags([t["id"]], existing["id"]))
            return
        self._run(lambda: api.rename_tag(t["id"], new))

    def merge(self) -> None:
        sel = self.selected()
        if len(sel) < 2:
            QMessageBox.information(self, "Теги", "Выберите хотя бы два тега")
            return
        names = [t["name"] for t in sel]
        target, ok = QInputDialog.getItem(self, "Слить теги", "Оставить тег:", names, 0, False)
        if not ok:
            return
        target_tag = next(t for t in sel if t["name"] == target)
        sources = [t["id"] for t in sel if t["id"] != target_tag["id"]]
        api = self.ctx.api
        self._run(lambda: api.merge_tags(sources, target_tag["id"]))

    def delete(self) -> None:
        sel = self.selected()
        if not sel:
            return
        total = sum(t["count"] for t in sel)
        names = ", ".join(t["name"] for t in sel[:5])
        if QMessageBox.question(self, "Теги", f"Удалить теги: {names}? Они пропадут у {total} видео.") != QMessageBox.StandardButton.Yes:
            return
        api = self.ctx.api
        self._run(lambda: [api.delete_tag(t["id"]) for t in sel])

    def delete_unused(self) -> None:
        api = self.ctx.api
        self._run(api.delete_unused_tags)


# ---------------------------------------------------------------------------


class LibraryTab(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.loaded = False
        self.videos: list[dict] = []
        self._auto_synced = False

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по названию, описанию, тегам, имени файла")
        self.search.setClearButtonEnabled(True)
        top.addWidget(self.search, 1)
        self.collection_filter = QComboBox()
        self.collection_filter.setMinimumWidth(200)
        self.collection_filter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.collection_filter.currentIndexChanged.connect(self._apply_filter)
        top.addWidget(self.collection_filter)
        refresh = QPushButton("Обновить")
        refresh.clicked.connect(self.reload)
        top.addWidget(refresh)
        layout.addLayout(top)

        actions = QHBoxLayout()
        self.edit_btn = QPushButton("Изменить…")
        self.edit_btn.clicked.connect(self.edit_selected)
        self.delete_btn = QPushButton("Удалить…")
        self.delete_btn.clicked.connect(self.delete_selected)
        cols = QPushButton("Коллекции…")
        cols.clicked.connect(lambda: CollectionsDialog(self.ctx, self).exec())
        tags = QPushButton("Теги…")
        tags.clicked.connect(lambda: TagsDialog(self.ctx, self.reload_and_sync, self).exec())
        self.sync_btn = QPushButton("Обновить подписи")
        self.sync_btn.clicked.connect(lambda: self.sync_captions(interactive=True))
        check = QPushButton("Проверить синхронизацию")
        check.clicked.connect(self.check_sync)
        for b in (self.edit_btn, self.delete_btn, cols, tags, self.sync_btn, check):
            actions.addWidget(b)
        actions.addStretch()
        self.status = QLabel()
        self.status.setObjectName("muted")
        actions.addWidget(self.status)
        layout.addLayout(actions)

        self.model = LibraryModel()
        self.proxy = LibraryFilter()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(6, Qt.SortOrder.DescendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col in range(2, len(COLUMNS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(lambda _i: self.edit_selected())
        layout.addWidget(self.table, 1)

        self.search.textChanged.connect(self.proxy.set_query)
        ctx.account_changed.connect(self._on_account)
        ctx.catalog_changed.connect(self._refresh_collections)

    # ---- загрузка ----

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self.loaded:
            self.reload()

    def _on_account(self) -> None:
        if self.ctx.api and (self.loaded or self.isVisible()):
            self.reload()
        elif self.ctx.api and not self._auto_synced:
            self.reload()  # фоновая загрузка — чтобы досинхронизировать подписи после правок на сайте

    def _refresh_collections(self) -> None:
        current = self.collection_filter.currentData()
        self.collection_filter.blockSignals(True)
        self.collection_filter.clear()
        self.collection_filter.addItem("Все коллекции", None)
        for c in self.ctx.collections:
            self.collection_filter.addItem(f"{c.get('emoji') or ''} {c['name']}".strip(), c["id"])
        idx = self.collection_filter.findData(current)
        self.collection_filter.setCurrentIndex(max(idx, 0))
        self.collection_filter.blockSignals(False)
        self._apply_filter()

    def reload(self) -> None:
        if not self.ctx.api:
            self.status.setText("Сайт не настроен")
            return
        api = self.ctx.api
        self.status.setText("Загружаю…")

        def done(lib: dict) -> None:
            self.loaded = True
            self.ctx.tags, self.ctx.collections = lib["tags"], lib["collections"]
            self.ctx.catalog_changed.emit()
            self.videos = lib["videos"]
            self._apply_filter()
            # Правки, сделанные на сайте, сразу доносим до Telegram.
            if not self._auto_synced and self.ctx.account and any(v.get("caption_dirty") for v in self.videos):
                self._auto_synced = True
                self.sync_captions(interactive=False)

        run_async(api.library, done, lambda e: self.status.setText(f"Ошибка: {e}"))

    def reload_and_sync(self) -> None:
        self._auto_synced = False
        self.reload()

    def _apply_filter(self) -> None:
        cid = self.collection_filter.currentData()
        videos = [v for v in self.videos if cid is None or cid in v["collections"]]
        self.model.set_data(videos, self.ctx.collections)
        dirty = sum(1 for v in self.videos if v.get("caption_dirty"))
        self.sync_btn.setText(f"Обновить подписи ({dirty})" if dirty else "Обновить подписи")
        self.sync_btn.setEnabled(bool(dirty))
        self.status.setText(f"Видео: {len(self.videos)}")

    def selected(self) -> list[dict]:
        rows = {self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()}
        return [self.model.videos[r] for r in sorted(rows)]

    def _need(self, telegram: bool = False) -> bool:
        if not self.ctx.api:
            QMessageBox.warning(self, "Библиотека", "Сайт не настроен")
            return False
        if telegram and not self.ctx.account:
            QMessageBox.warning(self, "Библиотека", self.ctx.account_error or "Нет входа в Telegram")
            return False
        return True

    # ---- действия ----

    def edit_selected(self) -> None:
        sel = self.selected()
        if len(sel) != 1 or not self._need():
            if len(sel) > 1:
                QMessageBox.information(self, "Библиотека", "Выберите одно видео. Массовые правки удобнее делать на сайте в режиме выбора.")
            return
        if VideoEditDialog(self.ctx, sel[0], self).exec():
            self.reload()

    def delete_selected(self) -> None:
        sel = self.selected()
        if not sel or not self._need():
            return
        dialog = DeleteDialog(sel, self)
        if not dialog.exec():
            return
        from_tg = dialog.from_telegram
        if from_tg and not self._need(telegram=True):
            return
        lib = LibraryService(self.ctx.api, self.ctx.telegram)  # type: ignore[arg-type]

        def go() -> list[str]:
            warnings = []
            for v in sel:
                w = lib.delete_video(v, from_telegram=from_tg)
                if w:
                    warnings.append(f"«{v['title']}»: {w}")
            return warnings

        def done(warnings: list[str]) -> None:
            if warnings:
                QMessageBox.warning(self, "Удаление", "\n".join(warnings))
            self.ctx.message.emit(f"Удалено: {len(sel)}")
            self.reload()

        run_async(go, done, lambda e: QMessageBox.warning(self, "Удаление", str(e)))

    def sync_captions(self, interactive: bool = True) -> None:
        if not self._need(telegram=True):
            return
        dirty = [v for v in self.videos if v.get("caption_dirty")]
        if not dirty:
            return
        lib = LibraryService(self.ctx.api, self.ctx.telegram)  # type: ignore[arg-type]
        self.status.setText(f"Обновляю подписи в Telegram: {len(dirty)}…")
        self.sync_btn.setEnabled(False)

        def done(result: tuple[int, list[str]]) -> None:
            ok, errors = result
            self.ctx.message.emit(f"Подписи в Telegram обновлены: {ok}" + (f", ошибок: {len(errors)}" if errors else ""))
            if errors and interactive:
                QMessageBox.warning(self, "Подписи", "\n".join(errors[:15]))
            self.reload()

        run_async(lambda: lib.sync_dirty_captions(dirty), done, lambda e: self.status.setText(f"Ошибка: {e}"))

    def check_sync(self) -> None:
        if not self._need(telegram=True) or not self.videos:
            return
        lib = LibraryService(self.ctx.api, self.ctx.telegram)  # type: ignore[arg-type]
        videos = list(self.videos)
        progress = QProgressDialog("Проверяю посты в канале…", "", 0, 0, self)
        progress.setCancelButton(None)
        progress.setWindowTitle("Проверка синхронизации")
        progress.show()

        def done(missing: list[dict]) -> None:
            progress.close()
            if not missing:
                QMessageBox.information(self, "Проверка синхронизации", f"Все {len(videos)} постов на месте.")
                return
            names = "\n".join(f"• {v['title']} (пост {v['tg_message_id']})" for v in missing[:20])
            more = f"\n…и ещё {len(missing) - 20}" if len(missing) > 20 else ""
            if QMessageBox.question(
                self, "Проверка синхронизации",
                f"В канале нет постов для {len(missing)} записей (их удалили вручную):\n\n{names}{more}\n\nУбрать эти записи с сайта?",
            ) == QMessageBox.StandardButton.Yes:
                run_async(lambda: lib.remove_from_site(missing), lambda errs: (
                    errs and QMessageBox.warning(self, "Удаление", "\n".join(errs)), self.reload()))

        def fail(err: Exception) -> None:
            progress.close()
            QMessageBox.warning(self, "Проверка синхронизации", str(err))

        run_async(lambda: lib.find_missing_posts(videos), done, fail)
