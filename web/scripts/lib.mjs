// Общие помощники для скриптов администратора (setup, invite, uploader).
import { execFileSync, spawnSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline/promises";
import { wranglerArgs } from "./wrangler-path.mjs";

import { ROOT, WEB } from "./lib-paths.mjs";

export { ROOT, WEB };
const ADMIN_FILE = join(WEB, ".admin.json");

/** Запуск wrangler. inherit — пользователь видит вывод и может отвечать на вопросы. */
export function wrangler(args, { inherit = false, cwd = WEB } = {}) {
  const [node, full] = wranglerArgs(args);
  if (inherit) {
    const r = spawnSync(node, full, { cwd, stdio: "inherit" });
    return { ok: r.status === 0, out: "" };
  }
  const r = spawnSync(node, full, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  return { ok: r.status === 0, out: `${r.stdout ?? ""}\n${r.stderr ?? ""}` };
}

/** npm через оболочку: на Windows npm — это npm.cmd. */
export function npm(args, { cwd = WEB } = {}) {
  const r = spawnSync("npm", args, { cwd, stdio: "inherit", shell: true });
  return r.status === 0;
}

export const sqlString = (s) => `'${String(s).replace(/'/g, "''")}'`;

export function d1(command, { local = false } = {}) {
  const [node, args] = wranglerArgs(["d1", "execute", "DB", local ? "--local" : "--remote", "--json", "--command", command]);
  const out = execFileSync(node, args, { cwd: WEB, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] });
  return JSON.parse(out)[0]?.results ?? [];
}

/** Создаёт загрузчика и возвращает его токен (в базе — только хеш). */
export function createToken(name, { local = false } = {}) {
  const token = `va_${randomBytes(32).toString("base64url")}`;
  const hash = createHash("sha256").update(token).digest("hex");
  const rows = d1(
    `INSERT INTO uploaders (name, token_hash, created_at, revoked) VALUES (${sqlString(name)}, ${sqlString(hash)}, ${Date.now()}, 0) RETURNING id`,
    { local },
  );
  return { token, id: rows[0]?.id };
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
