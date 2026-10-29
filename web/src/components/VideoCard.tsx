import { memo, useEffect, useRef, useState, type MouseEvent, type PointerEvent } from "react";
import { mediaUrl, type Video } from "../lib/api";
import { formatDuration } from "../lib/format";
import { IconCheck, IconFilm, IconHeart, OrientationIcon } from "./Icons";

/** Высота подписи под карточкой (название + теги), учитывается в раскладке сетки. */
export const CAPTION_H = 44;

export interface CardProps {
  video: Video;
  x: number;
  y: number;
  width: number;
  height: number; // вместе с подписью
  active: boolean;
  favorite: boolean;
  saved: boolean; // лежит хотя бы на одной доске
  selected: boolean;
  selectMode: boolean;
  priority: boolean;
  onActivate: (id: string | null) => void;
  onOpen: (id: string) => void;
  onToggleFavorite: (id: string) => void;
  onSave: (id: string, anchor: DOMRect) => void;
  onToggleSelect: (id: string, shift: boolean) => void;
}

/**
 * Карточка в стиле Pinterest: скруглённый постер, подпись снизу.
 * При наведении — беззвучное превью, движение мыши его перематывает, сверху кнопка «Сохранить».
 * На телефоне первый тап запускает превью, второй открывает просмотр.
 */
export const VideoCard = memo(function VideoCard(props: CardProps) {
  const { video, active, favorite, saved, selected, selectMode } = props;
  const videoRef = useRef<HTMLVideoElement>(null);
  const progressRef = useRef<HTMLDivElement>(null);
  const pointerType = useRef<string>("mouse");
  const [playing, setPlaying] = useState(false);
  const [posterFailed, setPosterFailed] = useState(false);
  const preview = mediaUrl(video.preview_key);
  const poster = posterFailed ? undefined : mediaUrl(video.poster_key);
  const mediaHeight = props.height - CAPTION_H;

  useEffect(() => {
    if (!active) {
      setPlaying(false);
      return;
    }
    let frame = 0;
    const tick = () => {
      const v = videoRef.current;
      const bar = progressRef.current;
      if (v && bar && v.duration) bar.style.transform = `scaleX(${v.currentTime / v.duration})`;
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [active]);

  const scrub = (e: PointerEvent<HTMLDivElement>) => {
    if (e.pointerType !== "mouse") return;
    const v = videoRef.current;
    if (!v || !Number.isFinite(v.duration) || v.duration <= 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 0.999);
    v.currentTime = ratio * v.duration;
  };

  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.metaKey || e.ctrlKey || e.button === 1) return; // открыть в новой вкладке
    e.preventDefault();
    if (selectMode) {
      props.onToggleSelect(video.id, e.shiftKey);
      return;
    }
    if (pointerType.current !== "mouse" && !active && preview) {
      props.onActivate(video.id);
      return;
    }
    props.onOpen(video.id);
  };

  const tags = video.tags.slice(0, 3);

  return (
    <div
      className={`card${active ? " is-active" : ""}${selected ? " is-selected" : ""}`}
      style={{ transform: `translate3d(${props.x}px, ${props.y}px, 0)`, width: props.width, height: props.height }}
      onPointerEnter={(e) => {
        pointerType.current = e.pointerType;
        if (e.pointerType === "mouse") props.onActivate(video.id);
      }}
      onPointerDown={(e) => {
        pointerType.current = e.pointerType;
      }}
      onPointerLeave={(e) => {
        if (e.pointerType === "mouse") props.onActivate(null);
      }}
    >
      <div className="card-frame" style={{ height: mediaHeight }} onPointerMove={scrub}>
        <a className="card-link" href={`?v=${video.id}`} onClick={onClick} aria-label={video.title} draggable={false}>
          <div className="card-media">
            {poster ? (
              <img
                src={poster}
                alt=""
                loading={props.priority ? "eager" : "lazy"}
                fetchPriority={props.priority ? "high" : "auto"}
                decoding="async"
                draggable={false}
                onError={() => setPosterFailed(true)}
              />
            ) : (
              <div className="card-noposter">
                <IconFilm size={28} />
              </div>
            )}
            {active && preview && (
              <video
                ref={videoRef}
                className={playing ? "is-playing" : ""}
                src={preview}
                poster={poster}
                muted
                loop
                playsInline
                autoPlay
                preload="auto"
                disablePictureInPicture
                onPlaying={() => setPlaying(true)}
              />
            )}
          </div>
          <div className="card-shade" />
          <div className="card-badges">
            {video.resolution_label && <span className="badge">{video.resolution_label}</span>}
            <span className="badge badge-icon" title={orientationTitle(video.orientation)}>
              <OrientationIcon orientation={video.orientation} />
            </span>
          </div>
          <span className="badge card-duration">{video.media_type === "photo" ? "Фото" : formatDuration(video.duration)}</span>
          {preview && (
            <div className="card-progress">
              <div ref={progressRef} />
            </div>
          )}
        </a>

        {selectMode ? (
          <span className={`card-check${selected ? " is-on" : ""}`} aria-hidden>
            {selected && <IconCheck size={14} />}
          </span>
        ) : (
          <>
            <button
              type="button"
              className={`card-save${saved ? " is-saved" : ""}`}
              onClick={(e) => props.onSave(video.id, e.currentTarget.getBoundingClientRect())}
            >
              {saved ? "Сохранено" : "Сохранить"}
            </button>
            <button
              type="button"
              className={`card-fav${favorite ? " is-on" : ""}`}
              aria-label={favorite ? "Убрать из избранного" : "В избранное"}
              aria-pressed={favorite}
              onClick={() => props.onToggleFavorite(video.id)}
            >
              <IconHeart size={16} filled={favorite} />
            </button>
          </>
        )}
      </div>

      <a className="card-caption" href={`?v=${video.id}`} onClick={onClick} tabIndex={-1} draggable={false}>
        <span className="card-title">{video.title}</span>
        {tags.length > 0 && <span className="card-tags">{tags.map((t) => `#${t}`).join("  ")}</span>}
      </a>
    </div>
  );
});

function orientationTitle(o: string | null): string {
  return o === "vertical" ? "Вертикальное" : o === "square" ? "Квадратное" : "Горизонтальное";
}
