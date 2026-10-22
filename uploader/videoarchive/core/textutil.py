"""Названия из имён файлов, нормализация тегов, подпись поста и хеш для дубликатов."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

CHUNK = 4 * 1024 * 1024

# Лимиты подписи к медиа в Telegram.
CAPTION_LIMIT = 1024
CAPTION_LIMIT_PREMIUM = 2048

# Лимиты размера файла: 4000 и 8000 частей по 512 КБ.
TG_LIMIT = 4000 * 512 * 1024  # ≈2 ГБ
TG_LIMIT_PREMIUM = 8000 * 512 * 1024  # ≈4 ГБ


def file_hash(path: Path) -> str:
    """sha256(размер файла + первые 4 МБ + последние 4 МБ) — быстро даже для 4 ГБ."""
    size = path.stat().st_size
    h = hashlib.sha256()
    h.update(str(size).encode())
    with path.open("rb") as f:
        h.update(f.read(CHUNK))
        if size > CHUNK:
            f.seek(max(CHUNK, size - CHUNK))
            h.update(f.read(CHUNK))
    return h.hexdigest()


def normalize_tag(raw: str) -> str | None:
    """Та же нормализация, что на сервере: нижний регистр, без #, _ → пробел."""
    name = unicodedata.normalize("NFC", raw)
    name = re.sub(r"^#+", "", name.strip())
    name = name.replace("_", " ")
    name = re.sub(r"\s+", " ", name).strip().lower()
    return name[:64].strip() or None


def normalize_tags(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        tag = normalize_tag(item)
        if tag and tag not in out:
            out.append(tag)
    return out


def parse_tags(text: str) -> list[str]:
    """Строка «закат, #море ночной город» → теги. Разделитель — запятая (или # для хештегов)."""
    parts = re.split(r"[,\n;]+|(?=#)", text)
    return normalize_tags([p for p in parts if p.strip()])


def hashtag(tag: str) -> str:
    """Тег → хештег Telegram: пробелы и знаки становятся _, допустимы буквы, цифры и _."""
    body = re.sub(r"[^\w]+", "_", tag, flags=re.UNICODE).strip("_")
    return f"#{body}" if body else ""


# Мусор в именах файлов камер, телефонов и монтажек — проверяется по словам целиком.
_JUNK_TOKEN = re.compile(
    r"^(?:"
    r"(?:img|vid|mvi|dsc|dscf|dscn|dji|gopr|gp|gx|gh|pxl|mov|clip|mah|c|a)?\d{3,}"  # IMG0001, C0042, 20240512
    r"|img|vid|mvi|dsc|dscf|dji|gopr|pxl|screen|recording|clip"
    r"|\d{3,4}p|[2-8]k|uhd|fhd|hd|hdr|sdr|h26[45]|hevc|avc|x26[45]|prores|proxy|log|rec709"
    r"|final|copy|edit|export|render|ver|v\d+|копия|финал|\(\d+\)"
    r")$",
    re.IGNORECASE,
)


def clean_title(file_name: str) -> str:
    """Имя файла без расширения и мусора: «DJI_0042_Закат_над_морем_4K.mp4» → «Закат над морем»."""
    stem = Path(file_name).stem
    tokens = [t for t in re.split(r"[\s_.\-]+", stem) if t]
    junk = [bool(_JUNK_TOKEN.match(t)) for t in tokens]
    # Короткие числа рядом с датами/номерами («2024 05 12») — тоже мусор; «Закат 2» — нет.
    for i, t in enumerate(tokens):
        if t.isdigit() and len(t) <= 2 and ((i > 0 and junk[i - 1] and tokens[i - 1].isdigit()) or
                                           (i + 1 < len(tokens) and junk[i + 1] and tokens[i + 1].isdigit())):
            junk[i] = True
    words = [t for t, j in zip(tokens, junk) if not j]
    text = " ".join(words).strip()
    if not re.search(r"[^\W\d_]", text):  # не осталось ни одной буквы — оставляем имя как есть
        return stem
    return text[:1].upper() + text[1:]


def tg_len(text: str) -> int:
    """Длина в единицах UTF-16 — так считает Telegram (эмодзи = 2)."""
    return len(text.encode("utf-16-le")) // 2


def build_caption(title: str, description: str | None, tags: list[str], limit: int = CAPTION_LIMIT) -> str:
    """Подпись поста:

        Название
        описание

        #тег1 #тег2

    Если не влезает в лимит Telegram — сокращается описание, затем отбрасываются последние теги.
    """
    title = title.strip()
    description = (description or "").strip()
    tag_list = [h for h in (hashtag(t) for t in tags) if h]

    def compose(desc: str, tag_items: list[str]) -> str:
        head = title + (f"\n{desc}" if desc else "")
        return head + (("\n\n" + " ".join(tag_items)) if tag_items else "")

    caption = compose(description, tag_list)
    if tg_len(caption) <= limit:
        return caption
    # 1) сокращаем описание
    room = limit - tg_len(compose("", tag_list)) - 2
    if description and room > 20:
        short = description
        while short and tg_len(short) > room - 1:
            short = short[: max(len(short) - max(1, len(short) // 20), 0)]
        caption = compose(short.rstrip() + "…", tag_list) if short else compose("", tag_list)
        if tg_len(caption) <= limit:
            return caption
    # 2) убираем описание и лишние теги
    while tag_list and tg_len(compose("", tag_list)) > limit:
        tag_list.pop()
    caption = compose("", tag_list)
    while tg_len(caption) > limit:
        caption = caption[:-2] + "…"
    return caption
