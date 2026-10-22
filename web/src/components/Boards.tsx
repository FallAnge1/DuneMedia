import { useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import { api, mediaUrl, type Collection } from "../lib/api";
import { coverKey, prepareCover } from "../lib/image";
import { plural } from "../lib/format";
import { useApp } from "../state";
import { IconBack, IconEdit, IconHeart, IconImage, IconPlus } from "./Icons";
import { Modal } from "./Modal";

export type BoardTarget = "all" | "fav" | number;

interface BoardsPageProps {
  collections: Collection[];
  covers: Map<number, string[]>;
  allCovers: string[];
  favCovers: string[];
  total: number;
  favoritesCount: number;
  onOpen: (target: BoardTarget) => void;
  onLogin: () => void;
}

/** Страница «Доски»: обложки из трёх последних постеров, как в Pinterest. */
export function BoardsPage(p: BoardsPageProps) {
  const { editor } = useApp();
  const [dialog, setDialog] = useState<Collection | "new" | null>(null);

  return (
    <section className="boards-page">
      <header className="boards-head">
        <h1>Доски</h1>
        <p className="muted">
          {p.collections.length} {plural(p.collections.length, "доска", "доски", "досок")} · раскладывайте видео по папкам кнопкой «Сохранить»
        </p>
      </header>

      <div className="boards-grid">
        <BoardCard title="Все видео" count={p.total} covers={p.allCovers} onClick={() => p.onOpen("all")} />
        <BoardCard
          title="Избранное"
          icon={<IconHeart size={16} filled />}
          count={p.favoritesCount}
          covers={p.favCovers}
          hint="только в этом браузере"
          onClick={() => p.onOpen("fav")}
        />
        {p.collections.map((c) => (
          <BoardCard
            key={c.id}
            title={c.emoji ? `${c.emoji} ${c.name}` : c.name}
            count={c.count}
            covers={p.covers.get(c.id) ?? []}
            custom={mediaUrl(c.cover_key)}
            onClick={() => p.onOpen(c.id)}
            onEdit={editor ? () => setDialog(c) : undefined}
          />
        ))}
        {editor ? (
          <button type="button" className="board-card board-new" onClick={() => setDialog("new")}>
            <span className="board-cover board-cover-new">
              <IconPlus size={36} />
            </span>
            <span className="board-title">Новая доска</span>
          </button>
        ) : (
          <button type="button" className="board-card board-new" onClick={p.onLogin}>
            <span className="board-cover board-cover-new">
              <IconPlus size={36} />
            </span>
            <span className="board-title">Новая доска</span>
            <span className="board-count">войдите по токену загрузчика</span>
          </button>
        )}
      </div>

      {dialog && (
        <BoardDialog
          board={dialog === "new" ? null : dialog}
          autoCover={dialog === "new" ? undefined : p.covers.get(dialog.id)?.[0]}
          onClose={() => setDialog(null)}
        />
      )}
    </section>
  );
}

function BoardCard(props: {
  title: string;
  count: number;
  covers: string[];
  custom?: string;
  icon?: React.ReactNode;
  hint?: string;
  onClick: () => void;
  onEdit?: () => void;
}) {
  const [a, b, c] = props.covers;
  return (
    <div className="board-card">
      <button type="button" className="board-open" onClick={props.onClick} aria-label={`Открыть доску ${props.title}`}>
        {props.custom ? (
          <span className="board-cover board-cover-custom">
            <img src={props.custom} alt="" loading="lazy" />
          </span>
        ) : (
          <span className="board-cover">
            <span className="board-cover-main">{a ? <img src={a} alt="" loading="lazy" /> : null}</span>
            <span className="board-cover-side">
              <span>{b ? <img src={b} alt="" loading="lazy" /> : null}</span>
              <span>{c ? <img src={c} alt="" loading="lazy" /> : null}</span>
            </span>
          </span>
        )}
      </button>
      <div className="board-meta">
        <span className="board-title">
          {props.icon} {props.title}
        </span>
        <span className="board-count">
          {props.count} {plural(props.count, "видео", "видео", "видео")}
          {props.hint ? ` · ${props.hint}` : ""}
        </span>
      </div>
      {props.onEdit && (
        <button type="button" className="board-edit icon-btn" onClick={props.onEdit} aria-label="Изменить доску">
          <IconEdit size={16} />
        </button>
      )}
    </div>
  );
}

/** Шапка открытой доски. */
export function BoardHeader(props: {
  title: string;
  count: number;
  board: Collection | null;
  autoCover?: string;
  onBack: () => void;
}) {
  const { editor } = useApp();
  const [editing, setEditing] = useState(false);
  const cover = mediaUrl(props.board?.cover_key) ?? props.autoCover;
  return (
    <header className="board-header">
      <button type="button" className="link-btn board-back" onClick={props.onBack}>
        <IconBack size={16} /> Все доски
      </button>
      {cover && <img className="board-header-cover" src={cover} alt="" />}
      <h1>{props.title}</h1>
      <p className="muted">
        {props.count} {plural(props.count, "видео", "видео", "видео")}
      </p>
      {editor && props.board && (
        <button type="button" className="btn btn-sm" onClick={() => setEditing(true)}>
          <IconEdit size={14} /> Изменить доску
        </button>
      )}
      {editing && props.board && (
        <BoardDialog board={props.board} autoCover={props.autoCover} onClose={() => setEditing(false)} onDeleted={props.onBack} />
      )}
    </header>
  );
}

/** Создать / переименовать / удалить доску, выбрать картинку-обложку. */
export function BoardDialog({
  board,
  autoCover,
  onClose,
  onDeleted,
}: {
  board: Collection | null;
  autoCover?: string;
  onClose: () => void;
  onDeleted?: () => void;
}) {
  const { run, toast } = useApp();
  const [name, setName] = useState(board?.name ?? "");
  const [emoji, setEmoji] = useState(board?.emoji ?? "");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  // Обложка: новый файл, «убрать свою» или без изменений.
  const [file, setFile] = useState<File | null>(null);
  const [removeCover, setRemoveCover] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!file) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const current = removeCover ? undefined : mediaUrl(board?.cover_key);
  const shown = preview ?? current ?? autoCover;
  const isCustom = !!preview || !!current;

  const pick = (f: File | undefined | null) => {
    if (!f) return;
    if (!f.type.startsWith("image/")) {
      toast("Это не картинка. Подойдут JPG, PNG или WebP.", "error");
      return;
    }
    setFile(f);
    setRemoveCover(false);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files[0]);
  };

  /** Загружает выбранную картинку и возвращает её ключ (или undefined — обложку не трогаем, null — убрать). */
  const uploadCover = async (token: string, id: number): Promise<string | null | undefined> => {
    if (file) {
      const blob = await prepareCover(file);
      const key = coverKey(id);
      await api.uploadMedia(token, key, blob);
      return key;
    }
    return removeCover ? null : undefined;
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    const ok = await run(async (t) => {
      if (board) {
        const cover = await uploadCover(t, board.id);
        return api.patchCollection(t, board.id, {
          name: name.trim(),
          emoji: emoji.trim() || null,
          ...(cover !== undefined ? { cover_key: cover } : {}),
        });
      }
      const { collection } = await api.createCollection(t, name.trim(), emoji.trim() || null);
      const cover = await uploadCover(t, collection.id);
      if (cover) await api.patchCollection(t, collection.id, { cover_key: cover });
      return collection;
    }, board ? "Доска сохранена" : "Доска создана");
    setBusy(false);
    if (ok) onClose();
  };

  const remove = async () => {
    if (!board) return;
    setBusy(true);
    const ok = await run((t) => api.deleteCollection(t, board.id), "Доска удалена");
    setBusy(false);
    if (ok) {
      onClose();
      onDeleted?.();
    }
  };

  return (
    <Modal onClose={onClose} className="dialog" label={board ? "Изменить доску" : "Новая доска"}>
      <form className="dialog-body" onSubmit={submit}>
        <h2>{board ? "Изменить доску" : "Новая доска"}</h2>

        <div
          className={`cover-picker${dragging ? " is-drag" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <button type="button" className="cover-preview" onClick={() => inputRef.current?.click()} aria-label="Выбрать картинку-обложку">
            {shown ? <img src={shown} alt="" /> : <IconImage size={36} />}
            {!isCustom && (
              <span className="cover-hint">{shown ? "Авто: из видео доски" : "Перетащите картинку сюда"}</span>
            )}
          </button>
          <div className="btn-row">
            <button type="button" className="btn btn-sm" onClick={() => inputRef.current?.click()}>
              <IconImage size={16} /> {isCustom ? "Другая картинка" : "Загрузить обложку"}
            </button>
            {isCustom && (
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  setFile(null);
                  setRemoveCover(true);
                }}
              >
                Убрать — брать из видео
              </button>
            )}
          </div>
          <input
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif,image/avif"
            hidden
            onChange={(e) => {
              pick(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </div>

        <div className="board-form-row">
          <label className="field">
            <span>Эмодзи</span>
            <input className="input emoji-input" value={emoji} onChange={(e) => setEmoji(e.target.value)} placeholder="🌲" maxLength={8} />
          </label>
          <label className="field">
            <span>Название</span>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Например, «Природа»" maxLength={100} autoFocus required />
          </label>
        </div>
        <div className="btn-row">
          <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>
            {busy ? "Сохраняю…" : board ? "Сохранить" : "Создать"}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            Отмена
          </button>
        </div>
        {board && (
          <div className="danger-zone">
            {confirm ? (
              <>
                <p className="small">Удалить доску «{board.name}»? Видео останутся в архиве.</p>
                <div className="btn-row">
                  <button type="button" className="btn btn-danger" onClick={remove} disabled={busy}>
                    Удалить доску
                  </button>
                  <button type="button" className="btn" onClick={() => setConfirm(false)}>
                    Отмена
                  </button>
                </div>
              </>
            ) : (
              <button type="button" className="link-btn danger small" onClick={() => setConfirm(true)}>
                Удалить доску…
              </button>
            )}
          </div>
        )}
      </form>
    </Modal>
  );
}
