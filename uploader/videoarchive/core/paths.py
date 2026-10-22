"""Пути: папка данных пользователя, рабочие файлы, логи, ffmpeg."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from platformdirs import user_data_dir

from videoarchive import APP_NAME


def data_dir() -> Path:
    """Папка с настройками, сессией Telegram, очередью и логами.

    Windows: %APPDATA%\\VideoArchive, macOS: ~/Library/Application Support/VideoArchive,
    Linux: ~/.local/share/VideoArchive. Для тестов можно переопределить VIDEOARCHIVE_HOME.
    """
    override = os.environ.get("VIDEOARCHIVE_HOME")
    path = Path(override) if override else Path(user_data_dir(APP_NAME, appauthor=False, roaming=True))
    path.mkdir(parents=True, exist_ok=True)
    return path


def work_dir(item_id: str) -> Path:
    """Временные файлы одного видео в очереди (превью, постер, кадры)."""
    path = data_dir() / "work" / item_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_path() -> Path:
    """Файл сессии Telegram (Telethon добавит расширение .session)."""
    return data_dir() / "telegram"


def _bundle_dirs() -> list[Path]:
    dirs: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:  # собранная программа (PyInstaller)
        dirs.append(Path(meipass) / "ffmpeg")
    exe_dir = Path(sys.executable).resolve().parent
    dirs += [exe_dir / "ffmpeg", Path(__file__).resolve().parents[2] / "ffmpeg"]
    return dirs


def find_tool(name: str) -> str | None:
    """Ищет ffmpeg/ffprobe: переменная окружения, папка рядом с программой, PATH."""
    env = os.environ.get(f"VIDEOARCHIVE_{name.upper()}")
    if env and Path(env).exists():
        return env
    exe = f"{name}.exe" if sys.platform == "win32" else name
    for d in _bundle_dirs():
        candidate = d / exe
        if candidate.exists():
            return str(candidate)
    return shutil.which(name)
