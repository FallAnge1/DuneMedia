import { badRequest } from "./http";

export type Orientation = "horizontal" | "vertical" | "square";
export type ResolutionLabel = "SD" | "HD" | "FullHD" | "2K" | "4K" | "8K";

export const MAX_TAG_LENGTH = 64;
export const MAX_TAGS_PER_VIDEO = 60;

/**
 * Нормализует тег: нижний регистр, без #, без лишних пробелов.
 * Возвращает null, если после очистки ничего не осталось.
 */
export function normalizeTag(raw: string): string | null {
  const name = raw
    .normalize("NFC")
    .replace(/^#+/, "")
    .replace(/_/g, " ")
    .replace(/[\s ]+/g, " ")
    .trim()
    .toLowerCase();
  if (!name) return null;
  return name.slice(0, MAX_TAG_LENGTH).trim();
}

export function normalizeTags(value: unknown, field = "tags"): string[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) throw badRequest(`Поле «${field}» должно быть массивом строк`);
  const out = new Set<string>();
  for (const item of value) {
    if (typeof item !== "string") throw badRequest(`Поле «${field}» должно быть массивом строк`);
    const tag = normalizeTag(item);
    if (tag) out.add(tag);
  }
  if (out.size > MAX_TAGS_PER_VIDEO) {
    throw badRequest(`Слишком много тегов: максимум ${MAX_TAGS_PER_VIDEO}`);
  }
  return [...out];
}

/** Username канала: без @ и ссылки t.me, в нижнем регистре. */
export function normalizeChannel(raw: unknown): string {
  if (typeof raw !== "string") throw badRequest("Не указан канал (tg_channel)");
  const name = raw
    .trim()
    .replace(/^https?:\/\//i, "")
    .replace(/^(t|telegram)\.me\//i, "")
    .replace(/^@/, "")
    .replace(/\/.*$/, "")
    .toLowerCase();
  if (!/^[a-z][a-z0-9_]{3,31}$/.test(name)) {
    throw badRequest("Некорректный username канала: нужны 5–32 символа, латиница, цифры и _");
  }
  return name;
}

export function orientationOf(width: number, height: number): Orientation {
  const ratio = width / height;
  if (ratio > 1.05) return "horizontal";
  if (ratio < 1 / 1.05) return "vertical";
  return "square";
}

const LABELS: ResolutionLabel[] = ["SD", "HD", "FullHD", "2K", "4K", "8K"];

/**
 * Метка разрешения. Считается и по короткой, и по длинной стороне, берётся большая:
 * так 1920×800 (кино) — FullHD, а 1440×1080 (4:3) — тоже FullHD.
 * Та же логика повторена в загрузчике (uploader/videoarchive/media.py).
 */
export function resolutionLabelOf(width: number, height: number): ResolutionLabel {
  const short = Math.min(width, height);
  const long = Math.max(width, height);
  const byShort = short >= 4320 ? 5 : short >= 2160 ? 4 : short >= 1440 ? 3 : short >= 1080 ? 2 : short >= 720 ? 1 : 0;
  const byLong = long >= 7680 ? 5 : long >= 3840 ? 4 : long >= 2560 ? 3 : long >= 1920 ? 2 : long >= 1280 ? 1 : 0;
  return LABELS[Math.max(byShort, byLong)]!;
}

// ---- Проверка полей ----

export function optString(body: Record<string, unknown>, key: string, max: number): string | null | undefined {
  const v = body[key];
  if (v === undefined) return undefined;
  if (v === null) return null;
  if (typeof v !== "string") throw badRequest(`Поле «${key}» должно быть строкой`);
  const s = v.trim();
  if (s.length > max) throw badRequest(`Поле «${key}» длиннее ${max} символов`);
  return s === "" ? null : s;
}

export function reqString(body: Record<string, unknown>, key: string, max: number): string {
  const s = optString(body, key, max);
  if (!s) throw badRequest(`Поле «${key}» обязательно`);
  return s;
}

export function optNumber(
  body: Record<string, unknown>,
  key: string,
  opts: { int?: boolean; min?: number; max?: number } = {},
): number | null | undefined {
  const v = body[key];
  if (v === undefined) return undefined;
  if (v === null) return null;
  if (typeof v !== "number" || !Number.isFinite(v)) throw badRequest(`Поле «${key}» должно быть числом`);
  if (opts.int && !Number.isInteger(v)) throw badRequest(`Поле «${key}» должно быть целым числом`);
  if (opts.min !== undefined && v < opts.min) throw badRequest(`Поле «${key}» должно быть не меньше ${opts.min}`);
  if (opts.max !== undefined && v > opts.max) throw badRequest(`Поле «${key}» должно быть не больше ${opts.max}`);
  return v;
}

export function idList(value: unknown, field: string): number[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value) || !value.every((x) => Number.isInteger(x) && x > 0)) {
    throw badRequest(`Поле «${field}» должно быть массивом целых положительных чисел`);
  }
  return [...new Set(value as number[])];
}

export function stringIdList(value: unknown, field: string): string[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value) || !value.every((x) => typeof x === "string" && UUID_RE.test(x))) {
    throw badRequest(`Поле «${field}» должно быть массивом id видео`);
  }
  return [...new Set(value as string[])];
}

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const HASH_RE = /^[0-9a-f]{64}$/;

/**
 * Ключи файлов в R2: previews/<имя>.mp4, posters/<имя>.jpg|webp.
 * Загрузчик добавляет к имени случайный суффикс, поэтому файлы можно кэшировать навсегда.
 */
export const MEDIA_KEY_RE = /^(previews\/[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.mp4|posters\/[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.(?:jpg|webp))$/;

export function optMediaKey(body: Record<string, unknown>, key: string): string | null | undefined {
  const v = body[key];
  if (v === undefined) return undefined;
  if (v === null) return null;
  if (typeof v !== "string" || !MEDIA_KEY_RE.test(v)) {
    throw badRequest(`Поле «${key}»: некорректный ключ файла`);
  }
  return v;
}

export function contentTypeForKey(key: string): string {
  if (key.endsWith(".mp4")) return "video/mp4";
  if (key.endsWith(".webp")) return "image/webp";
  return "image/jpeg";
}
