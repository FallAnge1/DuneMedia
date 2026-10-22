#!/bin/bash
# Установка программы-загрузчика видеоархива на Mac.
# Обычно запускается из файла «Установить (Mac).command», который создаёт invite.command.
# Можно и вручную в Терминале:
#   curl -fsSL https://raw.githubusercontent.com/FallAnge1/DuneMedia/main/install/mac.sh | VA_INVITE='КОД' bash
#
# Что делает: скачивает свежий .dmg из GitHub Releases (Apple Silicon или Intel), копирует программу
# в «Программы», записывает настройки из приглашения и запускает программу.

set -euo pipefail

say() { printf '%s\n' "$1"; }
fail() {
  printf '\n\033[31mОшибка:\033[0m %s\n' "$1"
  say "Проверьте интернет и запустите ещё раз. Если не помогло — пришлите скриншот этого окна."
  exit 1
}

say ""
say "Видеоархив — установка программы-загрузчика"
say "-------------------------------------------"

INVITE="${VA_INVITE:-}"
REPO="FallAnge1/DuneMedia"
INVITE_JSON=""
if [ -n "$INVITE" ]; then
  # base64url → base64 → JSON (через встроенный в macOS JavaScript, Python не нужен)
  INVITE_JSON=$(VA_INVITE="$INVITE" osascript -l JavaScript -e '
    ObjC.import("Foundation");
    var s = ObjC.unwrap($.NSProcessInfo.processInfo.environment.objectForKey("VA_INVITE")).trim().replace(/-/g, "+").replace(/_/g, "/");
    while (s.length % 4) s += "=";
    var data = $.NSData.alloc.initWithBase64EncodedStringOptions(s, 0);
    ObjC.unwrap($.NSString.alloc.initWithDataEncoding(data, 4));
  ') || fail "приглашение повреждено — попросите прислать его заново"
  NAME=$(VA_JSON="$INVITE_JSON" osascript -l JavaScript -e 'ObjC.import("Foundation"); var j = JSON.parse(ObjC.unwrap($.NSProcessInfo.processInfo.environment.objectForKey("VA_JSON"))); j.name || ""')
  INVITE_REPO=$(VA_JSON="$INVITE_JSON" osascript -l JavaScript -e 'ObjC.import("Foundation"); var j = JSON.parse(ObjC.unwrap($.NSProcessInfo.processInfo.environment.objectForKey("VA_JSON"))); j.repo || ""')
  [ -n "$INVITE_REPO" ] && REPO="$INVITE_REPO"
  say "Приглашение для: $NAME"
else
  say "Приглашения нет — программа установится, настройки введёте в мастере."
fi

case "$(uname -m)" in
  arm64) PLATFORM="mac-arm64" ;;
  *) PLATFORM="mac-x64" ;;
esac
URL="https://github.com/$REPO/releases/download/uploader-latest/VideoArchive-$PLATFORM.dmg"

TMP=$(mktemp -d)
trap 'hdiutil detach "$TMP/mnt" -quiet >/dev/null 2>&1 || true; rm -rf "$TMP"' EXIT

say "Скачиваю программу ($PLATFORM, около 110 МБ)..."
curl -fL --progress-bar -o "$TMP/va.dmg" "$URL" || fail "не удалось скачать $URL"

say "Устанавливаю..."
mkdir -p "$TMP/mnt"
hdiutil attach "$TMP/va.dmg" -nobrowse -readonly -mountpoint "$TMP/mnt" -quiet || fail "не удалось открыть .dmg"
DEST="/Applications"
[ -w "$DEST" ] || DEST="$HOME/Applications"
mkdir -p "$DEST"
pkill -x VideoArchive >/dev/null 2>&1 || true
rm -rf "$DEST/VideoArchive.app"
cp -R "$TMP/mnt/VideoArchive.app" "$DEST/" || fail "не удалось скопировать программу в $DEST"
hdiutil detach "$TMP/mnt" -quiet || true
# Файл скачан не браузером, но на всякий случай снимаем «карантин», чтобы macOS не блокировала запуск.
xattr -dr com.apple.quarantine "$DEST/VideoArchive.app" 2>/dev/null || true
say "Программа установлена в $DEST."

if [ -n "$INVITE_JSON" ]; then
  CFG_DIR="$HOME/Library/Application Support/VideoArchive"
  mkdir -p "$CFG_DIR"
  VA_JSON="$INVITE_JSON" VA_CFG="$CFG_DIR/config.json" osascript -l JavaScript -e '
    ObjC.import("Foundation");
    var env = $.NSProcessInfo.processInfo.environment;
    var invite = JSON.parse(ObjC.unwrap(env.objectForKey("VA_JSON")));
    var path = ObjC.unwrap(env.objectForKey("VA_CFG"));
    var cfg = {};
    var existing = $.NSString.stringWithContentsOfFileEncodingError(path, 4, null);
    if (existing && !existing.isNil()) { try { cfg = JSON.parse(ObjC.unwrap(existing)); } catch (e) { cfg = {}; } }
    ["site_url", "uploader_token", "channel"].forEach(function (k) { if (invite[k]) cfg[k] = invite[k]; });
    if (invite.api_id) { cfg.api_id = Number(invite.api_id); cfg.api_hash = invite.api_hash; }
    $(JSON.stringify(cfg, null, 2)).writeToFileAtomicallyEncodingError(path, true, 4, null);
    "ok";
  ' >/dev/null || fail "не удалось записать настройки"
  say "Настройки из приглашения записаны."
fi

if [ -z "${VA_NO_LAUNCH:-}" ]; then
  open "$DEST/VideoArchive.app"
fi
say ""
say "Готово! Программа откроется сама."
say "В мастере настройки введите свой номер телефона, нажмите «Получить код» и введите код из Telegram."
say "Остальные шаги уже заполнены — просто нажимайте «Далее»."
