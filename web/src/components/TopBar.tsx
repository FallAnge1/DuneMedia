import { forwardRef, useLayoutEffect, useRef } from "react";
import type { Filters, Page } from "../lib/filters";
import type { Editor } from "../state";
import { IconClose, IconFilter, IconKey, IconMoon, IconSearch, IconSelect, IconSettings, IconSun } from "./Icons";

interface Props {
  filters: Filters;
  page: Page;
  inBoard: boolean;
  onQuery: (q: string) => void;
  onHome: () => void;
  onBoards: () => void;
  theme: "dark" | "light";
  onToggleTheme: () => void;
  onToggleFilters: () => void;
  activeFilterCount: number;
  editor: Editor | null;
  selectMode: boolean;
  onToggleSelectMode: () => void;
  onOpenManage: () => void;
  onOpenLogin: () => void;
  onLogout: () => void;
}

/** Шапка в духе Pinterest: логотип, «Главная» / «Доски», большой поиск, кнопки справа. */
export const TopBar = forwardRef<HTMLInputElement, Props>(function TopBar(p, searchRef) {
  // Высота шапки нужна липким элементам (CSS-переменная --topbar-h).
  const headerRef = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const el = headerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => document.documentElement.style.setProperty("--topbar-h", `${el.offsetHeight}px`));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const homeActive = p.page === "home" && !p.inBoard;
  const boardsActive = p.page === "boards" || p.inBoard;

  return (
    <header className="topbar" ref={headerRef}>
      <a
        className="logo"
        href="/"
        aria-label="Видеоархив — на главную"
        onClick={(e) => {
          e.preventDefault();
          p.onHome();
        }}
      >
        <img src="/favicon.svg" alt="" width={32} height={32} />
      </a>

      <nav className="nav" aria-label="Разделы">
        <button type="button" className={`nav-pill${homeActive ? " is-active" : ""}`} onClick={p.onHome}>
          Главная
        </button>
        <button type="button" className={`nav-pill${boardsActive ? " is-active" : ""}`} onClick={p.onBoards}>
          Доски
        </button>
      </nav>

      <label className="search">
        <IconSearch />
        <input
          ref={searchRef}
          type="search"
          placeholder={p.page === "boards" ? "Поиск досок" : "Поиск видео, фото и тегов"}
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
        <button type="button" className="icon-btn filters-toggle" onClick={p.onToggleFilters} aria-label="Фильтры и сортировка" title="Фильтры и сортировка">
          <IconFilter />
          {p.activeFilterCount > 0 && <span className="dot-count">{p.activeFilterCount}</span>}
        </button>
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
          <>
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
            <button type="button" className="icon-btn" onClick={p.onOpenManage} title="Доски и теги" aria-label="Доски и теги">
              <IconSettings />
            </button>
            <button type="button" className="avatar" onClick={p.onLogout} title={`${p.editor.name} — выйти из режима редактирования`}>
              {p.editor.name.trim().charAt(0).toUpperCase() || "?"}
            </button>
          </>
        ) : (
          <button type="button" className="icon-btn" onClick={p.onOpenLogin} title="Войти для редактирования" aria-label="Войти для редактирования">
            <IconKey />
          </button>
        )}
      </div>
    </header>
  );
});
