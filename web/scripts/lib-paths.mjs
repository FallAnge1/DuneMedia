// Пути проекта без зависимостей (можно импортировать до npm install).
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
export const ROOT = join(WEB, "..");
