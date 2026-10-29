import type { MediaType, Orientation, ResolutionLabel, Video } from "./api";

export type DurationBucket = "lt10" | "10to30" | "30to60" | "gt60";
export type SortKey = "new" | "old" | "long" | "short" | "size" | "name";
/** Вкладка: все, избранное или id коллекции. */
export type CollectionTab = "all" | "fav" | number;

/** Группы фильтров с флажками (теги и поиск устроены иначе). */
export type FilterGroup = "media" | "orientation" | "resolution" | "duration";

export interface Filters {
  q: string;
  tags: string[];
  media: MediaType[];
  orientation: Orientation[];
  resolution: ResolutionLabel[];
  duration: DurationBucket[];
  tab: CollectionTab;
  sort: SortKey;
}

export const EMPTY_FILTERS: Filters = {
  q: "",
  tags: [],
  media: [],
  orientation: [],
  resolution: [],
  duration: [],
  tab: "all",
  sort: "new",
};

export const MEDIA_TYPES: { value: MediaType; label: string }[] = [
  { value: "video", label: "Видео" },
  { value: "photo", label: "Фото" },
];

export const ORIENTATIONS: { value: Orientation; label: string }[] = [
  { value: "horizontal", label: "Горизонтальные" },
  { value: "vertical", label: "Вертикальные" },
  { value: "square", label: "Квадратные" },
];

export const RESOLUTIONS: ResolutionLabel[] = ["SD", "HD", "FullHD", "2K", "4K", "8K"];

export const DURATIONS: { value: DurationBucket; label: string; test: (s: number) => boolean }[] = [
  { value: "lt10", label: "до 10 с", test: (s) => s < 10 },
  { value: "10to30", label: "10–30 с", test: (s) => s >= 10 && s < 30 },
  { value: "30to60", label: "30 с – 1 мин", test: (s) => s >= 30 && s < 60 },
  { value: "gt60", label: "больше 1 мин", test: (s) => s >= 60 },
];

export const SORTS: { value: SortKey; label: string }[] = [
  { value: "new", label: "Сначала новые" },
  { value: "old", label: "Сначала старые" },
  { value: "long", label: "Сначала длинные" },
  { value: "short", label: "Сначала короткие" },
  { value: "size", label: "По размеру файла" },
  { value: "name", label: "По названию" },
];

// ---- URL ----

const list = (params: URLSearchParams, key: string) =>
  (params.get(key) ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

export function filtersFromUrl(search: string): Filters {
  const p = new URLSearchParams(search);
  const tab = p.get("c");
  const sort = p.get("sort") as SortKey | null;
  return {
    q: p.get("q") ?? "",
    tags: p.getAll("tag").filter(Boolean),
    media: list(p, "m").filter((x): x is MediaType => MEDIA_TYPES.some((m) => m.value === x)),
    orientation: list(p, "o").filter((x): x is Orientation => ORIENTATIONS.some((o) => o.value === x)),
    resolution: list(p, "r").filter((x): x is ResolutionLabel => RESOLUTIONS.includes(x as ResolutionLabel)),
    duration: list(p, "d").filter((x): x is DurationBucket => DURATIONS.some((d) => d.value === x)),
    tab: tab === "fav" ? "fav" : tab && /^\d+$/.test(tab) ? Number(tab) : "all",
    sort: sort && SORTS.some((s) => s.value === sort) ? sort : "new",
  };
}

/** Страница: лента видео или список досок (коллекций). */
export type Page = "home" | "boards";

export const pageFromUrl = (search: string): Page => (new URLSearchParams(search).get("p") === "boards" ? "boards" : "home");

/** Строит строку запроса. Видео, открытое в просмотре, хранится в параметре v, страница досок — p=boards. */
export function filtersToUrl(f: Filters, openVideoId: string | null, page: Page = "home"): string {
  const p = new URLSearchParams();
  if (page === "boards") p.set("p", "boards");
  if (f.q) p.set("q", f.q);
  if (f.tab !== "all") p.set("c", String(f.tab));
  // Теги могут содержать запятые и пробелы, поэтому каждый — отдельным параметром.
  for (const tag of f.tags) p.append("tag", tag);
  if (f.media.length) p.set("m", f.media.join(","));
  if (f.orientation.length) p.set("o", f.orientation.join(","));
  if (f.resolution.length) p.set("r", f.resolution.join(","));
  if (f.duration.length) p.set("d", f.duration.join(","));
  if (f.sort !== "new") p.set("sort", f.sort);
  if (openVideoId) p.set("v", openVideoId);
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const hasActiveFilters = (f: Filters) =>
  !!f.q || f.tags.length > 0 || f.media.length > 0 || f.orientation.length > 0 || f.resolution.length > 0 || f.duration.length > 0;

// ---- Применение ----

/** Фильтры без тегов: для подсчёта тегов-«фасетов» по текущей выдаче. */
export function applyFilters(
  videos: Video[],
  f: Filters,
  ctx: { searchIds: Set<string> | null; favorites: Set<string> },
): Video[] {
  const tags = f.tags;
  return videos.filter((v) => {
    if (f.tab === "fav" && !ctx.favorites.has(v.id)) return false;
    if (typeof f.tab === "number" && !v.collections.includes(f.tab)) return false;
    if (ctx.searchIds && !ctx.searchIds.has(v.id)) return false;
    if (f.media.length && !f.media.includes(v.media_type ?? "video")) return false;
    if (f.orientation.length && (!v.orientation || !f.orientation.includes(v.orientation))) return false;
    if (f.resolution.length && (!v.resolution_label || !f.resolution.includes(v.resolution_label))) return false;
    if (f.duration.length) {
      if (v.media_type === "photo") return false; // у фото нет длительности
      const d = v.duration ?? 0;
      if (!f.duration.some((b) => DURATIONS.find((x) => x.value === b)!.test(d))) return false;
    }
    // Теги — логика «И»: у видео должны быть все выбранные.
    for (const t of tags) if (!v.tags.includes(t)) return false;
    return true;
  });
}

const collator = new Intl.Collator("ru", { sensitivity: "base", numeric: true });

export function sortVideos(videos: Video[], sort: SortKey): Video[] {
  const out = videos.slice();
  const num = (x: number | null) => x ?? -1;
  switch (sort) {
    case "new":
      return out.sort((a, b) => b.created_at - a.created_at);
    case "old":
      return out.sort((a, b) => a.created_at - b.created_at);
    case "long":
      return out.sort((a, b) => num(b.duration) - num(a.duration));
    case "short":
      return out.sort((a, b) => (a.duration ?? Infinity) - (b.duration ?? Infinity));
    case "size":
      return out.sort((a, b) => num(b.file_size) - num(a.file_size));
    case "name":
      return out.sort((a, b) => collator.compare(a.title, b.title));
  }
}

/** Количество видео по каждому тегу в наборе. */
export function tagCounts(videos: Video[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const v of videos) for (const t of v.tags) counts.set(t, (counts.get(t) ?? 0) + 1);
  return counts;
}
