#!/usr/bin/env python3
"""Скачивает статические ffmpeg и ffprobe для сборки в uploader/ffmpeg/.

    python build/get_ffmpeg.py                 # для текущей системы
    python build/get_ffmpeg.py --platform mac-arm64

Сборки ffmpeg — GPL (с libx264 для H.264-превью). Программа вызывает ffmpeg как отдельный файл,
поэтому её собственный код под GPL не попадает; исходники ffmpeg: https://ffmpeg.org/download.html.
Другой источник можно указать переменными FFMPEG_URL и FFPROBE_URL (zip или tar.xz).
"""

from __future__ import annotations

import argparse
import io
import os
import platform
import shutil
import stat
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ffmpeg"

BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
SOURCES: dict[str, list[dict[str, str]]] = {
    # shared: маленькие ffmpeg.exe/ffprobe.exe + общие DLL — вдвое меньше двух статических файлов
    "win64": [{"both": f"{BTBN}/ffmpeg-master-latest-win64-gpl-shared.zip"}, {"both": f"{BTBN}/ffmpeg-master-latest-win64-gpl.zip"}],
    "linux64": [{"both": f"{BTBN}/ffmpeg-master-latest-linux64-gpl.tar.xz"}],
    "mac-arm64": [
        {"ffmpeg": "https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffmpeg.zip",
         "ffprobe": "https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffprobe.zip"},
        # запасной вариант: Intel-сборка, на Apple Silicon работает через Rosetta 2
        {"ffmpeg": "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip", "ffprobe": "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"},
    ],
    "mac-x64": [
        {"ffmpeg": "https://ffmpeg.martin-riedl.de/redirect/latest/macos/amd64/release/ffmpeg.zip",
         "ffprobe": "https://ffmpeg.martin-riedl.de/redirect/latest/macos/amd64/release/ffprobe.zip"},
        {"ffmpeg": "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip", "ffprobe": "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"},
    ],
}


def current_platform() -> str:
    machine = platform.machine().lower()
    if sys.platform == "win32":
        return "win64"
    if sys.platform == "darwin":
        return "mac-arm64" if machine in ("arm64", "aarch64") else "mac-x64"
    return "linux64"


def download(url: str) -> bytes:
    print(f"  скачиваю {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "videoarchive-build"})
    with urllib.request.urlopen(req, timeout=300) as res:  # noqa: S310
        return res.read()


def extract(data: bytes, url: str, wanted: set[str]) -> dict[str, bytes]:
    """Достаёт из архива ffmpeg/ffprobe (с .exe или без) и DLL из папки bin — из любой вложенной папки."""
    found: dict[str, bytes] = {}
    if url.endswith(".zip") or data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                base = Path(name).name
                is_dll = base.lower().endswith(".dll") and "/bin/" in name
                if (Path(base).stem in wanted or is_dll) and not name.endswith("/"):
                    found[base] = z.read(name)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as t:
            for m in t.getmembers():
                base = Path(m.name).name
                if m.isfile() and Path(base).stem in wanted:
                    f = t.extractfile(m)
                    if f:
                        found[base] = f.read()
    return found


def fetch(plat: str) -> None:
    exe = ".exe" if plat == "win64" else ""
    env_ffmpeg, env_ffprobe = os.environ.get("FFMPEG_URL"), os.environ.get("FFPROBE_URL")
    sources = [{"ffmpeg": env_ffmpeg, "ffprobe": env_ffprobe or env_ffmpeg}] if env_ffmpeg else SOURCES[plat]
    errors = []
    for source in sources:
        try:
            files: dict[str, bytes] = {}
            if "both" in source:
                url = source["both"]
                files.update(extract(download(url), url, {"ffmpeg", "ffprobe"}))
            else:
                for tool in ("ffmpeg", "ffprobe"):
                    url = source[tool]
                    files.update(extract(download(url), url, {tool}))
            needed = {f"ffmpeg{exe}", f"ffprobe{exe}"}
            if not needed <= files.keys():
                raise RuntimeError(f"в архиве нет {needed - files.keys()}")
            shutil.rmtree(OUT, ignore_errors=True)
            OUT.mkdir(parents=True)
            for name in sorted(needed | {n for n in files if n.lower().endswith(".dll")}):
                target = OUT / name
                target.write_bytes(files[name])
                target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
                print(f"  → {target} ({target.stat().st_size // (1024 * 1024)} МБ)")
            return
        except Exception as err:  # noqa: BLE001
            print(f"  не получилось: {err}")
            errors.append(str(err))
    raise SystemExit("Не удалось скачать ffmpeg: " + "; ".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--platform", choices=sorted(SOURCES), default=current_platform())
    args = parser.parse_args()
    print(f"ffmpeg для {args.platform}:")
    fetch(args.platform)


if __name__ == "__main__":
    main()
