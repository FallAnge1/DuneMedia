import MiniSearch from "minisearch";
import type { Video } from "./api";

/**
 * Мгновенный поиск на клиенте: название, описание, теги.
 * - префиксы: «водо» находит «водопад»;
 * - опечатки: одна-две буквы в длинных словах;
 * - простая русская морфология: окончания отбрасываются («закаты» → «закат»).
 */

// Окончания от длинных к коротким. Это не полноценный стеммер, но покрывает падежи и множественное число.
const ENDINGS = [
  "иями", "ями", "ами", "ией", "иях", "иям", "ией", "ого", "его", "ому", "ему", "ыми", "ими",
  "ая", "яя", "ое", "ее", "ые", "ие", "ый", "ий", "ой", "ей", "ую", "юю", "ом", "ем", "ам", "ям",
  "ах", "ях", "ов", "ев", "ья", "ье", "ью", "ия", "ие", "ию", "ии",
  "а", "я", "о", "е", "ы", "и", "у", "ю", "ь", "й",
];

export function stem(word: string): string {
  if (!/[а-я]/.test(word) || word.length <= 4) return word;
  for (const end of ENDINGS) {
    if (word.endsWith(end) && word.length - end.length >= 3) return word.slice(0, -end.length);
  }
  return word;
}

const normalize = (term: string) => term.toLowerCase().replace(/ё/g, "е");

export function buildSearchIndex(videos: Video[]): MiniSearch<Video> {
  const index = new MiniSearch<Video>({
    fields: ["title", "description", "tagText"],
    storeFields: [],
    extractField: (doc, field) => {
      if (field === "tagText") return doc.tags.join(" ");
      return (doc as unknown as Record<string, unknown>)[field] as string;
    },
    // В индекс кладутся и слово целиком, и его основа.
    processTerm: (term) => {
      const t = normalize(term);
      if (!t) return null;
      const s = stem(t);
      return s === t ? t : [t, s];
    },
    searchOptions: {
      boost: { title: 3, tagText: 2 },
      prefix: true,
      fuzzy: (term) => (term.length > 4 ? 0.2 : false),
      combineWith: "AND",
      processTerm: (term) => {
        const t = normalize(term);
        return t ? stem(t) : null;
      },
    },
  });
  index.addAll(videos);
  return index;
}

/**
 * Каждое слово запроса ищется отдельно, все должны совпасть («И»):
 * - если у слова отброшено окончание («горах» → «гор»), основа ищется точно —
 *   иначе «гор» по префиксу нашла бы «город»;
 * - иначе слово считается недописанным и ищется по префиксу («водо» → «водопад»).
 */
export function searchIds(index: MiniSearch<Video>, query: string): Set<string> {
  const words = query
    .split(/[^\p{L}\p{N}]+/u)
    .map(normalize)
    .filter(Boolean);
  if (words.length === 0) return new Set();
  const queries = words.map((word) => {
    const base = stem(word);
    return {
      queries: [base],
      prefix: base === word,
      fuzzy: base.length > 4 ? 0.2 : false,
      processTerm: (t: string) => t,
    };
  });
  return new Set(index.search({ combineWith: "AND", queries }).map((r) => r.id as string));
}
