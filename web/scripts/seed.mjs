#!/usr/bin/env node
// Наполняет ЛОКАЛЬНЫЙ архив тестовыми видео для разработки сайта.
//
//   1) в одном терминале:  npm run db:migrate:local && npm run dev
//   2) в другом:            npm run seed            (по умолчанию 50 видео)
//                           npm run seed -- --count 120 --url http://localhost:8787
//
// ffmpeg генерирует цветные ролики разных пропорций (превью ~480p и постер),
// они загружаются через API так же, как это делает программа-загрузчик.
// Посты в Telegram не создаются: ссылки «Открыть в Telegram» ведут на несуществующий канал.

import { execFile, execFileSync } from "node:child_process";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { promisify } from "node:util";

const run = promisify(execFile);
const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i === -1 ? fallback : args[i + 1];
};
const BASE = opt("url", "http://localhost:8787").replace(/\/$/, "");
const COUNT = Number(opt("count", 50));
const CACHE = ".seed-cache";
const CHANNEL = "dune_media_test";

// Детерминированный генератор случайных чисел: при повторном запуске те же ролики.
let seed = 42;
const rnd = () => ((seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296);
const pick = (list) => list[Math.floor(rnd() * list.length)];
const pickSome = (list, min, max) => {
  const n = min + Math.floor(rnd() * (max - min + 1));
  return [...list].sort(() => rnd() - 0.5).slice(0, n);
};

// Пропорции превью (короткая сторона 480) и «оригинала», от которого считается метка разрешения.
const FORMATS = [
  { w: 854, h: 480, orig: [[1920, 1080], [3840, 2160], [1280, 720], [2560, 1440]] },
  { w: 270, h: 480, orig: [[1080, 1920], [2160, 3840], [720, 1280]] },
  { w: 480, h: 480, orig: [[1080, 1080], [2160, 2160]] },
  { w: 640, h: 480, orig: [[1440, 1080], [640, 480]] },
  { w: 1120, h: 480, orig: [[3840, 1646], [1920, 822]] },
  { w: 384, h: 480, orig: [[1080, 1350]] },
];

const SOURCES = [
  (w, h, c) => `gradients=s=${w}x${h}:c0=${c[0]}:c1=${c[1]}:c2=${c[2]}:speed=0.04:r=25`,
  (w, h) => `testsrc2=s=${w}x${h}:r=25`,
  (w, h) => `mandelbrot=s=${w}x${h}:r=25`,
  (w, h, c) => `life=s=${w}x${h}:mold=10:r=25:ratio=0.12:death_color=${c[0]}:life_color=${c[1]}`,
  (w, h) => `cellauto=s=${w}x${h}:rule=${pick([18, 30, 90, 110, 150])}:r=25`,
  (w, h) => `smptehdbars=s=${w}x${h}:r=25`,
];

const COLORS = ["0x1f3b73", "0xe8a33d", "0xd94f3d", "0x2f8a4c", "0x6a3d9a", "0x13a3a3", "0xf2d14b", "0x101010", "0xfafafa"];

const TITLES = [
  "Закат над морем", "Ночной город с высоты", "Туман в горах", "Дождь по стеклу", "Осенний лес",
  "Волны у пирса", "Снегопад в парке", "Огни мегаполиса", "Рассвет в поле", "Облака над долиной",
  "Пустынная дорога", "Кофе крупным планом", "Неоновые вывески", "Мост в тумане", "Лодки в гавани",
  "Таймлапс звёздного неба", "Водопад в ущелье", "Поезд в метро", "Цветущая сакура", "Ветер в траве",
  "Горное озеро", "Фонари на набережной", "Капли росы", "Старый город", "Северное сияние",
];

const TAGS = [
  "закат", "рассвет", "море", "город", "ночь", "дрон", "таймлапс", "слоумо", "лес", "горы", "снег",
  "дождь", "туман", "люди", "крупный план", "тёплые цвета", "холодные цвета", "архитектура", "вода",
  "небо", "облака", "осень", "зима", "лето", "весна", "неон", "природа", "дорога", "огни", "спокойное",
];

const COLLECTIONS = [
  { name: "Природа", emoji: "🌲" },
  { name: "Город", emoji: "🏙️" },
  { name: "Съёмка с дрона", emoji: "🚁" },
  { name: "Для рилс", emoji: "📱" },
];

function localToken() {
  // Создаём локального загрузчика «Seed» прямо в локальной D1.
  const token = `va_seed_${randomBytes(16).toString("hex")}`;
  const hash = createHash("sha256").update(token).digest("hex");
  execFileSync(
    "npx",
    [
      "wrangler", "d1", "execute", "DB", "--local", "--command",
      `INSERT INTO uploaders (name, token_hash, created_at, revoked) VALUES ('Seed', '${hash}', ${Date.now()}, 0)`,
    ],
    { stdio: "ignore" },
  );
  return token;
}

async function api(token, method, path, body, contentType = "application/json") {
  const res = await fetch(BASE + path, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": contentType } : {}) },
    body: body && contentType === "application/json" ? JSON.stringify(body) : body,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok && res.status !== 409) throw new Error(`${method} ${path}: ${res.status} ${data?.error?.message ?? ""}`);
  return data;
}

let drawtextOk = null;

async function makeClip(i, spec) {
  const dir = join(CACHE, String(i).padStart(3, "0"));
  const preview = join(dir, "preview.mp4");
  const poster = join(dir, "poster.jpg");
  if (existsSync(preview) && existsSync(poster)) return { preview, poster };
  mkdirSync(dir, { recursive: true });

  const label = `drawtext=text='№${i + 1}  %{pts\\:hms}':x=16:y=h-th-16:fontsize=${Math.round(Math.min(spec.w, spec.h) / 16)}:fontcolor=white:box=1:boxcolor=black@0.45:boxborderw=8`;
  const base = `${spec.source},hue=h=${spec.hue}+t*12,format=yuv420p`;
  const encode = (filter) =>
    run("ffmpeg", [
      "-loglevel", "error", "-y", "-f", "lavfi", "-i", filter, "-t", "8",
      "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", preview,
    ]);
  if (drawtextOk !== false) {
    try {
      await encode(`${base},${label}`);
      drawtextOk = true;
    } catch {
      drawtextOk = false; // нет шрифтов — делаем ролики без надписи
    }
  }
  if (!drawtextOk) await encode(base);
  await run("ffmpeg", ["-loglevel", "error", "-y", "-ss", "1", "-i", preview, "-frames:v", "1", "-q:v", "4", poster]);
  return { preview, poster };
}

async function main() {
  try {
    await fetch(`${BASE}/api/health`);
  } catch {
    console.error(`Сервер ${BASE} не отвечает. Сначала запустите: npm run dev`);
    process.exit(1);
  }
  try {
    execFileSync("ffmpeg", ["-version"], { stdio: "ignore" });
  } catch {
    console.error("Не найден ffmpeg. Установите его и добавьте в PATH.");
    process.exit(1);
  }

  const token = process.env.SEED_TOKEN || localToken();
  console.log(`Создаю ${COUNT} тестовых видео на ${BASE}…`);

  // Коллекции
  const existing = (await (await fetch(`${BASE}/api/collections`)).json()).collections;
  const colIds = [];
  for (const c of COLLECTIONS) {
    const found = existing.find((x) => x.name === c.name);
    colIds.push(found ? found.id : (await api(token, "POST", "/api/collections", c)).collection.id);
  }

  const specs = Array.from({ length: COUNT }, (_, i) => {
    const format = pick(FORMATS);
    const [ow, oh] = pick(format.orig);
    const colors = pickSome(COLORS, 3, 3);
    return {
      i,
      w: format.w,
      h: format.h,
      ow,
      oh,
      hue: Math.floor(rnd() * 360),
      source: pick(SOURCES)(format.w, format.h, colors),
      title: `${pick(TITLES)}${rnd() < 0.4 ? ` ${2 + Math.floor(rnd() * 8)}` : ""}`,
      tags: pickSome(TAGS, 2, 7),
      collections: pickSome(colIds, 0, 2),
      duration: Math.round((rnd() < 0.35 ? 2 + rnd() * 10 : rnd() < 0.7 ? 10 + rnd() * 50 : 60 + rnd() * 500) * 10) / 10,
      fps: pick([23.976, 25, 29.97, 30, 50, 60]),
      codec: pick(["h264", "hevc", "prores"]),
      description: rnd() < 0.5 ? "Тестовый ролик, сгенерированный ffmpeg для проверки сайта." : null,
      createdAt: Date.now() - Math.floor(rnd() * 120 * 24 * 3600 * 1000),
    };
  });

  // Ролики кодируются по 4 параллельно.
  const queue = [...specs];
  let done = 0;
  const worker = async () => {
    for (let s = queue.shift(); s; s = queue.shift()) {
      const { preview, poster } = await makeClip(s.i, s);
      const id = randomUUID();
      const suffix = randomBytes(4).toString("hex");
      const previewKey = `previews/${id}-${suffix}.mp4`;
      const posterKey = `posters/${id}-${suffix}.jpg`;
      await api(token, "PUT", `/api/media/${previewKey}`, readFileSync(preview), "video/mp4");
      await api(token, "PUT", `/api/media/${posterKey}`, readFileSync(poster), "image/jpeg");
      const bitrate = s.codec === "prores" ? 120e6 : s.ow >= 3840 ? 45e6 : 12e6;
      await api(token, "POST", "/api/videos", {
        id,
        tg_channel: CHANNEL,
        tg_message_id: 1000 + s.i + Math.floor(Date.now() / 1000) % 100000 * 1000,
        title: s.title,
        description: s.description,
        file_name: `${s.title.toLowerCase().replace(/\s+/g, "_")}.${s.codec === "prores" ? "mov" : "mp4"}`,
        file_size: Math.round((s.duration * bitrate) / 8),
        duration: s.duration,
        width: s.ow,
        height: s.oh,
        fps: s.fps,
        codec: s.codec,
        preview_key: previewKey,
        poster_key: posterKey,
        tags: s.tags,
        collections: s.collections,
        created_at: s.createdAt,
      });
      process.stdout.write(`\r  готово ${++done} из ${COUNT}`);
    }
  };
  await Promise.all([worker(), worker(), worker(), worker()]);
  console.log(`\nГотово. Откройте ${BASE}`);
  if (!process.env.SEED_TOKEN) console.log(`Токен для входа на сайт (режим редактирования): ${token}`);
}

main().catch((err) => {
  console.error("\nОшибка:", err.message);
  process.exit(1);
});
