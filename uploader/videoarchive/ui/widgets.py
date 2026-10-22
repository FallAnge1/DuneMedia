"""Небольшие виджеты: поле тегов с автодополнением, список коллекций, стили."""

from __future__ import annotations

from PySide6.QtCore import QStringListModel, Qt, Signal
from PySide6.QtWidgets import (
    QCompleter, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QWidget,
)

from videoarchive.core.textutil import parse_tags


class TagLineEdit(QLineEdit):
    """Теги через запятую. Подсказки — из уже существующих тегов, по последнему введённому слову."""

    tags_changed = Signal(list)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setPlaceholderText("закат, море, дрон — через запятую")
        self._model = QStringListModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchStartsWith)
        self._completer.setWidget(self)
        self._completer.activated.connect(self._insert_completion)
        self.textEdited.connect(self._on_edited)
        self.editingFinished.connect(lambda: self.tags_changed.emit(self.tags()))

    def set_suggestions(self, names: list[str]) -> None:
        self._model.setStringList(names)

    def tags(self) -> list[str]:
        return parse_tags(self.text())

    def set_tags(self, tags: list[str]) -> None:
        self.setText(", ".join(tags))

    def _current_token(self) -> str:
        text = self.text()[: self.cursorPosition()]
        return text.split(",")[-1].strip().lstrip("#")

    def _on_edited(self, _text: str) -> None:
        token = self._current_token()
        if len(token) < 1:
            self._completer.popup().hide()
            return
        self._completer.setCompletionPrefix(token)
        if self._completer.completionCount() > 0:
            rect = self.cursorRect()
            rect.setWidth(max(220, self._completer.popup().sizeHintForColumn(0) + 30))
            self._completer.complete(rect)
        else:
            self._completer.popup().hide()

    def _insert_completion(self, completion: str) -> None:
        pos = self.cursorPosition()
        before, after = self.text()[:pos], self.text()[pos:]
        parts = before.split(",")
        parts[-1] = (" " if len(parts) > 1 else "") + completion
        new_before = ",".join(parts) + ", "
        self.setText(new_before + after.lstrip(", "))
        self.setCursorPosition(len(new_before))
        self.tags_changed.emit(self.tags())


class CollectionList(QListWidget):
    """Коллекции с галочками."""

    selection_changed = Signal(list)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMaximumHeight(130)
        self.itemChanged.connect(lambda _i: self.selection_changed.emit(self.checked_ids()))

    def set_collections(self, collections: list[dict], checked: list[int]) -> None:
        self.blockSignals(True)
        self.clear()
        for c in collections:
            label = f"{c.get('emoji') or ''} {c['name']}".strip()
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, c["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if c["id"] in checked else Qt.CheckState.Unchecked)
            self.addItem(item)
        self.blockSignals(False)

    def checked_ids(self) -> list[int]:
        return [
            self.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.count())
            if self.item(i).checkState() == Qt.CheckState.Checked
        ]


class Banner(QFrame):
    """Плашка с сообщением и кнопкой действия."""

    def __init__(self, text: str = "", button: str | None = None, kind: str = "info", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(f"banner-{kind}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.label)
        self.button = QPushButton(button) if button else None
        if self.button:
            layout.addWidget(self.button)


def section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("section")
    return label


STYLE = """
QWidget { font-size: 10pt; }
QLabel#section { font-weight: 600; color: palette(mid); margin-top: 8px; }
QLabel#title { font-size: 13pt; font-weight: 600; }
QLabel#muted { color: palette(mid); }
QLabel#error { color: #d9534f; }
QFrame#banner-info { background: rgba(232,163,61,0.15); border: 1px solid rgba(232,163,61,0.6); border-radius: 6px; }
QFrame#banner-warn { background: rgba(217,83,79,0.12); border: 1px solid rgba(217,83,79,0.6); border-radius: 6px; }
QFrame#banner-ai { background: rgba(91,140,255,0.12); border: 1px solid rgba(91,140,255,0.55); border-radius: 6px; }
QPushButton#primary { background: #e8a33d; color: #1a1205; font-weight: 600; border: none; border-radius: 5px; padding: 6px 14px; }
QPushButton#primary:hover { background: #f0b04f; }
QPushButton#primary:disabled { background: #6b5a3c; color: #2a2418; }
QListView#queue { border: 1px solid palette(mid); border-radius: 6px; }
QListWidget::indicator, QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #8c8a82; border-radius: 3px; background: palette(base); }
QListWidget::indicator:checked, QCheckBox::indicator:checked { background: #e8a33d; border-color: #e8a33d; }
QLabel#drop { border: 2px dashed palette(mid); border-radius: 10px; padding: 24px; color: palette(mid); font-size: 11pt; }
"""
