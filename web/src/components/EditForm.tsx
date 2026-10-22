import { useState, type FormEvent } from "react";
import { api, type Collection, type Video } from "../lib/api";
import { useApp } from "../state";
import { TagInput } from "./TagInput";

interface Props {
  video: Video;
  collections: Collection[];
  tagSuggestions: string[];
  onDone: () => void;
  onDeleted: () => void;
}

/** Редактирование видео на сайте (для тех, кто вошёл по токену загрузчика). */
export function EditForm({ video, collections, tagSuggestions, onDone, onDeleted }: Props) {
  const { run } = useApp();
  const [title, setTitle] = useState(video.title);
  const [description, setDescription] = useState(video.description ?? "");
  const [tags, setTags] = useState(video.tags);
  const [cols, setCols] = useState(video.collections);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    const body: Parameters<typeof api.patchVideo>[2] = {};
    if (title.trim() !== video.title) body.title = title.trim();
    if ((description.trim() || null) !== video.description) body.description = description.trim() || null;
    if (tags.join("\n") !== video.tags.join("\n")) body.tags = tags;
    if ([...cols].sort().join() !== [...video.collections].sort().join()) body.collections = cols;
    const result = Object.keys(body).length ? await run((t) => api.patchVideo(t, video.id, body), "Сохранено") : true;
    setBusy(false);
    if (result) onDone();
  };

  const remove = async () => {
    setBusy(true);
    const result = await run((t) => api.deleteVideo(t, video.id), "Видео удалено с сайта");
    setBusy(false);
    if (result) onDeleted();
  };

  return (
    <form className="edit-form" onSubmit={submit}>
      <label className="field">
        <span>Название</span>
        <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} required autoFocus />
      </label>
      <label className="field">
        <span>Описание</span>
        <textarea className="input" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={4000} />
      </label>
      <div className="field">
        <span>Теги</span>
        <TagInput value={tags} onChange={setTags} suggestions={tagSuggestions} />
      </div>
      {collections.length > 0 && (
        <fieldset className="field">
          <legend>Коллекции</legend>
          <div className="col-checks">
            {collections.map((c) => (
              <label key={c.id} className="check">
                <input
                  type="checkbox"
                  checked={cols.includes(c.id)}
                  onChange={(e) => setCols(e.target.checked ? [...cols, c.id] : cols.filter((x) => x !== c.id))}
                />
                <span className="check-label">
                  {c.emoji} {c.name}
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      )}

      <p className="muted small">Подпись поста в Telegram обновит программа-загрузчик: сайт не может менять посты.</p>

      <div className="btn-row">
        <button type="submit" className="btn btn-primary" disabled={busy || !title.trim()}>
          {busy ? "Сохранение…" : "Сохранить"}
        </button>
        <button type="button" className="btn" onClick={onDone} disabled={busy}>
          Отмена
        </button>
      </div>

      <div className="danger-zone">
        {confirmDelete ? (
          <>
            <p className="small">
              Удалить видео с сайта? Пост в Telegram останется — удалить его можно в программе-загрузчике.
            </p>
            <div className="btn-row">
              <button type="button" className="btn btn-danger" onClick={remove} disabled={busy}>
                Удалить с сайта
              </button>
              <button type="button" className="btn" onClick={() => setConfirmDelete(false)} disabled={busy}>
                Отмена
              </button>
            </div>
          </>
        ) : (
          <button type="button" className="link-btn danger small" onClick={() => setConfirmDelete(true)}>
            Удалить видео с сайта…
          </button>
        )}
      </div>
    </form>
  );
}
