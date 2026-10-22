#!/usr/bin/env node
// Управление токенами загрузчиков.
//
//   npm run uploader:create -- "Имя"            создать токен (выводится один раз)
//   npm run uploader:revoke -- "Имя"            отозвать все активные токены с этим именем
//   npm run uploader:revoke -- --id 3           отозвать токен по id
//   npm run uploader:list                       список загрузчиков
//
// По умолчанию работает с боевой базой (--remote). Для локальной разработки добавьте --local:
//   npm run uploader:create -- "Тест" --local

import { execFileSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { wranglerArgs } from "./wrangler-path.mjs";

const args = process.argv.slice(2);
const command = args.shift();
const local = args.includes("--local");
const rest = args.filter((a) => a !== "--local" && a !== "--remote");

const sql = (s) => `'${String(s).replace(/'/g, "''")}'`;

function d1(command) {
  const [node, args] = wranglerArgs(["d1", "execute", "DB", local ? "--local" : "--remote", "--json", "--command", command]);
  const out = execFileSync(node, args, { encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] });
  const parsed = JSON.parse(out);
  return parsed[0]?.results ?? [];
}

function fail(message) {
  console.error(`Ошибка: ${message}`);
  process.exit(1);
}

const where = local ? "локальной базе" : "боевой базе (Cloudflare)";

try {
  if (command === "create") {
    const name = rest.join(" ").trim();
    if (!name) fail('укажите имя: npm run uploader:create -- "Имя"');
    const token = `va_${randomBytes(32).toString("base64url")}`;
    const hash = createHash("sha256").update(token).digest("hex");
    const rows = d1(
      `INSERT INTO uploaders (name, token_hash, created_at, revoked) VALUES (${sql(name)}, ${sql(hash)}, ${Date.now()}, 0) RETURNING id`,
    );
    console.log(`\nЗагрузчик «${name}» создан в ${where} (id ${rows[0]?.id}).`);
    console.log("\nТокен (показывается ОДИН раз, сохраните его и передайте загрузчику):\n");
    console.log(`  ${token}\n`);
  } else if (command === "revoke") {
    let rows;
    const idIndex = rest.indexOf("--id");
    if (idIndex !== -1) {
      const id = Number(rest[idIndex + 1]);
      if (!Number.isInteger(id) || id <= 0) fail("после --id укажите число");
      rows = d1(`UPDATE uploaders SET revoked = 1 WHERE id = ${id} AND revoked = 0 RETURNING id, name`);
    } else {
      const name = rest.join(" ").trim();
      if (!name) fail('укажите имя или --id: npm run uploader:revoke -- "Имя"');
      rows = d1(`UPDATE uploaders SET revoked = 1 WHERE name = ${sql(name)} AND revoked = 0 RETURNING id, name`);
    }
    if (rows.length === 0) console.log("Активных токенов с такими параметрами не найдено.");
    else for (const r of rows) console.log(`Отозван токен id ${r.id} («${r.name}») в ${where}.`);
  } else if (command === "list") {
    const rows = d1("SELECT id, name, created_at, revoked FROM uploaders ORDER BY id");
    if (rows.length === 0) console.log("Загрузчиков пока нет.");
    for (const r of rows) {
      const date = new Date(r.created_at).toLocaleString("ru-RU");
      console.log(`${String(r.id).padStart(4)}  ${r.revoked ? "отозван " : "активен "}  ${date}  ${r.name}`);
    }
  } else {
    fail("неизвестная команда. Доступно: create, revoke, list");
  }
} catch (err) {
  fail(err instanceof Error ? err.message : String(err));
}
