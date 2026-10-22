import { applyD1Migrations } from "cloudflare:test";
import { env } from "cloudflare:workers";

// Миграции применяются один раз: повторный вызов ничего не делает.
await applyD1Migrations(env.DB, env.TEST_MIGRATIONS);
