import { Hono } from "hono";
import type { AppEnv } from "../types";
import { requireUploader } from "../lib/auth";
import { ApiError, badRequest, readJsonObject } from "../lib/http";

/**
 * POST /api/ai/tag — прокси к Cloudflare Workers AI для ИИ-тегов (одно из звеньев цепочки в загрузчике).
 *
 * Тело: { images: string[] (jpeg в base64, можно data:-URL), prompt: string, system?: string,
 *         model?: string (только @cf/...), max_tokens?: number }
 * Ответ: { provider: "workers-ai", model, text, json } — json = разобранный объект или null.
 * Нормализация тегов делается в загрузчике (там же сопоставление с существующими тегами).
 *
 * Коды ошибок, по которым загрузчик переходит к следующему провайдеру:
 *  429 ai_quota — исчерпан дневной бесплатный лимит нейронов; 502 ai_error; 503 ai_unavailable.
 */
export const aiRoutes = new Hono<AppEnv>();
aiRoutes.use("*", requireUploader);

const MAX_IMAGES = 6;
const MAX_IMAGE_B64 = 2_000_000; // ~1.5 МБ на картинку

/** Достаёт JSON-объект из ответа модели (с учётом ```json-ограждений и текста вокруг). */
export function extractJson(text: string): Record<string, unknown> | null {
  const cleaned = text.replace(/```(?:json)?/gi, "");
  const start = cleaned.indexOf("{");
  const end = cleaned.lastIndexOf("}");
  if (start === -1 || end <= start) return null;
  try {
    const parsed: unknown = JSON.parse(cleaned.slice(start, end + 1));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function toDataUrl(image: string): string {
  if (image.startsWith("data:image/")) return image;
  return `data:image/jpeg;base64,${image}`;
}

function responseText(result: unknown): string {
  if (typeof result === "string") return result;
  const r = result as { response?: unknown; choices?: { message?: { content?: unknown } }[] };
  if (typeof r?.response === "string") return r.response;
  if (r?.response && typeof r.response === "object") return JSON.stringify(r.response);
  const content = r?.choices?.[0]?.message?.content;
  if (typeof content === "string") return content;
  return "";
}

aiRoutes.post("/tag", async (c) => {
  const body = await readJsonObject(c);
  const images = body.images;
  if (!Array.isArray(images) || images.length === 0 || !images.every((x) => typeof x === "string")) {
    throw badRequest("Поле «images» должно быть непустым массивом картинок в base64");
  }
  if (images.length > MAX_IMAGES) throw badRequest(`Не больше ${MAX_IMAGES} картинок`);
  if ((images as string[]).some((x) => x.length > MAX_IMAGE_B64)) throw badRequest("Картинка слишком большая, уменьшите до ~512 px");
  if (typeof body.prompt !== "string" || !body.prompt.trim()) throw badRequest("Поле «prompt» обязательно");
  if (body.prompt.length > 20_000) throw badRequest("Слишком длинный prompt");
  const system = typeof body.system === "string" ? body.system.slice(0, 10_000) : undefined;

  const model = typeof body.model === "string" && body.model ? body.model : c.env.AI_MODEL;
  if (!/^@cf\/[\w.-]+\/[\w.:-]+$/.test(model)) throw badRequest("Модель должна быть вида @cf/<автор>/<модель>");
  const maxTokens = Math.min(Math.max(Number(body.max_tokens) || 700, 64), 2048);

  if (!c.env.AI) throw new ApiError(503, "ai_unavailable", "Workers AI не подключён к Worker'у");

  const messages = [
    ...(system ? [{ role: "system", content: system }] : []),
    {
      role: "user",
      content: [
        { type: "text", text: body.prompt },
        ...(images as string[]).map((img) => ({ type: "image_url", image_url: { url: toDataUrl(img) } })),
      ],
    },
  ];
  const run = () =>
    c.env.AI.run(model as keyof AiModels, { messages, max_tokens: maxTokens, temperature: 0.2 } as never) as Promise<unknown>;

  let result: unknown;
  try {
    result = await run();
  } catch (err) {
    const message = String((err as Error)?.message ?? err);
    // Llama 3.2 Vision требует один раз принять лицензию Meta запросом "agree".
    if (/agree/i.test(message) && /licen|5016|prior to using/i.test(message)) {
      try {
        await c.env.AI.run(model as keyof AiModels, { prompt: "agree" } as never);
        result = await run();
      } catch (err2) {
        throw mapAiError(err2);
      }
    } else {
      throw mapAiError(err);
    }
  }

  const text = responseText(result);
  return c.json({ provider: "workers-ai", model, text, json: extractJson(text) });
});

function mapAiError(err: unknown): ApiError {
  const message = String((err as Error)?.message ?? err);
  console.error("Ошибка Workers AI", message);
  if (/3036|daily free allocation|neurons|rate limit|429|capacity/i.test(message)) {
    return new ApiError(429, "ai_quota", "Лимит Workers AI исчерпан, попробуйте позже", { provider_message: message.slice(0, 300) });
  }
  return new ApiError(502, "ai_error", "Workers AI вернул ошибку", { provider_message: message.slice(0, 300) });
}
