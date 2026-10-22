// Общие помощники для скриптов администратора (setup, invite, uploader).
import { spawnSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline/promises";
import { wranglerArgs } from "./wrangler-path.mjs";

import { ROOT, WEB } from "./lib-paths.mjs";

export { ROOT, WEB };
const ADMIN_FILE = join(WEB, ".admin.json");

// На Windows Node.js иногда падает уже ПОСЛЕ того, как wrangler всё сделал:
// «Assertion failed: !(handle->flags & UV_HANDLE_CLOSING), file src\win\async.c».
// Работа при этом выполнена, поэтому такое падение на выходе не считаем ошибкой, если wrangler не сообщал об ошибках.
const EXIT_CRASH = /UV_HANDLE_CLOSING|src[\\/]win[\\/]async\.c/;
const WRANGLER_ERROR = /\[ERROR\]|✘/;

function runWrangler(args, { inherit = false, cwd = WEB } = {}) {
  const [node, full] = wranglerArgs(args);
  const r = spawnSync(node, full, {
    cwd,
    encoding: "utf8",
    // stderr читаем всегда — чтобы распознать падение на выходе; при inherit показываем его пользователю.
    stdio: inherit ? ["inherit", "inherit", "pipe"] : ["ignore", "pipe", "pipe"],
    maxBuffer: 64 * 1024 * 1024,
  });
  let err = r.stderr ?? "";
  const out = r.stdout ?? "";
  const crashedOnExit = r.status !== 0 && EXIT_CRASH.test(err);
  if (crashedOnExit) err = err.split(/\r?\n/).filter((line) => !EXIT_CRASH.test(line)).join("\n");
  if (inherit && err.trim()) process.stderr.write(err.endsWith("\n") ? err : `${err}\n`);
  const ok = r.status === 0 || (crashedOnExit && !WRANGLER_ERROR.test(`${out}\n${err}`));
  return { ok, out, err, crashedOnExit };
}

/** Запуск wrangler. inherit — пользователь видит вывод и может отвечать на вопросы. */
export function wrangler(args, options = {}) {
  const r = runWrangler(args, options);
  return { ok: r.ok, out: `${r.out}\n${r.err}` };
}

/** npm через оболочку: на Windows npm — это npm.cmd. */
export function npm(args, { cwd = WEB } = {}) {
  const r = spawnSync("npm", args, { cwd, stdio: "inherit", shell: true });
  return r.status === 0;
}

export const sqlString = (s) => `'${String(s).replace(/'/g, "''")}'`;

function parseJson(text) {
  const start = text.search(/[[{]/);
  if (start < 0) return undefined;
  const end = Math.max(text.lastIndexOf("]"), text.lastIndexOf("}"));
  try {
    return JSON.parse(text.slice(start, end + 1));
  } catch {
    return undefined;
  }
}

/** SQL-запрос к базе D1 через wrangler. Возвращает строки результата. */
export function d1(command, { local = false } = {}) {
  const r = runWrangler(["d1", "execute", "DB", local ? "--local" : "--remote", "--json", "--command", command]);
  const parsed = parseJson(r.out);
  // Ответ с результатом — значит, запрос выполнен, даже если процесс потом упал на выходе.
  if (Array.isArray(parsed)) return parsed[0]?.results ?? [];
  const reason = parsed?.error?.text ?? parsed?.error?.message ?? (r.err || r.out).trim().split(/\r?\n/).slice(-6).join("\n");
  throw new Error(reason || "wrangler завершился с ошибкой");
}

/** Создаёт загрузчика и возвращает его токен (в базе — только хеш). */
export function createToken(name, { local = false } = {}) {
  const token = `va_${randomBytes(32).toString("base64url")}`;
  const hash = createHash("sha256").update(token).digest("hex");
  const insert = `INSERT INTO uploaders (name, token_hash, created_at, revoked) VALUES (${sqlString(name)}, ${sqlString(hash)}, ${Date.now()}, 0) RETURNING id`;
  const find = `SELECT id FROM uploaders WHERE token_hash = ${sqlString(hash)}`;
  let lastError;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const rows = d1(insert, { local });
      return { token, id: rows[0]?.id };
    } catch (err) {
      lastError = err;
      // Запрос мог дойти до базы, а ответ потеряться — проверим, есть ли уже такой токен.
      try {
        const rows = d1(find, { local });
        if (rows.length) return { token, id: rows[0].id };
      } catch {
        /* попробуем ещё раз */
      }
    }
  }
  throw lastError;
}

/** Запомненные ответы администратора (адрес сайта, канал…). Файл не попадает в git. */
export function readAdmin() {
  try {
    return JSON.parse(readFileSync(ADMIN_FILE, "utf8"));
  } catch {
    return {};
  }
}

export function writeAdmin(patch) {
  const next = { ...readAdmin(), ...patch };
  writeFileSync(ADMIN_FILE, JSON.stringify(next, null, 2));
  return next;
}

let rl;
export async function ask(question, fallback = "") {
  rl ??= createInterface({ input: process.stdin, output: process.stdout });
  const hint = fallback ? ` [${fallback}]` : "";
  const answer = (await rl.question(`${question}${hint}: `)).trim();
  return answer || fallback;
}

export async function confirm(question, yes = true) {
  const answer = (await ask(`${question} (${yes ? "Д/н" : "д/Н"})`)).toLowerCase();
  if (!answer) return yes;
  return ["д", "да", "y", "yes"].includes(answer);
}

export function closePrompts() {
  rl?.close();
  rl = undefined;
}

export function openPath(path) {
  const cmd = process.platform === "win32" ? "explorer" : process.platform === "darwin" ? "open" : "xdg-open";
  spawnSync(cmd, [path], { stdio: "ignore", shell: process.platform === "win32" });
}

export const exists = existsSync;

export function title(text) {
  console.log(`\n\x1b[1m${text}\x1b[0m`);
}
