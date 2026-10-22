import { useMemo, useState } from "react";
import { api, type Collection, type Video } from "../lib/api";
import { plural } from "../lib/format";
import { useApp } from "../state";
import { IconClose } from "./Icons";
import { TagInput } from "./TagInput";

interface Props {
  selected: Set<string>;
  videos: Map<string, Video>;
  visibleIds: string[];
  collections: Collection[];
  tagSuggestions: string[];
  onSelectAll: () => void;
  onClear: () => void;
  onExit: () => void;
}

type Panel = null | "addTags" | "removeTag" | "addCol" | "removeCol";

/** Нижняя панель массовых действий в режиме выбора. */
export function BulkBar(p: Props) {
  const { run } = useApp();
  const [panel, setPanel] = useState<Panel>(null);
  const [newTags, setNewTags] = useState<string[]>([]);
  const [progress, setProgress] = useState<string | null>(null);
  const ids = [...p.selected];
  const count = ids.length;

  const selectedTags = useMemo(() => {
    const counts = new Map<string, number>();
    for (const id of p.selected) for (const t of p.videos.get(id)?.tags ?? []) counts.set(t, (counts.get(t) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [p.selected, p.videos]);

  /** Меняет теги у выбранных видео: по одному PATCH на видео, по 4 параллельно. */
  const updateTags = async (change: (tags: string[]) => string[], message: string) => {
    const jobs = ids
      .map((id) => p.videos.get(id))
      .filter((v): v is Video => !!v)
      .map((v) => ({ v, next: change(v.tags) }))
      .filter(({ v, next }) => next.join("\n") !== v.tags.join("\n"));
    if (!jobs.length) {
      setPanel(null);
      return;
    }
    let done = 0;
    setProgress(`0 из ${jobs.length}`);
    await run(async (token) => {
      const queue = [...jobs];
      const worker = async () => {
        for (let job = queue.shift(); job; job = queue.shift()) {
          await api.patchVideo(token, job.v.id, { tags: job.next });
          setProgress(`${++done} из ${jobs.length}`);
        }
      };
      await Promise.all([worker(), worker(), worker(), worker()]);
      return true;
    }, message);
    setProgress(null);
    setPanel(null);
    setNewTags([]);
  };

  const collectionAction = async (id: number, action: "add" | "remove") => {
    await run(
      (t) => api.collectionVideos(t, id, action === "add" ? { add: ids } : { remove: ids }),
      action === "add" ? "Добавлено в коллекцию" : "Убрано из коллекции",
    );
    setPanel(null);
  };

  return (
    <div className="bulk" role="region" aria-label="Массовые действия">
      {panel && count > 0 && (
        <div className="bulk-panel">
          {panel === "addTags" && (
            <>
              <TagInput value={newTags} onChange={setNewTags} suggestions={p.tagSuggestions} placeholder="Теги для выбранных видео" autoFocus />
              <button
                type="button"
                className="btn btn-primary"
                disabled={!newTags.length || !!progress}
                onClick={() => updateTags((tags) => [...new Set([...tags, ...newTags])], "Теги добавлены")}
              >
                Добавить
              </button>
            </>
          )}
          {panel === "removeTag" && (
            <div className="tag-cloud">
              {selectedTags.length === 0 && <span className="muted small">У выбранных видео нет тегов</span>}
              {selectedTags.map(([t, n]) => (
                <button key={t} type="button" className="tag-chip" disabled={!!progress} onClick={() => updateTags((tags) => tags.filter((x) => x !== t), `Тег «${t}» убран`)}>
                  #{t} <span>{n}</span> <IconClose size={12} />
                </button>
              ))}
            </div>
          )}
          {(panel === "addCol" || panel === "removeCol") && (
            <div className="pill-row">
              {p.collections.length === 0 && <span className="muted small">Коллекций нет — создайте их в «Коллекции и теги»</span>}
              {p.collections.map((c) => (
                <button key={c.id} type="button" className="pill" onClick={() => collectionAction(c.id, panel === "addCol" ? "add" : "remove")}>
                  {c.emoji} {c.name}
                </button>
              ))}
            </div>
          )}
          {progress && <span className="muted small">Сохранение: {progress}</span>}
        </div>
      )}

      <div className="bulk-main">
        <span className="bulk-count">
          {count ? `Выбрано ${count} ${plural(count, "видео", "видео", "видео")}` : "Нажимайте на видео, чтобы выбрать"}
        </span>
        <div className="bulk-actions">
          <Toggle on={panel === "addTags"} disabled={!count} onClick={() => setPanel(panel === "addTags" ? null : "addTags")}>
            + Теги
          </Toggle>
          <Toggle on={panel === "removeTag"} disabled={!count} onClick={() => setPanel(panel === "removeTag" ? null : "removeTag")}>
            − Тег
          </Toggle>
          <Toggle on={panel === "addCol"} disabled={!count} onClick={() => setPanel(panel === "addCol" ? null : "addCol")}>
            В коллекцию
          </Toggle>
          <Toggle on={panel === "removeCol"} disabled={!count} onClick={() => setPanel(panel === "removeCol" ? null : "removeCol")}>
            Из коллекции
          </Toggle>
          <button type="button" className="btn btn-sm" onClick={p.onSelectAll}>
            Выбрать все найденные ({p.visibleIds.length})
          </button>
          {count > 0 && (
            <button type="button" className="btn btn-sm" onClick={p.onClear}>
              Снять выбор
            </button>
          )}
          <button type="button" className="icon-btn" onClick={p.onExit} aria-label="Выйти из режима выбора">
            <IconClose />
          </button>
        </div>
      </div>
    </div>
  );
}

function Toggle({ on, disabled, onClick, children }: { on: boolean; disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" className={`btn btn-sm${on ? " is-on" : ""}`} disabled={disabled} onClick={onClick} aria-pressed={on}>
      {children}
    </button>
  );
}
