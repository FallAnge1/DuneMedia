"""Точка входа программы-загрузчика."""

from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox, QStyleFactory

from videoarchive import APP_NAME, APP_TITLE, __version__
from videoarchive.core.logs import setup_logging
from videoarchive.core.paths import find_tool, logs_dir

log = logging.getLogger("videoarchive")


def dark_palette() -> QPalette:
    p = QPalette()
    base, window, text = QColor(30, 31, 34), QColor(23, 24, 27), QColor(236, 235, 231)
    p.setColor(QPalette.ColorRole.Window, window)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, base)
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(38, 39, 43))
    p.setColor(QPalette.ColorRole.ToolTipBase, base)
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.Button, QColor(42, 43, 48))
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.Highlight, QColor(232, 163, 61))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(26, 18, 5))
    p.setColor(QPalette.ColorRole.Link, QColor(232, 163, 61))
    p.setColor(QPalette.ColorRole.Mid, QColor(140, 138, 130))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(120, 118, 112))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(110, 110, 110))
    return p


def install_excepthook() -> None:
    """Непойманные ошибки — в лог и понятным окном, а не молчаливым падением."""

    def hook(exc_type, exc, tb):
        log.critical("Необработанная ошибка:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        app = QApplication.instance()
        if app:
            QMessageBox.critical(None, APP_TITLE, f"Произошла ошибка: {exc}\n\nПодробности записаны в лог:\n{logs_dir() / 'app.log'}")

    sys.excepthook = hook


def main() -> None:
    setup_logging(verbose="--verbose" in sys.argv)
    log.info("Запуск %s %s, Python %s", APP_NAME, __version__, sys.version.split()[0])
    install_excepthook()

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_TITLE)
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setPalette(dark_palette())

    from videoarchive.ui.context import AppContext
    from videoarchive.ui.main_window import MainWindow
    from videoarchive.ui.widgets import STYLE
    from videoarchive.ui.wizard import SetupWizard

    app.setStyleSheet(STYLE)
    icon = QIcon.fromTheme("video-x-generic")
    if not icon.isNull():
        app.setWindowIcon(icon)

    if not find_tool("ffmpeg") or not find_tool("ffprobe"):
        QMessageBox.critical(None, APP_TITLE, "Не найден ffmpeg. Переустановите программу или установите ffmpeg в систему.")

    ctx = AppContext()
    if not ctx.config.setup_done:
        wizard = SetupWizard(ctx)
        if not wizard.exec():
            log.info("Мастер настройки отменён")

    window = MainWindow(ctx)
    window.show()
    ctx.refresh()
    ctx.manager.resume_preparation()

    # Незавершённые загрузки после перезапуска.
    pending = len(ctx.store.unfinished_uploads())
    if pending:
        fired = False

        def resume() -> None:
            nonlocal fired
            if fired:
                return
            fired = True
            if ctx.config.auto_resume and ctx.account and ctx.api:
                ctx.manager.resume_uploads()
                window.upload_tab.show_resume(pending, auto=True)
            else:
                window.upload_tab.show_resume(pending, auto=False)

        # Даём время проверить вход в Telegram.
        ctx.account_changed.connect(lambda: QTimer.singleShot(0, resume))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
