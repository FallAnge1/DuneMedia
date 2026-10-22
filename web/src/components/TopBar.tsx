import { forwardRef, useLayoutEffect, useRef } from "react";
import type { Collection } from "../lib/api";
import { SORTS, type CollectionTab, type Filters, type SortKey } from "../lib/filters";
import type { Editor } from "../state";
import { IconClose, IconFilter, IconHeart, IconKey, IconMoon, IconSearch, IconSelect, IconSettings, IconSun } from "./Icons";

interface Props {
  filters: Filters;
  onQuery: (q: string) => void;
  onTab: (tab: CollectionTab) => void;
  onSort: (sort: SortKey) => void;
  collections: Collection[];
  total: number;
  favoritesCount: number;
  tileSize: number;
  onTileSize: (n: number) => void;
  theme: "dark" | "light";
  onToggleTheme: () => void;
  onToggleFilters: () => void;
  filtersOpen: boolean;
  activeFilterCount: number;
  editor: Editor | null;
  selectMode: boolean;
  onToggleSelectMode: () => void;
  onOpenManage: () => void;
  onOpenLogin: () => void;
  onLogout: () => void;
}

export const TopBar = forwardRef<HTMLInputElement, Props>(function TopBar(p, searchRef) {
  // Высота шапки нужна липкой панели фильтров (CSS-переменная --topbar-h).
  const headerRef = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const el = headerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => document.documentElement.style.setProperty("--topbar-h", `${el.offsetHeight}px`));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <header className="topbar" ref={headerRef}>
      <div className="topbar-row">
        <a className="logo" href="/" aria-label="Видеоархив — на главную">
          <img src="/favicon.svg" alt="" width={28} height={28} />
          <span>Видеоархив</span>
        </a>

        <button
          type="button"
          className={`icon-btn filters-toggle${p.filtersOpen ? " is-on" : ""}`}
          onClick={p.onToggleFilters}
          aria-label="Фильтры"
          aria-expanded={p.filtersOpen}
        >
          <IconFilter />
          {p.activeFilterCount > 0 && <span className="dot-count">{p.activeFilterCount}</span>}
        </button>

        <label className="search">
          <IconSearch />
          <input
            ref={searchRef}
            type="search"
            placeholder="Поиск по названию, описанию и тегам"
            value={p.filters.q}
            onChange={(e) => p.onQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                if (p.filters.q) p.onQuery("");
                else e.currentTarget.blur();
              }
            }}
            aria-label="Поиск"
            enterKeyHint="search"
          />
          {p.filters.q ? (
            <button type="button" className="search-clear" onClick={() => p.onQuery("")} aria-label="Очистить поиск">
              <IconClose size={16} />
            </button>
          ) : (
            <kbd className="search-hint" aria-hidden>
              /
            </kbd>
          )}
        </label>

        <div className="topbar-tools">
          <select
            className="select"
            value={p.filters.sort}
            onChange={(e) => p.onSort(e.target.value as SortKey)}
            aria-label="Сортировка"
          >
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>

          <label className="tile-slider" title="Размер плиток">
            <span className="sr-only">Размер плиток</span>
            <span className="tile-icon small" aria-hidden />
            <input type="range" min={140} max={480} step={10} value={p.tileSize} onChange={(e) => p.onTileSize(Number(e.target.value))} />
            <span className="tile-icon" aria-hidden />
          </label>

          <button
            type="button"
            className="icon-btn"
            onClick={p.onToggleTheme}
            aria-label={p.theme === "dark" ? "Светлая тема" : "Тёмная тема"}
            title={p.theme === "dark" ? "Светлая тема" : "Тёмная тема"}
          >
            {p.theme === "dark" ? <IconSun /> : <IconMoon />}
          </button>

          {p.editor ? (
            <div className="editor-tools">
              <button
                type="button"
                className={`icon-btn${p.selectMode ? " is-on" : ""}`}
                onClick={p.onToggleSelectMode}
                aria-pressed={p.selectMode}
                title="Выбрать несколько видео"
                aria-label="Выбрать несколько видео"
              >
                <IconSelect />
              </button>
              <button type="button" className="icon-btn" onClick={p.onOpenManage} title="Коллекции и теги" aria-label="Коллекции и теги">
                <IconSettings />
              </button>
              <button type="button" className="editor-name" onClick={p.onLogout} title="Выйти из режима редактирования">
                {p.editor.name} · выйти
              </button>
            </div>
          ) : (
            <button type="button" className="icon-btn" onClick={p.onOpenLogin} title="Войти для редактирования" aria-label="Войти для редактирования">
              <IconKey />
            </button>
          )}
        </div>
      </div>

      <nav className="tabs" aria-label="Коллекции">
        <Tab active={p.filters.tab === "all"} onClick={() => p.onTab("all")} label="Все" count={p.total} />
        <Tab
          active={p.filters.tab === "fav"}
          onClick={() => p.onTab("fav")}
          label={
            <>
              <IconHeart size={14} filled /> Избранное
            </>
          }
          count={p.favoritesCount}
        />
        {p.collections.map((c) => (
          <Tab
            key={c.id}
            active={p.filters.tab === c.id}
            onClick={() => p.onTab(c.id)}
            label={c.emoji ? `${c.emoji} ${c.name}` : c.name}
            count={c.count}
          />
        ))}
      </nav>
    </header>
  );
});

function Tab({ active, onClick, label, count }: { active: boolean; onClick: () => void; label: React.ReactNode; count: number }) {
  return (
    <button type="button" className={`tab${active ? " is-active" : ""}`} onClick={onClick} aria-current={active ? "page" : undefined}>
      {label}
      <span className="tab-count">{count}</span>
    </button>
  );
}
