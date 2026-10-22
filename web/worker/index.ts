import { Hono } from "hono";
import type { AppEnv } from "./types";
import { requireUploader } from "./lib/auth";
import { ApiError, errorResponse } from "./lib/http";
import { publicRoutes } from "./routes/public";
import { videoRoutes } from "./routes/videos";
import { tagRoutes } from "./routes/tags";
import { collectionRoutes } from "./routes/collections";
import { mediaPublicRoutes, mediaUploadRoutes } from "./routes/media";
import { aiRoutes } from "./routes/ai";

const app = new Hono<AppEnv>();

app.onError((err, c) => errorResponse(c, err));

// Публичное чтение
app.route("/api", publicRoutes);
app.route("/media", mediaPublicRoutes);

// Запись — только с токеном загрузчика
app.get("/api/me", requireUploader, (c) => c.json({ uploader: c.var.uploader }));
app.route("/api/videos", videoRoutes);
app.route("/api/tags", tagRoutes);
app.route("/api/collections", collectionRoutes);
app.route("/api/media", mediaUploadRoutes);
app.route("/api/ai", aiRoutes);

app.notFound((c) => {
  if (c.req.path.startsWith("/api/") || c.req.path.startsWith("/media/")) {
    return errorResponse(c, new ApiError(404, "not_found", "Неизвестный адрес API"));
  }
  // Всё остальное — статика сайта (SPA).
  return c.env.ASSETS.fetch(c.req.raw);
});

export default app satisfies ExportedHandler<Env>;
