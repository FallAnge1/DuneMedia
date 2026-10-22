"""Клиент API сайта (Cloudflare Worker). Повторяет запросы при обрывах сети и ошибках 5xx/429."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import httpx

from videoarchive import __version__

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details or {}


class ApiClient:
    def __init__(self, base_url: str, token: str, *, retries: int = 5, timeout: float = 60, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.retries = retries
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=15),
            headers={"Authorization": f"Bearer {token}", "User-Agent": f"VideoArchiveUploader/{__version__}"},
            transport=transport,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    # ---- базовый запрос ----

    def request(self, method: str, path: str, *, json: Any = None, content: bytes | None = None,
                headers: dict | None = None, retry: bool = True) -> Any:
        attempts = self.retries if retry else 1
        delay = 1.0
        for attempt in range(1, attempts + 1):
            try:
                res = self._client.request(method, path, json=json, content=content, headers=headers)
            except httpx.TransportError as err:
                log.warning("%s %s: сеть (%s), попытка %d/%d", method, path, err, attempt, attempts)
                if attempt == attempts:
                    raise ApiError(0, "network", "Нет связи с сайтом. Проверьте интернет и адрес сайта.") from err
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            if res.status_code in (429, 500, 502, 503, 504) and attempt < attempts and retry:
                wait = float(res.headers.get("Retry-After") or delay)
                log.warning("%s %s: %d, повтор через %.0f с", method, path, res.status_code, wait)
                time.sleep(min(wait, 60))
                delay = min(delay * 2, 30)
                continue
            return self._parse(res)
        raise AssertionError("unreachable")

    @staticmethod
    def _parse(res: httpx.Response) -> Any:
        try:
            data = res.json()
        except ValueError:
            data = None
        if res.status_code >= 400:
            err = (data or {}).get("error") or {}
            message = err.get("message") or f"Сайт вернул ошибку {res.status_code}"
            if res.status_code == 401:
                message = "Сайт не принял токен загрузчика. Проверьте токен в настройках."
            elif res.status_code == 403:
                message = "Токен загрузчика отозван. Попросите у администратора новый."
            raise ApiError(res.status_code, err.get("code", "http"), message, err)
        return data

    # ---- методы ----

    def me(self) -> dict:
        return self.request("GET", "/api/me", retry=False)["uploader"]

    def library(self) -> dict:
        return self.request("GET", "/api/library")

    def tags(self) -> list[dict]:
        return self.request("GET", "/api/tags")["tags"]

    def collections(self) -> list[dict]:
        return self.request("GET", "/api/collections")["collections"]

    def check_hash(self, file_hash: str) -> list[dict]:
        return self.request("GET", f"/api/videos/check-hash/{file_hash}")["videos"]

    def create_video(self, payload: dict) -> dict:
        try:
            return self.request("POST", "/api/videos", json=payload)["video"]
        except ApiError as err:
            # Пост уже записан (например, ответ на прошлую попытку потерялся) — считаем успехом.
            if err.code == "tg_post_exists" and err.details.get("existing_id"):
                return self.get_video(err.details["existing_id"])
            raise

    def get_video(self, video_id: str) -> dict:
        return self.request("GET", f"/api/videos/{video_id}")["video"]

    def patch_video(self, video_id: str, payload: dict) -> dict:
        return self.request("PATCH", f"/api/videos/{video_id}", json=payload)["video"]

    def delete_video(self, video_id: str) -> dict:
        return self.request("DELETE", f"/api/videos/{video_id}")["deleted"]

    def put_media(self, key: str, path: Path) -> dict:
        content_type = "video/mp4" if key.endswith(".mp4") else "image/webp" if key.endswith(".webp") else "image/jpeg"
        return self.request("PUT", f"/api/media/{key}", content=path.read_bytes(), headers={"Content-Type": content_type})

    def delete_media(self, key: str) -> None:
        self.request("DELETE", f"/api/media/{key}")

    def ai_tag(self, payload: dict) -> dict:
        # Без повторов: при ошибке цепочка ИИ сразу переходит к следующему провайдеру.
        return self.request("POST", "/api/ai/tag", json=payload, retry=False)

    # теги
    def rename_tag(self, tag_id: int, name: str) -> dict:
        return self.request("PATCH", f"/api/tags/{tag_id}", json={"name": name})

    def merge_tags(self, source_ids: list[int], target_id: int) -> dict:
        return self.request("POST", "/api/tags/merge", json={"source_ids": source_ids, "target_id": target_id})

    def delete_tag(self, tag_id: int) -> dict:
        return self.request("DELETE", f"/api/tags/{tag_id}")

    def delete_unused_tags(self) -> list[dict]:
        return self.request("DELETE", "/api/tags/unused")["deleted"]

    # коллекции
    def create_collection(self, name: str, emoji: str | None = None) -> dict:
        return self.request("POST", "/api/collections", json={"name": name, "emoji": emoji})["collection"]

    def patch_collection(self, collection_id: int, **fields: Any) -> dict:
        return self.request("PATCH", f"/api/collections/{collection_id}", json=fields)["collection"]

    def order_collections(self, ids: list[int]) -> list[dict]:
        return self.request("PUT", "/api/collections/order", json={"ids": ids})["collections"]

    def delete_collection(self, collection_id: int) -> None:
        self.request("DELETE", f"/api/collections/{collection_id}")

    def collection_videos(self, collection_id: int, add: list[str] | None = None, remove: list[str] | None = None) -> dict:
        return self.request("POST", f"/api/collections/{collection_id}/videos", json={"add": add or [], "remove": remove or []})
