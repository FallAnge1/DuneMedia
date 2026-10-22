/** Подготовка картинки-обложки в браузере: уменьшение до 1600 px и JPEG ~85 % — обычно 150–400 КБ. */

const MAX_SIDE = 1600;
const MAX_BYTES = 7 * 1024 * 1024;

export class ImageError extends Error {}

async function decode(file: File): Promise<{ draw: (ctx: CanvasRenderingContext2D, w: number, h: number) => void; width: number; height: number }> {
  if ("createImageBitmap" in window) {
    try {
      const bmp = await createImageBitmap(file);
      return { draw: (ctx, w, h) => ctx.drawImage(bmp, 0, 0, w, h), width: bmp.width, height: bmp.height };
    } catch {
      /* попробуем через <img> */
    }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error("decode"));
      el.src = url;
    });
    return { draw: (ctx, w, h) => ctx.drawImage(img, 0, 0, w, h), width: img.naturalWidth, height: img.naturalHeight };
  } catch {
    throw new ImageError("Не получилось открыть картинку. Подойдут JPG, PNG или WebP.");
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

export async function prepareCover(file: File): Promise<Blob> {
  if (!file.type.startsWith("image/") && !/\.(jpe?g|png|webp|gif|bmp|avif)$/i.test(file.name)) {
    throw new ImageError("Это не картинка. Подойдут JPG, PNG или WebP.");
  }
  const src = await decode(file);
  if (!src.width || !src.height) throw new ImageError("Пустая картинка");
  const scale = Math.min(1, MAX_SIDE / Math.max(src.width, src.height));
  const w = Math.max(1, Math.round(src.width * scale));
  const h = Math.max(1, Math.round(src.height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new ImageError("Браузер не может обработать картинку");
  ctx.fillStyle = "#ffffff"; // прозрачный фон PNG → белый
  ctx.fillRect(0, 0, w, h);
  src.draw(ctx, w, h);
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.86));
  if (!blob) throw new ImageError("Не удалось сжать картинку");
  if (blob.size > MAX_BYTES) throw new ImageError("Картинка слишком большая даже после сжатия");
  return blob;
}

export function coverKey(boardId: number): string {
  const rand = Math.random().toString(36).slice(2, 10);
  return `covers/board-${boardId}-${rand}.jpg`;
}
