from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Каждый тест работает в своей «папке пользователя»."""
    home = tmp_path / "home"
    monkeypatch.setenv("VIDEOARCHIVE_HOME", str(home))
    return home


def make_video(path: Path, *, size: str = "640x360", duration: float = 5, source: str = "testsrc2",
               extra_filter: str = "", rotate: int | None = None, audio: bool = False) -> Path:
    vf = f"{source}=s={size}:r=25" + (f",{extra_filter}" if extra_filter else "")
    args = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", vf]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440"]
    args += ["-t", str(duration), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac", "-shortest"]
    if rotate is not None:
        args += ["-metadata:s:v:0", f"rotate={rotate}"]
    args.append(str(path))
    subprocess.run(args, check=True)
    return path


@pytest.fixture(scope="session")
def videos(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("videos")
    return {
        "short": make_video(d / "short_clip.mp4", duration=4),
        "long": make_video(d / "DJI_0042_Закат_над_морем_4K.mp4", size="1920x1080", duration=40, audio=True),
        "vertical": make_video(d / "vertical.mp4", size="360x640", duration=12),
        # Первые 30 % ролика — чёрные: постер должен взять светлый кадр.
        "dark": make_video(d / "dark_start.mp4", size="640x360", duration=20,
                           extra_filter="drawbox=c=black:t=fill:enable='lt(t,6)'"),
    }
