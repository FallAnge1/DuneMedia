from __future__ import annotations

import time

import httpx
import pytest

from videoarchive.core.api import ApiClient, ApiError
from videoarchive.core.telegram import FloodWait, TelegramConnectionError, translate


def client(handler, **kw) -> ApiClient:
    return ApiClient("https://archive.test/", "va_token", transport=httpx.MockTransport(handler), **kw)


def test_auth_header_and_parse():
    seen = {}

    def handler(req: httpx.Request):
        seen["auth"] = req.headers["Authorization"]
        return httpx.Response(200, json={"uploader": {"id": 1, "name": "Анна"}})

    assert client(handler).me() == {"id": 1, "name": "Анна"}
    assert seen["auth"] == "Bearer va_token"


def test_errors_in_russian():
    def handler(req):
        if req.url.path == "/api/me":
            return httpx.Response(401, json={"error": {"code": "unauthorized", "message": "x"}})
        return httpx.Response(400, json={"error": {"code": "bad_request", "message": "Поле «title» обязательно"}})

    c = client(handler)
    with pytest.raises(ApiError, match="не принял токен"):
        c.me()
    with pytest.raises(ApiError, match="title") as err:
        c.patch_video("x", {})
    assert err.value.status == 400


def test_retries_network_and_5xx(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom")
        if calls["n"] == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"tags": [{"id": 1, "name": "a", "count": 1}]})

    assert client(handler).tags()[0]["name"] == "a"
    assert calls["n"] == 3


def test_network_gives_up(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)

    def handler(req):
        raise httpx.ConnectError("down")

    with pytest.raises(ApiError, match="Нет связи с сайтом"):
        client(handler, retries=2).tags()


def test_create_video_existing_post_is_success():
    def handler(req):
        if req.method == "POST":
            return httpx.Response(409, json={"error": {"code": "tg_post_exists", "message": "…", "existing_id": "abc"}})
        return httpx.Response(200, json={"video": {"id": "abc", "title": "t"}})

    assert client(handler).create_video({"id": "new"})["id"] == "abc"


def test_put_media_content_type(tmp_path):
    f = tmp_path / "p.mp4"
    f.write_bytes(b"data")
    seen = {}

    def handler(req):
        seen["ct"] = req.headers["Content-Type"]
        seen["path"] = req.url.path
        return httpx.Response(201, json={"key": "previews/a.mp4"})

    client(handler).put_media("previews/a.mp4", f)
    assert seen == {"ct": "video/mp4", "path": "/api/media/previews/a.mp4"}


def test_telegram_error_translation():
    from telethon import errors

    assert isinstance(translate(errors.FloodWaitError(request=None, capture=42)), FloodWait)
    assert translate(errors.FloodWaitError(request=None, capture=42)).seconds == 42
    assert isinstance(translate(ConnectionError()), TelegramConnectionError)
    assert "Неверный код" in str(translate(errors.PhoneCodeInvalidError(request=None)))
