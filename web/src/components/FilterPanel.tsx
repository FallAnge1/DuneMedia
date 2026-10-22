import { useMemo, useState } from "react";
import type { Orientation, ResolutionLabel } from "../lib/api";
import { DURATIONS, ORIENTATIONS, RESOLUTIONS, SORTS, type DurationBucket, type Filters, type SortKey } from "../lib/filters";
import { IconClose, OrientationIcon } from "./Icons";

interface Props {
  open: boolean;
  onClose: () => void;
  filters: Filters;
  /** Теги со счётчиками по текущей выдаче. */
  tagCounts: Map<string, number>;
  /** Сколько видео в выдаче по каждому значению — чтобы показать рядом с вариантом. */
  facetCounts: {
    orientation: Map<string, number>;
    resolution: Map<string, number>;
    duration: Map<string, number>;
  };
  onToggleTag: (tag: string) => void;
  onToggle: (group: "orientation" | "resolution" | "duration", value: string) => void;
  onReset: () => void;
  hasActive: boolean;
  onSort: (sort: SortKey) => void;
  tileSize: number;
  onTileSize: (n: number) => void;
  found: number;
}

const TAG_LIMIT = 40;

export function FilterPanel(p: Props) {
  const [tagQuery, setTagQuery] = useState("");
  const [showAll, setShowAll] = useState(false);

  const tags = useMemo(() => {
    const q = tagQuery.trim().toLowerCase().replace(/^#/, "");
    const entries = [...p.tagCounts.entries()].filter(([name]) => !q || name.includes(q));
    // Выбранные теги всегда вверху, даже если их нет в выдаче.
    for (const t of p.filters.tags) if (!p.tagCounts.has(t) && (!q || t.includes(q))) entries.push([t, 0]);
    entries.sort((a, b) => {
      const sa = p.filters.tags.includes(a[0]) ? 1 : 0;
      const sb = p.filters.tags.includes(b[0]) ? 1 : 0;
      return sb - sa || b[1] - a[1] || a[0].localeCompare(b[0], "ru");
    });
    return entries;
  }, [p.tagCounts, p.filters.tags, tagQuery]);

  const shownTags = showAll || tagQuery ? tags : tags.slice(0, TAG_LIMIT);

  return (
    <>
      <div className={`filters-backdrop${p.open ? " is-open" : ""}`} onClick={p.onClose} aria-hidden />
      <aside className={`filters${p.open ? " is-open" : ""}`} aria-label="Фильтры">
        <div className="filters-head">
          <h2>Фильтры</h2>
          <button type="button" className="icon-btn filters-close" onClick={p.onClose} aria-label="Закрыть фильтры">
            <IconClose />
          </button>
        </div>

        <section className="filter-group">
          <h3>Сортировка</h3>
          <select className="select select-block" value={p.filters.sort} onChange={(e) => p.onSort(e.target.value as SortKey)} aria-label="Сортировка">
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          <label className="tile-slider">
            <span className="small muted">Размер плиток</span>
            <input type="range" min={140} max={480} step={10} value={p.tileSize} onChange={(e) => p.onTileSize(Number(e.target.value))} />
          </label>
        </section>

        <section className="filter-group">
          <h3>Теги</h3>
          <input
            className="input input-sm"
            type="search"
            placeholder="Найти тег"
            value={tagQuery}
            onChange={(e) => setTagQuery(e.target.value)}
            aria-label="Найти тег"
          />
          <div className="tag-cloud">
            {shownTags.map(([name, count]) => {
              const on = p.filters.tags.includes(name);
              return (
                <button
                  key={name}
                  type="button"
                  className={`tag-chip${on ? " is-on" : ""}`}
                  onClick={() => p.onToggleTag(name)}
                  aria-pressed={on}
                >
                  #{name} <span>{count}</span>
                </button>
              );
            })}
            {tags.length === 0 && <p className="muted small">Тегов нет</p>}
          </div>
          {!tagQuery && tags.length > TAG_LIMIT && (
            <button type="button" className="link-btn" onClick={() => setShowAll((s) => !s)}>
              {showAll ? "Свернуть" : `Показать все (${tags.length})`}
            </button>
          )}
          {p.filters.tags.length > 1 && <p className="muted small">Показываются видео со всеми выбранными тегами</p>}
        </section>

        <section className="filter-group">
          <h3>Ориентация</h3>
          {ORIENTATIONS.map((o) => (
            <Check
              key={o.value}
              checked={p.filters.orientation.includes(o.value)}
              onChange={() => p.onToggle("orientation", o.value)}
              count={p.facetCounts.orientation.get(o.value) ?? 0}
            >
              <OrientationIcon orientation={o.value as Orientation} size={14} /> {o.label}
            </Check>
          ))}
        </section>

        <section className="filter-group">
          <h3>Разрешение</h3>
          <div className="pill-row">
            {RESOLUTIONS.map((r) => {
              const count = p.facetCounts.resolution.get(r) ?? 0;
              const on = p.filters.resolution.includes(r as ResolutionLabel);
              if (!count && !on) return null;
              return (
                <button key={r} type="button" className={`pill${on ? " is-on" : ""}`} onClick={() => p.onToggle("resolution", r)} aria-pressed={on}>
                  {r} <span>{count}</span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="filter-group">
          <h3>Длительность</h3>
          {DURATIONS.map((d) => (
            <Check
              key={d.value}
              checked={p.filters.duration.includes(d.value as DurationBucket)}
              onChange={() => p.onToggle("duration", d.value)}
              count={p.facetCounts.duration.get(d.value) ?? 0}
            >
              {d.label}
            </Check>
          ))}
        </section>

        <div className="filters-foot">
          <button type="button" className="btn" onClick={p.onReset} disabled={!p.hasActive}>
            Сбросить
          </button>
          <button type="button" className="btn btn-primary" onClick={p.onClose}>
            Показать {p.found.toLocaleString("ru-RU")}
          </button>
        </div>
      </aside>
    </>
  );
}

function Check({ checked, onChange, count, children }: { checked: boolean; onChange: () => void; count: number; children: React.ReactNode }) {
  return (
    <label className={`check${count === 0 && !checked ? " is-empty" : ""}`}>
      <input type="checkbox" checked={checked} onChange={onChange} />
      <span className="check-label">{children}</span>
      <span className="check-count">{count}</span>
    </label>
  );
}
