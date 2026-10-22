"""Мастер настройки (раздел 6.2 ТЗ): Telegram → канал → сайт → ИИ → итог."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget, QWizard,
    QWizardPage,
)

from videoarchive.core.api import ApiClient
from videoarchive.core.config import AIProviderConfig
from videoarchive.core.pipeline import format_size
from videoarchive.core.telegram import Account
from videoarchive.ui.context import AppContext
from videoarchive.ui.tasks import run_async

PROVIDER_INFO = {
    "groq": ("Groq", "Ключ: https://console.groq.com/keys"),
    "openrouter": ("OpenRouter", "Ключ: https://openrouter.ai/keys — бесплатные модели с суффиксом :free"),
    "workers_ai": ("Cloudflare Workers AI", "Через ваш сайт, ключ не нужен"),
    "gemini": ("Google Gemini", "Ключ: https://aistudio.google.com/apikey"),
    "ollama": ("Ollama (локально)", "Адрес сервера Ollama, обычно http://localhost:11434"),
}


def link_label(html: str) -> QLabel:
    label = QLabel(html)
    label.setWordWrap(True)
    label.setOpenExternalLinks(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    return label


def status_label() -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def set_status(label: QLabel, text: str, ok: bool | None = None) -> None:
    color = {True: "#5bbf7a", False: "#d9534f", None: ""}[ok]
    label.setStyleSheet(f"color: {color};" if color else "")
    label.setText(text)


# ---------------------------------------------------------------------------


class TelegramPage(QWizardPage):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.account: Account | None = None
        self.setTitle("1. Вход в Telegram")
        self.setSubTitle("Видео загружаются от имени вашего аккаунта. Аккаунт должен быть админом канала.")

        layout = QVBoxLayout(self)
        layout.addWidget(link_label(
            "Нужны <b>api_id</b> и <b>api_hash</b>: откройте "
            "<a href='https://my.telegram.org/apps'>my.telegram.org/apps</a>, войдите по номеру телефона, "
            "создайте приложение (название любое, платформа — Desktop) и скопируйте два значения. "
            "Подробно — в docs/02-telegram-api.md."
        ))
        form = QFormLayout()
        self.api_id = QLineEdit(str(ctx.config.api_id or ""))
        self.api_id.setValidator(QIntValidator(1, 2_000_000_000))
        self.api_hash = QLineEdit(ctx.config.api_hash)
        self.phone = QLineEdit(ctx.config.phone)
        self.phone.setPlaceholderText("+79991234567")
        form.addRow("api_id", self.api_id)
        form.addRow("api_hash", self.api_hash)
        form.addRow("Телефон", self.phone)
        layout.addLayout(form)

        self.send_btn = QPushButton("Получить код")
        self.send_btn.clicked.connect(self.send_code)
        layout.addWidget(self.send_btn)

        self.code_row = QWidget()
        row = QHBoxLayout(self.code_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.code = QLineEdit()
        self.code.setPlaceholderText("Код из Telegram")
        row.addWidget(self.code)
        self.sign_btn = QPushButton("Войти")
        self.sign_btn.clicked.connect(self.sign_in)
        row.addWidget(self.sign_btn)
        layout.addWidget(self.code_row)

        self.pass_row = QWidget()
        row = QHBoxLayout(self.pass_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Пароль двухэтапной проверки")
        row.addWidget(self.password)
        self.pass_btn = QPushButton("Подтвердить")
        self.pass_btn.clicked.connect(self.sign_in_password)
        row.addWidget(self.pass_btn)
        layout.addWidget(self.pass_row)

        self.status = status_label()
        layout.addWidget(self.status)
        self.logout_btn = QPushButton("Выйти из аккаунта")
        self.logout_btn.clicked.connect(self.log_out)
        layout.addWidget(self.logout_btn)
        layout.addStretch()

        self.code_row.hide()
        self.pass_row.hide()
        self.logout_btn.hide()

    def initializePage(self) -> None:  # noqa: N802
        if self.ctx.config.api_id and self.ctx.config.api_hash:
            set_status(self.status, "Проверяю сохранённый вход…")
            run_async(lambda: self.ctx.ensure_telegram().account(refresh=True), self._authorized,
                      lambda _e: set_status(self.status, "Войдите: введите телефон и нажмите «Получить код»."))

    def isComplete(self) -> bool:  # noqa: N802
        return self.account is not None

    def _save_credentials(self) -> bool:
        api_id = int(self.api_id.text() or 0)
        api_hash = self.api_hash.text().strip()
        if not api_id or len(api_hash) < 16:
            set_status(self.status, "Укажите api_id (число) и api_hash (32 символа).", False)
            return False
        if (api_id, api_hash) != (self.ctx.config.api_id, self.ctx.config.api_hash):
            self.ctx.reset_telegram()
        self.ctx.config.api_id, self.ctx.config.api_hash = api_id, api_hash
        self.ctx.config.phone = self.phone.text().strip().replace(" ", "")
        self.ctx.config.save()
        return True

    def _busy(self, busy: bool) -> None:
        for b in (self.send_btn, self.sign_btn, self.pass_btn):
            b.setEnabled(not busy)

    def _fail(self, err: Exception) -> None:
        self._busy(False)
        set_status(self.status, str(err), False)

    def send_code(self) -> None:
        if not self._save_credentials():
            return
        phone = self.ctx.config.phone
        if not phone:
            set_status(self.status, "Укажите номер телефона.", False)
            return
        self._busy(True)
        set_status(self.status, "Подключаюсь к Telegram…")

        def go() -> Account | None:
            tg = self.ctx.ensure_telegram()
            if tg.is_authorized():
                return tg.account(refresh=True)
            tg.send_code(phone)
            return None

        def done(account: Account | None) -> None:
            self._busy(False)
            if account:
                self._authorized(account)
                return
            self.code_row.show()
            self.code.setFocus()
            set_status(self.status, "Код отправлен в приложение Telegram (или по SMS). Введите его.")

        run_async(go, done, self._fail)

    def sign_in(self) -> None:
        code = self.code.text().strip()
        if not code:
            return
        self._busy(True)
        phone = self.ctx.config.phone
        run_async(lambda: self.ctx.ensure_telegram().sign_in(phone, code), self._after_code, self._fail)

    def _after_code(self, needs_password: bool) -> None:
        self._busy(False)
        if needs_password:
            self.pass_row.show()
            self.password.setFocus()
            set_status(self.status, "Включена двухэтапная проверка — введите пароль.")
            return
        run_async(lambda: self.ctx.ensure_telegram().account(refresh=True), self._authorized, self._fail)

    def sign_in_password(self) -> None:
        password = self.password.text()
        self._busy(True)

        def go() -> Account:
            tg = self.ctx.ensure_telegram()
            tg.sign_in_password(password)
            return tg.account(refresh=True)

        run_async(go, self._authorized, self._fail)

    def _authorized(self, account: Account) -> None:
        self.account = account
        self.ctx.account = account
        self._busy(False)
        self.code_row.hide()
        self.pass_row.hide()
        self.logout_btn.show()
        limit = "4 ГБ (Telegram Premium)" if account.premium else "2 ГБ"
        set_status(self.status, f"Вы вошли как {account.name}. Лимит размера файла: {limit}.", True)
        self.completeChanged.emit()

    def log_out(self) -> None:
        def done(_: object) -> None:
            self.account = None
            self.ctx.account = None
            self.logout_btn.hide()
            set_status(self.status, "Вы вышли из аккаунта.")
            self.completeChanged.emit()

        run_async(lambda: self.ctx.ensure_telegram().log_out(), done, self._fail)


# ---------------------------------------------------------------------------


class ChannelPage(QWizardPage):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.ok = False
        self.setTitle("2. Канал Telegram")
        self.setSubTitle("Публичный канал, в котором хранятся видео. Вы должны быть его администратором с правом публикации.")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.channel = QLineEdit(ctx.config.channel)
        self.channel.setPlaceholderText("my_video_archive или https://t.me/my_video_archive")
        self.channel.textEdited.connect(self._changed)
        form.addRow("Username канала", self.channel)
        layout.addLayout(form)
        check = QPushButton("Проверить")
        check.clicked.connect(self.check)
        layout.addWidget(check)
        self.status = status_label()
        layout.addWidget(self.status)
        layout.addStretch()

    def initializePage(self) -> None:  # noqa: N802
        if self.channel.text():
            self.check()

    def _changed(self) -> None:
        self.ok = False
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # noqa: N802
        return self.ok

    def check(self) -> None:
        raw = self.channel.text().strip()
        username = raw.split("t.me/")[-1].strip("/@ ").split("/")[0]
        if not username:
            return
        set_status(self.status, "Проверяю…")

        def done(info) -> None:
            if not info.can_post:
                set_status(self.status, f"Канал «{info.title}» найден, но у вас нет права публикации. "
                                        "Попросите владельца сделать вас админом с правом «Публикация сообщений».", False)
                return
            self.ok = True
            self.ctx.config.channel = info.username
            self.ctx.config.save()
            warn = "" if info.can_edit and info.can_delete else (
                " Внимание: нет права редактировать или удалять чужие посты — править подписи получится только у своих.")
            set_status(self.status, f"Канал «{info.title}» (@{info.username}): можно публиковать.{warn}", True)
            self.completeChanged.emit()

        run_async(lambda: self.ctx.ensure_telegram().check_channel(username), done,
                  lambda e: set_status(self.status, str(e), False))


# ---------------------------------------------------------------------------


class SitePage(QWizardPage):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.ok = False
        self.setTitle("3. Сайт и токен загрузчика")
        self.setSubTitle("Адрес вашего сайта на Cloudflare и персональный токен, который выдал администратор.")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.url = QLineEdit(ctx.config.site_url)
        self.url.setPlaceholderText("https://video-archive.example.workers.dev")
        self.token = QLineEdit(ctx.config.uploader_token)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("va_…")
        for w in (self.url, self.token):
            w.textEdited.connect(self._changed)
        form.addRow("Адрес сайта", self.url)
        form.addRow("Токен", self.token)
        self.access_id = QLineEdit(ctx.config.access_client_id)
        self.access_id.setPlaceholderText("только если сайт закрыт через Cloudflare Access")
        self.access_secret = QLineEdit(ctx.config.access_client_secret)
        self.access_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.access_secret.setPlaceholderText("необязательно")
        form.addRow("Access Client ID", self.access_id)
        form.addRow("Access Client Secret", self.access_secret)
        layout.addLayout(form)
        check = QPushButton("Проверить связь")
        check.clicked.connect(self.check)
        layout.addWidget(check)
        self.status = status_label()
        layout.addWidget(self.status)
        layout.addWidget(link_label("Токен создаёт администратор командой <code>npm run uploader:create -- \"Имя\"</code> "
                                    "(см. docs/04-tokens.md)."))
        layout.addStretch()

    def initializePage(self) -> None:  # noqa: N802
        if self.url.text() and self.token.text():
            self.check()

    def _changed(self) -> None:
        self.ok = False
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # noqa: N802
        return self.ok

    def check(self) -> None:
        url = self.url.text().strip().rstrip("/")
        if url and not url.startswith("http"):
            url = "https://" + url
        token = self.token.text().strip()
        access_id, access_secret = self.access_id.text().strip(), self.access_secret.text().strip()
        headers = {"CF-Access-Client-Id": access_id, "CF-Access-Client-Secret": access_secret} if access_id and access_secret else {}
        if not url or not token:
            set_status(self.status, "Укажите адрес и токен.", False)
            return
        set_status(self.status, "Проверяю…")

        def done(me: dict) -> None:
            self.ok = True
            self.ctx.config.site_url, self.ctx.config.uploader_token = url, token
            self.ctx.config.access_client_id, self.ctx.config.access_client_secret = access_id, access_secret
            self.url.setText(url)
            self.ctx.config.save()
            set_status(self.status, f"Связь есть. Вы загружаете как «{me['name']}».", True)
            self.completeChanged.emit()

        run_async(lambda: ApiClient(url, token, retries=1, extra_headers=headers).me(), done,
                  lambda e: set_status(self.status, str(e), False))


# ---------------------------------------------------------------------------


class AIPage(QWizardPage):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setTitle("4. ИИ-теги (необязательно)")
        self.setSubTitle("ИИ смотрит 4–6 кадров и предлагает название, описание и теги. Все провайдеры бесплатные; "
                         "можно включить несколько — при ошибке или лимите программа перейдёт к следующему.")
        self.layout_ = QVBoxLayout(self)
        self.enabled = QCheckBox("Включить ИИ-теги")
        self.enabled.setChecked(ctx.config.ai_enabled)
        self.auto = QCheckBox("Предлагать теги автоматически при добавлении файлов")
        self.auto.setChecked(ctx.config.ai_auto)
        self.layout_.addWidget(self.enabled)
        self.layout_.addWidget(self.auto)
        self.grid_host = QWidget()
        self.layout_.addWidget(self.grid_host)
        self.layout_.addWidget(link_label("Порядок сверху вниз — порядок, в котором пробуются провайдеры. "
                                          "Модели — через запятую; пустое поле — программа сама найдёт "
                                          "актуальные бесплатные vision-модели у провайдера."))
        check = QPushButton("Проверить провайдеров")
        check.clicked.connect(self.check)
        self.layout_.addWidget(check)
        self.check_status = status_label()
        self.layout_.addWidget(self.check_status)
        self.layout_.addStretch()
        self.rows: list[tuple[AIProviderConfig, QCheckBox, QLineEdit, QLineEdit]] = []
        self._build()

    def _build(self) -> None:
        old = self.grid_host.layout()
        if old:
            QWidget().setLayout(old)  # отсоединить старую сетку
        grid = QGridLayout(self.grid_host)
        grid.setContentsMargins(0, 8, 0, 0)
        self.rows = []
        providers = self.ctx.config.ai_providers
        for r, p in enumerate(providers):
            title, hint = PROVIDER_INFO.get(p.id, (p.id, ""))
            on = QCheckBox(title)
            on.setChecked(p.enabled)
            on.setToolTip(hint)
            key = QLineEdit(p.base_url if p.id == "ollama" else p.api_key)
            if p.id == "workers_ai":
                key.setEnabled(False)
                key.setPlaceholderText("через сайт")
            elif p.id == "ollama":
                key.setPlaceholderText("http://localhost:11434")
            else:
                key.setEchoMode(QLineEdit.EchoMode.Password)
                key.setPlaceholderText("API-ключ")
            key.setToolTip(hint)
            models = QLineEdit(", ".join(p.models))
            models.setToolTip("Модели через запятую, пробуются по порядку")
            up = QPushButton("↑")
            up.setFixedWidth(30)
            up.setEnabled(r > 0)
            up.clicked.connect(lambda _=False, i=r: self._move(i, -1))
            down = QPushButton("↓")
            down.setFixedWidth(30)
            down.setEnabled(r < len(providers) - 1)
            down.clicked.connect(lambda _=False, i=r: self._move(i, 1))
            for c, w in enumerate((on, key, models, up, down)):
                grid.addWidget(w, r, c)
            self.rows.append((p, on, key, models))
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 3)

    def _collect(self) -> None:
        for p, on, key, models in self.rows:
            p.enabled = on.isChecked()
            if p.id == "ollama":
                p.base_url = key.text().strip() or "http://localhost:11434"
            elif p.id != "workers_ai":
                p.api_key = key.text().strip()
            p.models = [m.strip() for m in models.text().split(",") if m.strip()]

    def check(self) -> None:
        """Проверяет ключи и показывает доступные модели у каждого включённого провайдера."""
        self._collect()
        from videoarchive.ai.providers import ProviderError, build_provider

        api = (ApiClient(self.ctx.config.site_url, self.ctx.config.uploader_token, retries=1,
                         extra_headers=self.ctx.config.access_headers()) if self.ctx.config.site_ready else None)
        providers = [build_provider(p, api) for p in self.ctx.config.ai_providers if p.enabled]

        def go() -> list[str]:
            lines = []
            for prov in providers:
                if prov is None:
                    continue
                if not prov.configured:
                    lines.append(f"{prov.title}: нет ключа — пропускается")
                    continue
                try:
                    lines.append(f"{prov.title}: ✓ {prov.check()}")
                except ProviderError as err:
                    lines.append(f"{prov.title}: ✗ {err}")
            return lines

        set_status(self.check_status, "Проверяю…")
        run_async(go, lambda lines: set_status(self.check_status, "\n".join(lines) or "Нет включённых провайдеров"),
                  lambda e: set_status(self.check_status, str(e), False))

    def _move(self, index: int, delta: int) -> None:
        self._collect()
        providers = self.ctx.config.ai_providers
        j = index + delta
        providers[index], providers[j] = providers[j], providers[index]
        self._build()

    def validatePage(self) -> bool:  # noqa: N802
        self._collect()
        self.ctx.config.ai_enabled = self.enabled.isChecked()
        self.ctx.config.ai_auto = self.auto.isChecked()
        self.ctx.config.save()
        return True


# ---------------------------------------------------------------------------


class SummaryPage(QWizardPage):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setTitle("Готово")
        layout = QVBoxLayout(self)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.text)
        layout.addStretch()

    def initializePage(self) -> None:  # noqa: N802
        c = self.ctx.config
        acc = self.ctx.account
        limit = acc.file_limit if acc else 0
        ai = [p.id for p in c.ai_providers if p.enabled and (p.api_key or p.id in ("workers_ai", "ollama"))]
        self.text.setText(
            f"<p><b>Telegram:</b> {acc.name if acc else '—'}{' (Premium)' if acc and acc.premium else ''}</p>"
            f"<p><b>Максимальный размер файла:</b> {format_size(limit) if limit else '—'}"
            f"{'' if acc and acc.premium else ' — файлы больше программа загрузить не даст'}</p>"
            f"<p><b>Канал:</b> @{c.channel}</p>"
            f"<p><b>Сайт:</b> {c.site_url}</p>"
            f"<p><b>ИИ:</b> {', '.join(ai) if c.ai_enabled and ai else 'выключен'}</p>"
            "<p>Настройки можно изменить в любой момент: меню «Настройки».</p>"
        )


class SetupWizard(QWizard):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Настройка видеоархива")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(720, 560)
        self.setButtonText(QWizard.WizardButton.NextButton, "Далее")
        self.setButtonText(QWizard.WizardButton.BackButton, "Назад")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Готово")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Отмена")
        for page in (TelegramPage(ctx), ChannelPage(ctx), SitePage(ctx), AIPage(ctx), SummaryPage(ctx)):
            self.addPage(page)

    def accept(self) -> None:
        self.ctx.config.setup_done = True
        self.ctx.config.save()
        self.ctx.refresh()
        super().accept()
