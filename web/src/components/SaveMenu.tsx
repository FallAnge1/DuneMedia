import { useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { api, mediaUrl, type Collection, type Video } from "../lib/api";
import { useApp } from "../state";
import { IconCheck, IconHeart, IconPlus } from "./Icons";

interface Props {
  video: Video;
  anchor: DOMRect;
  collections: Collection[];
  /** Обложка доски — постер её последнего видео. */
  covers: Map<number, string[]>;
  favorite: boolean;
  onToggleFavorite: (id: string) => void;
  onClose: () => void;
  onLogin: () => void;
}

const WIDTH = 300;

/**
 * Меню «Сохранить», как в Pinterest: избранное (только в этом браузере) и доски (общие для всех,
 * менять их может тот, кто вошёл по токену загрузчика).
 */
export function SaveMenu({ video, anchor, collections, covers, favorite, onToggleFavorite, onClose, onLogin }: Props) {
  const { editor, run } = useApp();
  const ref = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState<number | "new" | null>(null);
  const [pos, setPos] = useState({ top: anchor.bottom + 8, left: anchor.right - WIDTH });

  // Меню не должно вылезать за край экрана.
  useLayoutEffect(() => {
    const el = ref.current;
    const h = el?.offsetHeight ?? 360;
    let top = anchor.bottom + 8;
    if (top + h > window.innerHeight - 8) top = Math.max(8, anchor.top - h - 8);
    const left = Math.min(Math.max(8, anchor.right - WIDTH), window.innerWidth - WIDTH - 8);
    setPos({ top, left });
  }, [anchor, creating, collections.length]);

  useEffect(() => {
    const onDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    const onScroll = (e: Event) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [onClose]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return collections.filter((c) => !q || c.name.toLowerCase().includes(q));
  }, [collections, query]);

  const toggle = async (c: Collection) => {
    const inside = video.collections.includes(c.id);
    setBusy(c.id);
    await run(
      (t) => api.collectionVideos(t, c.id, inside ? { remove: [video.id] } : { add: [video.id] }),
      inside ? `Убрано с доски «${c.name}»` : `Сохранено на доску «${c.name}»`,
    );
    setBusy(null);
  };

  const create = async (e: FormEvent) => {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;
    setBusy("new");
    const created = await run(async (t) => {
      const { collection } = await api.createCollection(t, name, null);
      await api.collectionVideos(t, collection.id, { add: [video.id] });
      return collection;
    }, `Доска «${name}» создана`);
    setBusy(null);
    if (created) {
      setCreating(false);
      setNewName("");
    }
  };

  return createPortal(
    <div ref={ref} className="save-menu" style={{ top: pos.top, left: pos.left, width: WIDTH }} role="dialog" aria-label="Сохранить">
      <div className="save-menu-title">Сохранить</div>

      <button type="button" className="save-row" onClick={() => onToggleFavorite(video.id)}>
        <span className="save-cover save-cover-fav">
          <IconHeart size={18} filled />
        </span>
        <span className="save-name">
          Избранное
          <small>только в этом браузере</small>
        </span>
        <span className={`save-state${favorite ? " is-on" : ""}`}>{favorite ? <IconCheck size={14} /> : "Сохранить"}</span>
      </button>

      <div className="save-sep">Доски</div>

      {editor ? (
        <>
          {collections.length > 6 && (
            <input className="input input-sm save-search" placeholder="Найти доску" value={query} onChange={(e) => setQuery(e.target.value)} autoFocus />
          )}
          <div className="save-list">
            {shown.map((c) => {
              const inside = video.collections.includes(c.id);
              const cover = covers.get(c.id)?.[0];
              return (
                <button key={c.id} type="button" className="save-row" onClick={() => toggle(c)} disabled={busy !== null}>
                  <span className="save-cover">{cover ? <img src={cover} alt="" /> : <span>{c.emoji || "📁"}</span>}</span>
                  <span className="save-name">
                    {c.emoji ? `${c.emoji} ` : ""}
                    {c.name}
                    <small>{c.count} видео</small>
                  </span>
                  <span className={`save-state${inside ? " is-on" : ""}`}>
                    {busy === c.id ? "…" : inside ? <IconCheck size={14} /> : "Сохранить"}
                  </span>
                </button>
              );
            })}
            {shown.length === 0 && <p className="muted small save-empty">Досок пока нет</p>}
          </div>
          {creating ? (
            <form className="save-create" onSubmit={create}>
              <input className="input" placeholder="Название доски" value={newName} onChange={(e) => setNewName(e.target.value)} autoFocus maxLength={100} />
              <button type="submit" className="btn btn-primary btn-sm" disabled={!newName.trim() || busy === "new"}>
                Создать
              </button>
            </form>
          ) : (
            <button type="button" className="save-row save-new" onClick={() => setCreating(true)}>
              <span className="save-cover">
                <IconPlus size={18} />
              </span>
              <span className="save-name">Создать доску</span>
            </button>
          )}
        </>
      ) : (
        <div className="save-login">
          <p className="small muted">Раскладывать видео по доскам могут загрузчики.</p>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => {
              onClose();
              onLogin();
            }}
          >
            Войти по токену
          </button>
        </div>
      )}
    </div>,
    // Открытый <dialog> (окно просмотра) рисуется поверх страницы — меню должно быть внутри него.
    document.querySelector("dialog[open]") ?? document.body,
  );
}

/** Обложки досок: постер самого свежего видео каждой доски. */
export function boardCovers(videos: Video[]): Map<number, string[]> {
  const sorted = [...videos].sort((a, b) => b.created_at - a.created_at);
  const map = new Map<number, string[]>();
  for (const v of sorted) {
    const poster = mediaUrl(v.poster_key);
    if (!poster) continue;
    for (const c of v.collections) {
      const list = map.get(c) ?? [];
      if (list.length < 3) list.push(poster);
      map.set(c, list);
    }
  }
  return map;
}
