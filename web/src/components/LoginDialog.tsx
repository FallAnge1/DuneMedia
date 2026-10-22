import { useState, type FormEvent } from "react";
import { useApp } from "../state";
import { Modal } from "./Modal";

/** Вход в режим редактирования по персональному токену загрузчика. */
export function LoginDialog({ onClose }: { onClose: () => void }) {
  const { login, toast } = useApp();
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(token);
      toast("Режим редактирования включён", "success");
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось войти");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal onClose={onClose} className="dialog" label="Вход для редактирования">
      <form className="dialog-body" onSubmit={submit}>
        <h2>Вход для редактирования</h2>
        <p className="muted">
          Смотреть архив можно без входа. Чтобы менять названия, теги и коллекции, вставьте свой токен загрузчика — тот же, что в
          программе. Его выдаёт администратор.
        </p>
        <label className="field">
          <span>Токен</span>
          <input
            className="input mono"
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder="va_…"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            autoFocus
            required
          />
        </label>
        {error && <p className="error-text">{error}</p>}
        <p className="muted small">Токен хранится только в этом браузере. На чужом компьютере не забудьте выйти.</p>
        <div className="btn-row">
          <button type="submit" className="btn btn-primary" disabled={busy || !token.trim()}>
            {busy ? "Проверка…" : "Войти"}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            Отмена
          </button>
        </div>
      </form>
    </Modal>
  );
}
