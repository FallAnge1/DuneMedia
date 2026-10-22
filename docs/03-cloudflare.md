# 3. Сайт на Cloudflare: регистрация и деплой

Сайт, API, база и превью работают на бесплатном тарифе Cloudflare:
**Workers** (сайт и API), **D1** (база), **R2** (превью и постеры), **Workers AI** (ИИ-теги).

## Что понадобится

- Аккаунт Cloudflare — бесплатный: https://dash.cloudflare.com/sign-up
- **Node.js 20 или новее** — https://nodejs.org (кнопка LTS).
- Проект: скачайте ZIP с GitHub (Code → Download ZIP) или `git clone https://github.com/FallAnge1/DuneMedia.git`.

> **R2 и банковская карта.** Чтобы включить R2, Cloudflare просит один раз привязать карту или PayPal,
> даже на бесплатном тарифе. Деньги не списываются, пока вы в пределах 10 ГБ и бесплатных операций
> (см. [07-limits.md](07-limits.md)). Включить: панель Cloudflare → **R2 Object Storage** → **Purchase R2 Plan** (план Free, $0).

## Первый деплой

Все команды — в терминале, в папке `web` проекта:

```bash
cd web
npm install

# 1. Войти в Cloudflare (откроется браузер)
npx wrangler login

# 2. Создать базу D1
npx wrangler d1 create video-archive
```

Команда выведет блок с `database_id = "…"`. Откройте `web/wrangler.toml` и замените им строку
`database_id = "00000000-0000-0000-0000-000000000000"`.

```bash
# 3. Создать хранилище R2 для превью
npx wrangler r2 bucket create video-archive-previews

# 4. Создать таблицы в базе
npm run db:migrate:remote

# 5. Собрать сайт и выложить
npm run deploy
```

В конце `deploy` покажет адрес сайта, например `https://video-archive.ваше-имя.workers.dev`.
Откройте его — появится пустой архив.

```bash
# 6. Токен для первого загрузчика (выводится один раз — сохраните)
npm run uploader:create -- "Анна"
```

Подробнее о токенах — [04-tokens.md](04-tokens.md).

## Свой домен (по желанию, но полезно)

Если у вас есть домен, подключённый к Cloudflare: панель → **Workers & Pages** → `video-archive` →
**Settings → Domains & Routes → Add → Custom domain**, например `archive.example.com`.

С собственным доменом:
- превью и постеры кэшируются в сети Cloudflare (на `*.workers.dev` кэш недоступен);
- сайт можно закрыть паролем через Cloudflare Access ([08-cloudflare-access.md](08-cloudflare-access.md)).

## Обновление сайта

```bash
git pull               # или скачайте новую версию
cd web
npm install
npm run db:migrate:remote   # если появились новые миграции — применятся только они
npm run deploy
```

## Деплой из GitHub (без своего компьютера)

1. Cloudflare → **My Profile → API Tokens → Create Token** → шаблон **Edit Cloudflare Workers**.
   Добавьте права **Account → D1 → Edit**. Создайте и скопируйте токен.
2. ID аккаунта — справа на главной странице панели Cloudflare (**Account ID**).
3. GitHub → репозиторий → **Settings → Secrets and variables → Actions**: добавьте
   `CLOUDFLARE_API_TOKEN` и `CLOUDFLARE_ACCOUNT_ID`.
4. **Actions → «Деплой сайта» → Run workflow.**

`database_id` в `wrangler.toml` при этом должен быть уже заполнен (шаг 2 первого деплоя).

## Настройки ИИ на сайте

В `web/wrangler.toml`, раздел `[vars]`:
- `AI_MODEL` — модель Workers AI по умолчанию (vision-модель из каталога https://developers.cloudflare.com/workers-ai/models/).
  Если модель уберут из каталога — замените и сделайте `npm run deploy`.

## Локальная разработка

См. [README](../README.md#быстрый-старт-разработка): `npm run dev`, `npm run seed` (50 тестовых видео).
