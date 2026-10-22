import { env, exports } from "cloudflare:workers";

const BASE = "https://archive.test";

let counter = 0;

/** Создаёт загрузчика прямо в базе и возвращает его токен. */
export async function createUploader(name = "Тестер", revoked = false): Promise<string> {
  const token = `va_test_${Date.now()}_${++counter}_${Math.random().toString(36).slice(2)}`;
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token));
  const hash = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  await env.DB.prepare("INSERT INTO uploaders (name, token_hash, created_at, revoked) VALUES (?, ?, ?, ?)")
    .bind(name, hash, Date.now(), revoked ? 1 : 0)
    .run();
  return token;
}

export async function api(path: string, init: RequestInit & { token?: string; json?: unknown } = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.token) headers.set("Authorization", `Bearer ${init.token}`);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  return exports.default.fetch(new Request(`${BASE}${path}`, { ...init, headers, body }));
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function json<T = any>(res: Response): Promise<T> {
  return (await res.json()) as T;
}

let msgId = 1000;
export const nextMessageId = () => ++msgId;

export function videoPayload(overrides: Record<string, unknown> = {}) {
  return {
    tg_channel: "@my_archive",
    tg_message_id: nextMessageId(),
    title: "Тестовое видео",
    width: 1920,
    height: 1080,
    duration: 12.5,
    fps: 25,
    codec: "h264",
    file_name: "test.mp4",
    file_size: 123456,
    ...overrides,
  };
}

/** Минимальные «файлы» с правильными сигнатурами. */
export const fakeJpeg = (size = 2000) => {
  const b = new Uint8Array(size);
  b.set([0xff, 0xd8, 0xff, 0xe0]);
  for (let i = 4; i < size; i++) b[i] = i % 251;
  return b;
};

export const fakeMp4 = (size = 5000) => {
  const b = new Uint8Array(size);
  b.set([0, 0, 0, 0x20, 0x66, 0x74, 0x79, 0x70, 0x69, 0x73, 0x6f, 0x6d]); // ....ftypisom
  for (let i = 12; i < size; i++) b[i] = i % 253;
  return b;
};
