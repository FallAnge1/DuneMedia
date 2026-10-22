// Файлы приглашения: «Установить (Windows).bat», «Установить (Mac).command», «Как установить.txt».
// Используется invite.mjs и проверкой в CI:  node web/scripts/invite-files.mjs <папка> <код>
import { chmodSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { ROOT } from "./lib-paths.mjs";

export function writeInviteFiles({ name, code, repo, shareKeys, dir: targetDir }) {
  const safe = name.replace(/[\\/:*?"<>|]+/g, "_").trim() || "загрузчик";
  const dir = targetDir ?? join(ROOT, "invites", safe);
  mkdirSync(dir, { recursive: true });

  const ps1 = readFileSync(join(ROOT, "install", "windows.ps1"), "utf8");
  const bat = [
    "@echo off",
    "chcp 65001 >nul",
    `set "VA_INVITE=${code}"`,
    // Батник читает сам себя и выполняет PowerShell-часть после метки.
    `powershell -NoProfile -ExecutionPolicy Bypass -Command "$s = Get-Content -Raw -Encoding UTF8 -LiteralPath '%~f0'; $m = '#' + 'PS1' + '#'; iex ($s.Substring($s.IndexOf($m) + $m.Length)); exit $global:VA_RESULT"`,
    "set VA_CODE=%errorlevel%",
    "echo.",
    "pause",
    "exit /b %VA_CODE%",
    "#PS1#",
    ps1,
  ].join("\r\n");
  writeFileSync(join(dir, "Установить (Windows).bat"), bat);

  const sh = readFileSync(join(ROOT, "install", "mac.sh"), "utf8").replace(/^#!.*\n/, "");
  const command = `#!/bin/bash\nexport VA_INVITE='${code}'\n${sh}`;
  const commandPath = join(dir, "Установить (Mac).command");
  writeFileSync(commandPath, command);
  try {
    chmodSync(commandPath, 0o755);
  } catch {
    /* Windows */
  }

  const raw = `https://raw.githubusercontent.com/${repo}/main/install`;
  const readme = `Видеоархив — установка программы-загрузчика для: ${name}

ЧТО ПРИСЛАЛИ
Файлы в этой папке — ваше личное приглашение. В нём ваш токен: никому его не пересылайте.

WINDOWS
1. Дважды щёлкните «Установить (Windows).bat».
   Если появится синее окно «Windows защитила ваш компьютер» — нажмите «Подробнее» → «Выполнить в любом случае».
2. Подождите, пока скачается и установится программа (несколько минут), — она откроется сама.

MAC
1. Откройте программу «Терминал» (Cmd+Пробел → «Терминал»).
2. Вставьте строку ниже целиком и нажмите Enter:

curl -fsSL ${raw}/mac.sh | VA_INVITE='${code}' bash

   (Или дважды щёлкните «Установить (Mac).command». Если Mac скажет, что не может открыть файл, —
   правый клик по нему → «Открыть» → «Открыть». Если пишет про права доступа — в Терминале наберите
   bash и пробел, перетащите файл в окно Терминала и нажмите Enter.)

ПОСЛЕ УСТАНОВКИ
Откроется мастер настройки. Введите СВОЙ номер телефона → «Получить код» → код из Telegram
(и пароль, если включена двухэтапная проверка). Остальные шаги уже заполнены — просто нажимайте «Далее».
${shareKeys ? "" : "\nНа первом шаге понадобятся api_id и api_hash: как их получить — https://my.telegram.org → API development tools\n(подробно: docs/02-telegram-api.md в репозитории).\n"}
ЕСЛИ ФАЙЛЫ НЕ ЗАПУСКАЮТСЯ (Windows, вручную)
Откройте PowerShell и вставьте:

$env:VA_INVITE='${code}'; irm ${raw}/windows.ps1 | iex
`;
  writeFileSync(join(dir, "Как установить.txt"), readme.replace(/\n/g, process.platform === "win32" ? "\r\n" : "\n"));

  return dir;
}

// Запуск из командной строки (для CI): создать файлы в указанной папке.
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [dir, code] = process.argv.slice(2);
  const invite = JSON.parse(Buffer.from(code, "base64url").toString("utf8"));
  console.log(writeInviteFiles({ name: invite.name, code, repo: invite.repo, shareKeys: !!invite.api_id, dir }));
}
