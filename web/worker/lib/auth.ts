import { createMiddleware } from "hono/factory";
import { ApiError, sha256Hex } from "./http";
import type { AppEnv } from "../types";

/**
 * Проверяет персональный токен загрузчика (Authorization: Bearer <токен>).
 * В базе хранится только sha256 от токена.
 */
export const requireUploader = createMiddleware<AppEnv>(async (c, next) => {
  const header = c.req.header("Authorization") ?? "";
  const match = /^Bearer\s+(\S+)$/i.exec(header);
  if (!match) {
    throw new ApiError(401, "unauthorized", "Нужен токен загрузчика (заголовок Authorization: Bearer …)");
  }
  const hash = await sha256Hex(match[1]!);
  const row = await c.env.DB.prepare("SELECT id, name, revoked FROM uploaders WHERE token_hash = ?")
    .bind(hash)
    .first<{ id: number; name: string; revoked: number }>();
  if (!row) throw new ApiError(401, "unauthorized", "Неизвестный токен загрузчика");
  if (row.revoked) throw new ApiError(403, "token_revoked", "Токен загрузчика отозван");
  c.set("uploader", { id: row.id, name: row.name });
  await next();
});
