/** Поиск досок по названию на странице «Доски». */

const normalizeName = (s: string) => s.toLowerCase().replace(/ё/g, "е");

/** Подходит ли название доски к запросу: каждое слово запроса — начало какого-то слова названия. */
export function boardMatches(name: string, query: string): boolean {
  const words = normalizeName(query).split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  if (words.length === 0) return true;
  const nameWords = normalizeName(name).split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  return words.every((w) => nameWords.some((n) => n.startsWith(w)));
}
