import { Hono } from "hono";
import type { AppEnv } from "../types";
import { requireUploader } from "../lib/auth";
import { bumpRev } from "../lib/db";
import { ApiError, badRequest, notFound, readJsonObject } from "../lib/http";
import { idList, optNumber, optString, stringIdList } from "../lib/normalize";

/** Управление коллекциями (только для загрузчиков). Публичный список — GET /api/collections. */
export const collectionRoutes = new Hono<AppEnv>();
collectionRoutes.use("*", requireUploader);

interface CollectionRow {
  id: number;
  name: string;
  sort_order: number;
  emoji: string | null;
}

function parseId(raw: string): number {
  const id = Number(raw);
  if (!Number.isInteger(id) || id <= 0) throw notFound("Коллекция не найдена");
  return id;
}

async function getCollection(db: D1Database, id: number): Promise<CollectionRow> {
  const row = await db.prepare("SELECT id, name, sort_order, emoji FROM collections WHERE id = ?").bind(id).first<CollectionRow>();
  if (!row) throw notFound("Коллекция не найдена");
  return row;
}

function readEmoji(body: Record<string, unknown>): string | null | undefined {
  const emoji = optString(body, "emoji", 16);
  return emoji;
}

const nameTaken = (name: string) => new ApiError(409, "collection_exists", `Коллекция «${name}» уже существует`);

collectionRoutes.post("/", async (c) => {
  const body = await readJsonObject(c);
  const name = optString(body, "name", 100);
  if (!name) throw badRequest("Название коллекции обязательно");
  const emoji = readEmoji(body) ?? null;
  const db = c.env.DB;
  if (await db.prepare("SELECT 1 FROM collections WHERE name = ?").bind(name).first()) throw nameTaken(name);
  let sortOrder = optNumber(body, "sort_order", { int: true });
  if (sortOrder === undefined || sortOrder === null) {
    const row = await db.prepare("SELECT coalesce(max(sort_order), 0) + 1 AS next FROM collections").first<{ next: number }>();
    sortOrder = row?.next ?? 1;
  }
  const [inserted] = await db.batch([
    db
      .prepare("INSERT INTO collections (name, sort_order, emoji) VALUES (?, ?, ?) RETURNING id, name, sort_order, emoji")
      .bind(name, sortOrder, emoji),
    bumpRev(db),
  ]);
  return c.json({ collection: inserted!.results[0] }, 201);
});

/** PUT /api/collections/order — новый порядок: { ids: [3, 1, 2] }. */
collectionRoutes.put("/order", async (c) => {
  const ids = idList((await readJsonObject(c)).ids, "ids");
  const db = c.env.DB;
  await db.batch([
    ...ids.map((id, index) => db.prepare("UPDATE collections SET sort_order = ? WHERE id = ?").bind(index + 1, id)),
    bumpRev(db),
  ]);
  const { results } = await db.prepare("SELECT id, name, sort_order, emoji FROM collections ORDER BY sort_order, name").all();
  return c.json({ collections: results });
});

collectionRoutes.patch("/:id{[0-9]+}", async (c) => {
  const id = parseId(c.req.param("id"));
  const body = await readJsonObject(c);
  const db = c.env.DB;
  const current = await getCollection(db, id);
  const name = optString(body, "name", 100);
  if (body.name !== undefined && !name) throw badRequest("Название коллекции не может быть пустым");
  const emoji = readEmoji(body);
  const sortOrder = optNumber(body, "sort_order", { int: true });
  if (name && name !== current.name) {
    if (await db.prepare("SELECT 1 FROM collections WHERE name = ?").bind(name).first()) throw nameTaken(name);
  }
  const next: CollectionRow = {
    id,
    name: name ?? current.name,
    emoji: emoji === undefined ? current.emoji : emoji,
    sort_order: sortOrder ?? current.sort_order,
  };
  await db.batch([
    db.prepare("UPDATE collections SET name = ?, emoji = ?, sort_order = ? WHERE id = ?").bind(next.name, next.emoji, next.sort_order, id),
    bumpRev(db),
  ]);
  return c.json({ collection: next });
});

collectionRoutes.delete("/:id{[0-9]+}", async (c) => {
  const id = parseId(c.req.param("id"));
  const db = c.env.DB;
  const current = await getCollection(db, id);
  await db.batch([
    db.prepare("DELETE FROM video_collections WHERE collection_id = ?").bind(id),
    db.prepare("DELETE FROM collections WHERE id = ?").bind(id),
    bumpRev(db),
  ]);
  return c.json({ deleted: current });
});

/** POST /api/collections/:id/videos — массово добавить/убрать видео: { add: [...], remove: [...] }. */
collectionRoutes.post("/:id{[0-9]+}/videos", async (c) => {
  const id = parseId(c.req.param("id"));
  const body = await readJsonObject(c);
  const add = stringIdList(body.add, "add");
  const remove = stringIdList(body.remove, "remove");
  if (add.length === 0 && remove.length === 0) throw badRequest("Укажите видео в «add» или «remove»");
  const db = c.env.DB;
  await getCollection(db, id);
  const statements: D1PreparedStatement[] = [];
  if (add.length) {
    statements.push(
      db
        .prepare(
          "INSERT OR IGNORE INTO video_collections (video_id, collection_id) SELECT id, ? FROM videos WHERE id IN (SELECT value FROM json_each(?))",
        )
        .bind(id, JSON.stringify(add)),
    );
  }
  if (remove.length) {
    statements.push(
      db
        .prepare("DELETE FROM video_collections WHERE collection_id = ? AND video_id IN (SELECT value FROM json_each(?))")
        .bind(id, JSON.stringify(remove)),
    );
  }
  statements.push(bumpRev(db));
  await db.batch(statements);
  const row = await db.prepare("SELECT count(*) AS count FROM video_collections WHERE collection_id = ?").bind(id).first<{ count: number }>();
  return c.json({ collection_id: id, count: row?.count ?? 0 });
});
