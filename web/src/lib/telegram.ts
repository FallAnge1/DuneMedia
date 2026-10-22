import { telegramUrl } from "./format";

/**
 * Открывает пост: сначала приложение Telegram (tg://), если оно не перехватило переход —
 * веб-версию t.me. Признак того, что приложение открылось, — страница теряет фокус или скрывается.
 */
export function openInTelegram(channel: string, messageId: number): void {
  const web = telegramUrl(channel, messageId);
  const app = `tg://resolve?domain=${encodeURIComponent(channel)}&post=${messageId}`;

  let appOpened = false;
  const markOpened = () => {
    appOpened = true;
  };
  window.addEventListener("blur", markOpened, { once: true });
  document.addEventListener("visibilitychange", markOpened, { once: true });

  window.location.href = app;

  window.setTimeout(() => {
    window.removeEventListener("blur", markOpened);
    document.removeEventListener("visibilitychange", markOpened);
    // В той же вкладке: новое окно не из обработчика клика заблокировал бы браузер.
    if (!appOpened && !document.hidden) window.location.assign(web);
  }, 1200);
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Запасной вариант для старых браузеров и http.
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}
