import { Hono } from "hono";
import type { AppEnv } from "../types";
import { requireUploader } from "../lib/auth";
import { ApiError, badRequest, notFound } from "../lib/http";
import { contentTypeForKey, MEDIA_KEY_RE } from "../lib/normalize";

const LONG_CACHE = "public, max-age=31536000, immutable";

// ---------------------------------------------------------------------------
// GET /media/:key — отдача превью и постеров (публично).
// Файлы маленькие (≤ нескольких МБ), поэтому объект читается целиком, а Range
// вырезается из него: так одинаково работают кэш Cloudflare и прямое чтение из R2.
// ---------------------------------------------------------------------------

export const mediaPublicRoutes = new Hono<AppEnv>();

mediaPublicRoutes.get("/*", async (c) => {
  const key = decodeURIComponent(new URL(c.req.url).pathname.replace(/^\/media\//, ""));
  if (!MEDIA_KEY_RE.test(key)) throw notFound("Файл не найден");

  const cache = (globalThis as unknown as { caches?: CacheStorage }).caches?.default;
  const cacheKey = new Request(new URL(`/media/${key}`, c.req.url).toString(), { method: "GET" });

  let body: ArrayBuffer;
  let etag: string;
  let contentType: string;
  const cached = cache ? await cache.match(cacheKey) : undefined;
  if (cached) {
    body = await cached.arrayBuffer();
    etag = cached.headers.get("ETag") ?? "";
    contentType = cached.headers.get("Content-Type") ?? contentTypeForKey(key);
  } else {
    const object = await c.env.PREVIEWS.get(key);
    if (!object) throw notFound("Файл не найден");
    body = await object.arrayBuffer();
    etag = object.httpEtag;
    contentType = object.httpMetadata?.contentType ?? contentTypeForKey(key);
    if (cache) {
      const toCache = new Response(body.slice(0), {
        headers: { "Content-Type": contentType, ETag: etag, "Cache-Control": LONG_CACHE },
      });
      c.executionCtx.waitUntil(cache.put(cacheKey, toCache));
    }
  }

  const headers = new Headers({
    "Content-Type": contentType,
    "Cache-Control": LONG_CACHE,
    "Accept-Ranges": "bytes",
    ETag: etag,
  });
  if (etag && c.req.header("If-None-Match") === etag) return new Response(null, { status: 304, headers });

  const size = body.byteLength;
  const rangeHeader = c.req.header("Range");
  if (rangeHeader) {
    const range = parseRange(rangeHeader, size);
    if (range === "invalid") {
      headers.set("Content-Range", `bytes */${size}`);
      return new Response(null, { status: 416, headers });
    }
    if (range) {
      headers.set("Content-Range", `bytes ${range.start}-${range.end}/${size}`);
      headers.set("Content-Length", String(range.end - range.start + 1));
      return new Response(body.slice(range.start, range.end + 1), { status: 206, headers });
    }
  }
  headers.set("Content-Length", String(size));
  return new Response(body, { status: 200, headers });
});

/** Разбирает один диапазон "bytes=a-b". null — заголовок не поддерживается (отдаём весь файл). */
export function parseRange(header: string, size: number): { start: number; end: number } | "invalid" | null {
  const m = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (!m) return null;
  const [, a, b] = m;
  if (a === "" && b === "") return null;
  let start: number;
  let end: number;
  if (a === "") {
    const suffix = Number(b);
    if (suffix === 0) return "invalid";
    start = Math.max(size - suffix, 0);
    end = size - 1;
  } else {
    start = Number(a);
    end = b === "" ? size - 1 : Math.min(Number(b), size - 1);
  }
  if (start >= size || start > end) return "invalid";
  return { start, end };
}

// ---------------------------------------------------------------------------
// PUT /api/media/:key — загрузка превью или постера (только загрузчики).
// ---------------------------------------------------------------------------

export const mediaUploadRoutes = new Hono<AppEnv>();
mediaUploadRoutes.use("*", requireUploader);

function keyFromPath(url: string): string {
  const key = decodeURIComponent(new URL(url).pathname.replace(/^\/api\/media\//, ""));
  if (!MEDIA_KEY_RE.test(key)) {
    throw badRequest("Некорректный ключ файла. Допустимо: previews/<имя>.mp4, posters/<имя>.jpg|webp, covers/<имя>.jpg|png|webp");
  }
  return key;
}

function looksLike(key: string, bytes: Uint8Array): boolean {
  const ascii = (from: number, to: number) => String.fromCharCode(...bytes.subarray(from, to));
  if (key.endsWith(".mp4")) return bytes.length > 12 && ascii(4, 8) === "ftyp";
  if (key.endsWith(".webp")) return bytes.length > 12 && ascii(0, 4) === "RIFF" && ascii(8, 12) === "WEBP";
  if (key.endsWith(".png")) return bytes.length > 8 && bytes[0] === 0x89 && ascii(1, 4) === "PNG";
  return bytes.length > 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff;
}

mediaUploadRoutes.put("/*", async (c) => {
  const key = keyFromPath(c.req.url);
  const maxBytes = Number(c.env.MEDIA_MAX_BYTES) || 8 * 1024 * 1024;
  const declared = Number(c.req.header("Content-Length") ?? NaN);
  if (Number.isFinite(declared) && declared > maxBytes) {
    throw new ApiError(413, "too_large", `Файл больше ${Math.round(maxBytes / 1024 / 1024)} МБ`);
  }
  const bytes = new Uint8Array(await c.req.arrayBuffer());
  if (bytes.byteLength === 0) throw badRequest("Пустой файл");
  if (bytes.byteLength > maxBytes) {
    throw new ApiError(413, "too_large", `Файл больше ${Math.round(maxBytes / 1024 / 1024)} МБ`);
  }
  if (!looksLike(key, bytes)) throw badRequest("Содержимое файла не соответствует расширению");

  const object = await c.env.PREVIEWS.put(key, bytes, {
    httpMetadata: { contentType: contentTypeForKey(key), cacheControl: LONG_CACHE },
    customMetadata: { uploader: c.var.uploader.name },
  });
  return c.json({ key, size: bytes.byteLength, etag: object?.httpEtag ?? null, url: `/media/${key}` }, 201);
});

/** DELETE /api/media/:key — удалить «осиротевший» файл (если загрузка видео сорвалась). */
mediaUploadRoutes.delete("/*", async (c) => {
  const key = keyFromPath(c.req.url);
  const used = await c.env.DB.prepare("SELECT id FROM videos WHERE preview_key = ?1 OR poster_key = ?1 LIMIT 1")
    .bind(key)
    .first<{ id: string }>();
  if (used) throw new ApiError(409, "media_in_use", "Файл используется видео", { video_id: used.id });
  const cover = await c.env.DB.prepare("SELECT id FROM collections WHERE cover_key = ? LIMIT 1").bind(key).first<{ id: number }>();
  if (cover) throw new ApiError(409, "media_in_use", "Файл — обложка доски", { collection_id: cover.id });
  await c.env.PREVIEWS.delete(key);
  return c.json({ deleted: key });
});
