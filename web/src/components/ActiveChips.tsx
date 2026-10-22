import { DURATIONS, ORIENTATIONS, type Filters } from "../lib/filters";
import { IconClose } from "./Icons";

interface Props {
  filters: Filters;
  found: number;
  onRemoveTag: (tag: string) => void;
  onRemove: (group: "orientation" | "resolution" | "duration", value: string) => void;
  onClearQuery: () => void;
  onReset: () => void;
}

/** Активные фильтры чипсами над сеткой и счётчик найденного. */
export function ActiveChips({ filters: f, found, ...p }: Props) {
  const chips: { key: string; label: string; remove: () => void }[] = [];
  if (f.q) chips.push({ key: "q", label: `«${f.q}»`, remove: p.onClearQuery });
  for (const t of f.tags) chips.push({ key: `t:${t}`, label: `#${t}`, remove: () => p.onRemoveTag(t) });
  for (const o of f.orientation) {
    chips.push({ key: `o:${o}`, label: ORIENTATIONS.find((x) => x.value === o)!.label, remove: () => p.onRemove("orientation", o) });
  }
  for (const r of f.resolution) chips.push({ key: `r:${r}`, label: r, remove: () => p.onRemove("resolution", r) });
  for (const d of f.duration) {
    chips.push({ key: `d:${d}`, label: DURATIONS.find((x) => x.value === d)!.label, remove: () => p.onRemove("duration", d) });
  }

  return (
    <div className="chips-bar">
      <span className="found" aria-live="polite">
        Найдено: <b>{found.toLocaleString("ru-RU")}</b>
      </span>
      {chips.map((c) => (
        <button key={c.key} type="button" className="chip" onClick={c.remove} aria-label={`Убрать фильтр ${c.label}`}>
          {c.label}
          <IconClose size={12} />
        </button>
      ))}
      {chips.length > 1 && (
        <button type="button" className="link-btn" onClick={p.onReset}>
          Сбросить всё
        </button>
      )}
    </div>
  );
}
