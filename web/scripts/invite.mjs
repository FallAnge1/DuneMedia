#!/usr/bin/env node
// Приглашение нового загрузчика: токен + папка с установщиками для Windows и Mac.
// Запускается файлами invite.bat (Windows) или invite.command (Mac) в корне проекта.
//
// Человек получает папку, дважды щёлкает «Установить (Windows).bat» или «Установить (Mac).command» —
// программа скачивается, ставится и уже знает адрес сайта, канал и токен.
// Ему останется только войти в свой Telegram (телефон и код).

import { execFileSync } from "node:child_process";
import { writeInviteFiles } from "./invite-files.mjs";
import { ask, closePrompts, confirm, createToken, openPath, readAdmin, ROOT, title, writeAdmin } from "./lib.mjs";

const local = process.argv.includes("--local");

function fail(message) {
  console.error(`\n\x1b[31mОшибка:\x1b[0m ${message}\n`);
  closePrompts();
  process.exit(1);
}

function detectRepo() {
  try {
    const url = execFileSync("git", ["config", "--get", "remote.origin.url"], { cwd: ROOT, encoding: "utf8" }).trim();
    const m = /github\.com[:/]([^/]+\/[^/.]+)/i.exec(url);
    if (m) return m[1];
  } catch {
    /* скачан ZIP-архивом — git нет */
  }
  return "FallAnge1/DuneMedia";
}

async function checkSite(url) {
  try {
    const res = await fetch(`${url}/api/health`);
    return res.ok;
  } catch {
    return false;
  }
}

async function main() {
  console.log("Видеоархив — приглашение загрузчика\n");
  const admin = readAdmin();

  // Адрес сайта
  let site = await ask("Адрес сайта", admin.site_url ?? "");
  site = site.trim().replace(/\/+$/, "");
  if (!site) fail("нужен адрес сайта (его выводит setup-site при публикации)");
  if (!/^https?:\/\//.test(site)) site = `https://${site}`;
  if (!local && !(await checkSite(site))) fail(`сайт ${site} не отвечает. Проверьте адрес или запустите setup-site заново.`);

  // Канал
  let channel = await ask("Username канала в Telegram", admin.channel ?? "");
  channel = channel.replace(/^https?:\/\/t\.me\//, "").replace(/^@/, "").split("/")[0].trim();
  if (!channel) fail("нужен username канала");

  // Ключи Telegram — по желанию
  let apiId = admin.api_id ?? "";
  let apiHash = admin.api_hash ?? "";
  let shareKeys = false;
  console.log(
    "\nЕсли передать человеку ваши api_id и api_hash (с my.telegram.org), ему не придётся регистрировать их самому." +
      "\nЭто безопасно для вашего аккаунта: по ним нельзя войти к вам, каждый входит своим телефоном и кодом.",
  );
  if (apiId && apiHash) {
    shareKeys = await confirm(`Передать сохранённые api_id ${apiId}?`);
  } else {
    apiId = await ask("Ваш api_id (Enter — не передавать)");
    if (apiId) {
      apiHash = await ask("Ваш api_hash");
      shareKeys = !!apiHash;
    }
  }
  if (shareKeys && !/^\d+$/.test(String(apiId))) fail("api_id — это число");

  // Человек
  const name = await ask("\nИмя человека (будет подписью «Загрузил»)");
  if (!name) fail("нужно имя");

  title("Создаю токен…");
  let token;
  try {
    ({ token } = createToken(name, { local }));
  } catch (err) {
    fail(`не удалось создать токен: ${err.message}`);
  }
  if (!local) {
    const me = await fetch(`${site}/api/me`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => null);
    if (!me?.ok) fail("токен создан, но сайт его не принял — похоже, адрес сайта от другого проекта");
  }

  const repo = admin.repo ?? detectRepo();
  writeAdmin({ site_url: site, channel, repo, ...(shareKeys ? { api_id: String(apiId), api_hash: apiHash } : {}) });

  const invite = { v: 1, name, site_url: site, uploader_token: token, channel, repo };
  if (shareKeys) Object.assign(invite, { api_id: Number(apiId), api_hash: apiHash });
  const code = Buffer.from(JSON.stringify(invite), "utf8").toString("base64url");

  const dir = writeInviteFiles({ name, code, repo, shareKeys });

  // Проверим, что установщики уже опубликованы.
  const releaseUrl = `https://github.com/${repo}/releases/download/uploader-latest/VideoArchive-Setup.exe`;
  const head = await fetch(releaseUrl, { method: "HEAD", redirect: "follow" }).catch(() => null);

  title("Готово!");
  console.log(`Приглашение: ${dir}`);
  console.log("\nОтправьте человеку ЛИЧНО всю эту папку (или нужный файл + «Как установить.txt»).");
  console.log("И не забудьте сделать его администратором канала с правом публикации.");
  console.log("Чтобы поставить программу себе — просто запустите установщик из этой папки.");
  if (!head?.ok) {
    console.log(
      `\n\x1b[33mВнимание:\x1b[0m на GitHub пока нет готового установщика (${releaseUrl}).` +
        "\nОн появится после сборки: GitHub → Actions → «Сборка загрузчика».",
    );
  }
  console.log("\nОтозвать доступ: npm run uploader:revoke -- \"" + name + "\" (в папке web)\n");
  closePrompts();
  if (!local) openPath(dir);
}

main().catch((err) => fail(err?.message ?? String(err)));
