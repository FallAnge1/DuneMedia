"""Проверка и нормализация ответа ИИ: теги приводятся к уже существующим, чтобы не плодить синонимы."""

from __future__ import annotations

import json
import re

from videoarchive.core.textutil import normalize_tag

MAX_TAGS = 12
MIN_TAGS = 3

# Частые синонимы → тег, который принят в архиве (ТЗ: «дрон, таймлапс, слоумо, крупный план»).
SYNONYMS = {
    "квадрокоптер": "дрон",
    "коптер": "дрон",
    "аэросъемка": "дрон",
    "аэросъёмка": "дрон",
    "съемка с дрона": "дрон",
    "съёмка с дрона": "дрон",
    "вид с дрона": "дрон",
    "drone": "дрон",
    "aerial": "дрон",
    "timelapse": "таймлапс",
    "time lapse": "таймлапс",
    "тайм лапс": "таймлапс",
    "замедленная съемка": "слоумо",
    "замедленная съёмка": "слоумо",
    "slow motion": "слоумо",
    "слоу мо": "слоумо",
    "slowmo": "слоумо",
    "close up": "крупный план",
    "closeup": "крупный план",
    "макро": "крупный план",
    "заход солнца": "закат",
    "закат солнца": "закат",
    "sunset": "закат",
    "восход": "рассвет",
    "восход солнца": "рассвет",
    "sunrise": "рассвет",
    "ночное время": "ночь",
    "night": "ночь",
    "мегаполис": "город",
    "city": "город",
}

_ENDINGS = (
    "иями", "ями", "ами", "ией", "иях", "иям", "ого", "его", "ому", "ему", "ыми", "ими",
    "ая", "яя", "ое", "ее", "ые", "ие", "ый", "ий", "ой", "ей", "ую", "юю", "ом", "ем", "ам", "ям",
    "ах", "ях", "ов", "ев", "ья", "ье", "ью", "ия", "ию", "ии",
    "а", "я", "о", "е", "ы", "и", "у", "ю", "ь", "й",
)


def stem(word: str) -> str:
    """Грубая основа русского слова — та же логика, что в поиске на сайте."""
    if not re.search(r"[а-я]", word) or len(word) <= 4:
        return word
    for end in _ENDINGS:
        if word.endswith(end) and len(word) - len(end) >= 3:
            return word[: -len(end)]
    return word


def phrase_key(tag: str) -> str:
    return " ".join(stem(w) for w in tag.replace("ё", "е").split())


def levenshtein(a: str, b: str, limit: int = 3) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def match_existing(tag: str, existing: list[str]) -> str:
    """Тег ИИ → существующий тег архива, если это та же форма, синоним или опечатка."""
    if tag in existing:
        return tag
    synonym = SYNONYMS.get(tag) or SYNONYMS.get(tag.replace("ё", "е"))
    if synonym:
        return synonym
    key = phrase_key(tag)
    for e in existing:
        if phrase_key(e) == key:
            return e
    if len(tag) >= 5:
        allowed = 1 if len(tag) < 9 else 2
        best, best_d = None, allowed + 1
        for e in existing:
            if abs(len(e) - len(tag)) > allowed:
                continue
            d = levenshtein(tag, e, allowed)
            if d < best_d:
                best, best_d = e, d
        if best is not None:
            return best
    return tag


def extract_json(text: str) -> dict | None:
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


class InvalidAnswer(ValueError):
    """Ответ модели не подходит: нет JSON или нет тегов."""


def normalize_answer(data: dict | None, existing: list[str]) -> tuple[str, str, list[str]]:
    """Возвращает (название, описание, теги) или бросает InvalidAnswer."""
    if not data:
        raise InvalidAnswer("Модель вернула не JSON")
    raw_tags = data.get("tags")
    if isinstance(raw_tags, str):
        raw_tags = re.split(r"[,#\n]+", raw_tags)
    if not isinstance(raw_tags, list):
        raise InvalidAnswer("В ответе нет списка тегов")

    tags: list[str] = []
    for raw in raw_tags:
        if not isinstance(raw, str):
            continue
        t = normalize_tag(raw.strip(" .\"'«»"))
        if not t or len(t) > 40 or not re.search(r"\w", t) or len(t.split()) > 4:
            continue
        t = match_existing(t, existing)
        if t not in tags:
            tags.append(t)
    tags = tags[:MAX_TAGS]
    if len(tags) < MIN_TAGS:
        raise InvalidAnswer("Слишком мало тегов в ответе")

    title = str(data.get("title") or "").strip().strip("\"'«»").strip()
    title = re.sub(r"\s+", " ", title)[:100]
    description = re.sub(r"\s+", " ", str(data.get("description") or "")).strip()[:400]
    return title, description, tags
