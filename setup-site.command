#!/bin/bash
# Двойной щелчок в Finder откроет Терминал и запустит скрипт.
cd "$(dirname "$0")" || exit 1
if ! command -v node >/dev/null 2>&1; then
  for p in /opt/homebrew/bin /usr/local/bin; do [ -x "$p/node" ] && export PATH="$p:$PATH"; done
fi
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js не найден. Скачайте и установите его с https://nodejs.org (кнопка LTS), затем запустите этот файл снова."
  open "https://nodejs.org"
  exit 1
fi
if [ ! -d web/node_modules/wrangler ]; then
  echo "Устанавливаю зависимости..."
  (cd web && npm install --no-fund --no-audit) || exit 1
fi
node web/scripts/setup.mjs
