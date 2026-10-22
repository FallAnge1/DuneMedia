/** Работа с D1: выборки видео, синхронизация FTS, ревизия архива. */

export interface VideoRow {
  id: string;
  tg_channel: string;
  tg_message_id: number;
  title: string;
  description: string | null;
  file_name: string | null;
  file_size: number | null;
  file_hash: string | null;
  duration: number | null;
  width: number | null;
  height: number | null;
  orientation: string | null;
  resolution_label: string | null;
  fps: number | null;
  codec: string | null;
  preview_key: string | null;
  poster_key: string | null;
  uploaded_by: string | null;
  /** 1 — подпись поста в Telegram устарела (правки сделаны на сайте). */
  caption_dirty: number;
  created_at: number;
  updated_at: number;
}

export interface Video extends VideoRow {
  tags: string[];
  collections: number[];
}

export const VIDEO_COLUMNS = `id, tg_channel, tg_message_id, title, description, file_name, file_size, file_hash,
  duration, width, height, orientation, resolution_label, fps, codec, preview_key, poster_key,
  uploaded_by, caption_dirty, created_at, updated_at`;

/** Увеличивает ревизию архива (ETag для /api/library). Добавляйте в каждый batch с изменениями. */
export const bumpRev = (db: D1Database) =>
  db.prepare("UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'library_rev'");

export async function getRev(db: D1Database): Promise<number> {
  const row = await db.prepare("SELECT value FROM meta WHERE key = 'library_rev'").first<{ value: string }>();
  return Number(row?.value ?? 0);
}

/**
 * Пересобирает строки FTS для указанных видео. Возвращает два запроса для batch.
 * Список id передаётся одним JSON-параметром (json_each), чтобы не упираться в лимит параметров.
 */
export function ftsSync(db: D1Database, ids: string[]): D1PreparedStatement[] {
  const json = JSON.stringify(ids);
  return [
    db.prepare("DELETE FROM videos_fts WHERE video_id IN (SELECT value FROM json_each(?))").bind(json),
    db
      .prepare(
        `INSERT INTO videos_fts (video_id, title, description, tags)
         SELECT v.id, v.title, coalesce(v.description, ''),
                coalesce((SELECT group_concat(t.name, ' ') FROM video_tags vt JOIN tags t ON t.id = vt.tag_id
                          WHERE vt.video_id = v.id), '')
         FROM videos v WHERE v.id IN (SELECT value FROM json_each(?))`,
      )
      .bind(json),
  ];
}

/** Запросы, которые создают недостающие теги и привязывают их к видео (заменяя старые). */
export function setVideoTags(db: D1Database, videoId: string, tags: string[]): D1PreparedStatement[] {
  const json = JSON.stringify(tags);
  return [
    db.prepare("INSERT INTO tags (name) SELECT value FROM json_each(?) WHERE true ON CONFLICT (name) DO NOTHING").bind(json),
    db.prepare("DELETE FROM video_tags WHERE video_id = ?").bind(videoId),
    db
      .prepare("INSERT OR IGNORE INTO video_tags (video_id, tag_id) SELECT ?, id FROM tags WHERE name IN (SELECT value FROM json_each(?))")
      .bind(videoId, json),
  ];
}

export function setVideoCollections(db: D1Database, videoId: string, ids: number[]): D1PreparedStatement[] {
  return [
    db.prepare("DELETE FROM video_collections WHERE video_id = ?").bind(videoId),
    db
      .prepare(
        "INSERT OR IGNORE INTO video_collections (video_id, collection_id) SELECT ?, id FROM collections WHERE id IN (SELECT value FROM json_each(?))",
      )
      .bind(videoId, JSON.stringify(ids)),
  ];
}

/** Проверяет, что все коллекции существуют. Возвращает отсутствующие id. */
export async function missingCollections(db: D1Database, ids: number[]): Promise<number[]> {
  if (ids.length === 0) return [];
  const { results } = await db
    .prepare("SELECT id FROM collections WHERE id IN (SELECT value FROM json_each(?))")
    .bind(JSON.stringify(ids))
    .all<{ id: number }>();
  const found = new Set(results.map((r) => r.id));
  return ids.filter((id) => !found.has(id));
}

/** Загружает видео вместе с тегами и коллекциями. */
export async function loadVideos(db: D1Database, ids: string[]): Promise<Video[]> {
  if (ids.length === 0) return [];
  const json = JSON.stringify(ids);
  const [videos, tags, cols] = await db.batch([
    db.prepare(`SELECT ${VIDEO_COLUMNS} FROM videos WHERE id IN (SELECT value FROM json_each(?))`).bind(json),
    db
      .prepare(
        `SELECT vt.video_id, t.name FROM video_tags vt JOIN tags t ON t.id = vt.tag_id
         WHERE vt.video_id IN (SELECT value FROM json_each(?)) ORDER BY t.name`,
      )
      .bind(json),
    db
      .prepare("SELECT video_id, collection_id FROM video_collections WHERE video_id IN (SELECT value FROM json_each(?))")
      .bind(json),
  ]);
  return attachRelations(
    videos!.results as unknown as VideoRow[],
    tags!.results as unknown as { video_id: string; name: string }[],
    cols!.results as unknown as { video_id: string; collection_id: number }[],
  );
}

export async function loadVideo(db: D1Database, id: string): Promise<Video | null> {
  const [video] = await loadVideos(db, [id]);
  return video ?? null;
}

export function attachRelations(
  rows: VideoRow[],
  tagRows: { video_id: string; name: string }[],
  colRows: { video_id: string; collection_id: number }[],
): Video[] {
  const tagMap = new Map<string, string[]>();
  for (const r of tagRows) {
    const list = tagMap.get(r.video_id);
    if (list) list.push(r.name);
    else tagMap.set(r.video_id, [r.name]);
  }
  const colMap = new Map<string, number[]>();
  for (const r of colRows) {
    const list = colMap.get(r.video_id);
    if (list) list.push(r.collection_id);
    else colMap.set(r.video_id, [r.collection_id]);
  }
  return rows.map((v) => ({ ...v, tags: tagMap.get(v.id) ?? [], collections: colMap.get(v.id) ?? [] }));
}

/** Удаляет из R2 файлы, на которые больше не ссылается ни одно видео. */
export async function deleteUnreferencedMedia(env: Env, keys: (string | null | undefined)[]): Promise<void> {
  const candidates = [...new Set(keys.filter((k): k is string => !!k))];
  if (candidates.length === 0) return;
  const json = JSON.stringify(candidates);
  const { results } = await env.DB.prepare(
    `SELECT preview_key AS k FROM videos WHERE preview_key IN (SELECT value FROM json_each(?1))
     UNION SELECT poster_key FROM videos WHERE poster_key IN (SELECT value FROM json_each(?1))`,
  )
    .bind(json)
    .all<{ k: string }>();
  const stillUsed = new Set(results.map((r) => r.k));
  const toDelete = candidates.filter((k) => !stillUsed.has(k));
  if (toDelete.length) await env.PREVIEWS.delete(toDelete);
}
