import { useId, useMemo, useState } from "react";
import { normalizeTag } from "../lib/api";
import { IconClose } from "./Icons";

interface Props {
  value: string[];
  onChange: (tags: string[]) => void;
  /** Существующие теги для автодополнения (уже отсортированы по популярности). */
  suggestions: string[];
  placeholder?: string;
  autoFocus?: boolean;
}

/** Поле тегов: Enter или запятая добавляют тег, Backspace удаляет последний, подсказки — из существующих тегов. */
export function TagInput({ value, onChange, suggestions, placeholder = "Добавить тег", autoFocus }: Props) {
  const [text, setText] = useState("");
  const [highlight, setHighlight] = useState(0);
  const [focused, setFocused] = useState(false);
  const listId = useId();

  const matches = useMemo(() => {
    const q = normalizeTag(text);
    if (!q) return [];
    const starts: string[] = [];
    const contains: string[] = [];
    for (const s of suggestions) {
      if (value.includes(s)) continue;
      if (s.startsWith(q)) starts.push(s);
      else if (s.includes(q)) contains.push(s);
      if (starts.length >= 8) break;
    }
    return [...starts, ...contains].slice(0, 8);
  }, [text, suggestions, value]);

  const add = (raw: string) => {
    const parts = raw.split(/[,\n]/).map(normalizeTag).filter((t): t is string => !!t);
    const next = [...value];
    for (const t of parts) if (!next.includes(t)) next.push(t);
    if (next.length !== value.length) onChange(next);
    setText("");
    setHighlight(0);
  };

  const showList = focused && matches.length > 0;

  return (
    <div className="tag-input">
      {value.map((t) => (
        <span key={t} className="tag-pill">
          #{t}
          <button type="button" onClick={() => onChange(value.filter((x) => x !== t))} aria-label={`Убрать тег ${t}`}>
            <IconClose size={12} />
          </button>
        </span>
      ))}
      <input
        value={text}
        placeholder={value.length ? "" : placeholder}
        autoFocus={autoFocus}
        onChange={(e) => {
          const v = e.target.value;
          if (v.includes(",")) add(v);
          else {
            setText(v);
            setHighlight(0);
          }
        }}
        onFocus={() => setFocused(true)}
        onBlur={() => {
          setFocused(false);
          if (text.trim()) add(text);
        }}
        onPaste={(e) => {
          const pasted = e.clipboardData.getData("text");
          if (/[,\n]/.test(pasted)) {
            e.preventDefault();
            add(text + pasted);
          }
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            if (showList && matches[highlight]) add(matches[highlight]!);
            else if (text.trim()) add(text);
          } else if (e.key === "ArrowDown" && showList) {
            e.preventDefault();
            setHighlight((h) => (h + 1) % matches.length);
          } else if (e.key === "ArrowUp" && showList) {
            e.preventDefault();
            setHighlight((h) => (h - 1 + matches.length) % matches.length);
          } else if (e.key === "Tab" && showList && text) {
            e.preventDefault();
            add(matches[highlight]!);
          } else if (e.key === "Backspace" && !text && value.length) {
            onChange(value.slice(0, -1));
          }
          e.stopPropagation();
        }}
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-label={placeholder}
      />
      {showList && (
        <ul className="tag-suggest" id={listId} role="listbox">
          {matches.map((m, i) => (
            <li
              key={m}
              role="option"
              aria-selected={i === highlight}
              className={i === highlight ? "is-hl" : ""}
              onMouseDown={(e) => {
                e.preventDefault();
                add(m);
              }}
            >
              #{m}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
