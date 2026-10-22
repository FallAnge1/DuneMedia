import type { Context } from "hono";
import type { ContentfulStatusCode } from "hono/utils/http-status";

/** Ошибка API с понятным сообщением на русском и машинным кодом. */
export class ApiError extends Error {
  constructor(
    public status: ContentfulStatusCode,
    public code: string,
    message: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
  }
}

export const badRequest = (message: string, details?: Record<string, unknown>) =>
  new ApiError(400, "bad_request", message, details);

export const notFound = (message = "Не найдено") => new ApiError(404, "not_found", message);

export function errorResponse(c: Context, err: unknown): Response {
  if (err instanceof ApiError) {
    return c.json({ error: { code: err.code, message: err.message, ...err.details } }, err.status);
  }
  console.error("Необработанная ошибка", err);
  return c.json({ error: { code: "internal", message: "Внутренняя ошибка сервера" } }, 500);
}

/** Читает JSON-тело запроса и проверяет, что это объект. */
export async function readJsonObject(c: Context): Promise<Record<string, unknown>> {
  let body: unknown;
  try {
    body = await c.req.json();
  } catch {
    throw badRequest("Тело запроса должно быть корректным JSON");
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw badRequest("Тело запроса должно быть JSON-объектом");
  }
  return body as Record<string, unknown>;
}

export async function sha256Hex(data: string | ArrayBuffer | Uint8Array): Promise<string> {
  const bytes = typeof data === "string" ? new TextEncoder().encode(data) : data;
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
