import { Hono } from "hono";
import type { AppEnv } from "../types";
import { requireUploader } from "../lib/auth";
import { bumpRev, ftsSync } from "../lib/db";
import { ApiError, badRequest, notFound, readJsonObject } from "../lib/http";
import { idList, normalizeTag } from "../lib/normalize";

/**
 * Управление тегами (только для загрузчиков). Публичный список — GET /api/tags.
 * Операции, меняющие теги у видео, возвращают affected_video_ids: загрузчику
 * нужно обновить подписи этих постов в Telegram.
 */
export const tagRoutes = new Hono<AppEnv>();
tagRoutes.use("*", requireUploader);

function readName(body: Record<string, unknown>): string {
  if (typeof body.name !== "string") throw badRequest("Поле «name» обязательно");
  const name = normalizeTag(body.name);
  if (!name) throw badRequest("Название тега не может быть пустым");
  return name;
}

function parseId(raw: string): number {
  const id = Number(raw);
  if (!Number.isInteger(id) || id <= 0) throw notFound("Тег не найден");
  return id;
}

async function videosWithTags(db: D1Database, tagIds: number[]): Promise<string[]> {
  const { results } = await db
    .prepare("SELECT DISTINCT video_id FROM video_tags WHERE tag_id IN (SELECT value FROM json_each(?))")
    .bind(JSON.stringify(tagIds))
    .all<{ video_id: string }>();
  return results.map((r) => r.video_id);
}

/** Помечает видео изменёнными и пересобирает их строки поиска. */
function touchVideos(db: D1Database, ids: string[]): D1PreparedStatement[] {
  if (ids.length === 0) return [];
  return [
    db.prepare("UPDATE videos SET updated_at = ? WHERE id IN (SELECT value FROM json_each(?))").bind(Date.now(), JSON.stringify(ids)),
    ...ftsSync(db, ids),
  ];
}

tagRoutes.post("/", async (c) => {
  const name = readName(await readJsonObject(c));
  const db = c.env.DB;
  const existing = await db.prepare("SELECT id, name FROM tags WHERE name = ?").bind(name).first<{ id: number; name: string }>();
  if (existing) return c.json({ tag: existing, existing: true });
  const [inserted] = await db.batch([
    db.prepare("INSERT INTO tags (name) VALUES (?) RETURNING id, name").bind(name),
    bumpRev(db),
  ]);
  return c.json({ tag: inserted!.results[0] }, 201);
});

/** Переименование. Если тег с новым именем уже есть — 409, используйте слияние. */
tagRoutes.patch("/:id{[0-9]+}", async (c) => {
  const id = parseId(c.req.param("id"));
  const name = readName(await readJsonObject(c));
  const db = c.env.DB;
  const tag = await db.prepare("SELECT id, name FROM tags WHERE id = ?").bind(id).first<{ id: number; name: string }>();
  if (!tag) throw notFound("Тег не найден");
  if (tag.name === name) return c.json({ tag, affected_video_ids: [] });
  const clash = await db.prepare("SELECT id FROM tags WHERE name = ?").bind(name).first<{ id: number }>();
  if (clash) {
    throw new ApiError(409, "tag_exists", `Тег «${name}» уже существует. Чтобы объединить теги, используйте слияние.`, {
      existing_id: clash.id,
    });
  }
  const affected = await videosWithTags(db, [id]);
  await db.batch([
    db.prepare("UPDATE tags SET name = ? WHERE id = ?").bind(name, id),
    ...touchVideos(db, affected),
    bumpRev(db),
  ]);
  return c.json({ tag: { id, name }, affected_video_ids: affected });
});

/** Слияние: все видео с тегами source_ids получают target_id, исходные теги удаляются. */
tagRoutes.post("/merge", async (c) => {
  const body = await readJsonObject(c);
  const sources = idList(body.source_ids, "source_ids");
  const target = Number(body.target_id);
  if (!Number.isInteger(target) || target <= 0) throw badRequest("Поле «target_id» обязательно");
  const sourceIds = sources.filter((s) => s !== target);
  if (sourceIds.length === 0) throw badRequest("Укажите хотя бы один тег, отличный от целевого");
  const db = c.env.DB;

  const { results } = await db
    .prepare("SELECT id FROM tags WHERE id IN (SELECT value FROM json_each(?))")
    .bind(JSON.stringify([...sourceIds, target]))
    .all<{ id: number }>();
  const found = new Set(results.map((r) => r.id));
  const missing = [...sourceIds, target].filter((x) => !found.has(x));
  if (missing.length) throw notFound(`Теги не найдены: ${missing.join(", ")}`);

  const affected = await videosWithTags(db, sourceIds);
  const json = JSON.stringify(sourceIds);
  await db.batch([
    db
      .prepare(
        "INSERT OR IGNORE INTO video_tags (video_id, tag_id) SELECT video_id, ? FROM video_tags WHERE tag_id IN (SELECT value FROM json_each(?))",
      )
      .bind(target, json),
    db.prepare("DELETE FROM video_tags WHERE tag_id IN (SELECT value FROM json_each(?))").bind(json),
    db.prepare("DELETE FROM tags WHERE id IN (SELECT value FROM json_each(?))").bind(json),
    ...touchVideos(db, affected),
    bumpRev(db),
  ]);
  const tag = await db.prepare("SELECT id, name FROM tags WHERE id = ?").bind(target).first();
  return c.json({ tag, merged_ids: sourceIds, affected_video_ids: affected });
});

/** Удалить теги, которые не привязаны ни к одному видео. */
tagRoutes.delete("/unused", async (c) => {
  const db = c.env.DB;
  const [deleted] = await db.batch([
    db.prepare("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM video_tags) RETURNING id, name"),
    bumpRev(db),
  ]);
  return c.json({ deleted: deleted!.results });
});

tagRoutes.delete("/:id{[0-9]+}", async (c) => {
  const id = parseId(c.req.param("id"));
  const db = c.env.DB;
  const tag = await db.prepare("SELECT id, name FROM tags WHERE id = ?").bind(id).first();
  if (!tag) throw notFound("Тег не найден");
  const affected = await videosWithTags(db, [id]);
  await db.batch([
    db.prepare("DELETE FROM video_tags WHERE tag_id = ?").bind(id),
    db.prepare("DELETE FROM tags WHERE id = ?").bind(id),
    ...touchVideos(db, affected),
    bumpRev(db),
  ]);
  return c.json({ deleted: tag, affected_video_ids: affected });
});
