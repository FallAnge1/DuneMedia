#!/usr/bin/env node
// Настройка и обновление сайта на Cloudflare «одной кнопкой».
// Запускается файлами setup-site.bat (Windows) или setup-site.command (Mac) в корне проекта.
// Можно запускать повторно: уже сделанные шаги пропускаются, сайт просто обновится.

import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { ask, closePrompts, confirm, createToken, npm, readAdmin, title, WEB, wrangler, writeAdmin } from "./lib.mjs";

const TOML = join(WEB, "wrangler.toml");
const DB_NAME = "video-archive";
const BUCKET = "video-archive-previews";
const ZERO_ID = "00000000-0000-0000-0000-000000000000";

function fail(message) {
  console.error(`\n\x1b[31mОшибка:\x1b[0m ${message}\n`);
  closePrompts();
  process.exit(1);
}

async function main() {
  console.log("Видеоархив — настройка сайта на Cloudflare\n");
  const [major] = process.versions.node.split(".").map(Number);
  if (major < 20) fail(`нужен Node.js 20 или новее (сейчас ${process.versions.node}). Скачайте с https://nodejs.org`);

  title("1/6. Установка зависимостей");
  if (!npm(["install", "--no-fund", "--no-audit"])) fail("npm install не удался. Проверьте интернет и запустите снова.");

  title("2/6. Вход в Cloudflare");
  const who = wrangler(["whoami"]);
  if (!who.ok || /not authenticated|You are not logged in/i.test(who.out)) {
    console.log("Сейчас откроется браузер — войдите в Cloudflare и нажмите «Allow».");
    if (!wrangler(["login"], { inherit: true }).ok) fail("вход в Cloudflare не выполнен");
  } else {
    const email = /associated with the email ([^\s]+)/i.exec(who.out)?.[1];
    console.log(`Уже вошли${email ? ` (${email.replace(/\.$/, "")})` : ""}.`);
  }

  title("3/6. База данных D1");
  let toml = readFileSync(TOML, "utf8");
  const currentId = /database_id\s*=\s*"([^"]+)"/.exec(toml)?.[1];
  if (!currentId || currentId === ZERO_ID) {
    let id = null;
    const created = wrangler(["d1", "create", DB_NAME]);
    id = /database_id"?\s*[=:]\s*"([0-9a-f-]{36})"/i.exec(created.out)?.[1] ?? null;
    if (!id) {
      // База уже есть — найдём её id в списке.
      const list = wrangler(["d1", "list", "--json"]);
      try {
        const start = list.out.indexOf("[");
        const dbs = JSON.parse(list.out.slice(start, list.out.lastIndexOf("]") + 1));
        id = dbs.find((d) => d.name === DB_NAME)?.uuid ?? null;
      } catch {
        /* разберём ниже */
      }
    }
    if (!id) fail(`не удалось создать базу D1:\n${created.out.trim().slice(0, 800)}`);
    toml = toml.replace(/database_id\s*=\s*"[^"]*"/, `database_id = "${id}"`);
    writeFileSync(TOML, toml);
    console.log(`База готова, id записан в wrangler.toml: ${id}`);
  } else {
    console.log(`База уже настроена (${currentId}).`);
  }

  title("4/6. Хранилище превью R2");
  const bucket = wrangler(["r2", "bucket", "create", BUCKET]);
  if (bucket.ok) console.log("Хранилище создано.");
  else if (/already exists|already own/i.test(bucket.out)) console.log("Хранилище уже есть.");
  else if (/enable R2|10042/i.test(bucket.out)) {
    fail(
      "R2 не включён в аккаунте. Откройте https://dash.cloudflare.com → R2 Object Storage → «Purchase R2 Plan» (план Free, $0), " +
        "привяжите карту (деньги не списываются в пределах 10 ГБ) и запустите этот файл снова.",
    );
  } else fail(`не удалось создать хранилище R2:\n${bucket.out.trim().slice(0, 800)}`);

  title("5/6. Таблицы в базе");
  console.log("Если wrangler спросит подтверждение — нажмите Enter или «y».");
  if (!wrangler(["d1", "migrations", "apply", "DB", "--remote"], { inherit: true }).ok) fail("миграции базы не применились");

  title("6/6. Сборка и публикация сайта");
  if (!npm(["run", "build"])) fail("сборка сайта не удалась");
  console.log("Если wrangler попросит придумать адрес (subdomain) — латиница, цифры и дефис, например dune-media.");
  if (!wrangler(["deploy"], { inherit: true }).ok) fail("публикация не удалась (см. сообщения выше)");

  const admin = readAdmin();
  console.log("\nВ выводе выше есть адрес сайта вида https://video-archive.ИМЯ.workers.dev");
  let site = await ask("Вставьте его сюда (нужен для приглашений)", admin.site_url ?? "");
  site = site.trim().replace(/\/+$/, "");
  if (site && !/^https?:\/\//.test(site)) site = `https://${site}`;
  if (site) writeAdmin({ site_url: site });

  if (!admin.self_token_created && (await confirm("\nСоздать токен загрузчика для себя?"))) {
    const name = await ask("Ваше имя (будет подписью «Загрузил»)", admin.name ?? "");
    if (name) {
      const { token } = createToken(name);
      writeAdmin({ name, self_token_created: true });
      console.log(`\nВаш токен (показывается один раз — сохраните):\n\n  ${token}\n`);
      console.log("Он нужен в программе-загрузчике и для входа в режим редактирования на сайте (кнопка с ключом).");
    }
  }

  title("Готово!");
  if (site) console.log(`Сайт: ${site}`);
  console.log("Дальше: запустите invite.bat (Windows) или invite.command (Mac), чтобы установить программу-загрузчик");
  console.log("себе или подготовить приглашение для другого человека.\n");
  closePrompts();
}

main().catch((err) => fail(err?.message ?? String(err)));
