// Wrangler требует существующую папку статики. До сборки фронтенда кладём заглушку.
import { existsSync, mkdirSync, writeFileSync } from "node:fs";

if (!existsSync("dist/index.html")) {
  mkdirSync("dist", { recursive: true });
  writeFileSync("dist/index.html", '<!doctype html><meta charset="utf-8"><title>Видеоархив</title><p>Фронтенд ещё не собран.</p>\n');
}
