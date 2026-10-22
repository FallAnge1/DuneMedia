from __future__ import annotations

import hashlib

import pytest

from videoarchive.core.textutil import (
    build_caption, clean_title, file_hash, hashtag, normalize_tag, parse_tags, tg_len,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("DJI_0042_Закат_над_морем_4K.mp4", "Закат над морем"),
        ("IMG_20240512_143000.MOV", "IMG_20240512_143000"),
        ("night-city_timelapse_final (2).mov", "Night city timelapse"),
        ("Мост в тумане 1080p copy.mp4", "Мост в тумане"),
        ("VID_20231001_120000_дождь.mp4", "Дождь"),
        ("video.mp4", "Video"),
        ("горы.2024-05-12.h265.mkv", "Горы"),
    ],
)
def test_clean_title(name, expected):
    assert clean_title(name) == expected


def test_tags():
    assert normalize_tag("  #Ночной_Город ") == "ночной город"
    assert normalize_tag("#") is None
    assert parse_tags("закат, #Море #ночной_город; дрон") == ["закат", "море", "ночной город", "дрон"]
    assert hashtag("тёплые цвета") == "#тёплые_цвета"
    assert hashtag("слоу-мо") == "#слоу_мо"
    assert hashtag("4k") == "#4k"
    assert hashtag("!!!") == ""


def test_caption_format():
    caption = build_caption("Закат", "Солнце садится в море.", ["закат", "море", "крупный план"])
    assert caption == "Закат\nСолнце садится в море.\n\n#закат #море #крупный_план"
    assert build_caption("Без тегов", None, []) == "Без тегов"
    assert build_caption("Только теги", "", ["a"]) == "Только теги\n\n#a"


def test_caption_fits_limit():
    long_desc = "очень длинное описание " * 100
    tags = [f"тег{i}" for i in range(30)]
    caption = build_caption("Название", long_desc, tags, limit=1024)
    assert tg_len(caption) <= 1024
    assert caption.startswith("Название\n")
    assert "#тег29" in caption  # теги важнее описания
    assert "…" in caption

    many_tags = [f"длинный_тег_номер_{i}" for i in range(200)]
    caption = build_caption("Название", "", many_tags, limit=1024)
    assert tg_len(caption) <= 1024
    assert caption.startswith("Название\n\n#длинный_тег_номер_0")


def test_caption_counts_utf16():
    assert tg_len("😀") == 2
    caption = build_caption("😀" * 600, None, [], limit=1024)
    assert tg_len(caption) <= 1024


def test_file_hash(tmp_path):
    small = tmp_path / "small.bin"
    small.write_bytes(b"abc")
    assert file_hash(small) == hashlib.sha256(b"3" + b"abc").hexdigest()

    big = tmp_path / "big.bin"
    data = bytes(range(256)) * (40 * 1024)  # 10 МБ
    big.write_bytes(data)
    expected = hashlib.sha256(str(len(data)).encode() + data[: 4 << 20] + data[-(4 << 20):]).hexdigest()
    assert file_hash(big) == expected

    # Середина файла на хеш не влияет — это осознанный компромисс ради скорости.
    changed = bytearray(data)
    changed[5 << 20] ^= 1
    big.write_bytes(changed)
    assert file_hash(big) == expected
