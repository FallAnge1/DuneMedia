"""Главное окно: вкладки «Загрузка» и «Библиотека», строка состояния с аккаунтом."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtWidgets import QLabel, QMainWindow, QMessageBox, QTabWidget, QWidget

from videoarchive import APP_TITLE, __version__
from videoarchive.core.paths import data_dir, logs_dir
from videoarchive.core.pipeline import format_size
from videoarchive.core.queue import UPLOADING
from videoarchive.ui.context import AppContext
from videoarchive.ui.upload_tab import UploadTab
from videoarchive.ui.wizard import SetupWizard


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_TITLE)
        self.resize(1180, 760)

        self.tabs = QTabWidget()
        self.upload_tab = UploadTab(ctx)
        self.tabs.addTab(self.upload_tab, "Загрузка")
        self.library_tab = self._make_library_tab()
        if self.library_tab:
            self.tabs.addTab(self.library_tab, "Библиотека")
        self.setCentralWidget(self.tabs)

        self.account_label = QLabel()
        self.statusBar().addPermanentWidget(self.account_label)
        ctx.message.connect(lambda text: self.statusBar().showMessage(text, 8000))
        ctx.account_changed.connect(self._update_account)
        self._build_menu()
        self._update_account()

    def _make_library_tab(self) -> QWidget | None:
        try:
            from videoarchive.ui.library_tab import LibraryTab
        except ImportError:
            return None
        return LibraryTab(self.ctx)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("Файл")
        add = QAction("Добавить файлы…", self)
        add.setShortcut("Ctrl+O")
        add.triggered.connect(self.upload_tab.choose_files)
        file_menu.addAction(add)
        folder = QAction("Добавить папку…", self)
        folder.triggered.connect(self.upload_tab.choose_folder)
        file_menu.addAction(folder)
        file_menu.addSeparator()
        quit_action = QAction("Выход", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        settings = self.menuBar().addMenu("Настройки")
        wizard = QAction("Мастер настройки…", self)
        wizard.triggered.connect(self.open_wizard)
        settings.addAction(wizard)
        refresh = QAction("Проверить подключение", self)
        refresh.triggered.connect(self.ctx.refresh)
        settings.addAction(refresh)
        settings.addSeparator()
        logs = QAction("Открыть папку с логами", self)
        logs.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir()))))
        settings.addAction(logs)
        data = QAction("Открыть папку с данными программы", self)
        data.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir()))))
        settings.addAction(data)

        help_menu = self.menuBar().addMenu("Справка")
        about = QAction("О программе", self)
        about.triggered.connect(lambda: QMessageBox.about(
            self, "О программе",
            f"<b>{APP_TITLE}</b><br>Версия {__version__}<br><br>"
            "Загружает видео в Telegram-канал и публикует их на сайте архива.<br>"
            f"Данные программы: {data_dir()}",
        ))
        help_menu.addAction(about)
        site = QAction("Открыть сайт архива", self)
        site.triggered.connect(lambda: self.ctx.config.site_url and QDesktopServices.openUrl(QUrl(self.ctx.config.site_url)))
        help_menu.addAction(site)

    def _update_account(self) -> None:
        parts = []
        acc = self.ctx.account
        if acc:
            parts.append(f"Telegram: {acc.name}{' ★ Premium' if acc.premium else ''} · лимит {format_size(acc.file_limit)}")
        else:
            parts.append(f"Telegram: {self.ctx.account_error or 'проверяю…'}")
        if self.ctx.config.channel:
            parts.append(f"@{self.ctx.config.channel}")
        if self.ctx.uploader_name:
            parts.append(f"сайт: {self.ctx.uploader_name}")
        elif self.ctx.site_error:
            parts.append(f"сайт: {self.ctx.site_error}")
        self.account_label.setText("   |   ".join(parts))

    def open_wizard(self) -> None:
        SetupWizard(self.ctx, self).exec()
        self._update_account()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        uploading = any(i.status == UPLOADING for i in self.ctx.store.all())
        if uploading and QMessageBox.question(
            self, "Выход",
            "Идёт загрузка. Если закрыть программу, она продолжится при следующем запуске (файл в Telegram "
            "загрузится заново, если не успел дойти). Закрыть?",
        ) != QMessageBox.StandardButton.Yes:
            event.ignore()
            return
        self.ctx.shutdown()
        event.accept()
