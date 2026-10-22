"""Вкладка «Загрузка» (раздел 6.3 ТЗ)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListView, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from videoarchive.core.manager import VIDEO_EXTENSIONS
from videoarchive.core.pipeline import format_size
from videoarchive.core.queue import DONE, ERROR, QUEUED, UPLOADING, QueueItem
from videoarchive.core.textutil import normalize_tags
from videoarchive.ui.context import AppContext
from videoarchive.ui.queue_view import ItemRole, QueueDelegate, QueueModel, format_duration, status_line
from videoarchive.ui.tasks import run_async
from videoarchive.ui.widgets import Banner, CollectionList, TagLineEdit, section_label

LOCKED = (UPLOADING, DONE)


class ItemEditor(QWidget):
    """Редактирование одного файла: название, описание, теги, коллекции, ИИ, дубликаты."""

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.item_id: str | None = None
        self._loading = False
        self._save_timer = QTimer(self, singleShot=True, interval=600)
        self._save_timer.timeout.connect(self.ctx.store.save)

        layout = QVBoxLayout(self)
        self.header = QLabel()
        self.header.setObjectName("title")
        self.header.setWordWrap(True)
        layout.addWidget(self.header)
        self.meta = QLabel()
        self.meta.setObjectName("muted")
        self.meta.setWordWrap(True)
        self.meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.meta)

        self.error_banner = Banner("", "Повторить", kind="warn")
        self.error_banner.button.clicked.connect(lambda: self.item_id and self.ctx.manager.retry(self.item_id))
        layout.addWidget(self.error_banner)

        self.dup_banner = Banner("", None, kind="warn")
        self.dup_check = QCheckBox("Загрузить всё равно")
        self.dup_banner.layout().addWidget(self.dup_check)
        self.dup_check.toggled.connect(lambda v: self._update(allow_duplicate=v))
        layout.addWidget(self.dup_banner)

        form = QFormLayout()
        self.title = QLineEdit()
        self.title.setMaxLength(300)
        self.title.textEdited.connect(lambda t: self._update(title=t))
        form.addRow("Название", self.title)
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText("Необязательно")
        self.description.setMaximumHeight(90)
        self.description.textChanged.connect(lambda: self._loading or self._update(description=self.description.toPlainText()))
        form.addRow("Описание", self.description)
        self.tags = TagLineEdit()
        self.tags.tags_changed.connect(lambda tags: self._update(tags=tags))
        form.addRow("Теги", self.tags)
        layout.addLayout(form)

        col_row = QHBoxLayout()
        col_row.addWidget(section_label("Коллекции"))
        col_row.addStretch()
        new_col = QPushButton("+ Новая коллекция")
        new_col.setFlat(True)
        new_col.clicked.connect(self._new_collection)
        col_row.addWidget(new_col)
        layout.addLayout(col_row)
        self.collections = CollectionList()
        self.collections.selection_changed.connect(lambda ids: self._update(collections=ids))
        layout.addWidget(self.collections)

        ai_row = QHBoxLayout()
        self.ai_button = QPushButton("✨ Предложить теги (ИИ)")
        self.ai_button.clicked.connect(self._suggest)
        ai_row.addWidget(self.ai_button)
        ai_row.addStretch()
        layout.addLayout(ai_row)

        self.ai_banner = Banner("", None, kind="ai")
        self.ai_banner.label.setTextFormat(Qt.TextFormat.PlainText)
        ai_buttons = QHBoxLayout()
        self.ai_apply_all = QPushButton("Применить всё")
        self.ai_apply_all.clicked.connect(lambda: self._apply_ai(title=True, description=True, tags=True))
        self.ai_apply_tags = QPushButton("Добавить теги")
        self.ai_apply_tags.clicked.connect(lambda: self._apply_ai(tags=True))
        self.ai_apply_title = QPushButton("Взять название")
        self.ai_apply_title.clicked.connect(lambda: self._apply_ai(title=True))
        for b in (self.ai_apply_all, self.ai_apply_tags, self.ai_apply_title):
            ai_buttons.addWidget(b)
        wrap = QWidget()
        wrap.setLayout(ai_buttons)
        self.ai_banner.layout().addWidget(wrap)
        layout.addWidget(self.ai_banner)
        self.ai_error = QLabel()
        self.ai_error.setObjectName("error")
        self.ai_error.setWordWrap(True)
        layout.addWidget(self.ai_error)

        self.caption_note = QLabel("Подпись поста: название, описание и хештеги.")
        self.caption_note.setObjectName("muted")
        layout.addWidget(self.caption_note)
        layout.addStretch()

        ctx.item_changed.connect(self._on_item_changed)
        ctx.catalog_changed.connect(self._refresh_catalog)

    # ---- данные ----

    def item(self) -> QueueItem | None:
        return self.ctx.store.get(self.item_id) if self.item_id else None

    def show_item(self, item_id: str) -> None:
        self.item_id = item_id
        self.reload()

    def _refresh_catalog(self) -> None:
        self.tags.set_suggestions([t["name"] for t in self.ctx.tags])
        item = self.item()
        self.collections.set_collections(self.ctx.collections, item.collections if item else [])

    def reload(self) -> None:
        item = self.item()
        if not item:
            return
        self._loading = True
        self.header.setText(item.title or item.file_name)
        info = item.info or {}
        meta = [item.path, format_size(item.file_size)]
        if info:
            meta += [
                format_duration(info.get("duration")),
                f"{info.get('width')}×{info.get('height')} ({info.get('resolution_label')})",
                f"{info.get('fps') or '—'} к/с",
                info.get("codec") or "",
            ]
        meta.append(status_line(item))
        self.meta.setText("  ·  ".join(str(m) for m in meta if m))

        if self.title.text() != item.title:
            self.title.setText(item.title)
        if self.description.toPlainText() != item.description:
            self.description.setPlainText(item.description)
        if not self.tags.hasFocus():
            self.tags.set_tags(item.tags)
        self._refresh_catalog()

        locked = item.status in LOCKED
        for w in (self.title, self.description, self.tags, self.collections, self.ai_button):
            w.setEnabled(not locked)

        self.error_banner.setVisible(item.status == ERROR)
        self.error_banner.label.setText(f"Ошибка: {item.error}" if item.error else "")

        self.dup_banner.setVisible(bool(item.duplicates) and not item.tg_message_id)
        if item.duplicates:
            where = {"site": "на сайте", "queue": "в очереди"}
            lines = [f"«{d['title']}» ({where.get(d['where'], '')})" for d in item.duplicates[:3]]
            self.dup_banner.label.setText("⚠ Такое видео уже есть: " + ", ".join(lines))
            self.dup_check.blockSignals(True)
            self.dup_check.setChecked(item.allow_duplicate)
            self.dup_check.blockSignals(False)

        s = item.ai_suggestion
        self.ai_banner.setVisible(bool(s) and not locked)
        if s:
            self.ai_banner.label.setText(
                f"✨ Предложение ИИ ({s.get('provider')}):\n«{s.get('title')}»\n{s.get('description') or ''}\n"
                + " ".join(f"#{t}" for t in s.get("tags", []))
            )
        busy_ai = item.stage == "ai"
        self.ai_button.setText("✨ ИИ думает…" if busy_ai else "✨ Предложить теги (ИИ)")
        self.ai_button.setEnabled(not locked and not busy_ai and bool(item.info))
        self.ai_error.setVisible(bool(item.ai_error))
        self.ai_error.setText(f"ИИ: {item.ai_error}" if item.ai_error else "")
        self._loading = False

    def _on_item_changed(self, item_id: str) -> None:
        if item_id == self.item_id and self.isVisible():
            self.reload()

    def _update(self, **fields: object) -> None:
        if self._loading or not self.item_id:
            return
        self.ctx.store.update(self.item_id, save=False, **fields)
        self._save_timer.start()
        self.ctx.item_changed.emit(self.item_id)

    # ---- действия ----

    def _suggest(self) -> None:
        if not self.ctx.manager.pipeline.tagger:
            QMessageBox.information(self, "ИИ-теги", "Не настроен ни один провайдер ИИ. Добавьте ключи в настройках.")
            return
        if self.item_id:
            self.ctx.manager.suggest_tags(self.item_id)
            self.ctx.item_changed.emit(self.item_id)

    def _apply_ai(self, title: bool = False, description: bool = False, tags: bool = False) -> None:
        item = self.item()
        if not item or not item.ai_suggestion:
            return
        s = item.ai_suggestion
        fields: dict[str, object] = {}
        if title and s.get("title"):
            fields["title"] = s["title"]
        if description and s.get("description"):
            fields["description"] = s["description"]
        if tags:
            fields["tags"] = normalize_tags(item.tags + list(s.get("tags", [])))
        self.ctx.store.update(item.id, **fields)
        self.ctx.item_changed.emit(item.id)

    def _new_collection(self) -> None:
        if not self.ctx.api:
            QMessageBox.warning(self, "Коллекции", "Сайт не настроен")
            return
        name, ok = QInputDialog.getText(self, "Новая коллекция", "Название:")
        if not ok or not name.strip():
            return
        api = self.ctx.api
        run_async(lambda: api.create_collection(name.strip()), lambda _c: self.ctx.reload_catalog(),
                  lambda err: QMessageBox.warning(self, "Коллекции", str(err)))


class BulkEditor(QWidget):
    """Массовые действия над несколькими выбранными файлами."""

    def __init__(self, ctx: AppContext, selected_ids):
        super().__init__()
        self.ctx = ctx
        self.selected_ids = selected_ids  # функция → список id
        layout = QVBoxLayout(self)
        self.header = QLabel()
        self.header.setObjectName("title")
        layout.addWidget(self.header)

        layout.addWidget(section_label("Добавить теги выбранным"))
        row = QHBoxLayout()
        self.tags = TagLineEdit()
        row.addWidget(self.tags)
        add = QPushButton("Добавить")
        add.clicked.connect(self._add_tags)
        row.addWidget(add)
        layout.addLayout(row)

        layout.addWidget(section_label("Убрать тег"))
        row = QHBoxLayout()
        self.remove_tag = QComboBox()
        row.addWidget(self.remove_tag, 1)
        rm = QPushButton("Убрать")
        rm.clicked.connect(self._remove_tag)
        row.addWidget(rm)
        layout.addLayout(row)

        layout.addWidget(section_label("Коллекция"))
        row = QHBoxLayout()
        self.collection = QComboBox()
        row.addWidget(self.collection, 1)
        add_c = QPushButton("Добавить в коллекцию")
        add_c.clicked.connect(lambda: self._collection(True))
        row.addWidget(add_c)
        rm_c = QPushButton("Убрать")
        rm_c.clicked.connect(lambda: self._collection(False))
        row.addWidget(rm_c)
        layout.addLayout(row)

        layout.addWidget(section_label("ИИ"))
        ai = QPushButton("✨ Предложить теги для всех выбранных")
        ai.clicked.connect(self._ai_all)
        layout.addWidget(ai)
        apply_ai = QPushButton("Добавить предложенные ИИ теги")
        apply_ai.clicked.connect(self._apply_ai_tags)
        layout.addWidget(apply_ai)

        layout.addWidget(section_label("Загрузка"))
        upload = QPushButton("Загрузить выбранные")
        upload.setObjectName("primary")
        upload.clicked.connect(lambda: self.ctx.manager.start_upload(self.selected_ids()))
        layout.addWidget(upload)
        layout.addStretch()
        ctx.catalog_changed.connect(self.refresh)

    def items(self) -> list[QueueItem]:
        return [i for i in (self.ctx.store.get(x) for x in self.selected_ids()) if i and i.status not in LOCKED]

    def refresh(self) -> None:
        ids = self.selected_ids()
        self.header.setText(f"Выбрано файлов: {len(ids)}")
        self.tags.set_suggestions([t["name"] for t in self.ctx.tags])
        present = sorted({t for i in self.items() for t in i.tags})
        self.remove_tag.clear()
        self.remove_tag.addItems(present)
        self.collection.clear()
        for c in self.ctx.collections:
            self.collection.addItem(f"{c.get('emoji') or ''} {c['name']}".strip(), c["id"])

    def _each(self, change) -> None:
        for item in self.items():
            fields = change(item)
            if fields:
                self.ctx.store.update(item.id, save=False, **fields)
                self.ctx.item_changed.emit(item.id)
        self.ctx.store.save()
        self.refresh()

    def _add_tags(self) -> None:
        new = self.tags.tags()
        if new:
            self._each(lambda i: {"tags": normalize_tags(i.tags + new)})
            self.tags.clear()

    def _remove_tag(self) -> None:
        tag = self.remove_tag.currentText()
        if tag:
            self._each(lambda i: {"tags": [t for t in i.tags if t != tag]})

    def _collection(self, add: bool) -> None:
        cid = self.collection.currentData()
        if cid is None:
            return
        if add:
            self._each(lambda i: {"collections": i.collections + [cid]} if cid not in i.collections else None)
        else:
            self._each(lambda i: {"collections": [c for c in i.collections if c != cid]})

    def _ai_all(self) -> None:
        if not self.ctx.manager.pipeline.tagger:
            QMessageBox.information(self, "ИИ-теги", "Не настроен ни один провайдер ИИ. Добавьте ключи в настройках.")
            return
        for item in self.items():
            if item.info:
                self.ctx.manager.suggest_tags(item.id)

    def _apply_ai_tags(self) -> None:
        self._each(lambda i: {"tags": normalize_tags(i.tags + i.ai_suggestion.get("tags", []))} if i.ai_suggestion else None)


class UploadTab(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        add_files = QPushButton("Добавить файлы…")
        add_files.clicked.connect(self.choose_files)
        add_folder = QPushButton("Добавить папку…")
        add_folder.clicked.connect(self.choose_folder)
        self.upload_btn = QPushButton("Загрузить всё")
        self.upload_btn.setObjectName("primary")
        self.upload_btn.clicked.connect(self.toggle_upload)
        retry = QPushButton("Повторить ошибки")
        retry.clicked.connect(self.retry_errors)
        clear = QPushButton("Убрать загруженные")
        clear.clicked.connect(self.ctx.manager.clear_done)
        remove = QPushButton("Удалить из очереди")
        remove.clicked.connect(self.remove_selected)
        for w in (add_files, add_folder, retry, clear, remove):
            toolbar.addWidget(w)
        toolbar.addStretch()
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        toolbar.addWidget(self.summary)
        toolbar.addWidget(self.upload_btn)
        layout.addLayout(toolbar)

        self.resume_banner = Banner("", "Продолжить", kind="info")
        self.resume_banner.button.clicked.connect(self._resume)
        self.resume_banner.hide()
        layout.addWidget(self.resume_banner)

        splitter = QSplitter()
        left = QStackedWidget()
        self.drop_hint = QLabel("Перетащите сюда видео или папки\nили нажмите «Добавить файлы…»")
        self.drop_hint.setObjectName("drop")
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.drop_hint)

        self.model = QueueModel(ctx.store)
        self.view = QListView()
        self.view.setObjectName("queue")
        self.view.setModel(self.model)
        self.view.setItemDelegate(QueueDelegate(self.view))
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setMouseTracking(True)
        self.view.setUniformItemSizes(True)
        self.view.selectionModel().selectionChanged.connect(self._on_selection)
        left.addWidget(self.view)
        self.left = left
        splitter.addWidget(left)

        self.editor_stack = QStackedWidget()
        empty = QLabel("Выберите файл в списке, чтобы изменить название, теги и коллекции.\n"
                       "Выделите несколько (Ctrl/Shift), чтобы изменить их разом.")
        empty.setObjectName("muted")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setWordWrap(True)
        self.editor = ItemEditor(ctx)
        self.bulk = BulkEditor(ctx, self.selected_ids)
        for w in (empty, self.editor, self.bulk):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(w)
            self.editor_stack.addWidget(scroll)
        splitter.addWidget(self.editor_stack)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([640, 460])
        layout.addWidget(splitter, 1)

        ctx.queue_changed.connect(self._on_queue_changed)
        ctx.item_changed.connect(self._on_item_changed)
        self._summary_timer = QTimer(self, interval=500)
        self._summary_timer.timeout.connect(self._update_summary)
        self._summary_timer.start()
        self._on_queue_changed()

    # ---- очередь ----

    def selected_ids(self) -> list[str]:
        return [self.model.ids[i.row()] for i in self.view.selectionModel().selectedRows()]

    def _on_queue_changed(self) -> None:
        selected = set(self.selected_ids())
        self.model.reload()
        self.left.setCurrentIndex(1 if self.model.ids else 0)
        sel = self.view.selectionModel()
        for row, item_id in enumerate(self.model.ids):
            if item_id in selected:
                sel.select(self.model.index(row), QItemSelectionModel.SelectionFlag.Select)
        self._on_selection()
        self._update_summary()

    def _on_item_changed(self, item_id: str) -> None:
        self.model.item_changed(item_id)

    def _on_selection(self, *_args) -> None:
        ids = self.selected_ids()
        if len(ids) == 1:
            self.editor.show_item(ids[0])
            self.editor_stack.setCurrentIndex(1)
        elif len(ids) > 1:
            self.bulk.refresh()
            self.editor_stack.setCurrentIndex(2)
        else:
            self.editor_stack.setCurrentIndex(0)

    def _update_summary(self) -> None:
        items = self.ctx.store.all()
        counts = {s: sum(1 for i in items if i.status == s) for s in (DONE, ERROR, UPLOADING, QUEUED)}
        waiting = sum(1 for i in items if i.upload_requested and i.status != UPLOADING)
        parts = [f"в очереди: {len(items)}"]
        if counts[DONE]:
            parts.append(f"загружено: {counts[DONE]}")
        if counts[ERROR]:
            parts.append(f"ошибок: {counts[ERROR]}")
        if waiting:
            parts.append(f"ждут загрузки: {waiting}")
        self.summary.setText("  ·  ".join(parts))
        self.upload_btn.setText("Остановить" if self.ctx.manager.uploading else "Загрузить всё")

    # ---- добавление ----

    def add_paths(self, paths: list[Path]) -> None:
        added, skipped = self.ctx.manager.add_paths(paths)
        if added:
            row = self.model.ids.index(added[0].id)
            self.view.setCurrentIndex(self.model.index(row))
        if skipped:
            self.ctx.message.emit(f"Пропущено: {len(skipped)} — " + "; ".join(skipped[:3]))

    def choose_files(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(self, "Выберите видео", "", f"Видео ({exts});;Все файлы (*)")
        if files:
            self.add_paths([Path(f) for f in files])

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку с видео")
        if folder:
            self.add_paths([Path(folder)])

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()

    # ---- загрузка ----

    def toggle_upload(self) -> None:
        if self.ctx.manager.uploading:
            self.ctx.manager.stop()
            return
        if not self.ctx.telegram or not self.ctx.account:
            QMessageBox.warning(self, "Загрузка", self.ctx.account_error or "Сначала войдите в Telegram (Настройки)")
            return
        if not self.ctx.api:
            QMessageBox.warning(self, "Загрузка", "Сначала настройте сайт и токен загрузчика (Настройки)")
            return
        items = self.ctx.store.all()
        missing_title = [i for i in items if i.status not in (DONE,) and not i.title.strip()]
        if missing_title:
            QMessageBox.warning(self, "Загрузка", f"У {len(missing_title)} файлов нет названия")
            return
        count = self.ctx.manager.start_upload()
        dups = sum(1 for i in items if i.is_duplicate and i.status != DONE)
        msg = f"В загрузку поставлено: {count}"
        if dups:
            msg += f". Дубликаты пропущены: {dups} (отметьте «Загрузить всё равно», если нужно)"
        self.ctx.message.emit(msg)

    def retry_errors(self) -> None:
        for item in self.ctx.store.all():
            if item.status == ERROR:
                self.ctx.manager.retry(item.id)

    def remove_selected(self) -> None:
        ids = self.selected_ids()
        if not ids:
            return
        uploading = [i for i in ids if (it := self.ctx.store.get(i)) and it.status == UPLOADING]
        if uploading:
            QMessageBox.information(self, "Очередь", "Файл, который сейчас загружается, удалить нельзя — сначала остановите загрузку.")
        half_done = [i for i in ids if (it := self.ctx.store.get(i)) and it.tg_message_id and it.status != DONE]
        if half_done and QMessageBox.question(
            self, "Очередь",
            "Часть файлов уже в Telegram, но ещё не на сайте. Если убрать их из очереди, на сайт они не попадут. Убрать?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.ctx.manager.remove(ids)

    def show_resume(self, count: int, auto: bool) -> None:
        if not count:
            return
        if auto:
            self.resume_banner.label.setText(f"Продолжаю незавершённые загрузки: {count}")
            self.resume_banner.button.hide()
        else:
            self.resume_banner.label.setText(f"Есть незавершённые загрузки: {count}")
        self.resume_banner.show()

    def _resume(self) -> None:
        self.ctx.manager.resume_uploads()
        self.resume_banner.hide()
