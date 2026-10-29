import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import type MiniSearch from "minisearch";
import { mediaUrl, type Video } from "./lib/api";
import {
  applyFilters,
  EMPTY_FILTERS,
  filtersFromUrl,
  filtersToUrl,
  hasActiveFilters,
  sortVideos,
  tagCounts,
  pageFromUrl,
  type FilterGroup,
  type Filters,
  type Page,
} from "./lib/filters";
import { buildSearchIndexAsync, fallbackSearchIds, searchIds } from "./lib/search";
import { useStoredState } from "./lib/storage";
import { useApp } from "./state";
import { ActiveChips } from "./components/ActiveChips";
import { BoardHeader, BoardsPage, type BoardTarget } from "./components/Boards";
import { boardCovers, SaveMenu } from "./components/SaveMenu";
import { TagStrip } from "./components/TagStrip";
import { BulkBar } from "./components/BulkBar";
import { FilterPanel } from "./components/FilterPanel";
import { LoginDialog } from "./components/LoginDialog";
import { ManageDialog } from "./components/ManageDialog";
import { GridSkeleton, MasonryGrid } from "./components/MasonryGrid";
import { Toasts } from "./components/Toasts";
import { TopBar } from "./components/TopBar";
import { Viewer } from "./components/Viewer";

export function App() {
  const { library, loadError, reload, editor, logout, toast } = useApp();

  // ---- Состояние в URL ----
  const [filters, setFilters] = useState<Filters>(() => filtersFromUrl(window.location.search));
  const [openId, setOpenId] = useState<string | null>(() => new URLSearchParams(window.location.search).get("v"));
  const [page, setPage] = useState<Page>(() => pageFromUrl(window.location.search));
  const pushedViewer = useRef(false);

  useEffect(() => {
    const url = window.location.pathname + filtersToUrl(filters, openId, page);
    if (url !== window.location.pathname + window.location.search) window.history.replaceState(null, "", url);
  }, [filters, openId, page]);

  useEffect(() => {
    const onPop = () => {
      pushedViewer.current = false;
      setFilters(filtersFromUrl(window.location.search));
      setOpenId(new URLSearchParams(window.location.search).get("v"));
      setPage(pageFromUrl(window.location.search));
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const openVideo = useCallback(
    (id: string) => {
      // Открытие просмотра — новый шаг истории: «Назад» в браузере закроет окно.
      if (!pushedViewer.current) {
        window.history.pushState(null, "", window.location.pathname + filtersToUrl(filters, id, page));
        pushedViewer.current = true;
      }
      setOpenId(id);
    },
    [filters, page],
  );

  const closeVideo = useCallback(() => {
    if (pushedViewer.current) window.history.back();
    else setOpenId(null);
  }, []);

  /** Закрыть просмотр, оставшись на новой записи истории (для перехода к фильтру из окна). */
  const leaveViewer = useCallback(() => {
    pushedViewer.current = false;
    setOpenId(null);
  }, []);

  const update = useCallback((patch: Partial<Filters>) => setFilters((f) => ({ ...f, ...patch })), []);

  // ---- Настройки вида (localStorage) ----
  const [tileSize, setTileSize] = useStoredState("va.tileSize", 260);
  const [theme, setTheme] = useStoredState<"dark" | "light">("va.theme", "light");
  const [favoriteList, setFavoriteList] = useStoredState<string[]>("va.favorites", []);
  const favorites = useMemo(() => new Set(favoriteList), [favoriteList]);
  const [filtersOpen, setFiltersOpen] = useState(false);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#121212" : "#ffffff");
  }, [theme]);

  const toggleFavorite = useCallback(
    (id: string) => setFavoriteList((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id])),
    [setFavoriteList],
  );

  // ---- Выдача ----
  const videos = useMemo(() => library?.videos ?? [], [library]);
  // Индекс поиска строится в фоне кусками; пока его нет (или он от прошлой версии архива) —
  // простой поиск по подстроке. Старый индекс не выбрасываем: лишние id всё равно отсекаются выдачей.
  const [index, setIndex] = useState<{ videos: Video[]; index: MiniSearch<Video> } | null>(null);
  useEffect(() => {
    if (videos.length === 0) return;
    let cancelled = false;
    void buildSearchIndexAsync(videos).then((built) => {
      if (!cancelled) setIndex({ videos, index: built });
    });
    return () => {
      cancelled = true;
    };
  }, [videos]);
  // Поиск отстаёт от набора на кадр-другой: буквы появляются сразу, выдача догоняет.
  const query = useDeferredValue(filters.q);
  const searchSet = useMemo(() => {
    if (!query.trim()) return null;
    if (index && index.videos === videos) return searchIds(index.index, query);
    return fallbackSearchIds(videos, query);
  }, [index, videos, query]);
  const ctx = useMemo(() => ({ searchIds: searchSet, favorites }), [searchSet, favorites]);

  const results = useMemo(() => sortVideos(applyFilters(videos, filters, ctx), filters.sort), [videos, filters, ctx]);

  // Счётчики возле вариантов фильтра: для каждой группы считаем без её собственного фильтра.
  const facets = useMemo(() => {
    const countBy = (list: Video[], key: (v: Video) => string | null) => {
      const m = new Map<string, number>();
      for (const v of list) {
        const k = key(v);
        if (k) m.set(k, (m.get(k) ?? 0) + 1);
      }
      return m;
    };
    const without = (patch: Partial<Filters>) => applyFilters(videos, { ...filters, ...patch }, ctx);
    const durationKey = (v: Video) => {
      if (v.media_type === "photo") return null;
      const d = v.duration ?? 0;
      return d < 10 ? "lt10" : d < 30 ? "10to30" : d < 60 ? "30to60" : "gt60";
    };
    return {
      media: countBy(without({ media: [] }), (v) => v.media_type ?? "video"),
      orientation: countBy(without({ orientation: [] }), (v) => v.orientation),
      resolution: countBy(without({ resolution: [] }), (v) => v.resolution_label),
      duration: countBy(without({ duration: [] }), durationKey),
    };
  }, [videos, filters, ctx]);

  const tagsInResults = useMemo(() => tagCounts(results), [results]);
  const tagSuggestions = useMemo(() => (library?.tags ?? []).map((t) => t.name), [library]);
  const videoMap = useMemo(() => new Map(videos.map((v) => [v.id, v])), [videos]);
  const favoritesCount = useMemo(() => favoriteList.filter((id) => videoMap.has(id)).length, [favoriteList, videoMap]);

  // ---- Наведение и выбор ----
  const [activeId, setActiveId] = useState<string | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const lastSelected = useRef<string | null>(null);

  const toggleSelect = useCallback(
    (id: string, shift: boolean) => {
      setSelected((prev) => {
        const next = new Set(prev);
        // Shift+клик выделяет диапазон в текущей выдаче.
        if (shift && lastSelected.current) {
          const a = results.findIndex((v) => v.id === lastSelected.current);
          const b = results.findIndex((v) => v.id === id);
          if (a >= 0 && b >= 0) {
            for (let i = Math.min(a, b); i <= Math.max(a, b); i++) next.add(results[i]!.id);
            return next;
          }
        }
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
      lastSelected.current = id;
    },
    [results],
  );

  useEffect(() => {
    if (!editor) {
      setSelectMode(false);
      setSelected(new Set());
    }
  }, [editor]);

  // ---- Диалоги ----
  const [loginOpen, setLoginOpen] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);

  // ---- Горячие клавиши ----
  const searchRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable);
      if (e.key === "/" && !typing && !openId) {
        e.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openId]);

  // ---- Просмотр ----
  const openVideoData = openId ? videoMap.get(openId) : undefined;
  const position = openId ? results.findIndex((v) => v.id === openId) : -1;
  const step = useCallback(
    (delta: number) => {
      if (position < 0 || results.length === 0) return;
      const next = results[(position + delta + results.length) % results.length]!;
      setOpenId(next.id);
    },
    [position, results],
  );

  // Видео из ссылки удалили — закрываем просмотр.
  useEffect(() => {
    if (library && openId && !videoMap.has(openId)) {
      setOpenId(null);
      toast("Видео не найдено — возможно, его удалили", "error");
    }
  }, [library, openId, videoMap, toast]);

  const activeCount = filters.tags.length + filters.media.length + filters.orientation.length + filters.resolution.length + filters.duration.length;
  const resetFilters = () => update({ ...EMPTY_FILTERS, tab: filters.tab, sort: filters.sort });
  const toggleIn = (group: FilterGroup, value: string) =>
    setFilters((f) => {
      const list = f[group] as string[];
      return { ...f, [group]: list.includes(value) ? list.filter((x) => x !== value) : [...list, value] };
    });
  const toggleTag = (tag: string) =>
    setFilters((f) => ({ ...f, tags: f.tags.includes(tag) ? f.tags.filter((x) => x !== tag) : [...f.tags, tag] }));

  const collections = library?.collections ?? [];

  // ---- Доски ----
  const covers = useMemo(() => boardCovers(videos), [videos]);
  const latestPosters = (list: Video[]) =>
    [...list]
      .sort((a, b) => b.created_at - a.created_at)
      .map((v) => mediaUrl(v.poster_key))
      .filter((x): x is string => !!x)
      .slice(0, 3);
  const allCovers = useMemo(() => latestPosters(videos), [videos]);
  const favCovers = useMemo(() => latestPosters(videos.filter((v) => favorites.has(v.id))), [videos, favorites]);

  const goHome = useCallback(() => {
    setPage("home");
    setFilters((f) => ({ ...EMPTY_FILTERS, sort: f.sort }));
    window.scrollTo({ top: 0 });
  }, []);
  const goBoards = useCallback(() => {
    setPage("boards");
    setFilters((f) => ({ ...f, tab: "all" }));
    window.scrollTo({ top: 0 });
  }, []);
  const openBoard = useCallback((target: BoardTarget) => {
    setPage("home");
    setFilters((f) => ({ ...EMPTY_FILTERS, sort: f.sort, tab: target }));
    window.scrollTo({ top: 0 });
  }, []);

  const currentBoard = typeof filters.tab === "number" ? collections.find((c) => c.id === filters.tab) ?? null : null;
  const boardTitle =
    filters.tab === "fav" ? "♡ Избранное" : currentBoard ? `${currentBoard.emoji ? `${currentBoard.emoji} ` : ""}${currentBoard.name}` : null;
  const boardCount = filters.tab === "fav" ? favoritesCount : currentBoard?.count ?? 0;

  // ---- «Сохранить» ----
  const [saveFor, setSaveFor] = useState<{ id: string; anchor: DOMRect } | null>(null);
  const openSave = useCallback((id: string, anchor: DOMRect) => setSaveFor({ id, anchor }), []);
  const saveVideo = saveFor ? videoMap.get(saveFor.id) : undefined;

  // ---- Похожие видео: больше общих тегов — выше ----
  const similar = useMemo(() => {
    if (!openVideoData || openVideoData.tags.length === 0) return [];
    const own = new Set(openVideoData.tags);
    return videos
      .filter((v) => v.id !== openVideoData.id)
      .map((v) => ({ v, score: v.tags.filter((t) => own.has(t)).length }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score || b.v.created_at - a.v.created_at)
      .slice(0, 9)
      .map((x) => x.v);
  }, [openVideoData, videos]);

  return (
    <div className={`app${filtersOpen ? " filters-open" : ""}${selectMode ? " select-mode" : ""}`}>
      <TopBar
        ref={searchRef}
        filters={filters}
        page={page}
        inBoard={filters.tab !== "all"}
        onQuery={(q) => {
          if (page === "boards") setPage("home");
          update({ q });
        }}
        onHome={goHome}
        onBoards={goBoards}
        theme={theme}
        onToggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
        onToggleFilters={() => setFiltersOpen((o) => !o)}
        activeFilterCount={activeCount}
        editor={editor}
        selectMode={selectMode}
        onToggleSelectMode={() => {
          setSelectMode((m) => !m);
          setSelected(new Set());
        }}
        onOpenManage={() => setManageOpen(true)}
        onOpenLogin={() => setLoginOpen(true)}
        onLogout={logout}
      />

      <div className="layout">
        <FilterPanel
          open={filtersOpen}
          onClose={() => setFiltersOpen(false)}
          filters={filters}
          tagCounts={tagsInResults}
          facetCounts={facets}
          onToggleTag={toggleTag}
          onToggle={toggleIn}
          onReset={resetFilters}
          hasActive={hasActiveFilters(filters)}
          onSort={(sort) => update({ sort })}
          tileSize={tileSize}
          onTileSize={setTileSize}
          found={results.length}
        />

        <main className="main">
          {loadError && !library ? (
            <div className="empty">
              <h2>Архив не загрузился</h2>
              <p className="muted">{loadError}</p>
              <button type="button" className="btn btn-primary" onClick={() => void reload()}>
                Повторить
              </button>
            </div>
          ) : !library ? (
            <GridSkeleton tileSize={tileSize} />
          ) : page === "boards" ? (
            <BoardsPage
              collections={collections}
              covers={covers}
              allCovers={allCovers}
              favCovers={favCovers}
              total={videos.length}
              favoritesCount={favoritesCount}
              onOpen={openBoard}
              onLogin={() => setLoginOpen(true)}
            />
          ) : (
            <>
              {boardTitle && (
                <BoardHeader
                  title={boardTitle}
                  count={boardCount}
                  board={currentBoard}
                  autoCover={currentBoard ? covers.get(currentBoard.id)?.[0] : favCovers[0]}
                  onBack={goBoards}
                />
              )}
              <TagStrip selected={filters.tags} counts={tagsInResults} onToggle={toggleTag} />
              <ActiveChips
                filters={filters}
                found={results.length}
                onRemoveTag={toggleTag}
                onRemove={toggleIn}
                onClearQuery={() => update({ q: "" })}
                onReset={resetFilters}
              />
              {results.length > 0 ? (
                <MasonryGrid
                  videos={results}
                  tileSize={tileSize}
                  activeId={activeId}
                  favorites={favorites}
                  selected={selected}
                  selectMode={selectMode}
                  onActivate={setActiveId}
                  onOpen={openVideo}
                  onToggleFavorite={toggleFavorite}
                  onSave={openSave}
                  onToggleSelect={toggleSelect}
                />
              ) : videos.length === 0 ? (
                <div className="empty">
                  <h2>Архив пока пуст</h2>
                  <p className="muted">Видео и фото появятся здесь после загрузки через программу-загрузчик.</p>
                </div>
              ) : (
                <div className="empty">
                  <h2>Ничего не найдено</h2>
                  <p className="muted">
                    {filters.tab === "fav" && favoritesCount === 0
                      ? "В избранном пока ничего нет. Нажмите ♡ на карточке, чтобы добавить."
                      : currentBoard && currentBoard.count === 0
                        ? "Доска пока пустая. Нажмите «Сохранить» на любом видео и выберите эту доску."
                        : "Попробуйте изменить запрос или убрать часть фильтров."}
                  </p>
                  {(hasActiveFilters(filters) || filters.tab !== "all") && (
                    <button type="button" className="btn btn-primary" onClick={() => setFilters({ ...EMPTY_FILTERS, sort: filters.sort })}>
                      Сбросить фильтры
                    </button>
                  )}
                </div>
              )}
            </>
          )}
        </main>
      </div>

      {selectMode && editor && (
        <BulkBar
          selected={selected}
          videos={videoMap}
          visibleIds={results.map((v) => v.id)}
          collections={collections}
          tagSuggestions={tagSuggestions}
          onSelectAll={() => setSelected(new Set(results.map((v) => v.id)))}
          onClear={() => setSelected(new Set())}
          onExit={() => {
            setSelectMode(false);
            setSelected(new Set());
          }}
        />
      )}

      {openVideoData && (
        <Viewer
          video={openVideoData}
          position={position}
          total={results.length}
          collections={collections}
          tagSuggestions={tagSuggestions}
          favorite={favorites.has(openVideoData.id)}
          onToggleFavorite={toggleFavorite}
          onPrev={() => step(-1)}
          onNext={() => step(1)}
          onClose={closeVideo}
          onTagClick={(tag) => {
            leaveViewer();
            setFilters((f) => (f.tags.includes(tag) ? f : { ...f, tags: [...f.tags, tag] }));
          }}
          onCollectionClick={(id) => {
            leaveViewer();
            openBoard(id);
          }}
          onSave={(anchor) => openSave(openVideoData.id, anchor)}
          similar={similar}
          onOpenSimilar={(id) => setOpenId(id)}
        />
      )}

      {saveFor && saveVideo && (
        <SaveMenu
          video={saveVideo}
          anchor={saveFor.anchor}
          collections={collections}
          covers={covers}
          favorite={favorites.has(saveVideo.id)}
          onToggleFavorite={toggleFavorite}
          onClose={() => setSaveFor(null)}
          onLogin={() => setLoginOpen(true)}
        />
      )}

      {loginOpen && <LoginDialog onClose={() => setLoginOpen(false)} />}
      {manageOpen && editor && library && (
        <ManageDialog collections={collections} tags={library.tags} onClose={() => setManageOpen(false)} />
      )}
      <Toasts />
    </div>
  );
}
