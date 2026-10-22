import { useCallback, useEffect, useState } from "react";

/** localStorage с защитой от ошибок (приватный режим, запрет cookies). */
export function readStorage<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function writeStorage(key: string, value: unknown): void {
  try {
    if (value === null || value === undefined) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* хранилище недоступно — значение живёт до перезагрузки */
  }
}

/** Состояние, которое переживает перезагрузку и синхронизируется между вкладками. */
export function useStoredState<T>(key: string, fallback: T): [T, (value: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => readStorage(key, fallback));

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === key) setValue(readStorage(key, fallback));
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
    // fallback намеренно не в зависимостях: это начальное значение
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const set = useCallback(
    (next: T | ((prev: T) => T)) => {
      setValue((prev) => {
        const resolved = typeof next === "function" ? (next as (p: T) => T)(prev) : next;
        writeStorage(key, resolved);
        return resolved;
      });
    },
    [key],
  );
  return [value, set];
}
