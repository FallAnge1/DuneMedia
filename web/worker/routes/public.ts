import { Hono } from "hono";
import type { AppEnv } from "../types";
import { getRev, loadVideo } from "../lib/db";
import { notFound, ApiError } from "../lib/http";
import { UUID_RE } from "../lib/normalize";

export const publicRoutes = new Hono<AppEnv>();

const TAGS_WITH_COUNTS = `SELECT t.id, t.name, count(vt.video_id) AS count
  FROM tags t LEFT JOIN video_tags vt ON vt.tag_id = t.id
  GROUP BY t.id ORDER BY count DESC, t.name`;

const COLLECTIONS_WITH_COUNTS = `SELECT c.id, c.name, c.emoji, c.sort_order, c.cover_key, count(vc.video_id) AS count
  FROM collections c LEFT JOIN video_collections vc ON vc.collection_id = c.id
  GROUP BY c.id ORDER BY c.sort_order, c.name`;

const LIBRARY_PREFIX = "_cache/library-";

// JSON каждого видео собирает сама D1 (SQLite json_*): на бесплатном тарифе у Worker'а 10 мс CPU
// на запрос, а JSON.stringify архива на 10+ тысяч видео в него не укладывается. Время D1 в лимит не входит.
const VIDEO_JSON = `json_object(
  'id', v.id, 'tg_channel', v.tg_channel, 'tg_message_id', v.tg_message_id, 'title', v.title,
  'description', v.description, 'file_name', v.file_name, 'file_size', v.file_size, 'duration', v.duration,
  'width', v.width, 'height', v.height, 'orientation', v.orientation, 'resolution_label', v.resolution_label,
  'fps', v.fps, 'codec', v.codec, 'preview_key', v.preview_key, 'poster_key', v.poster_key,
  'uploaded_by', v.uploaded_by, 'caption_dirty', v.caption_dirty, 'created_at', v.created_at, 'updated_at', v.updated_at,
  'tags', json((SELECT json_group_array(name) FROM (
    SELECT t.name FROM video_tags vt JOIN tags t ON t.id = vt.tag_id WHERE vt.video_id = v.id ORDER BY t.name))),
  'collections', json((SELECT json_group_array(collection_id) FROM video_collections WHERE video_id = v.id))
)`;

// Куски по диапазонам rowid: одно значение в D1 — не больше 2 МБ.
const CHUNK_ROWS = 1500;

/** Собирает полный JSON библиотеки. Порядок видео не важен: сайт сортирует сам. */
async function buildLibrary(db: D1Database): Promise<{ rev: number; json: string }> {
  const head = await db
    .prepare(
      `SELECT (SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'library_rev') AS rev,
              min(rowid) AS lo, max(rowid) AS hi FROM videos`,
    )
    .first<{ rev: number; lo: number | null; hi: number | null }>();
  const rev = Number(head?.rev ?? 0);
  const statements: D1PreparedStatement[] = [
    db.prepare(`SELECT json_group_array(json_object('id', id, 'name', name, 'count', count)) AS j FROM (${TAGS_WITH_COUNTS})`),
    db.prepare(
      `SELECT json_group_array(json_object('id', id, 'name', name, 'emoji', emoji, 'sort_order', sort_order, 'cover_key', cover_key, 'count', count)) AS j
       FROM (${COLLECTIONS_WITH_COUNTS})`,
    ),
  ];
  if (head?.lo != null && head.hi != null) {
    for (let from = head.lo; from <= head.hi; from += CHUNK_ROWS) {
      statements.push(
        db
          .prepare(`SELECT json_group_array(${VIDEO_JSON}) AS j FROM videos v WHERE v.rowid BETWEEN ? AND ?`)
          .bind(from, from + CHUNK_ROWS - 1),
      );
    }
  }
  const results = await db.batch<{ j: string }>(statements);
  const value = (i: number) => results[i]!.results[0]?.j ?? "[]";
  // Склеиваем массивы кусков без разбора JSON: «[a,b]» + «[c]» → «[a,b,c]».
  const parts: string[] = [];
  for (let i = 2; i < results.length; i++) {
    const inner = value(i).slice(1, -1);
    if (inner) parts.push(inner);
  }
  const json = `{"rev":${rev},"generated_at":${Date.now()},"videos":[${parts.join(",")}],"tags":${value(0)},"collections":${value(1)}}`;
  return { rev, json };
}

/**
 * GET /api/library — весь архив одним JSON.
 * Кэш: ETag по ревизии архива + готовый снимок в R2 (работает и на *.workers.dev,
 * где Cache API недоступен). Пока архив не меняется, D1 читает одну строку на запрос.
 */
publicRoutes.get("/library", async (c) => {
  const rev = await getRev(c.env.DB);
  const etag = `"lib-${rev}"`;
  const headers = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "public, max-age=0, must-revalidate",
    ETag: etag,
  };
  if (c.req.header("If-None-Match") === etag) return new Response(null, { status: 304, headers });

  const snapshotKey = `${LIBRARY_PREFIX}${rev}.json`;
  const snapshot = await c.env.PREVIEWS.get(snapshotKey);
  if (snapshot) return new Response(snapshot.body, { headers: { ...headers, "X-Library-Cache": "hit" } });

  const built = await buildLibrary(c.env.DB);
  const builtEtag = `"lib-${built.rev}"`;
  c.executionCtx.waitUntil(saveSnapshot(c.env, built.rev, built.json));
  return new Response(built.json, { headers: { ...headers, ETag: builtEtag, "X-Library-Cache": "miss" } });
});

async function saveSnapshot(env: Env, rev: number, json: string): Promise<void> {
  try {
    await env.PREVIEWS.put(`${LIBRARY_PREFIX}${rev}.json`, json, {
      httpMetadata: { contentType: "application/json; charset=utf-8" },
    });
    // Старые снимки больше не нужны.
    const listed = await env.PREVIEWS.list({ prefix: LIBRARY_PREFIX });
    const stale = listed.objects.map((o) => o.key).filter((k) => k !== `${LIBRARY_PREFIX}${rev}.json`);
    if (stale.length) await env.PREVIEWS.delete(stale);
  } catch (err) {
    console.error("Не удалось сохранить снимок библиотеки", err);
  }
}

publicRoutes.get("/tags", async (c) => {
  const { results } = await c.env.DB.prepare(TAGS_WITH_COUNTS).all();
  return c.json({ tags: results });
});

publicRoutes.get("/collections", async (c) => {
  const { results } = await c.env.DB.prepare(COLLECTIONS_WITH_COUNTS).all();
  return c.json({ collections: results });
});

/**
 * GET /api/search?q=… — полнотекстовый поиск (FTS5) по названию, описанию и тегам.
 * Сайт ищет на клиенте; этот эндпоинт нужен для очень больших архивов и для загрузчика.
 */
publicRoutes.get("/search", async (c) => {
  const q = (c.req.query("q") ?? "").trim();
  const limit = Math.min(Math.max(Number(c.req.query("limit") ?? 100) || 100, 1), 500);
  const terms = q
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean)
    .slice(0, 10);
  if (terms.length === 0) return c.json({ ids: [] });
  // Каждое слово ищется как префикс: «закат» найдёт «закаты», «закатное».
  const match = terms.map((t) => `"${t.replace(/"/g, '""')}"*`).join(" AND ");
  try {
    const { results } = await c.env.DB.prepare(
      "SELECT video_id FROM videos_fts WHERE videos_fts MATCH ? ORDER BY bm25(videos_fts, 0, 10, 2, 5) LIMIT ?",
    )
      .bind(match, limit)
      .all<{ video_id: string }>();
    return c.json({ ids: results.map((r) => r.video_id) });
  } catch (err) {
    console.error("Ошибка FTS", err);
    throw new ApiError(400, "bad_query", "Не удалось разобрать поисковый запрос");
  }
});

publicRoutes.get("/videos/:id{[0-9a-fA-F-]{36}}", async (c) => {
  const id = c.req.param("id");
  if (!UUID_RE.test(id)) throw notFound("Видео не найдено");
  const video = await loadVideo(c.env.DB, id);
  if (!video) throw notFound("Видео не найдено");
  const { file_hash: _hash, ...rest } = video;
  return c.json({ video: rest });
});

publicRoutes.get("/health", (c) => c.json({ ok: true }));
