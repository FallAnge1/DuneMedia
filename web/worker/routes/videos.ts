import { Hono } from "hono";
import type { AppEnv } from "../types";
import { requireUploader } from "../lib/auth";
import {
  bumpRev,
  deleteUnreferencedMedia,
  ftsSync,
  loadVideo,
  loadVideos,
  missingCollections,
  setVideoCollections,
  setVideoTags,
  VIDEO_COLUMNS,
  type VideoRow,
} from "../lib/db";
import { ApiError, badRequest, notFound, readJsonObject } from "../lib/http";
import {
  HASH_RE,
  idList,
  normalizeChannel,
  normalizeTags,
  optMediaKey,
  optNumber,
  optString,
  orientationOf,
  reqString,
  resolutionLabelOf,
  UUID_RE,
} from "../lib/normalize";

export const videoRoutes = new Hono<AppEnv>();
videoRoutes.use("*", requireUploader);

/** Поля метаданных, общие для создания и изменения. */
function readMetadata(body: Record<string, unknown>) {
  const fileHash = optString(body, "file_hash", 64);
  if (fileHash && !HASH_RE.test(fileHash)) throw badRequest("Поле «file_hash» должно быть sha256 в hex (64 символа)");
  return {
    title: optString(body, "title", 300),
    description: optString(body, "description", 4000),
    file_name: optString(body, "file_name", 500),
    file_size: optNumber(body, "file_size", { int: true, min: 0 }),
    file_hash: fileHash,
    duration: optNumber(body, "duration", { min: 0 }),
    width: optNumber(body, "width", { int: true, min: 1, max: 100_000 }),
    height: optNumber(body, "height", { int: true, min: 1, max: 100_000 }),
    fps: optNumber(body, "fps", { min: 0, max: 10_000 }),
    codec: optString(body, "codec", 50),
    preview_key: optMediaKey(body, "preview_key"),
    poster_key: optMediaKey(body, "poster_key"),
  };
}

/** Ориентация и метка разрешения всегда вычисляются сервером из ширины и высоты. */
function derived(width: number | null | undefined, height: number | null | undefined) {
  if (!width || !height) return { orientation: null, resolution_label: null };
  return { orientation: orientationOf(width, height), resolution_label: resolutionLabelOf(width, height) };
}

/** GET /api/videos/check-hash/:hash — поиск дубликатов по хешу файла. */
videoRoutes.get("/check-hash/:hash", async (c) => {
  const hash = c.req.param("hash").toLowerCase();
  if (!HASH_RE.test(hash)) throw badRequest("Хеш должен быть sha256 в hex (64 символа)");
  const { results } = await c.env.DB.prepare("SELECT id FROM videos WHERE file_hash = ? ORDER BY created_at")
    .bind(hash)
    .all<{ id: string }>();
  const videos = await loadVideos(
    c.env.DB,
    results.map((r) => r.id),
  );
  return c.json({ duplicate: videos.length > 0, videos });
});

/** POST /api/videos — создать запись после загрузки видео в Telegram. */
videoRoutes.post("/", async (c) => {
  const body = await readJsonObject(c);
  const db = c.env.DB;

  const id = body.id === undefined ? crypto.randomUUID() : String(body.id).toLowerCase();
  if (!UUID_RE.test(id)) throw badRequest("Поле «id» должно быть UUID");
  const tg_channel = normalizeChannel(body.tg_channel);
  const tg_message_id = optNumber(body, "tg_message_id", { int: true, min: 1 });
  if (!tg_message_id) throw badRequest("Поле «tg_message_id» обязательно");
  const title = reqString(body, "title", 300);
  const meta = readMetadata(body);
  const tags = normalizeTags(body.tags);
  const collections = idList(body.collections, "collections");
  const createdAt = optNumber(body, "created_at", { int: true, min: 0 }) ?? Date.now();
  const now = Date.now();

  // Повторный запрос с тем же id (например, загрузчик повторяет шаг после обрыва сети) — не ошибка.
  const existingById = await db.prepare("SELECT tg_channel, tg_message_id FROM videos WHERE id = ?")
    .bind(id)
    .first<{ tg_channel: string; tg_message_id: number }>();
  if (existingById) {
    if (existingById.tg_channel === tg_channel && existingById.tg_message_id === tg_message_id) {
      return c.json({ video: await loadVideo(db, id), existing: true }, 200);
    }
    throw new ApiError(409, "id_exists", "Видео с таким id уже существует");
  }
  const existingByPost = await db.prepare("SELECT id FROM videos WHERE tg_channel = ? AND tg_message_id = ?")
    .bind(tg_channel, tg_message_id)
    .first<{ id: string }>();
  if (existingByPost) {
    throw new ApiError(409, "tg_post_exists", "Этот пост Telegram уже есть в архиве", { existing_id: existingByPost.id });
  }
  const missing = await missingCollections(db, collections);
  if (missing.length) throw badRequest(`Коллекции не найдены: ${missing.join(", ")}`);

  const { orientation, resolution_label } = derived(meta.width, meta.height);
  await db.batch([
    db
      .prepare(
        `INSERT INTO videos (${VIDEO_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .bind(
        id,
        tg_channel,
        tg_message_id,
        title,
        meta.description ?? null,
        meta.file_name ?? null,
        meta.file_size ?? null,
        meta.file_hash ?? null,
        meta.duration ?? null,
        meta.width ?? null,
        meta.height ?? null,
        orientation,
        resolution_label,
        meta.fps ?? null,
        meta.codec ?? null,
        meta.preview_key ?? null,
        meta.poster_key ?? null,
        c.var.uploader.name,
        0,
        createdAt,
        now,
      ),
    ...setVideoTags(db, id, tags),
    ...setVideoCollections(db, id, collections),
    ...ftsSync(db, [id]),
    bumpRev(db),
  ]);
  return c.json({ video: await loadVideo(db, id) }, 201);
});

/**
 * PATCH /api/videos/:id — изменить метаданные; tags и collections заменяются целиком.
 * caption_synced: true — загрузчик уже обновил подпись поста в Telegram.
 */
videoRoutes.patch("/:id", async (c) => {
  const id = c.req.param("id").toLowerCase();
  const db = c.env.DB;
  const current = await db.prepare(`SELECT ${VIDEO_COLUMNS} FROM videos WHERE id = ?`).bind(id).first<VideoRow>();
  if (!current) throw notFound("Видео не найдено");

  const body = await readJsonObject(c);
  const meta = readMetadata(body);
  if (body.title !== undefined && !meta.title) throw badRequest("Название не может быть пустым");

  const updates: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(meta)) {
    if (value !== undefined) updates[key] = value;
  }
  if (body.tg_channel !== undefined) updates.tg_channel = normalizeChannel(body.tg_channel);
  const msgId = optNumber(body, "tg_message_id", { int: true, min: 1 });
  if (msgId) updates.tg_message_id = msgId;
  if ("width" in updates || "height" in updates) {
    const width = (updates.width ?? current.width) as number | null;
    const height = (updates.height ?? current.height) as number | null;
    Object.assign(updates, derived(width, height));
  }
  // Подпись поста в Telegram: загрузчик сам обновляет пост и передаёт caption_synced: true.
  // Правки названия, описания или тегов без этого флага (например, с сайта) помечают подпись устаревшей.
  if (body.caption_synced === true) updates.caption_dirty = 0;
  else if (body.title !== undefined || body.description !== undefined || body.tags !== undefined) updates.caption_dirty = 1;
  updates.updated_at = Date.now();

  const statements: D1PreparedStatement[] = [];
  const columns = Object.keys(updates);
  statements.push(
    db
      .prepare(`UPDATE videos SET ${columns.map((col) => `${col} = ?`).join(", ")} WHERE id = ?`)
      .bind(...columns.map((col) => updates[col]), id),
  );
  if (body.tags !== undefined) statements.push(...setVideoTags(db, id, normalizeTags(body.tags)));
  if (body.collections !== undefined) {
    const collections = idList(body.collections, "collections");
    const missing = await missingCollections(db, collections);
    if (missing.length) throw badRequest(`Коллекции не найдены: ${missing.join(", ")}`);
    statements.push(...setVideoCollections(db, id, collections));
  }
  statements.push(...ftsSync(db, [id]), bumpRev(db));

  try {
    await db.batch(statements);
  } catch (err) {
    if (String(err).includes("UNIQUE")) {
      throw new ApiError(409, "tg_post_exists", "Этот пост Telegram уже привязан к другому видео");
    }
    throw err;
  }

  // Старые превью и постеры, на которые больше никто не ссылается, удаляются из R2.
  const replaced = [
    "preview_key" in updates && updates.preview_key !== current.preview_key ? current.preview_key : null,
    "poster_key" in updates && updates.poster_key !== current.poster_key ? current.poster_key : null,
  ];
  c.executionCtx.waitUntil(deleteUnreferencedMedia(c.env, replaced));
  return c.json({ video: await loadVideo(db, id) });
});

/** DELETE /api/videos/:id — удалить запись и её файлы в R2. Пост в Telegram удаляет загрузчик. */
videoRoutes.delete("/:id", async (c) => {
  const id = c.req.param("id").toLowerCase();
  const db = c.env.DB;
  const video = await loadVideo(db, id);
  if (!video) throw notFound("Видео не найдено");
  await db.batch([
    db.prepare("DELETE FROM video_tags WHERE video_id = ?").bind(id),
    db.prepare("DELETE FROM video_collections WHERE video_id = ?").bind(id),
    db.prepare("DELETE FROM videos_fts WHERE video_id = ?").bind(id),
    db.prepare("DELETE FROM videos WHERE id = ?").bind(id),
    bumpRev(db),
  ]);
  await deleteUnreferencedMedia(c.env, [video.preview_key, video.poster_key]);
  return c.json({ deleted: video });
});
