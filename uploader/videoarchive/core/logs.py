"""Подробный лог в файл (logs/app.log с ротацией) — для разбора проблем."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from videoarchive.core.paths import logs_dir


def setup_logging(verbose: bool = False) -> None:
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return
    root.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(threadName)s %(name)s: %(message)s")

    file_handler = RotatingFileHandler(logs_dir() / "app.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)

    if sys.stderr is not None:  # в собранной Windows-программе stderr может отсутствовать
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        console.setLevel(logging.DEBUG if verbose else logging.INFO)
        root.addHandler(console)

    # Telethon очень разговорчив на DEBUG.
    logging.getLogger("telethon").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
