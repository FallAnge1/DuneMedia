"""ffprobe и ffmpeg: метаданные, превью, постер, миниатюра для Telegram, кадры для ИИ. Видео и фото."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from videoarchive.core.paths import find_tool

log = logging.getLogger(__name__)

PREVIEW_MAX_BYTES = 1_500_000
PREVIEW_SHORT_SIDE = 480
PREVIEW_WHOLE_IF_SHORTER = 8.0  # секунд
FRAGMENT_POINTS = (0.10, 0.35, 0.60, 0.85)
FRAGMENT_LENGTH = 2.0
POSTER_SHORT_SIDE = 480
THUMB_LONG_SIDE = 320
AI_FRAME_LONG_SIDE = 512
AI_FRAME_POINTS = (0.08, 0.28, 0.5, 0.72, 0.92)
DARK_THRESHOLD = 40  # средняя яркость 0–255, ниже — кадр считается тёмным
PHOTO_POSTER_SHORT_SIDE = 720  # у фото постер — это и есть картинка на сайте, поэтому крупнее
PHOTO_AI_LONG_SIDE = 1024

VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".m2ts", ".mxf", ".wmv", ".flv", ".3gp", ".mpg", ".mpeg", ".ts", ".r3d", ".braw",
})
PHOTO_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".avif", ".tif", ".tiff", ".bmp"})
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | PHOTO_EXTENSIONS


def is_photo(path: str | Path) -> bool:
    return Path(path).suffix.lower() in PHOTO_EXTENSIONS


class MediaError(Exception):
    """Ошибка обработки видео с понятным сообщением на русском."""


@dataclass
class VideoInfo:
    duration: float | None
    width: int
    height: int  # размеры с учётом поворота и неквадратных пикселей
    fps: float | None
    codec: str | None
    size: int
    orientation: str
    resolution_label: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "VideoInfo":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})  # type: ignore[arg-type]


# ---- Ориентация и метка разрешения: та же логика, что на сервере (web/worker/lib/normalize.ts) ----

LABELS = ("SD", "HD", "FullHD", "2K", "4K", "8K")


def orientation_of(width: int, height: int) -> str:
    ratio = width / height
    if ratio > 1.05:
        return "horizontal"
    if ratio < 1 / 1.05:
        return "vertical"
    return "square"


def resolution_label_of(width: int, height: int) -> str:
    short, long = min(width, height), max(width, height)
    by_short = 5 if short >= 4320 else 4 if short >= 2160 else 3 if short >= 1440 else 2 if short >= 1080 else 1 if short >= 720 else 0
    by_long = 5 if long >= 7680 else 4 if long >= 3840 else 3 if long >= 2560 else 2 if long >= 1920 else 1 if long >= 1280 else 0
    return LABELS[max(by_short, by_long)]


# ---- Запуск инструментов ----


def _tool(name: str) -> str:
    path = find_tool(name)
    if not path:
        raise MediaError(f"Не найден {name}. Он должен лежать в папке программы или быть установлен в системе.")
    return path


def _run(args: list[str], timeout: float = 600, binary_output: bool = False) -> subprocess.CompletedProcess:
    log.debug("Запуск: %s", " ".join(args))
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=False, **kwargs)
    except subprocess.TimeoutExpired as err:
        raise MediaError("ffmpeg не уложился во время. Возможно, файл повреждён.") from err
    except OSError as err:
        raise MediaError(f"Не удалось запустить {Path(args[0]).name}: {err}") from err
    if result.returncode != 0:
        tail = result.stderr.decode("utf-8", "replace").strip().splitlines()[-5:]
        log.error("Ошибка %s (код %s): %s", Path(args[0]).name, result.returncode, "\n".join(tail))
        raise MediaError("ffmpeg не смог обработать файл: " + (tail[-1] if tail else "неизвестная ошибка"))
    return result


def _ratio(value: str | None) -> float | None:
    if not value or value in ("0/0", "N/A"):
        return None
    value = value.replace(":", "/")  # SAR в ffprobe пишется как 64:45
    if "/" in value:
        num, _, den = value.partition("/")
        try:
            n, d = float(num), float(den)
        except ValueError:
            return None
        return n / d if d else None
    try:
        return float(value)
    except ValueError:
        return None


# ---- ffprobe ----


def probe(path: Path) -> VideoInfo:
    """Длительность, размеры (с учётом поворота), fps, кодек, ориентация, метка разрешения."""
    result = _run([_tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=120)
    try:
        data = json.loads(result.stdout.decode("utf-8", "replace"))
    except ValueError as err:
        raise MediaError("ffprobe вернул непонятный ответ") from err
    return parse_probe(data, path.stat().st_size)


def probe_photo(path: Path) -> VideoInfo:
    """Размеры фото с учётом поворота. У JPEG с телефона поворот (EXIF) виден только на уровне кадра."""
    result = _run([_tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                   "-select_streams", "v:0", "-show_frames", "-read_intervals", "%+#1", str(path)], timeout=120)
    try:
        data = json.loads(result.stdout.decode("utf-8", "replace"))
    except ValueError as err:
        raise MediaError("ffprobe вернул непонятный ответ") from err
    frames = data.get("frames") or []
    streams = data.get("streams") or []
    if frames and streams and not any("rotation" in s for s in streams[0].get("side_data_list") or []):
        rotations = [s for s in frames[0].get("side_data_list") or [] if "rotation" in s]
        if rotations:
            streams[0]["side_data_list"] = (streams[0].get("side_data_list") or []) + rotations[:1]
    info = parse_probe(data, path.stat().st_size, kind="фото")
    info.duration = None
    info.fps = None
    return info


def parse_probe(data: dict, size: int, kind: str = "видео") -> VideoInfo:
    streams = [
        s for s in data.get("streams", [])
        if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")
    ]
    if not streams:
        raise MediaError("Не удалось прочитать фото" if kind == "фото" else "В файле нет видеодорожки")
    s = streams[0]
    width, height = int(s.get("width") or 0), int(s.get("height") or 0)
    if not width or not height:
        raise MediaError("Не удалось определить размер кадра")

    # Неквадратные пиксели (анаморф, DV): приводим к размерам на экране.
    sar = _ratio(s.get("sample_aspect_ratio"))
    if sar and abs(sar - 1) > 0.01:
        width = int(round(width * sar / 2) * 2)

    # Поворот (телефоны пишут вертикальное видео как горизонтальное + метку поворота).
    rotation = 0.0
    for side in s.get("side_data_list") or []:
        if "rotation" in side:
            rotation = float(side["rotation"])
    if not rotation and (s.get("tags") or {}).get("rotate"):
        rotation = float(s["tags"]["rotate"])
    if int(abs(rotation)) % 180 == 90:
        width, height = height, width

    duration = _ratio((data.get("format") or {}).get("duration")) or _ratio(s.get("duration"))
    fps = _ratio(s.get("avg_frame_rate")) or _ratio(s.get("r_frame_rate"))
    if fps and fps > 1000:  # мусорные значения у некоторых контейнеров
        fps = _ratio(s.get("r_frame_rate"))
    return VideoInfo(
        duration=round(duration, 3) if duration else None,
        width=width,
        height=height,
        fps=round(fps, 3) if fps else None,
        codec=s.get("codec_name"),
        size=size,
        orientation=orientation_of(width, height),
        resolution_label=resolution_label_of(width, height),
    )


# ---- Размеры ----


def fit_short_side(width: int, height: int, short: int) -> tuple[int, int]:
    """Масштаб по короткой стороне без увеличения, чётные размеры (нужно для H.264)."""
    current = min(width, height)
    target = min(short, current)
    scale = target / current
    w = max(2, int(round(width * scale / 2)) * 2)
    h = max(2, int(round(height * scale / 2)) * 2)
    return w, h


def fit_long_side(width: int, height: int, long: int) -> tuple[int, int]:
    current = max(width, height)
    scale = min(1.0, long / current)
    return max(2, int(round(width * scale / 2)) * 2), max(2, int(round(height * scale / 2)) * 2)


# ---- Превью ----


def preview_segments(duration: float | None) -> list[tuple[float, float]]:
    """Короткое видео — целиком; длинное — 4 фрагмента по 2 с из точек 10/35/60/85 %."""
    if not duration or duration <= PREVIEW_WHOLE_IF_SHORTER:
        return [(0.0, duration or PREVIEW_WHOLE_IF_SHORTER)]
    segments = []
    for p in FRAGMENT_POINTS:
        start = min(duration * p, max(duration - FRAGMENT_LENGTH, 0))
        segments.append((round(start, 3), FRAGMENT_LENGTH))
    return segments


def make_preview(src: Path, dst: Path, info: VideoInfo, max_bytes: int = PREVIEW_MAX_BYTES) -> Path:
    """MP4 H.264 без звука, ~480p по короткой стороне, faststart, не больше max_bytes."""
    segments = preview_segments(info.duration)
    total = sum(length for _, length in segments)
    fps = min(info.fps or 30.0, 30.0)
    short = PREVIEW_SHORT_SIDE
    crf = 26
    bitrate = int(max_bytes * 8 / total * 0.85)

    for attempt in range(6):
        w, h = fit_short_side(info.width, info.height, short)
        args = [_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y"]
        for start, length in segments:
            args += ["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(src)]
        chains = [
            f"[{i}:v:0]scale={w}:{h}:flags=bicubic,setsar=1,fps={fps:.3f},format=yuv420p,setpts=PTS-STARTPTS[v{i}]"
            for i in range(len(segments))
        ]
        concat = "".join(f"[v{i}]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=1:a=0[out]"
        args += [
            "-filter_complex", ";".join(chains) + ";" + concat,
            "-map", "[out]", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high",
            "-crf", str(crf), "-maxrate", str(bitrate), "-bufsize", str(bitrate * 2),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(dst),
        ]
        _run(args)
        size = dst.stat().st_size
        log.info("Превью %s: %dx%d crf=%d, %d КБ", src.name, w, h, crf, size // 1024)
        if size <= max_bytes:
            return dst
        # Не уложились: сильнее сжимаем, потом уменьшаем размер кадра.
        crf += 3
        bitrate = int(bitrate * 0.75)
        if attempt >= 2:
            short = 360 if short > 360 else 270
    raise MediaError("Не удалось уложить превью в 1,5 МБ")


# ---- Постер и кадры ----


def frame_brightness(src: Path, at: float) -> float | None:
    """Средняя яркость кадра (0–255) по уменьшенной копии 32×32."""
    try:
        result = _run(
            [_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-ss", f"{at:.3f}", "-i", str(src),
             "-frames:v", "1", "-vf", "scale=32:32,format=gray", "-f", "rawvideo", "-"],
            timeout=60,
        )
    except MediaError:
        return None
    data = result.stdout
    return sum(data) / len(data) if data else None


def pick_poster_time(src: Path, duration: float | None) -> float:
    """Кадр около 10 %, но не тёмный: перебираем несколько точек, иначе берём самый светлый."""
    if not duration:
        return 0.0
    best_time, best_value = duration * 0.1, -1.0
    for p in (0.10, 0.15, 0.22, 0.30, 0.40, 0.50, 0.65, 0.05):
        t = min(duration * p, max(duration - 0.1, 0))
        value = frame_brightness(src, t)
        if value is None:
            continue
        if value >= DARK_THRESHOLD:
            return t
        if value > best_value:
            best_time, best_value = t, value
    return best_time


def extract_frame(src: Path, dst: Path, at: float, size: tuple[int, int], quality: int = 4) -> Path:
    """Один кадр в JPEG. quality — шкала ffmpeg (2 лучше, 31 хуже): 4 ≈ качество 80–85."""
    seek = [] if is_photo(src) else ["-ss", f"{at:.3f}"]
    _run(
        [_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *seek, "-i", str(src),
         "-frames:v", "1", "-vf", f"scale={size[0]}:{size[1]}:flags=bicubic,setsar=1", "-q:v", str(quality), str(dst)],
        timeout=120,
    )
    if not dst.exists() or dst.stat().st_size == 0:
        raise MediaError("Не удалось извлечь кадр")
    return dst


def make_poster(src: Path, dst: Path, info: VideoInfo) -> Path:
    at = pick_poster_time(src, info.duration)
    return extract_frame(src, dst, at, fit_short_side(info.width, info.height, POSTER_SHORT_SIDE), quality=4)


def make_photo_poster(src: Path, dst: Path, info: VideoInfo) -> Path:
    """Уменьшенная копия фото для сайта (JPEG, ~720 px по короткой стороне), поворот уже учтён."""
    return extract_frame(src, dst, 0.0, fit_short_side(info.width, info.height, PHOTO_POSTER_SHORT_SIDE), quality=3)


def extract_photo_ai_frame(src: Path, out_dir: Path, info: VideoInfo) -> list[Path]:
    """Для фото ИИ получает одну картинку, но крупнее, чем кадры видео."""
    return [extract_frame(src, out_dir / "ai_0.jpg", 0.0, fit_long_side(info.width, info.height, PHOTO_AI_LONG_SIDE), quality=4)]


def make_thumb(poster: Path, dst: Path, info: VideoInfo) -> Path:
    """Миниатюра документа в Telegram: JPEG до 320 px по длинной стороне и до 200 КБ."""
    size = fit_long_side(info.width, info.height, THUMB_LONG_SIDE)
    for quality in (5, 8, 12):
        _run([_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(poster),
              "-vf", f"scale={size[0]}:{size[1]}", "-q:v", str(quality), str(dst)], timeout=60)
        if dst.stat().st_size < 200_000:
            break
    return dst


def extract_ai_frames(src: Path, out_dir: Path, info: VideoInfo) -> list[Path]:
    """4–6 кадров ~512 px из разных точек видео — ИИ получает картинки, а не видео."""
    size = fit_long_side(info.width, info.height, AI_FRAME_LONG_SIDE)
    duration = info.duration or 0
    frames = []
    for i, p in enumerate(AI_FRAME_POINTS):
        at = duration * p if duration else 0
        try:
            frames.append(extract_frame(src, out_dir / f"ai_{i}.jpg", at, size, quality=5))
        except MediaError as err:
            log.warning("Кадр %.1f с не извлечён: %s", at, err)
    if not frames:
        raise MediaError("Не удалось извлечь кадры для ИИ")
    return frames
