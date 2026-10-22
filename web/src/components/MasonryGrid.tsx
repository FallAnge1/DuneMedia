import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { Video } from "../lib/api";
import { VideoCard } from "./VideoCard";

interface Props {
  videos: Video[];
  tileSize: number;
  activeId: string | null;
  favorites: Set<string>;
  selected: Set<string>;
  selectMode: boolean;
  onActivate: (id: string | null) => void;
  onOpen: (id: string) => void;
  onToggleFavorite: (id: string) => void;
  onToggleSelect: (id: string, shift: boolean) => void;
}

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

const OVERSCAN = 800; // px сверху и снизу от экрана, которые тоже рендерятся

/** Пропорции плитки = пропорции видео (с ограничением для слишком узких/широких). */
export function aspectOf(v: Video): number {
  if (!v.width || !v.height) return 9 / 16;
  return Math.min(Math.max(v.height / v.width, 0.45), 2);
}

export function columnsFor(width: number, tileSize: number, gap: number): number {
  const n = Math.max(1, Math.floor((width + gap) / (tileSize + gap)));
  return width < 640 ? Math.max(2, n) : n;
}

/**
 * Masonry-сетка с виртуализацией: позиции всех плиток считаются заранее,
 * а в DOM попадают только видимые (плюс запас), поэтому 10–20 тысяч видео не тормозят.
 */
export function MasonryGrid(props: Props) {
  const { videos, tileSize } = props;
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [viewport, setViewport] = useState({ top: 0, bottom: 2000 });

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(entry!.contentRect.width));
    ro.observe(el);
    setWidth(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, []);

  const gap = width < 640 ? 8 : 12;

  const layout = useMemo(() => {
    if (width <= 0) return { boxes: [] as Box[], height: 0 };
    const cols = columnsFor(width, tileSize, gap);
    const colWidth = (width - gap * (cols - 1)) / cols;
    const heights = new Array<number>(cols).fill(0);
    const boxes: Box[] = videos.map((v) => {
      let col = 0;
      for (let i = 1; i < cols; i++) if (heights[i]! < heights[col]!) col = i;
      const h = Math.round(colWidth * aspectOf(v));
      const box = { x: Math.round(col * (colWidth + gap)), y: heights[col]!, w: Math.round(colWidth), h };
      heights[col] = heights[col]! + h + gap;
      return box;
    });
    return { boxes, height: Math.max(0, ...heights) - gap };
  }, [videos, width, tileSize, gap]);

  // Видимая область относительно сетки, обновляется не чаще раза за кадр.
  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const el = ref.current;
      if (!el) return;
      const top = el.getBoundingClientRect().top;
      const next = { top: -top - OVERSCAN, bottom: -top + window.innerHeight + OVERSCAN };
      setViewport((prev) =>
        Math.abs(prev.top - next.top) < 100 && Math.abs(prev.bottom - next.bottom) < 100 ? prev : next,
      );
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [layout]);

  const visible: number[] = [];
  layout.boxes.forEach((b, i) => {
    if (b.y < viewport.bottom && b.y + b.h > viewport.top) visible.push(i);
  });

  return (
    <div ref={ref} className="grid" style={{ height: layout.height }}>
      {visible.map((i) => {
        const v = videos[i]!;
        const b = layout.boxes[i]!;
        return (
          <VideoCard
            key={v.id}
            video={v}
            x={b.x}
            y={b.y}
            width={b.w}
            height={b.h}
            priority={i < 8}
            active={props.activeId === v.id}
            favorite={props.favorites.has(v.id)}
            selected={props.selected.has(v.id)}
            selectMode={props.selectMode}
            onActivate={props.onActivate}
            onOpen={props.onOpen}
            onToggleFavorite={props.onToggleFavorite}
            onToggleSelect={props.onToggleSelect}
          />
        );
      })}
    </div>
  );
}

/** Скелетон сетки на время загрузки. */
export function GridSkeleton({ tileSize }: { tileSize: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    if (ref.current) setWidth(ref.current.getBoundingClientRect().width);
  }, []);
  const gap = width < 640 ? 8 : 12;
  const cols = width ? columnsFor(width, tileSize, gap) : 4;
  const ratios = [0.56, 1.4, 0.75, 1, 0.56, 1.78, 0.56, 1.2];
  return (
    <div ref={ref} className="skeleton-grid" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)`, gap }} aria-busy="true" aria-label="Загрузка">
      {Array.from({ length: cols }, (_, c) => (
        <div key={c} className="skeleton-col" style={{ gap }}>
          {Array.from({ length: 4 }, (_, r) => (
            <div key={r} className="skeleton" style={{ aspectRatio: `1 / ${ratios[(c * 3 + r) % ratios.length]}` }} />
          ))}
        </div>
      ))}
    </div>
  );
}
