from __future__ import annotations

import json
import time

import httpx
import pytest

from videoarchive.ai.chain import AIChain, AIError, Cooldowns, build_prompt, make_collage
from videoarchive.ai.normalize import InvalidAnswer, extract_json, match_existing, normalize_answer
from videoarchive.ai.providers import Gemini, Groq, Ollama, OpenRouter, RateLimited, WorkersAI, parse_retry_after
from videoarchive.core import media
from videoarchive.core.api import ApiError
from videoarchive.core.config import AIProviderConfig

GOOD = {"title": "Закат над морем", "description": "Солнце садится.", "tags": ["Закаты", "#море", "квадрокоптер", "тёплые цвета", "вечер"]}


@pytest.fixture
def frames(videos, tmp_path):
    info = media.probe(videos["long"])
    return media.extract_ai_frames(videos["long"], tmp_path, info)


def openai_reply(content: str, model: str = "m") -> httpx.Response:
    return httpx.Response(200, json={"model": model, "choices": [{"message": {"content": content}}]})


# ---------------------------------------------------------------- нормализация


def test_match_existing():
    existing = ["закат", "дрон", "ночной город", "водопад", "тёплые цвета"]
    assert match_existing("закаты", existing) == "закат"  # форма слова
    assert match_existing("квадрокоптер", existing) == "дрон"  # синоним
    assert match_existing("ночные города", existing) == "ночной город"
    assert match_existing("вадопад", existing) == "водопад"  # опечатка
    assert match_existing("теплые цвета", existing) == "тёплые цвета"  # ё/е
    assert match_existing("лес", existing) == "лес"  # новый тег остаётся


def test_normalize_answer():
    title, desc, tags = normalize_answer(GOOD, ["закат", "дрон"])
    assert title == "Закат над морем" and desc == "Солнце садится."
    assert tags == ["закат", "море", "дрон", "тёплые цвета", "вечер"]
    _, _, tags = normalize_answer({"tags": "лес, горы, #туман, лес"}, [])
    assert tags == ["лес", "горы", "туман"]
    with pytest.raises(InvalidAnswer):
        normalize_answer(None, [])
    with pytest.raises(InvalidAnswer):
        normalize_answer({"tags": ["один"]}, [])
    long = {"tags": [f"тег{i}" for i in range(30)] + ["слишком длинный тег из пяти слов"]}
    assert len(normalize_answer(long, [])[2]) == 12


def test_extract_json():
    assert extract_json('Вот: ```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json("нет") is None


def test_prompt_mentions_existing_tags():
    prompt = build_prompt("DJI_001.mp4", ["закат", "дрон"])
    assert "DJI_001.mp4" in prompt and "закат, дрон" in prompt and '"tags"' in prompt


def test_retry_after_formats():
    assert parse_retry_after(httpx.Response(429, headers={"retry-after": "12"})) == 12
    assert parse_retry_after(httpx.Response(429, headers={"x-ratelimit-reset-requests": "2m30s"})) == 150
    assert parse_retry_after(httpx.Response(429)) == 60


def test_collage(frames, tmp_path):
    out = make_collage(frames, tmp_path / "c.jpg")
    info = media.probe(out)
    assert info.width > info.height  # сетка 3×2


# ---------------------------------------------------------------- провайдеры


def test_groq_request_and_model_fallback(frames):
    seen = []

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        seen.append(body["model"])
        assert req.headers["Authorization"] == "Bearer gk"
        if body["model"] == "old":
            return httpx.Response(400, json={"error": {"message": "The model `old` has been decommissioned"}})
        content = body["messages"][1]["content"]
        assert content[0]["type"] == "text" and content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        return openai_reply(json.dumps(GOOD), body["model"])

    p = Groq(AIProviderConfig("groq", api_key="gk", models=["old", "new"]), transport=httpx.MockTransport(handler))
    answer = p.ask(frames[:1], "p", "s")
    assert seen == ["old", "new"] and answer.model == "new"


def test_groq_rate_limit(frames):
    p = Groq(AIProviderConfig("groq", api_key="k", models=["m"]),
             transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"retry-after": "42"}, json={"error": {"message": "rate"}})))
    with pytest.raises(RateLimited) as err:
        p.ask(frames[:1], "p", "s")
    assert err.value.retry_after == 42


def test_openrouter_discovers_free_vision_models(frames):
    catalog = {"data": [
        {"id": "a/vision:free", "pricing": {"prompt": "0", "completion": "0"}, "architecture": {"input_modalities": ["text", "image"]}, "context_length": 100},
        {"id": "b/text:free", "pricing": {"prompt": "0", "completion": "0"}, "architecture": {"input_modalities": ["text"]}},
        {"id": "c/paid-vision", "pricing": {"prompt": "0.001", "completion": "0.002"}, "architecture": {"input_modalities": ["image", "text"]}},
        {"id": "d/zero-vision", "pricing": {"prompt": "0", "completion": "0"}, "architecture": {"input_modalities": ["image"]}, "context_length": 500},
    ]}
    sent = {}

    def handler(req: httpx.Request):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json=catalog)
        sent.update(json.loads(req.content))
        return openai_reply(json.dumps(GOOD), "d/zero-vision")

    p = OpenRouter(AIProviderConfig("openrouter", api_key="k", models=[]), transport=httpx.MockTransport(handler))
    assert p.discover_models() == ["d/zero-vision", "a/vision:free"]
    assert p.models() == ["d/zero-vision", "a/vision:free", "openrouter/free"]
    answer = p.ask(frames[:2], "p", "s")
    assert sent["model"] == "d/zero-vision"
    assert answer.model == "d/zero-vision"


def test_openrouter_skips_audio_and_safety_models():
    catalog = {"data": [
        {"id": "g/music", "pricing": {"prompt": "0", "completion": "0"},
         "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text", "audio"]}},
        {"id": "n/content-safety:free", "pricing": {"prompt": "0", "completion": "0"},
         "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]}},
        {"id": "a/vision:free", "pricing": {"prompt": "0", "completion": "0"},
         "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]}},
    ]}
    p = OpenRouter(AIProviderConfig("openrouter", api_key="k"), transport=httpx.MockTransport(lambda r: httpx.Response(200, json=catalog)))
    assert p.discover_models() == ["a/vision:free"]


def test_openrouter_model_refusal_is_not_key_error(frames):
    """403 «лимит ключа» или «только для агентов» — проблема модели, а не ключа: пробуем следующую."""
    seen = []

    def handler(req: httpx.Request):
        model = json.loads(req.content)["model"]
        seen.append(model)
        if model == "paid":
            return httpx.Response(403, json={"error": {"message": "Key limit exceeded (total limit). Raise this API key's usage limit"}})
        if model == "gated":
            return httpx.Response(403, json={"error": {"message": "gated is only available on agentic harnesses"}})
        if model == "empty":
            return openai_reply("", model)
        return openai_reply(json.dumps(GOOD), model)

    p = OpenRouter(AIProviderConfig("openrouter", api_key="k", models=["paid", "gated", "empty", "ok"]), transport=httpx.MockTransport(handler))
    assert p.ask(frames[:1], "p", "s").model == "ok"
    assert seen == ["paid", "gated", "empty", "ok"]


def test_renamed_models_fall_back_to_discovered(frames):
    """Модели из настроек пропали у провайдера — программа берёт актуальные из его списка."""
    seen = []

    def handler(req: httpx.Request):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen/qwen3.8-27b"}, {"id": "whisper-large-v3"}]})
        model = json.loads(req.content)["model"]
        seen.append(model)
        if model.startswith("old"):
            return httpx.Response(404, json={"error": {"message": f"The model `{model}` does not exist"}})
        return openai_reply(json.dumps(GOOD), model)

    p = Groq(AIProviderConfig("groq", api_key="k", models=["old-a", "old-b"]), transport=httpx.MockTransport(handler))
    assert p.ask(frames[:1], "p", "s").model == "qwen/qwen3.8-27b"
    assert seen == ["old-a", "old-b", "qwen/qwen3.8-27b"]


def test_gemini_request(frames):
    def handler(req: httpx.Request):
        assert req.url.path.endswith("/models/gemini-flash-latest:generateContent")
        body = json.loads(req.content)
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["contents"][0]["parts"][1]["inline_data"]["mime_type"] == "image/jpeg"
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(GOOD)}]}}]})

    p = Gemini(AIProviderConfig("gemini", api_key="k", models=["gemini-flash-latest"]), transport=httpx.MockTransport(handler))
    assert json.loads(p.ask(frames, "p", "s").text)["title"] == "Закат над морем"


def test_gemini_rate_limit_delay(frames):
    body = '{"error": {"code": 429, "details": [{"retryDelay": "37s"}]}}'
    p = Gemini(AIProviderConfig("gemini", api_key="k", models=["m"]), transport=httpx.MockTransport(lambda r: httpx.Response(429, text=body)))
    with pytest.raises(RateLimited) as err:
        p.ask(frames, "p", "s")
    assert err.value.retry_after == 37


def test_ollama_uses_installed_vision_models(frames):
    def handler(req: httpx.Request):
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3:8b"}, {"name": "qwen2.5vl:7b"}]})
        body = json.loads(req.content)
        assert body["model"] == "qwen2.5vl:7b" and body["format"] == "json" and len(body["messages"][1]["images"]) == 2
        return httpx.Response(200, json={"message": {"content": json.dumps(GOOD)}})

    p = Ollama(AIProviderConfig("ollama", models=["gemma3:4b"], base_url="http://ollama.test"), transport=httpx.MockTransport(handler))
    assert p.models() == ["qwen2.5vl:7b"]  # gemma3 не установлена — берём то, что есть
    assert json.loads(p.ask(frames[:2], "p", "s").text)["title"] == "Закат над морем"


class FakeSiteApi:
    def __init__(self, fail: ApiError | None = None):
        self.fail = fail
        self.payload = None

    def ai_tag(self, payload):
        if self.fail:
            raise self.fail
        self.payload = payload
        return {"provider": "workers-ai", "model": "@cf/x/y", "text": json.dumps(GOOD)}


def test_workers_ai_via_site(frames):
    api = FakeSiteApi()
    p = WorkersAI(AIProviderConfig("workers_ai", models=[]), api)
    answer = p.ask(frames[:1], "p", "s")
    assert answer.model == "@cf/x/y" and "model" not in api.payload  # модель по умолчанию — на сайте
    quota = WorkersAI(AIProviderConfig("workers_ai"), FakeSiteApi(ApiError(429, "ai_quota", "Лимит")))
    with pytest.raises(RateLimited):
        quota.ask(frames[:1], "p", "s")


# ---------------------------------------------------------------- цепочка


def test_chain_falls_back_and_remembers_cooldown(frames, tmp_path):
    calls = []

    def groq_handler(req):
        calls.append("groq")
        return httpx.Response(429, headers={"retry-after": "3600"}, json={"error": {"message": "daily limit"}})

    def gemini_handler(req):
        calls.append("gemini")
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "не JSON"}]}}]})

    groq = Groq(AIProviderConfig("groq", api_key="k", models=["m"]), transport=httpx.MockTransport(groq_handler))
    gemini = Gemini(AIProviderConfig("gemini", api_key="k", models=["g"]), transport=httpx.MockTransport(gemini_handler))
    site = WorkersAI(AIProviderConfig("workers_ai"), FakeSiteApi())
    cooldowns = Cooldowns(tmp_path / "cd.json")
    chain = AIChain([groq, gemini, site], cooldowns)

    s = chain.suggest(frames, "f.mp4", ["закат"])
    assert s.provider == "Cloudflare Workers AI" and s.tags[0] == "закат"
    assert calls == ["groq", "gemini"]  # Groq — лимит, Gemini — невалидный JSON, ответил Workers AI
    assert cooldowns.blocked("groq") > 3500

    # второй раз Groq пропускается сразу (остывает), и это переживает «перезапуск»
    chain2 = AIChain([groq, gemini, site], Cooldowns(tmp_path / "cd.json"))
    chain2.suggest(frames, "f.mp4", [])
    assert calls == ["groq", "gemini", "gemini"]


def test_chain_all_fail(frames, tmp_path):
    bad = Groq(AIProviderConfig("groq", api_key="k", models=["m"]),
               transport=httpx.MockTransport(lambda r: httpx.Response(500, json={"error": {"message": "oops"}})))
    with pytest.raises(AIError, match="Ни один ИИ-провайдер не ответил. Groq"):
        AIChain([bad], Cooldowns(tmp_path / "c.json")).suggest(frames, "f", [])


def test_rate_limiter_spaces_requests(frames, tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    site = WorkersAI(AIProviderConfig("workers_ai"), FakeSiteApi())
    chain = AIChain([site], Cooldowns(tmp_path / "c.json"), rpm_override=6)  # раз в 10 с
    chain.suggest(frames, "f", [])
    chain.suggest(frames, "f", [])
    assert sleeps and 9 <= sleeps[-1] <= 10.1
