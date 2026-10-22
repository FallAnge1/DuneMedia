import { useEffect, useState } from "react";
import { mediaUrl, type Collection, type Video } from "../lib/api";
import { formatDate, formatDuration, formatFps, formatSize, telegramUrl } from "../lib/format";
import { copyText, openInTelegram } from "../lib/telegram";
import { useApp } from "../state";
import { EditForm } from "./EditForm";
import { IconChevronLeft, IconChevronRight, IconClose, IconCopy, IconEdit, IconHeart, IconLink, IconTelegram, OrientationIcon } from "./Icons";
import { Modal } from "./Modal";

interface Props {
  video: Video;
  position: number; // 0-based в текущей выдаче, -1 если видео не в выдаче
  total: number;
  collections: Collection[];
  tagSuggestions: string[];
  favorite: boolean;
  onToggleFavorite: (id: string) => void;
  onPrev: () => void;
  onNext: () => void;
  onClose: () => void;
  onTagClick: (tag: string) => void;
  onCollectionClick: (id: number) => void;
}

/** Окно просмотра: большое превью, все метаданные, переход в Telegram, листание ← →. */
export function Viewer(p: Props) {
  const { video: v } = p;
  const { toast, editor } = useApp();
  const [editing, setEditing] = useState(false);

  // При листании выходим из режима редактирования.
  useEffect(() => setEditing(false), [v.id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (e.key === "ArrowLeft") p.onPrev();
      else if (e.key === "ArrowRight") p.onNext();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [p.onPrev, p.onNext]);

  const preview = mediaUrl(v.preview_key);
  const poster = mediaUrl(v.poster_key);
  const tgLink = telegramUrl(v.tg_channel, v.tg_message_id);
  const collections = p.collections.filter((c) => v.collections.includes(c.id));
  const ratio = v.width && v.height ? `${v.width} / ${v.height}` : "16 / 9";

  const copy = async (text: string, what: string) => {
    toast((await copyText(text)) ? `${what} скопирована` : "Не удалось скопировать", "success");
  };

  return (
    <Modal onClose={p.onClose} className="viewer" label={v.title}>
      <div className="viewer-body">
        <div className="viewer-stage">
          <div className="viewer-media" style={{ aspectRatio: ratio }}>
            {preview ? (
              <video key={v.id} src={preview} poster={poster} autoPlay muted loop playsInline controls preload="auto" />
            ) : poster ? (
              <img src={poster} alt="" />
            ) : (
              <div className="card-noposter">Нет превью</div>
            )}
          </div>
          {p.total > 1 && p.position >= 0 && (
            <>
              <button type="button" className="viewer-nav prev" onClick={p.onPrev} aria-label="Предыдущее видео (←)">
                <IconChevronLeft size={28} />
              </button>
              <button type="button" className="viewer-nav next" onClick={p.onNext} aria-label="Следующее видео (→)">
                <IconChevronRight size={28} />
              </button>
            </>
          )}
        </div>

        <aside className="viewer-side">
          <div className="viewer-top">
            {p.position >= 0 && (
              <span className="muted small">
                {p.position + 1} из {p.total}
              </span>
            )}
            <button type="button" className="icon-btn" onClick={p.onClose} aria-label="Закрыть (Esc)">
              <IconClose />
            </button>
          </div>

          {editing && editor ? (
            <EditForm
              video={v}
              collections={p.collections}
              tagSuggestions={p.tagSuggestions}
              onDone={() => setEditing(false)}
              onDeleted={p.onClose}
            />
          ) : (
            <>
              <h2 className="viewer-title">{v.title}</h2>
              {v.description && <p className="viewer-desc">{v.description}</p>}

              <div className="viewer-actions">
                <button type="button" className="btn btn-primary" onClick={() => openInTelegram(v.tg_channel, v.tg_message_id)}>
                  <IconTelegram /> Открыть в Telegram
                </button>
                <div className="btn-row">
                  <button type="button" className="btn" onClick={() => copy(tgLink, "Ссылка на пост")} title={tgLink}>
                    <IconCopy /> Скопировать ссылку
                  </button>
                  <button
                    type="button"
                    className={`btn btn-icon${p.favorite ? " is-on" : ""}`}
                    onClick={() => p.onToggleFavorite(v.id)}
                    aria-pressed={p.favorite}
                    title={p.favorite ? "Убрать из избранного" : "В избранное"}
                  >
                    <IconHeart filled={p.favorite} /> {p.favorite ? "В избранном" : "В избранное"}
                  </button>
                </div>
                <button type="button" className="link-btn small" onClick={() => copy(window.location.href, "Ссылка на это видео на сайте")}>
                  <IconLink size={14} /> Ссылка на это видео на сайте
                </button>
              </div>

              {v.tags.length > 0 && (
                <div className="viewer-tags">
                  {v.tags.map((t) => (
                    <button key={t} type="button" className="tag-chip" onClick={() => p.onTagClick(t)} title="Показать видео с этим тегом">
                      #{t}
                    </button>
                  ))}
                </div>
              )}

              {collections.length > 0 && (
                <div className="viewer-collections">
                  {collections.map((c) => (
                    <button key={c.id} type="button" className="pill" onClick={() => p.onCollectionClick(c.id)}>
                      {c.emoji} {c.name}
                    </button>
                  ))}
                </div>
              )}

              <dl className="meta">
                <dt>Длительность</dt>
                <dd>{formatDuration(v.duration)}</dd>
                <dt>Разрешение</dt>
                <dd>
                  {v.width && v.height ? `${v.width}×${v.height}` : "—"} {v.resolution_label && <span className="badge">{v.resolution_label}</span>}{" "}
                  <OrientationIcon orientation={v.orientation} />
                </dd>
                <dt>Частота кадров</dt>
                <dd>{formatFps(v.fps)}</dd>
                <dt>Размер файла</dt>
                <dd>{formatSize(v.file_size)}</dd>
                {v.codec && (
                  <>
                    <dt>Кодек</dt>
                    <dd>{v.codec}</dd>
                  </>
                )}
                {v.file_name && (
                  <>
                    <dt>Файл</dt>
                    <dd className="break">{v.file_name}</dd>
                  </>
                )}
                <dt>Добавлено</dt>
                <dd>{formatDate(v.created_at)}</dd>
                {v.uploaded_by && (
                  <>
                    <dt>Загрузил</dt>
                    <dd>{v.uploaded_by}</dd>
                  </>
                )}
              </dl>

              {editor && (
                <button type="button" className="btn btn-block" onClick={() => setEditing(true)}>
                  <IconEdit /> Редактировать
                </button>
              )}
              {editor && v.caption_dirty === 1 && (
                <p className="muted small">Подпись поста в Telegram обновит программа-загрузчик при следующем запуске.</p>
              )}
            </>
          )}
        </aside>
      </div>
    </Modal>
  );
}
