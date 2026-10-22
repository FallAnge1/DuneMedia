import { Hono } from "hono";
import type { AppEnv } from "../types";
import { attachRelations, getRev, loadVideo, VIDEO_COLUMNS, type VideoRow } from "../lib/db";
import { notFound, ApiError } from "../lib/http";
import { UUID_RE } from "../lib/normalize";

export const publicRoutes = new Hono<AppEnv>();

const TAGS_WITH_COUNTS = `SELECT t.id, t.name, count(vt.video_id) AS count
  FROM tags t LEFT JOIN video_tags vt ON vt.tag_id = t.id
  GROUP BY t.id ORDER BY count DESC, t.name`;

const COLLECTIONS_WITH_COUNTS = `SELECT c.id, c.name, c.emoji, c.sort_order, count(vc.video_id) AS count
  FROM collections c LEFT JOIN video_collections vc ON vc.collection_id = c.id
  GROUP BY c.id ORDER BY c.sort_order, c.name`;

const LIBRARY_PREFIX = "_cache/library-";

/** Собирает полный JSON библиотеки из D1 одной транзакцией (batch). */
async function buildLibrary(db: D1Database): Promise<{ rev: number; json: string }> {
  const [rev, videos, tagLinks, colLinks, tags, collections] = await db.batch([
    db.prepare("SELECT CAST(value AS INTEGER) AS rev FROM meta WHERE key = 'library_rev'"),
    db.prepare(`SELECT ${VIDEO_COLUMNS} FROM videos ORDER BY created_at DESC`),
    db.prepare("SELECT vt.video_id, t.name FROM video_tags vt JOIN tags t ON t.id = vt.tag_id ORDER BY t.name"),
    db.prepare("SELECT video_id, collection_id FROM video_collections"),
    db.prepare(TAGS_WITH_COUNTS),
    db.prepare(COLLECTIONS_WITH_COUNTS),
  ]);
  const revNum = Number((rev!.results[0] as { rev: number } | undefined)?.rev ?? 0);
  const list = attachRelations(
    videos!.results as unknown as VideoRow[],
    tagLinks!.results as unknown as { video_id: string; name: string }[],
    colLinks!.results as unknown as { video_id: string; collection_id: number }[],
  ).map(({ file_hash: _hash, ...v }) => v);
  const json = JSON.stringify({
    rev: revNum,
    generated_at: Date.now(),
    videos: list,
    tags: tags!.results,
    collections: collections!.results,
  });
  return { rev: revNum, json };
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
