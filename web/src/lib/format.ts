export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

export function formatSize(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  const digits = value >= 100 || unit === 0 ? 0 : 1;
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: digits })} ${units[unit]}`;
}

export function formatDate(ms: number): string {
  return new Date(ms).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
}

export function formatFps(fps: number | null | undefined): string {
  if (!fps) return "—";
  return `${Number(fps.toFixed(2))} к/с`;
}

/** Склонение: plural(5, "видео", "видео", "видео"), plural(n, "тег", "тега", "тегов"). */
export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}

export const telegramUrl = (channel: string, messageId: number) => `https://t.me/${channel}/${messageId}`;
