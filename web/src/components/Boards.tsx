import { useState, type FormEvent } from "react";
import { api, type Collection } from "../lib/api";
import { plural } from "../lib/format";
import { useApp } from "../state";
import { IconBack, IconEdit, IconHeart, IconPlus } from "./Icons";
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

      {dialog && <BoardDialog board={dialog === "new" ? null : dialog} onClose={() => setDialog(null)} />}
    </section>
  );
}

function BoardCard(props: {
  title: string;
  count: number;
  covers: string[];
  icon?: React.ReactNode;
  hint?: string;
  onClick: () => void;
  onEdit?: () => void;
}) {
  const [a, b, c] = props.covers;
  return (
    <div className="board-card">
      <button type="button" className="board-open" onClick={props.onClick} aria-label={`Открыть доску ${props.title}`}>
        <span className="board-cover">
          <span className="board-cover-main">{a ? <img src={a} alt="" loading="lazy" /> : null}</span>
          <span className="board-cover-side">
            <span>{b ? <img src={b} alt="" loading="lazy" /> : null}</span>
            <span>{c ? <img src={c} alt="" loading="lazy" /> : null}</span>
          </span>
        </span>
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
  onBack: () => void;
}) {
  const { editor } = useApp();
  const [editing, setEditing] = useState(false);
  return (
    <header className="board-header">
      <button type="button" className="link-btn board-back" onClick={props.onBack}>
        <IconBack size={16} /> Все доски
      </button>
      <h1>{props.title}</h1>
      <p className="muted">
        {props.count} {plural(props.count, "видео", "видео", "видео")}
      </p>
      {editor && props.board && (
        <button type="button" className="btn btn-sm" onClick={() => setEditing(true)}>
          <IconEdit size={14} /> Изменить доску
        </button>
      )}
      {editing && props.board && <BoardDialog board={props.board} onClose={() => setEditing(false)} onDeleted={props.onBack} />}
    </header>
  );
}

/** Создать / переименовать / удалить доску. */
export function BoardDialog({ board, onClose, onDeleted }: { board: Collection | null; onClose: () => void; onDeleted?: () => void }) {
  const { run } = useApp();
  const [name, setName] = useState(board?.name ?? "");
  const [emoji, setEmoji] = useState(board?.emoji ?? "");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    const ok = board
      ? await run((t) => api.patchCollection(t, board.id, { name: name.trim(), emoji: emoji.trim() || null }), "Доска сохранена")
      : await run((t) => api.createCollection(t, name.trim(), emoji.trim() || null), "Доска создана");
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
            {board ? "Сохранить" : "Создать"}
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
