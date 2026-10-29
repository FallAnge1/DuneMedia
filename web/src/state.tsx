import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiRequestError, fetchLibrary, type Library } from "./lib/api";
import { readStorage, writeStorage } from "./lib/storage";

// ---------------------------------------------------------------------------
// Уведомления
// ---------------------------------------------------------------------------

export interface Toast {
  id: number;
  text: string;
  kind: "info" | "error" | "success";
}

// ---------------------------------------------------------------------------
// Редактор: вход на сайт по токену загрузчика
// ---------------------------------------------------------------------------

export interface Editor {
  token: string;
  name: string;
}

const EDITOR_KEY = "va.editor";

interface AppState {
  library: Library | null;
  loadError: string | null;
  reload: () => Promise<void>;
  editor: Editor | null;
  login: (token: string) => Promise<void>;
  logout: () => void;
  toasts: Toast[];
  toast: (text: string, kind?: Toast["kind"]) => void;
  dismissToast: (id: number) => void;
  /** Выполняет запрос редактора: показывает ошибку, при успехе перечитывает архив. */
  run: <T>(action: (token: string) => Promise<T>, success?: string) => Promise<T | undefined>;
}

const Ctx = createContext<AppState | null>(null);

export function useApp(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp вне AppProvider");
  return ctx;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [library, setLibrary] = useState<Library | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editor, setEditor] = useState<Editor | null>(() => readStorage<Editor | null>(EDITOR_KEY, null));
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastId = useRef(0);

  const dismissToast = useCallback((id: number) => setToasts((list) => list.filter((t) => t.id !== id)), []);
  const toast = useCallback(
    (text: string, kind: Toast["kind"] = "info") => {
      const id = ++toastId.current;
      setToasts((list) => [...list.slice(-3), { id, text, kind }]);
      window.setTimeout(() => dismissToast(id), kind === "error" ? 6000 : 3000);
    },
    [dismissToast],
  );

  const reload = useCallback(async () => {
    try {
      const lib = await fetchLibrary();
      // Архив не менялся (та же ревизия) — оставляем прежний объект: иначе вся страница
      // пересчитала бы выдачу и заново построила индекс поиска.
      setLibrary((prev) => (prev && prev.rev === lib.rev ? prev : lib));
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Не удалось загрузить архив");
    }
  }, []);

  useEffect(() => {
    void reload();
    // Архив мог измениться, пока вкладка была в фоне. ETag делает повторный запрос почти бесплатным.
    const onVisible = () => {
      if (document.visibilityState === "visible") void reload();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [reload]);

  const logout = useCallback(() => {
    setEditor(null);
    writeStorage(EDITOR_KEY, null);
  }, []);

  const login = useCallback(async (token: string) => {
    const { uploader } = await api.me(token.trim());
    const next = { token: token.trim(), name: uploader.name };
    setEditor(next);
    writeStorage(EDITOR_KEY, next);
  }, []);

  // Проверяем сохранённый токен: его могли отозвать.
  useEffect(() => {
    if (!editor) return;
    api.me(editor.token).catch((err: unknown) => {
      if (err instanceof ApiRequestError && (err.status === 401 || err.status === 403)) {
        logout();
        toast("Токен редактора больше не действует. Войдите заново.", "error");
      }
    });
    // только при загрузке страницы
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const run = useCallback(
    async <T,>(action: (token: string) => Promise<T>, success?: string): Promise<T | undefined> => {
      if (!editor) {
        toast("Войдите как редактор", "error");
        return undefined;
      }
      try {
        const result = await action(editor.token);
        await reload();
        if (success && result !== undefined) toast(success, "success");
        return result;
      } catch (err) {
        if (err instanceof ApiRequestError && (err.status === 401 || err.status === 403)) logout();
        toast(err instanceof Error ? err.message : "Ошибка", "error");
        await reload();
        return undefined;
      }
    },
    [editor, reload, toast, logout],
  );

  const value = useMemo(
    () => ({ library, loadError, reload, editor, login, logout, toasts, toast, dismissToast, run }),
    [library, loadError, reload, editor, login, logout, toasts, toast, dismissToast, run],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
