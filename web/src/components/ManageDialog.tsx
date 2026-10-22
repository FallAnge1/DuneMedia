import { useMemo, useState } from "react";
import { api, ApiRequestError, normalizeTag, type Collection, type Tag } from "../lib/api";
import { plural } from "../lib/format";
import { useApp } from "../state";
import { IconCheck, IconClose, IconDown, IconEdit, IconTrash, IconUp } from "./Icons";
import { Modal } from "./Modal";

interface Props {
  collections: Collection[];
  tags: Tag[];
  onClose: () => void;
}

/** Управление коллекциями (создать, переименовать, упорядочить, удалить) и тегами (переименовать, слить, удалить). */
export function ManageDialog({ collections, tags, onClose }: Props) {
  const [tab, setTab] = useState<"collections" | "tags">("collections");
  return (
    <Modal onClose={onClose} className="dialog dialog-wide" label="Коллекции и теги">
      <div className="dialog-body">
        <div className="dialog-head">
          <div className="segmented" role="tablist">
            <button type="button" role="tab" aria-selected={tab === "collections"} className={tab === "collections" ? "is-on" : ""} onClick={() => setTab("collections")}>
              Коллекции
            </button>
            <button type="button" role="tab" aria-selected={tab === "tags"} className={tab === "tags" ? "is-on" : ""} onClick={() => setTab("tags")}>
              Теги
            </button>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Закрыть">
            <IconClose />
          </button>
        </div>
        {tab === "collections" ? <Collections collections={collections} /> : <Tags tags={tags} />}
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------

function Collections({ collections }: { collections: Collection[] }) {
  const { run } = useApp();
  const [name, setName] = useState("");
  const [emoji, setEmoji] = useState("");
  const [busy, setBusy] = useState(false);

  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    const ok = await run((t) => api.createCollection(t, name.trim(), emoji.trim() || null), "Коллекция создана");
    setBusy(false);
    if (ok) {
      setName("");
      setEmoji("");
    }
  };

  const move = async (index: number, delta: number) => {
    const ids = collections.map((c) => c.id);
    const j = index + delta;
    if (j < 0 || j >= ids.length) return;
    [ids[index], ids[j]] = [ids[j]!, ids[index]!];
    await run((t) => api.orderCollections(t, ids));
  };

  return (
    <div className="manage">
      <form
        className="manage-create"
        onSubmit={(e) => {
          e.preventDefault();
          void create();
        }}
      >
        <input className="input emoji-input" value={emoji} onChange={(e) => setEmoji(e.target.value)} placeholder="🎬" maxLength={8} aria-label="Эмодзи" />
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Новая коллекция" maxLength={100} aria-label="Название коллекции" />
        <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>
          Создать
        </button>
      </form>

      {collections.length === 0 && <p className="muted">Коллекций пока нет.</p>}
      <ul className="manage-list">
        {collections.map((c, i) => (
          <CollectionRow key={c.id} c={c} first={i === 0} last={i === collections.length - 1} onMove={(d) => move(i, d)} />
        ))}
      </ul>
    </div>
  );
}

function CollectionRow({ c, first, last, onMove }: { c: Collection; first: boolean; last: boolean; onMove: (delta: number) => void }) {
  const { run } = useApp();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(c.name);
  const [emoji, setEmoji] = useState(c.emoji ?? "");
  const [confirm, setConfirm] = useState(false);

  const save = async () => {
    const ok = await run((t) => api.patchCollection(t, c.id, { name: name.trim(), emoji: emoji.trim() || null }), "Сохранено");
    if (ok) setEditing(false);
  };

  if (editing) {
    return (
      <li className="manage-row">
        <form
          className="manage-create"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <input className="input emoji-input" value={emoji} onChange={(e) => setEmoji(e.target.value)} maxLength={8} aria-label="Эмодзи" />
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} autoFocus aria-label="Название" />
          <button type="submit" className="icon-btn" aria-label="Сохранить" disabled={!name.trim()}>
            <IconCheck />
          </button>
          <button type="button" className="icon-btn" aria-label="Отмена" onClick={() => setEditing(false)}>
            <IconClose />
          </button>
        </form>
      </li>
    );
  }

  return (
    <li className="manage-row">
      <span className="manage-name">
        {c.emoji} {c.name}
      </span>
      <span className="muted small">
        {c.count} {plural(c.count, "видео", "видео", "видео")}
      </span>
      {confirm ? (
        <span className="manage-actions">
          <span className="small">Удалить? Видео останутся.</span>
          <button type="button" className="btn btn-danger btn-sm" onClick={() => run((t) => api.deleteCollection(t, c.id), "Коллекция удалена")}>
            Удалить
          </button>
          <button type="button" className="btn btn-sm" onClick={() => setConfirm(false)}>
            Нет
          </button>
        </span>
      ) : (
        <span className="manage-actions">
          <button type="button" className="icon-btn" onClick={() => onMove(-1)} disabled={first} aria-label="Выше">
            <IconUp />
          </button>
          <button type="button" className="icon-btn" onClick={() => onMove(1)} disabled={last} aria-label="Ниже">
            <IconDown />
          </button>
          <button type="button" className="icon-btn" onClick={() => setEditing(true)} aria-label="Переименовать">
            <IconEdit />
          </button>
          <button type="button" className="icon-btn" onClick={() => setConfirm(true)} aria-label="Удалить">
            <IconTrash />
          </button>
        </span>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------

function Tags({ tags }: { tags: Tag[] }) {
  const { run, toast } = useApp();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const [target, setTarget] = useState<number | "">("");
  const [renaming, setRenaming] = useState<number | null>(null);
  const [newName, setNewName] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase().replace(/^#/, "");
    return tags.filter((t) => !q || t.name.includes(q));
  }, [tags, query]);
  const unused = tags.filter((t) => t.count === 0).length;
  const byId = (id: number) => tags.find((t) => t.id === id);

  const toggle = (id: number) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const rename = async (tag: Tag) => {
    const name = normalizeTag(newName);
    if (!name || name === tag.name) {
      setRenaming(null);
      return;
    }
    try {
      await run(async (t) => {
        try {
          return await api.renameTag(t, tag.id, name);
        } catch (err) {
          // Такой тег уже есть — предлагаем слить.
          if (err instanceof ApiRequestError && err.code === "tag_exists") {
            setSelected([tag.id]);
            setTarget(Number(err.details.existing_id));
            toast(`Тег «${name}» уже есть. Выбраны оба — нажмите «Слить».`, "info");
            return undefined;
          }
          throw err;
        }
      }, "Тег переименован");
    } finally {
      setRenaming(null);
    }
  };

  const merge = async () => {
    if (target === "" || selected.length === 0) return;
    const sources = selected.filter((id) => id !== target);
    if (!sources.length) return;
    const ok = await run((t) => api.mergeTags(t, sources, target), `Теги слиты в «${byId(target)?.name}»`);
    if (ok) {
      setSelected([]);
      setTarget("");
    }
  };

  return (
    <div className="manage">
      <div className="manage-create">
        <input className="input" type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Найти тег" aria-label="Найти тег" />
        {unused > 0 && (
          <button type="button" className="btn" onClick={() => run((t) => api.deleteUnusedTags(t), "Неиспользуемые теги удалены")}>
            Удалить неиспользуемые ({unused})
          </button>
        )}
      </div>

      {selected.length > 0 && (
        <div className="merge-bar">
          <span>
            Выбрано {selected.length}. Слить в:
          </span>
          <select className="select" value={target} onChange={(e) => setTarget(e.target.value ? Number(e.target.value) : "")} aria-label="Целевой тег">
            <option value="">— выберите тег —</option>
            {tags.map((t) => (
              <option key={t.id} value={t.id}>
                #{t.name} ({t.count})
              </option>
            ))}
          </select>
          <button type="button" className="btn btn-primary btn-sm" onClick={merge} disabled={target === "" || selected.every((id) => id === target)}>
            Слить
          </button>
          <button type="button" className="btn btn-sm" onClick={() => setSelected([])}>
            Снять выбор
          </button>
        </div>
      )}

      <p className="muted small">
        Изменения тегов меняют подписи постов — их обновит программа-загрузчик. Отметьте несколько тегов, чтобы слить их в один.
      </p>

      <ul className="manage-list">
        {filtered.slice(0, 300).map((t) => (
          <li key={t.id} className="manage-row">
            <input type="checkbox" checked={selected.includes(t.id)} onChange={() => toggle(t.id)} aria-label={`Выбрать тег ${t.name}`} />
            {renaming === t.id ? (
              <form
                className="manage-create"
                onSubmit={(e) => {
                  e.preventDefault();
                  void rename(t);
                }}
              >
                <input className="input" value={newName} onChange={(e) => setNewName(e.target.value)} autoFocus aria-label="Новое имя тега" />
                <button type="submit" className="icon-btn" aria-label="Сохранить">
                  <IconCheck />
                </button>
                <button type="button" className="icon-btn" onClick={() => setRenaming(null)} aria-label="Отмена">
                  <IconClose />
                </button>
              </form>
            ) : (
              <>
                <span className="manage-name">#{t.name}</span>
                <span className="muted small">{t.count}</span>
                <span className="manage-actions">
                  <button
                    type="button"
                    className="icon-btn"
                    onClick={() => {
                      setRenaming(t.id);
                      setNewName(t.name);
                    }}
                    aria-label="Переименовать"
                  >
                    <IconEdit />
                  </button>
                  <button
                    type="button"
                    className="icon-btn"
                    onClick={() => {
                      if (window.confirm(`Удалить тег «${t.name}» у ${t.count} ${plural(t.count, "видео", "видео", "видео")}?`)) {
                        void run((tok) => api.deleteTag(tok, t.id), "Тег удалён");
                      }
                    }}
                    aria-label="Удалить"
                  >
                    <IconTrash />
                  </button>
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
      {filtered.length > 300 && <p className="muted small">Показаны первые 300 — уточните поиск.</p>}
    </div>
  );
}
