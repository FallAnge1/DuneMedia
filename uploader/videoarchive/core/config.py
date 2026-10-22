"""Настройки программы: хранятся в config.json в папке пользователя, никогда не в коде."""

from __future__ import annotations

import json
import logging
import os
import tempfile
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
    """Порядок фолбэка по умолчанию (раздел 7 ТЗ). Ключей нет — провайдеры без ключа пропускаются."""
    return [
        AIProviderConfig("groq", models=["meta-llama/llama-4-scout-17b-16e-instruct"]),
        AIProviderConfig(
            "openrouter",
            models=[
                "google/gemma-3-27b-it:free",
                "mistralai/mistral-small-3.2-24b-instruct:free",
                "qwen/qwen2.5-vl-72b-instruct:free",
            ],
        ),
        AIProviderConfig("workers_ai", models=["@cf/mistralai/mistral-small-3.1-24b-instruct"]),
        AIProviderConfig("gemini", models=["gemini-2.5-flash", "gemini-2.0-flash"]),
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
    # ИИ
    ai_enabled: bool = True
    ai_auto: bool = False  # предлагать теги автоматически при добавлении файла
    ai_providers: list[AIProviderConfig] = field(default_factory=default_ai_providers)
    ai_requests_per_minute: int = 20
    # Прочее
    setup_done: bool = False
    auto_resume: bool = True

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

    def provider(self, provider_id: str) -> AIProviderConfig | None:
        return next((p for p in self.ai_providers if p.id == provider_id), None)


def write_json_atomic(path: Path, data: Any) -> None:
    """Запись через временный файл: при сбое старый файл не портится."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
