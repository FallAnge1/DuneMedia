"""Список очереди: модель над QueueStore и отрисовка карточки файла."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from videoarchive.core.pipeline import format_size
from videoarchive.core.queue import DONE, ERROR, NEW, PREPARING, QUEUED, READY, SKIPPED, STAGE_LABELS, UPLOADING, QueueItem, QueueStore

ItemRole = Qt.ItemDataRole.UserRole + 1

STATUS_TEXT = {
    NEW: "в очереди на обработку",
    PREPARING: "обработка",
    READY: "готово к загрузке",
    QUEUED: "ждёт загрузки",
    UPLOADING: "загрузка",
    DONE: "загружено",
    ERROR: "ошибка",
    SKIPPED: "пропущено",
}
STATUS_COLOR = {
    READY: "#5bbf7a",
    DONE: "#5bbf7a",
    ERROR: "#d9534f",
    UPLOADING: "#e8a33d",
    QUEUED: "#e8a33d",
    PREPARING: "#8a8a8a",
    NEW: "#8a8a8a",
    SKIPPED: "#8a8a8a",
}


def format_duration(seconds: float | None) -> str:
    if not seconds:
        return "—"
    s = int(round(seconds))
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def format_eta(seconds: float | None) -> str:
    if seconds is None:
        return ""
    s = int(seconds)
    if s >= 3600:
        return f"≈{s // 3600} ч {s % 3600 // 60} мин"
    if s >= 60:
        return f"≈{s // 60} мин {s % 60} с"
    return f"≈{s} с"


def status_line(item: QueueItem) -> str:
    text = STATUS_TEXT.get(item.status, item.status)
    if item.stage and item.status in (PREPARING, UPLOADING, QUEUED):
        text += f" · {STAGE_LABELS.get(item.stage, item.stage)}"
    if item.status == UPLOADING and item.stage == "telegram":
        text += f" · {item.progress * 100:.0f}%"
        if item.speed:
            text += f" · {format_size(item.speed)}/с {format_eta(item.eta)}"
    if item.note:
        text += f" · {item.note}"
    if item.status == ERROR and item.error:
        text += f": {item.error}"
    return text


class QueueModel(QAbstractListModel):
    def __init__(self, store: QueueStore):
        super().__init__()
        self.store = store
        self.ids: list[str] = []
        self.reload()

    def reload(self) -> None:
        self.beginResetModel()
        self.ids = [i.id for i in sorted(self.store.all(), key=lambda i: i.added_at)]
        self.endResetModel()

    def item_changed(self, item_id: str) -> None:
        try:
            row = self.ids.index(item_id)
        except ValueError:
            return
        idx = self.index(row)
        self.dataChanged.emit(idx, idx)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.ids)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.store.get(self.ids[index.row()])
        if item is None:
            return None
        if role == ItemRole:
            return item
        if role == Qt.ItemDataRole.DisplayRole:
            return item.title or item.file_name
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{item.path}\n{status_line(item)}"
        return None


class QueueDelegate(QStyledItemDelegate):
    """Карточка: постер, название, параметры файла, статус и прогресс."""

    HEIGHT = 78
    THUMB_W = 112

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmaps: dict[str, QPixmap] = {}

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(320, self.HEIGHT)

    def _poster(self, path: str | None) -> QPixmap | None:
        if not path:
            return None
        if path not in self._pixmaps:
            pm = QPixmap(path)
            if pm.isNull():
                return None
            self._pixmaps[path] = pm.scaled(self.THUMB_W, self.HEIGHT - 12, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
        return self._pixmaps[path]

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        item: QueueItem | None = index.data(ItemRole)
        if item is None:
            return
        painter.save()
        palette = option.palette
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(option.rect, palette.highlight())
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, palette.alternateBase())
        text_color = palette.highlightedText().color() if selected else palette.text().color()
        muted = QColor(text_color)
        muted.setAlpha(150)

        r = option.rect.adjusted(6, 6, -8, -6)
        # постер
        thumb_rect = QRect(r.left(), r.top(), self.THUMB_W, r.height())
        painter.fillRect(thumb_rect, QColor(0, 0, 0, 60))
        pm = self._poster(item.poster_path)
        if pm:
            x = thumb_rect.left() + (thumb_rect.width() - pm.width()) // 2
            y = thumb_rect.top() + (thumb_rect.height() - pm.height()) // 2
            painter.drawPixmap(x, y, pm)
        else:
            painter.setPen(muted)
            painter.drawText(thumb_rect, Qt.AlignmentFlag.AlignCenter, "…" if item.status in (NEW, PREPARING) else "нет постера")

        left = thumb_rect.right() + 10
        width = r.right() - left
        font = QFont(option.font)
        bold = QFont(font)
        bold.setBold(True)

        # название
        painter.setFont(bold)
        painter.setPen(text_color)
        fm = QFontMetrics(bold)
        title = fm.elidedText(item.title or item.file_name, Qt.TextElideMode.ElideRight, width)
        painter.drawText(QRect(left, r.top(), width, fm.height()), Qt.AlignmentFlag.AlignLeft, title)

        # параметры
        painter.setFont(font)
        fm = QFontMetrics(font)
        info = item.info or {}
        parts = [item.file_name, format_size(item.file_size)]
        if info:
            first = "фото" if item.is_photo else format_duration(info.get("duration"))
            parts += [first, f"{info.get('width')}×{info.get('height')} {info.get('resolution_label', '')}"]
        if item.tags:
            parts.append(" ".join(f"#{t}" for t in item.tags[:4]))
        painter.setPen(muted)
        line2 = fm.elidedText("  ·  ".join(parts), Qt.TextElideMode.ElideRight, width)
        painter.drawText(QRect(left, r.top() + fm.height() + 2, width, fm.height()), Qt.AlignmentFlag.AlignLeft, line2)

        # статус
        status_y = r.top() + 2 * fm.height() + 6
        color = QColor(STATUS_COLOR.get(item.status, "#8a8a8a"))
        flags = []
        if item.is_duplicate:
            flags.append("⚠ дубликат")
        if item.ai_suggestion:
            flags.append(f"✨ ИИ: {item.ai_suggestion.get('provider')}")
        status = status_line(item) + ("  ·  " + "  ".join(flags) if flags else "")
        painter.setPen(text_color if selected else color)
        painter.drawText(QRect(left, status_y, width, fm.height()), Qt.AlignmentFlag.AlignLeft,
                         fm.elidedText(status, Qt.TextElideMode.ElideRight, width))

        # прогресс
        if item.status in (UPLOADING,) or (item.status == PREPARING):
            bar = QRect(left, r.bottom() - 4, width, 4)
            painter.fillRect(bar, QColor(128, 128, 128, 60))
            value = item.progress if item.stage == "telegram" else None
            if value is not None:
                done = QRect(bar.left(), bar.top(), int(bar.width() * value), bar.height())
                painter.fillRect(done, QColor("#e8a33d"))
            else:  # неопределённый прогресс: короткая полоска
                painter.fillRect(QRect(bar.left(), bar.top(), bar.width() // 5, bar.height()), QColor("#8a8a8a"))
        elif item.status == DONE:
            painter.fillRect(QRect(left, r.bottom() - 4, width, 4), QColor("#5bbf7a"))
        painter.restore()
