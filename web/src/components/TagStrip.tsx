import { useMemo } from "react";
import { IconClose } from "./Icons";

interface Props {
  selected: string[];
  counts: Map<string, number>;
  onToggle: (tag: string) => void;
}

const LIMIT = 24;

/** Полоса тегов-подсказок под шапкой (как «идеи» в Pinterest): популярные теги текущей выдачи. */
export function TagStrip({ selected, counts, onToggle }: Props) {
  const tags = useMemo(
    () =>
      [...counts.entries()]
        .filter(([t]) => !selected.includes(t))
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "ru"))
        .slice(0, LIMIT)
        .map(([t]) => t),
    [counts, selected],
  );
  if (selected.length === 0 && tags.length === 0) return null;
  return (
    <div className="tag-strip" role="list" aria-label="Теги">
      {selected.map((t) => (
        <button key={t} type="button" className="strip-chip is-on" onClick={() => onToggle(t)} aria-label={`Убрать тег ${t}`}>
          {t} <IconClose size={12} />
        </button>
      ))}
      {tags.map((t, i) => (
        <button key={t} type="button" className={`strip-chip tone-${i % 6}`} onClick={() => onToggle(t)}>
          {t}
        </button>
      ))}
    </div>
  );
}
