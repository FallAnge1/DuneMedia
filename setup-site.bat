@echo off
chcp 65001 >nul
title Видеоархив — настройка сайта
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 goto nonode
if not exist "web\node_modules\wrangler" (
  echo Устанавливаю зависимости...
  pushd web
  call npm install --no-fund --no-audit
  popd
)
node web\scripts\setup.mjs
echo.
pause
exit /b

:nonode
echo Node.js не найден. Пробую установить через winget...
winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
if errorlevel 1 (
  echo Не получилось. Установите Node.js вручную с https://nodejs.org ^(кнопка LTS^) и запустите этот файл снова.
  start https://nodejs.org
) else (
  echo Node.js установлен. Закройте это окно и запустите файл ещё раз.
)
pause
