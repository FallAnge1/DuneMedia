import { env } from "cloudflare:workers";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { api, createUploader, fakeJpeg, fakeMp4, json, videoPayload } from "./helpers";

let token: string;

beforeAll(async () => {
  token = await createUploader("Анна");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("общее", () => {
  it("health", async () => {
    const res = await api("/api/health");
    expect(res.status).toBe(200);
    expect(await json(res)).toEqual({ ok: true });
  });

  it("неизвестный адрес API — 404 в JSON", async () => {
    const res = await api("/api/nope");
    expect(res.status).toBe(404);
    expect((await json(res)).error.code).toBe("not_found");
  });

  it("остальные адреса отдают статику сайта", async () => {
    const res = await api("/some/page");
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toContain("text/html");
  });
});

describe("авторизация", () => {
  it("без токена — 401", async () => {
    const res = await api("/api/videos", { method: "POST", json: videoPayload() });
    expect(res.status).toBe(401);
    expect((await json(res)).error.message).toMatch(/токен/i);
  });

  it("неизвестный токен — 401", async () => {
    const res = await api("/api/me", { token: "va_wrong" });
    expect(res.status).toBe(401);
  });

  it("отозванный токен — 403", async () => {
    const revoked = await createUploader("Бывший", true);
    const res = await api("/api/me", { token: revoked });
    expect(res.status).toBe(403);
    expect((await json(res)).error.code).toBe("token_revoked");
  });

  it("/api/me возвращает имя загрузчика", async () => {
    const res = await api("/api/me", { token });
    expect(res.status).toBe(200);
    expect((await json(res)).uploader.name).toBe("Анна");
  });
});

describe("видео", () => {
  it("создаёт запись, нормализует теги и вычисляет ориентацию и разрешение", async () => {
    const res = await api("/api/videos", {
      method: "POST",
      token,
      json: videoPayload({
        title: "  Закат над морем ",
        tags: ["#Закат", "ночной_город", "  Море  ", "закат"],
        width: 2160,
        height: 3840,
      }),
    });
    expect(res.status).toBe(201);
    const { video } = await json(res);
    expect(video.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(video.title).toBe("Закат над морем");
    expect(video.tg_channel).toBe("my_archive");
    expect(video.tags).toEqual(["закат", "море", "ночной город"]);
    expect(video.orientation).toBe("vertical");
    expect(video.resolution_label).toBe("4K");
    expect(video.uploaded_by).toBe("Анна");
  });

  it("повтор с тем же id и постом — не ошибка (идемпотентность)", async () => {
    const id = crypto.randomUUID();
    const payload = videoPayload({ id });
    const first = await api("/api/videos", { method: "POST", token, json: payload });
    expect(first.status).toBe(201);
    const second = await api("/api/videos", { method: "POST", token, json: payload });
    expect(second.status).toBe(200);
    expect((await json(second)).existing).toBe(true);
  });

  it("тот же пост Telegram под другим id — 409", async () => {
    const payload = videoPayload();
    await api("/api/videos", { method: "POST", token, json: payload });
    const res = await api("/api/videos", { method: "POST", token, json: { ...payload, id: crypto.randomUUID() } });
    expect(res.status).toBe(409);
    expect((await json(res)).error.code).toBe("tg_post_exists");
  });

  it("проверяет входные данные", async () => {
    const cases: [Record<string, unknown>, RegExp][] = [
      [videoPayload({ title: "" }), /title/],
      [videoPayload({ tg_channel: "a b" }), /канал/],
      [videoPayload({ tg_message_id: -1 }), /tg_message_id/],
      [videoPayload({ width: "wide" }), /width/],
      [videoPayload({ preview_key: "../etc/passwd" }), /preview_key/],
      [videoPayload({ collections: [999999] }), /Коллекции не найдены/],
      [videoPayload({ file_hash: "xyz" }), /file_hash/],
    ];
    for (const [payload, message] of cases) {
      const res = await api("/api/videos", { method: "POST", token, json: payload });
      expect(res.status, JSON.stringify(payload)).toBe(400);
      expect((await json(res)).error.message).toMatch(message);
    }
  });

  it("PATCH меняет поля, теги и коллекции", async () => {
    const created = await json(
      await api("/api/videos", { method: "POST", token, json: videoPayload({ tags: ["старый"] }) }),
    );
    const col = await json(await api("/api/collections", { method: "POST", token, json: { name: "Для PATCH" } }));
    const res = await api(`/api/videos/${created.video.id}`, {
      method: "PATCH",
      token,
      json: { title: "Новое имя", description: "Описание", tags: ["Новый", "второй"], collections: [col.collection.id], width: 1000, height: 1000 },
    });
    expect(res.status).toBe(200);
    const { video } = await json(res);
    expect(video.title).toBe("Новое имя");
    expect(video.description).toBe("Описание");
    expect(video.tags).toEqual(["второй", "новый"]);
    expect(video.collections).toEqual([col.collection.id]);
    expect(video.orientation).toBe("square");
    expect(video.resolution_label).toBe("HD");
    expect(video.updated_at).toBeGreaterThanOrEqual(created.video.updated_at);
  });

  it("правки подписи без caption_synced помечают пост устаревшим", async () => {
    const { video } = await json(await api("/api/videos", { method: "POST", token, json: videoPayload({ tags: ["a1"] }) }));
    expect(video.caption_dirty).toBe(0);
    const patch = (body: Record<string, unknown>) =>
      api(`/api/videos/${video.id}`, { method: "PATCH", token, json: body }).then((r) => json(r));
    expect((await patch({ collections: [] })).video.caption_dirty).toBe(0);
    expect((await patch({ title: "С сайта" })).video.caption_dirty).toBe(1);
    expect((await patch({ title: "Из программы", caption_synced: true })).video.caption_dirty).toBe(0);
    const { tags } = await json(await api("/api/tags"));
    const tagId = tags.find((t: { name: string }) => t.name === "a1").id;
    await api(`/api/tags/${tagId}`, { method: "PATCH", token, json: { name: "a2" } });
    expect((await json(await api(`/api/videos/${video.id}`))).video.caption_dirty).toBe(1);
  });

  it("PATCH несуществующего видео — 404", async () => {
    const res = await api(`/api/videos/${crypto.randomUUID()}`, { method: "PATCH", token, json: { title: "x" } });
    expect(res.status).toBe(404);
  });

  it("GET /api/videos/:id — публично, без file_hash", async () => {
    const hash = "a".repeat(64);
    const { video } = await json(await api("/api/videos", { method: "POST", token, json: videoPayload({ file_hash: hash }) }));
    const res = await api(`/api/videos/${video.id}`);
    expect(res.status).toBe(200);
    const body = await json(res);
    expect(body.video.id).toBe(video.id);
    expect(body.video.file_hash).toBeUndefined();
  });

  it("check-hash находит дубликаты", async () => {
    const hash = "b".repeat(64);
    const none = await json(await api(`/api/videos/check-hash/${hash}`, { token }));
    expect(none.duplicate).toBe(false);
    await api("/api/videos", { method: "POST", token, json: videoPayload({ file_hash: hash, title: "Оригинал" }) });
    const found = await json(await api(`/api/videos/check-hash/${hash}`, { token }));
    expect(found.duplicate).toBe(true);
    expect(found.videos[0].title).toBe("Оригинал");
    expect((await api(`/api/videos/check-hash/${hash}`)).status).toBe(401);
    expect((await api("/api/videos/check-hash/zzz", { token })).status).toBe(400);
  });

  it("DELETE удаляет запись и файлы в R2", async () => {
    await env.PREVIEWS.put("previews/del-test.mp4", fakeMp4());
    await env.PREVIEWS.put("posters/del-test.jpg", fakeJpeg());
    const { video } = await json(
      await api("/api/videos", {
        method: "POST",
        token,
        json: videoPayload({ preview_key: "previews/del-test.mp4", poster_key: "posters/del-test.jpg" }),
      }),
    );
    const res = await api(`/api/videos/${video.id}`, { method: "DELETE", token });
    expect(res.status).toBe(200);
    expect((await json(res)).deleted.tg_message_id).toBe(video.tg_message_id);
    expect(await env.PREVIEWS.head("previews/del-test.mp4")).toBeNull();
    expect(await env.PREVIEWS.head("posters/del-test.jpg")).toBeNull();
    expect((await api(`/api/videos/${video.id}`)).status).toBe(404);
  });
});

describe("библиотека", () => {
  it("отдаёт все видео с тегами, ETag и 304", async () => {
    const { video } = await json(
      await api("/api/videos", { method: "POST", token, json: videoPayload({ title: "В библиотеке", tags: ["лес"] }) }),
    );
    const res = await api("/api/library");
    expect(res.status).toBe(200);
    const etag = res.headers.get("ETag");
    expect(etag).toMatch(/^"lib-\d+"$/);
    const lib = await json(res);
    const item = lib.videos.find((v: { id: string }) => v.id === video.id);
    expect(item.tags).toEqual(["лес"]);
    expect(item.file_hash).toBeUndefined();
    expect(lib.tags.find((t: { name: string }) => t.name === "лес").count).toBeGreaterThanOrEqual(1);

    const notModified = await api("/api/library", { headers: { "If-None-Match": etag! } });
    expect(notModified.status).toBe(304);
  });

  it("второй запрос берётся из снимка в R2, после изменения ревизия растёт", async () => {
    const first = await api("/api/library");
    const etag1 = first.headers.get("ETag");
    await first.text();
    // снимок сохраняется в waitUntil — дождёмся его появления
    const rev = etag1!.replace(/\D/g, "");
    await vi.waitFor(async () => expect(await env.PREVIEWS.head(`_cache/library-${rev}.json`)).not.toBeNull());
    const second = await api("/api/library");
    expect(second.headers.get("X-Library-Cache")).toBe("hit");
    await second.text();

    await api("/api/videos", { method: "POST", token, json: videoPayload() });
    const third = await api("/api/library");
    expect(third.headers.get("ETag")).not.toBe(etag1);
    expect(third.headers.get("X-Library-Cache")).toBe("miss");
    await third.text();
  });

  it("удаление видео тоже меняет ETag", async () => {
    const { video } = await json(await api("/api/videos", { method: "POST", token, json: videoPayload() }));
    const before = (await api("/api/library")).headers.get("ETag");
    await api(`/api/videos/${video.id}`, { method: "DELETE", token });
    const after = (await api("/api/library")).headers.get("ETag");
    expect(after).not.toBe(before);
  });
});

describe("поиск (FTS5)", () => {
  it("ищет по префиксу в названии и тегах", async () => {
    const { video } = await json(
      await api("/api/videos", {
        method: "POST",
        token,
        json: videoPayload({ title: "Горный водопад", tags: ["весна", "природа"] }),
      }),
    );
    for (const q of ["водопад", "водо", "Горн", "весна природа"]) {
      const res = await json(await api(`/api/search?q=${encodeURIComponent(q)}`));
      expect(res.ids, q).toContain(video.id);
    }
    const none = await json(await api(`/api/search?q=${encodeURIComponent("водопад зима")}`));
    expect(none.ids).not.toContain(video.id);
    expect((await json(await api("/api/search?q="))).ids).toEqual([]);
  });

  it("поиск видит изменения тегов", async () => {
    const { video } = await json(await api("/api/videos", { method: "POST", token, json: videoPayload({ tags: ["кактус"] }) }));
    await api(`/api/videos/${video.id}`, { method: "PATCH", token, json: { tags: ["пустыня"] } });
    expect((await json(await api("/api/search?q=кактус"))).ids).not.toContain(video.id);
    expect((await json(await api("/api/search?q=пустыня"))).ids).toContain(video.id);
  });
});

describe("теги", () => {
  async function tagId(name: string): Promise<number> {
    const { tags } = await json(await api("/api/tags"));
    return tags.find((t: { name: string }) => t.name === name).id;
  }

  it("переименование обновляет видео и возвращает затронутые id", async () => {
    const { video } = await json(await api("/api/videos", { method: "POST", token, json: videoPayload({ tags: ["котик"] }) }));
    const id = await tagId("котик");
    const res = await api(`/api/tags/${id}`, { method: "PATCH", token, json: { name: "Кошка" } });
    expect(res.status).toBe(200);
    const body = await json(res);
    expect(body.tag.name).toBe("кошка");
    expect(body.affected_video_ids).toEqual([video.id]);
    expect((await json(await api(`/api/videos/${video.id}`))).video.tags).toEqual(["кошка"]);
    expect((await json(await api("/api/search?q=кошка"))).ids).toContain(video.id);
  });

  it("переименование в существующий тег — 409", async () => {
    await api("/api/videos", { method: "POST", token, json: videoPayload({ tags: ["дрон", "квадрокоптер"] }) });
    const res = await api(`/api/tags/${await tagId("квадрокоптер")}`, { method: "PATCH", token, json: { name: "дрон" } });
    expect(res.status).toBe(409);
    expect((await json(res)).error.existing_id).toBe(await tagId("дрон"));
  });

  it("слияние тегов", async () => {
    const a = await json(await api("/api/videos", { method: "POST", token, json: videoPayload({ tags: ["авто", "машина"] }) }));
    const b = await json(await api("/api/videos", { method: "POST", token, json: videoPayload({ tags: ["автомобиль"] }) }));
    const target = await tagId("машина");
    const res = await api("/api/tags/merge", {
      method: "POST",
      token,
      json: { source_ids: [await tagId("авто"), await tagId("автомобиль")], target_id: target },
    });
    expect(res.status).toBe(200);
    const body = await json(res);
    expect(body.affected_video_ids.sort()).toEqual([a.video.id, b.video.id].sort());
    expect((await json(await api(`/api/videos/${a.video.id}`))).video.tags).toEqual(["машина"]);
    expect((await json(await api(`/api/videos/${b.video.id}`))).video.tags).toEqual(["машина"]);
    const { tags } = await json(await api("/api/tags"));
    expect(tags.map((t: { name: string }) => t.name)).not.toContain("авто");
  });

  it("удаление тега и неиспользуемых тегов", async () => {
    const { video } = await json(await api("/api/videos", { method: "POST", token, json: videoPayload({ tags: ["удалить-меня", "оставить"] }) }));
    const res = await api(`/api/tags/${await tagId("удалить-меня")}`, { method: "DELETE", token });
    expect((await json(res)).affected_video_ids).toEqual([video.id]);
    expect((await json(await api(`/api/videos/${video.id}`))).video.tags).toEqual(["оставить"]);

    await json(await api("/api/tags", { method: "POST", token, json: { name: "#Пустой_тег" } }));
    const unused = await json(await api("/api/tags/unused", { method: "DELETE", token }));
    expect(unused.deleted.map((t: { name: string }) => t.name)).toContain("пустой тег");
  });

  it("запись тегов без токена запрещена", async () => {
    expect((await api("/api/tags", { method: "POST", json: { name: "x" } })).status).toBe(401);
  });
});

describe("коллекции", () => {
  it("CRUD, порядок и массовое добавление", async () => {
    const a = await json(await api("/api/collections", { method: "POST", token, json: { name: "Природа", emoji: "🌲" } }));
    const b = await json(await api("/api/collections", { method: "POST", token, json: { name: "Город" } }));
    expect(a.collection.emoji).toBe("🌲");
    expect(b.collection.sort_order).toBeGreaterThan(a.collection.sort_order);

    const dup = await api("/api/collections", { method: "POST", token, json: { name: "Природа" } });
    expect(dup.status).toBe(409);

    const order = await json(
      await api("/api/collections/order", { method: "PUT", token, json: { ids: [b.collection.id, a.collection.id] } }),
    );
    const names = order.collections.map((c: { name: string }) => c.name);
    expect(names.indexOf("Город")).toBeLessThan(names.indexOf("Природа"));

    const renamed = await json(
      await api(`/api/collections/${a.collection.id}`, { method: "PATCH", token, json: { name: "Природа и лес" } }),
    );
    expect(renamed.collection.name).toBe("Природа и лес");
    expect(renamed.collection.emoji).toBe("🌲");

    const v1 = await json(await api("/api/videos", { method: "POST", token, json: videoPayload() }));
    const v2 = await json(await api("/api/videos", { method: "POST", token, json: videoPayload() }));
    const added = await json(
      await api(`/api/collections/${a.collection.id}/videos`, {
        method: "POST",
        token,
        json: { add: [v1.video.id, v2.video.id] },
      }),
    );
    expect(added.count).toBe(2);
    const removed = await json(
      await api(`/api/collections/${a.collection.id}/videos`, { method: "POST", token, json: { remove: [v1.video.id] } }),
    );
    expect(removed.count).toBe(1);

    const { collections } = await json(await api("/api/collections"));
    expect(collections.find((c: { id: number }) => c.id === a.collection.id).count).toBe(1);

    expect((await api(`/api/collections/${a.collection.id}`, { method: "DELETE", token })).status).toBe(200);
    expect((await json(await api(`/api/videos/${v2.video.id}`))).video.collections).toEqual([]);
  });
});

describe("медиа (R2)", () => {
  it("загрузка и отдача постера", async () => {
    const bytes = fakeJpeg(3000);
    const put = await api("/api/media/posters/p1-abc.jpg", { method: "PUT", token, body: bytes });
    expect(put.status).toBe(201);
    expect((await json(put)).url).toBe("/media/posters/p1-abc.jpg");

    const get = await api("/media/posters/p1-abc.jpg");
    expect(get.status).toBe(200);
    expect(get.headers.get("Content-Type")).toBe("image/jpeg");
    expect(get.headers.get("Cache-Control")).toContain("max-age=31536000");
    expect(new Uint8Array(await get.arrayBuffer())).toEqual(bytes);

    const etag = get.headers.get("ETag")!;
    const cached = await api("/media/posters/p1-abc.jpg", { headers: { "If-None-Match": etag } });
    expect(cached.status).toBe(304);
  });

  it("Range-запросы для превью", async () => {
    const bytes = fakeMp4(10_000);
    await api("/api/media/previews/r1.mp4", { method: "PUT", token, body: bytes });

    const part = await api("/media/previews/r1.mp4", { headers: { Range: "bytes=100-199" } });
    expect(part.status).toBe(206);
    expect(part.headers.get("Content-Range")).toBe("bytes 100-199/10000");
    expect(new Uint8Array(await part.arrayBuffer())).toEqual(bytes.slice(100, 200));

    const open = await api("/media/previews/r1.mp4", { headers: { Range: "bytes=9990-" } });
    expect(open.status).toBe(206);
    expect((await open.arrayBuffer()).byteLength).toBe(10);

    const suffix = await api("/media/previews/r1.mp4", { headers: { Range: "bytes=-5" } });
    expect(new Uint8Array(await suffix.arrayBuffer())).toEqual(bytes.slice(-5));

    const bad = await api("/media/previews/r1.mp4", { headers: { Range: "bytes=20000-" } });
    expect(bad.status).toBe(416);
    expect(bad.headers.get("Content-Range")).toBe("bytes */10000");
  });

  it("отклоняет неправильные ключи и содержимое", async () => {
    expect((await api("/api/media/previews/x.mp4", { method: "PUT", token, body: fakeJpeg() })).status).toBe(400);
    expect((await api("/api/media/other/x.jpg", { method: "PUT", token, body: fakeJpeg() })).status).toBe(400);
    expect((await api("/api/media/_cache/library-1.json", { method: "PUT", token, body: "{}" })).status).toBe(400);
    expect((await api("/api/media/posters/x.jpg", { method: "PUT", body: fakeJpeg() })).status).toBe(401);
    expect((await api("/media/_cache/library-1.json")).status).toBe(404);
    expect((await api("/media/posters/missing.jpg")).status).toBe(404);
  });

  it("слишком большой файл — 413", async () => {
    const big = fakeJpeg(Number(env.MEDIA_MAX_BYTES) + 10);
    expect((await api("/api/media/posters/big.jpg", { method: "PUT", token, body: big })).status).toBe(413);
  });

  it("замена постера через PATCH удаляет старый файл; занятый файл удалить нельзя", async () => {
    await api("/api/media/posters/old-1.jpg", { method: "PUT", token, body: fakeJpeg() });
    await api("/api/media/posters/new-1.jpg", { method: "PUT", token, body: fakeJpeg() });
    const { video } = await json(
      await api("/api/videos", { method: "POST", token, json: videoPayload({ poster_key: "posters/old-1.jpg" }) }),
    );
    expect((await api("/api/media/posters/old-1.jpg", { method: "DELETE", token })).status).toBe(409);
    await api(`/api/videos/${video.id}`, { method: "PATCH", token, json: { poster_key: "posters/new-1.jpg" } });
    await vi.waitFor(async () => expect(await env.PREVIEWS.head("posters/old-1.jpg")).toBeNull());
    expect(await env.PREVIEWS.head("posters/new-1.jpg")).not.toBeNull();
  });
});

describe("ИИ-теги (Workers AI)", () => {
  const body = { images: ["AAAA"], prompt: "Опиши кадры и верни JSON" };

  it("возвращает текст и разобранный JSON", async () => {
    const run = vi.spyOn(env.AI, "run").mockResolvedValue({
      response: 'Вот ответ:\n```json\n{"title":"Закат","description":"Солнце садится.","tags":["закат","море"]}\n```',
    } as never);
    const res = await api("/api/ai/tag", { method: "POST", token, json: body });
    expect(res.status).toBe(200);
    const out = await json(res);
    expect(out.provider).toBe("workers-ai");
    expect(out.model).toBe(env.AI_MODEL);
    expect(out.json).toEqual({ title: "Закат", description: "Солнце садится.", tags: ["закат", "море"] });
    const [model, input] = run.mock.calls[0]!;
    expect(model).toBe(env.AI_MODEL);
    const content = (input as { messages: { content: { type: string; image_url?: { url: string } }[] }[] }).messages.at(-1)!.content;
    expect(content[1]!.image_url!.url).toBe("data:image/jpeg;base64,AAAA");
  });

  it("невалидный JSON от модели — json: null", async () => {
    vi.spyOn(env.AI, "run").mockResolvedValue({ response: "не знаю" } as never);
    const out = await json(await api("/api/ai/tag", { method: "POST", token, json: body }));
    expect(out.json).toBeNull();
    expect(out.text).toBe("не знаю");
  });

  it("исчерпан лимит — 429 ai_quota", async () => {
    vi.spyOn(env.AI, "run").mockRejectedValue(new Error("3036: you have used up your daily free allocation of 10,000 neurons"));
    const res = await api("/api/ai/tag", { method: "POST", token, json: body });
    expect(res.status).toBe(429);
    expect((await json(res)).error.code).toBe("ai_quota");
  });

  it("лицензия Llama принимается автоматически", async () => {
    const run = vi
      .spyOn(env.AI, "run")
      .mockRejectedValueOnce(new Error("5016: Prior to using this model, you must submit the prompt 'agree'"))
      .mockResolvedValueOnce({ response: "ok" } as never)
      .mockResolvedValueOnce({ response: '{"title":"a","tags":[]}' } as never);
    const res = await api("/api/ai/tag", { method: "POST", token, json: { ...body, model: "@cf/meta/llama-3.2-11b-vision-instruct" } });
    expect(res.status).toBe(200);
    expect(run.mock.calls[1]![1]).toEqual({ prompt: "agree" });
  });

  it("проверяет вход", async () => {
    expect((await api("/api/ai/tag", { method: "POST", token, json: { prompt: "x" } })).status).toBe(400);
    expect((await api("/api/ai/tag", { method: "POST", token, json: { ...body, model: "gpt-4" } })).status).toBe(400);
    expect((await api("/api/ai/tag", { method: "POST", json: body })).status).toBe(401);
  });
});
