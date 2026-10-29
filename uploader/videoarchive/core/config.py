"""Настройки программы: хранятся в config.json в папке пользователя, никогда не в коде."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from videoarchive.core.paths import data_dir

log = logging.getLogger(__name__)


@dataclass
class AIProviderConfig:
    """Один провайдер ИИ в цепочке. Модели не захардкожены — их можно поменять в настройках."""

    id: str  # groq | openrouter | workers_ai | gemini | ollama
    enabled: bool = True
    api_key: str = ""
    models: list[str] = field(default_factory=list)
    base_url: str = ""  # для Ollama: http://localhost:11434


def default_ai_providers() -> list[AIProviderConfig]:
    """Порядок фолбэка по умолчанию (раздел 7 ТЗ). Без ключа провайдер пропускается.

    Пустой список моделей — программа сама спросит у провайдера актуальные бесплатные vision-модели.
    """
    return [
        AIProviderConfig("groq", models=[]),  # берутся у Groq: модели там часто переименовывают
        AIProviderConfig("openrouter", models=[]),
        AIProviderConfig("workers_ai", models=[]),  # модель по умолчанию задана на сайте (AI_MODEL)
        AIProviderConfig("gemini", models=["gemini-2.5-flash", "gemini-flash-latest"]),
        AIProviderConfig("ollama", enabled=False, models=["qwen2.5vl:7b", "gemma3:4b"], base_url="http://localhost:11434"),
    ]


@dataclass
class Config:
    # Telegram
    api_id: int = 0
    api_hash: str = ""
    phone: str = ""
    channel: str = ""  # username канала без @
    # Сайт
    site_url: str = ""
    uploader_token: str = ""
    # Если сайт закрыт через Cloudflare Access — сервисный токен (см. docs/08-cloudflare-access.md).
    access_client_id: str = ""
    access_client_secret: str = ""
    # ИИ
    ai_enabled: bool = True
    ai_auto: bool = False  # предлагать теги автоматически при добавлении файла
    ai_auto_apply: bool = False  # сразу подставлять предложение ИИ: название, описание и теги
    ai_providers: list[AIProviderConfig] = field(default_factory=default_ai_providers)
    ai_requests_per_minute: int = 20
    # Прочее
    setup_done: bool = False
    auto_resume: bool = True
    upload_connections: int = 8  # параллельных соединений при загрузке в Telegram (1 — по-старому)

    @property
    def telegram_ready(self) -> bool:
        return bool(self.api_id and self.api_hash and self.channel)

    @property
    def site_ready(self) -> bool:
        return bool(self.site_url and self.uploader_token)

    # ---- сохранение ----

    @staticmethod
    def path() -> Path:
        return data_dir() / "config.json"

    @classmethod
    def load(cls) -> "Config":
        p = cls.path()
        if not p.exists():
            return cls()
        try:
            raw: dict[str, Any] = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError) as err:
            log.error("Не удалось прочитать %s: %s", p, err)
            return cls()
        known = {f for f in cls.__dataclass_fields__}  # noqa: C416
        data = {k: v for k, v in raw.items() if k in known}
        providers = data.pop("ai_providers", None)
        cfg = cls(**data)
        if isinstance(providers, list):
            loaded = []
            for item in providers:
                if isinstance(item, dict) and "id" in item:
                    fields = AIProviderConfig.__dataclass_fields__
                    loaded.append(AIProviderConfig(**{k: v for k, v in item.items() if k in fields}))
            # Новые провайдеры из будущих версий добавляются в конец.
            ids = {p.id for p in loaded}
            loaded += [p for p in default_ai_providers() if p.id not in ids]
            cfg.ai_providers = loaded
        return cfg

    def save(self) -> None:
        write_json_atomic(self.path(), asdict(self))

    def access_headers(self) -> dict[str, str]:
        if self.access_client_id and self.access_client_secret:
            return {"CF-Access-Client-Id": self.access_client_id, "CF-Access-Client-Secret": self.access_client_secret}
        return {}

    def provider(self, provider_id: str) -> AIProviderConfig | None:
        return next((p for p in self.ai_providers if p.id == provider_id), None)


_write_lock = threading.Lock()


def write_json_atomic(path: Path, data: Any) -> None:
    """Запись через временный файл: при сбое старый файл не портится.

    Записи идут по одной: на Windows две одновременные замены одного файла
    дают PermissionError. Короткие блокировки (антивирус, индексатор) пережидаем.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            for attempt in range(10):
                try:
                    os.replace(tmp, path)
                    break
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
