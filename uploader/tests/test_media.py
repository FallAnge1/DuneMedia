from __future__ import annotations

import json
import subprocess

import pytest

from videoarchive.core import media
from videoarchive.core.media import MediaError, parse_probe


def duration_of(path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", str(path)],
                         capture_output=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def test_probe(videos):
    info = media.probe(videos["long"])
    assert info.width == 1920 and info.height == 1080
    assert info.orientation == "horizontal"
    assert info.resolution_label == "FullHD"
    assert info.fps == 25
    assert info.codec == "h264"
    assert 39 < (info.duration or 0) < 41

    v = media.probe(videos["vertical"])
    assert (v.width, v.height, v.orientation, v.resolution_label) == (360, 640, "vertical", "SD")


def test_probe_rotation_and_sar():
    data = {
        "format": {"duration": "10.0"},
        "streams": [
            {"codec_type": "audio"},
            {"codec_type": "video", "codec_name": "hevc", "width": 3840, "height": 2160, "avg_frame_rate": "30000/1001",
             "side_data_list": [{"rotation": -90}]},
        ],
    }
    info = parse_probe(data, 100)
    assert (info.width, info.height, info.orientation, info.resolution_label) == (2160, 3840, "vertical", "4K")
    assert info.fps == pytest.approx(29.97, abs=0.01)

    anamorphic = {"format": {}, "streams": [{"codec_type": "video", "width": 720, "height": 576, "sample_aspect_ratio": "64:45"}]}
    assert parse_probe(anamorphic, 1).width == 1024

    cover_only = {"format": {}, "streams": [{"codec_type": "video", "width": 600, "height": 600, "disposition": {"attached_pic": 1}}]}
    with pytest.raises(MediaError, match="нет видеодорожки"):
        parse_probe(cover_only, 1)


def test_preview_segments():
    assert media.preview_segments(5) == [(0.0, 5)]
    assert media.preview_segments(None) == [(0.0, 8.0)]
    segs = media.preview_segments(100)
    assert [s for s, _ in segs] == [10.0, 35.0, 60.0, 85.0]
    assert all(length == 2.0 for _, length in segs)
    # фрагмент не выходит за конец
    assert media.preview_segments(9)[-1][0] <= 7


def test_preview_long_video(videos, tmp_path):
    info = media.probe(videos["long"])
    out = media.make_preview(videos["long"], tmp_path / "p.mp4", info)
    assert out.stat().st_size <= media.PREVIEW_MAX_BYTES
    assert 7.5 <= duration_of(out) <= 8.5  # 4 фрагмента по 2 с
    p = media.probe(out)
    assert (p.width, p.height) == (854, 480)
    assert p.codec == "h264"
    # без звука
    streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(out)],
                                        capture_output=True, check=True).stdout)["streams"]
    assert [s["codec_type"] for s in streams] == ["video"]
    # faststart: moov в начале файла
    head = out.read_bytes()[:200_000]
    assert head.find(b"moov") < head.find(b"mdat")


def test_preview_short_video_is_whole(videos, tmp_path):
    info = media.probe(videos["short"])
    out = media.make_preview(videos["short"], tmp_path / "p.mp4", info)
    assert 3.8 <= duration_of(out) <= 4.2
    p = media.probe(out)
    assert (p.width, p.height) == (640, 360)  # не увеличиваем маленькое видео


def test_preview_respects_size_limit(videos, tmp_path):
    info = media.probe(videos["long"])
    out = media.make_preview(videos["long"], tmp_path / "p.mp4", info, max_bytes=150_000)
    assert out.stat().st_size <= 150_000


def test_poster_skips_dark_frames(videos, tmp_path):
    info = media.probe(videos["dark"])
    assert media.frame_brightness(videos["dark"], 2.0) < media.DARK_THRESHOLD
    at = media.pick_poster_time(videos["dark"], info.duration)
    assert at >= 6
    poster = media.make_poster(videos["dark"], tmp_path / "poster.jpg", info)
    assert poster.read_bytes()[:3] == b"\xff\xd8\xff"
    thumb = media.make_thumb(poster, tmp_path / "thumb.jpg", info)
    t = media.probe(thumb)
    assert max(t.width, t.height) <= 320
    assert thumb.stat().st_size < 200_000


def test_ai_frames(videos, tmp_path):
    info = media.probe(videos["vertical"])
    frames = media.extract_ai_frames(videos["vertical"], tmp_path, info)
    assert len(frames) == 5
    f = media.probe(frames[0])
    assert max(f.width, f.height) <= 512


def test_broken_file(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video at all")
    with pytest.raises(MediaError):
        media.probe(bad)


def test_photo_probe_respects_exif_rotation(photos):
    info = media.probe_photo(photos["rotated"])
    assert (info.width, info.height, info.orientation) == (600, 800, "vertical")
    assert info.duration is None and info.fps is None
    png = media.probe_photo(photos["png"])
    assert (png.width, png.height, png.orientation) == (1280, 720, "horizontal")


def test_photo_poster_and_ai_frame(photos, tmp_path):
    info = media.probe_photo(photos["rotated"])
    poster = media.make_photo_poster(photos["rotated"], tmp_path / "poster.jpg", info)
    assert media.probe_photo(poster).width == 600  # маленькое фото не увеличиваем, поворот учтён
    frames = media.extract_photo_ai_frame(photos["rotated"], tmp_path, info)
    assert len(frames) == 1 and frames[0].exists()


def test_media_extensions():
    assert media.is_photo("a/IMG_1.HEIC") and media.is_photo("b.jpeg")
    assert not media.is_photo("clip.mov")
    assert {".mp4", ".jpg"} <= media.MEDIA_EXTENSIONS
