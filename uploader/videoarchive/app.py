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


def selftest() -> int:
    """Проверка собранной программы (для CI): ffmpeg с H.264, Telethon, cryptg, Qt. Код возврата 0 — всё хорошо."""
    import importlib
    import tempfile
    from pathlib import Path

    from videoarchive.core import media

    report: list[str] = []
    ok = True

    def check(name: str, fn) -> None:
        nonlocal ok
        try:
            report.append(f"OK   {name}: {fn()}")
        except Exception as err:  # noqa: BLE001
            ok = False
            report.append(f"FAIL {name}: {err}")

    check("ffmpeg", lambda: find_tool("ffmpeg") or (_ for _ in ()).throw(RuntimeError("не найден")))
    check("ffprobe", lambda: find_tool("ffprobe") or (_ for _ in ()).throw(RuntimeError("не найден")))

    def video_pipeline() -> str:
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "test.mp4"
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}  # type: ignore[attr-defined]
            subprocess.run([find_tool("ffmpeg"), "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=25",
                            "-t", "12", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True, capture_output=True, **kwargs)
            info = media.probe(src)
            preview = media.make_preview(src, Path(tmp) / "p.mp4", info)
            poster = media.make_poster(src, Path(tmp) / "p.jpg", info)
            return f"{info.width}x{info.height} {info.resolution_label}, превью {preview.stat().st_size // 1024} КБ, постер {poster.stat().st_size // 1024} КБ"

    check("превью и постер (libx264)", video_pipeline)
    check("telethon", lambda: importlib.import_module("telethon").__version__)
    check("cryptg", lambda: importlib.import_module("cryptg").__name__)

    def qt() -> str:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import __version__ as pyside_version
        from PySide6.QtWidgets import QApplication, QLabel

        app = QApplication.instance() or QApplication([])
        QLabel("тест").grab()
        return f"PySide6 {pyside_version}, платформа {app.platformName()}"

    check("Qt", qt)
    text = "\n".join(report) + ("\nSELFTEST OK\n" if ok else "\nSELFTEST FAILED\n")
    out = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--selftest-report=")), None)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    if sys.stdout:
        print(text)
    return 0 if ok else 1


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(selftest())
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
