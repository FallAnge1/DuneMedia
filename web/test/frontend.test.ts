import { describe, expect, it } from "vitest";
import type { Video } from "../src/lib/api";
import { applyFilters, EMPTY_FILTERS, filtersFromUrl, filtersToUrl, pageFromUrl, sortVideos, type Filters } from "../src/lib/filters";
import { buildSearchIndex, searchIds, stem } from "../src/lib/search";

let n = 0;
function video(over: Partial<Video>): Video {
  n++;
  return {
    id: `id-${n}`,
    tg_channel: "c",
    tg_message_id: n,
    title: `Видео ${n}`,
    description: null,
    file_name: null,
    file_size: n * 1000,
    duration: 10,
    width: 1920,
    height: 1080,
    orientation: "horizontal",
    resolution_label: "FullHD",
    fps: 25,
    codec: "h264",
    preview_key: null,
    poster_key: null,
    uploaded_by: null,
    caption_dirty: 0,
    created_at: n,
    updated_at: n,
    tags: [],
    collections: [],
    ...over,
  };
}

const videos = [
  video({ title: "Закат над морем", tags: ["закат", "море"], duration: 5, collections: [1] }),
  video({ title: "Ночной город", tags: ["город", "ночь"], duration: 45, orientation: "vertical", width: 1080, height: 1920 }),
  video({ title: "Водопад в горах", description: "Съёмка с дрона", tags: ["горы", "вода", "дрон"], duration: 120, resolution_label: "4K" }),
  video({ title: "Закаты у озера", tags: ["закат", "вода"], duration: 20 }),
];

const ctx = { searchIds: null, favorites: new Set<string>() };
const titles = (list: Video[]) => list.map((v) => v.title);

describe("фильтры", () => {
  it("теги — логика И", () => {
    expect(titles(applyFilters(videos, { ...EMPTY_FILTERS, tags: ["закат"] }, ctx))).toHaveLength(2);
    expect(titles(applyFilters(videos, { ...EMPTY_FILTERS, tags: ["закат", "вода"] }, ctx))).toEqual(["Закаты у озера"]);
  });

  it("ориентация, разрешение, длительность, коллекция, избранное", () => {
    expect(titles(applyFilters(videos, { ...EMPTY_FILTERS, orientation: ["vertical"] }, ctx))).toEqual(["Ночной город"]);
    expect(titles(applyFilters(videos, { ...EMPTY_FILTERS, resolution: ["4K"] }, ctx))).toEqual(["Водопад в горах"]);
    expect(titles(applyFilters(videos, { ...EMPTY_FILTERS, duration: ["lt10", "gt60"] }, ctx))).toHaveLength(2);
    expect(titles(applyFilters(videos, { ...EMPTY_FILTERS, tab: 1 }, ctx))).toEqual(["Закат над морем"]);
    const fav = { ...ctx, favorites: new Set([videos[1]!.id]) };
    expect(titles(applyFilters(videos, { ...EMPTY_FILTERS, tab: "fav" }, fav))).toEqual(["Ночной город"]);
  });

  it("сортировка", () => {
    expect(sortVideos(videos, "long")[0]!.title).toBe("Водопад в горах");
    expect(sortVideos(videos, "short")[0]!.title).toBe("Закат над морем");
    expect(sortVideos(videos, "name").map((v) => v.title)[0]).toBe("Водопад в горах");
    expect(sortVideos(videos, "new")[0]!.title).toBe("Закаты у озера");
  });

  it("состояние фильтров переживает URL", () => {
    const f: Filters = {
      q: "закат",
      tags: ["крупный план", "a,b"],
      orientation: ["vertical", "square"],
      resolution: ["4K"],
      duration: ["10to30"],
      tab: 3,
      sort: "long",
    };
    const url = filtersToUrl(f, "vid-1");
    expect(filtersFromUrl(url)).toEqual(f);
    expect(new URLSearchParams(url).get("v")).toBe("vid-1");
    expect(filtersToUrl(EMPTY_FILTERS, null)).toBe("");
    expect(filtersFromUrl("?o=bogus&sort=bad&c=fav").orientation).toEqual([]);
    expect(pageFromUrl(filtersToUrl(EMPTY_FILTERS, null, "boards"))).toBe("boards");
    expect(pageFromUrl("?c=3")).toBe("home");
  });
});

describe("поиск", () => {
  const index = buildSearchIndex(videos);
  const find = (q: string) => [...searchIds(index, q)].map((id) => videos.find((v) => v.id === id)!.title).sort();

  it("по префиксу", () => {
    expect(find("водо")).toEqual(["Водопад в горах"]);
  });

  it("по тегам и описанию", () => {
    expect(find("дрон")).toEqual(["Водопад в горах"]);
    expect(find("съёмка")).toEqual(["Водопад в горах"]);
  });

  it("морфология: формы слова", () => {
    expect(find("закаты")).toEqual(["Закат над морем", "Закаты у озера"]);
    expect(find("закатов")).toEqual(["Закат над морем", "Закаты у озера"]);
    expect(find("горах")).toEqual(["Водопад в горах"]);
    expect(find("ночного")).toEqual(["Ночной город"]);
  });

  it("опечатки в длинных словах", () => {
    expect(find("вадопад")).toEqual(["Водопад в горах"]);
  });

  it("несколько слов — все должны найтись", () => {
    expect(find("закат море")).toEqual(["Закат над морем"]);
  });

  it("stem", () => {
    expect(stem("закаты")).toBe("закат");
    expect(stem("дождь")).toBe("дожд");
    expect(stem("лес")).toBe("лес");
  });
});
