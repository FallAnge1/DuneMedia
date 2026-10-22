/** Типы данных и запросы к API. */

export type Orientation = "horizontal" | "vertical" | "square";
export type ResolutionLabel = "SD" | "HD" | "FullHD" | "2K" | "4K" | "8K";

export interface Video {
  id: string;
  tg_channel: string;
  tg_message_id: number;
  title: string;
  description: string | null;
  file_name: string | null;
  file_size: number | null;
  duration: number | null;
  width: number | null;
  height: number | null;
  orientation: Orientation | null;
  resolution_label: ResolutionLabel | null;
  fps: number | null;
  codec: string | null;
  preview_key: string | null;
  poster_key: string | null;
  uploaded_by: string | null;
  caption_dirty: number;
  created_at: number;
  updated_at: number;
  tags: string[];
  collections: number[];
}

export interface Tag {
  id: number;
  name: string;
  count: number;
}

export interface Collection {
  id: number;
  name: string;
  emoji: string | null;
  sort_order: number;
  count: number;
}

export interface Library {
  rev: number;
  generated_at: number;
  videos: Video[];
  tags: Tag[];
  collections: Collection[];
}

export class ApiRequestError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

export const mediaUrl = (key: string | null | undefined) => (key ? `/media/${key}` : undefined);

export async function fetchLibrary(): Promise<Library> {
  const res = await fetch("/api/library");
  if (!res.ok) throw new ApiRequestError(res.status, "library", "Не удалось загрузить архив");
  return (await res.json()) as Library;
}

/** Запрос с токеном редактора. Ошибки API превращаются в ApiRequestError с русским сообщением. */
export async function apiCall<T>(token: string, method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiRequestError(0, "network", "Нет связи с сервером. Проверьте интернет.");
  }
  const data = (await res.json().catch(() => null)) as { error?: { code: string; message: string } } | null;
  if (!res.ok) {
    const err = data?.error;
    throw new ApiRequestError(res.status, err?.code ?? "http", err?.message ?? `Ошибка сервера (${res.status})`, err ?? {});
  }
  return data as T;
}

export const api = {
  me: (token: string) => apiCall<{ uploader: { id: number; name: string } }>(token, "GET", "/api/me"),
  patchVideo: (token: string, id: string, body: Partial<Pick<Video, "title" | "description" | "tags" | "collections">>) =>
    apiCall<{ video: Video }>(token, "PATCH", `/api/videos/${id}`, body),
  deleteVideo: (token: string, id: string) => apiCall<{ deleted: Video }>(token, "DELETE", `/api/videos/${id}`),

  createCollection: (token: string, name: string, emoji: string | null) =>
    apiCall<{ collection: Collection }>(token, "POST", "/api/collections", { name, emoji }),
  patchCollection: (token: string, id: number, body: { name?: string; emoji?: string | null }) =>
    apiCall<{ collection: Collection }>(token, "PATCH", `/api/collections/${id}`, body),
  orderCollections: (token: string, ids: number[]) => apiCall(token, "PUT", "/api/collections/order", { ids }),
  deleteCollection: (token: string, id: number) => apiCall(token, "DELETE", `/api/collections/${id}`),
  collectionVideos: (token: string, id: number, body: { add?: string[]; remove?: string[] }) =>
    apiCall<{ count: number }>(token, "POST", `/api/collections/${id}/videos`, body),

  renameTag: (token: string, id: number, name: string) =>
    apiCall<{ affected_video_ids: string[] }>(token, "PATCH", `/api/tags/${id}`, { name }),
  mergeTags: (token: string, sourceIds: number[], targetId: number) =>
    apiCall<{ affected_video_ids: string[] }>(token, "POST", "/api/tags/merge", { source_ids: sourceIds, target_id: targetId }),
  deleteTag: (token: string, id: number) => apiCall<{ affected_video_ids: string[] }>(token, "DELETE", `/api/tags/${id}`),
  deleteUnusedTags: (token: string) => apiCall<{ deleted: { id: number; name: string }[] }>(token, "DELETE", "/api/tags/unused"),
};

/** Нормализация тега — та же, что на сервере (worker/lib/normalize.ts). */
export function normalizeTag(raw: string): string | null {
  const name = raw
    .normalize("NFC")
    .replace(/^#+/, "")
    .replace(/_/g, " ")
    .replace(/[\s ]+/g, " ")
    .trim()
    .toLowerCase();
  return name ? name.slice(0, 64).trim() : null;
}
