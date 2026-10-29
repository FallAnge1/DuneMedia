# API видеоархива

Все ответы — JSON. Ошибки приходят в виде:

```json
{ "error": { "code": "bad_request", "message": "Понятное сообщение на русском" } }
```

Эндпоинты записи требуют заголовок `Authorization: Bearer <токен загрузчика>`.
Токен выдаёт администратор командой `npm run uploader:create -- "Имя"` (см. ниже).

## Публичные (только чтение)

| Метод и путь | Что делает |
|---|---|
| `GET /api/library` | Весь архив одним JSON: `{ rev, generated_at, videos[], tags[], collections[] }`. Есть `ETag` (по ревизии архива) и ответ `304`, если ничего не менялось |
| `GET /api/tags` | `{ tags: [{ id, name, count }] }`, по убыванию популярности |
| `GET /api/collections` | `{ collections: [{ id, name, emoji, sort_order, cover_key, count }] }` |
| `GET /api/videos/:id` | Одно видео с тегами и коллекциями |
| `GET /api/search?q=…&limit=100` | Полнотекстовый поиск (FTS5, по префиксам слов): `{ ids: [...] }` |
| `GET /media/<ключ>` | Превью и постеры из R2. Поддерживает `Range`, `ETag`, кэшируется на год |
| `GET /api/health` | `{ ok: true }` |

Видео в ответах:

```json
{
  "id": "uuid", "tg_channel": "my_archive", "tg_message_id": 15,
  "title": "Закат над морем", "description": null,
  "file_name": "sunset.mov", "file_size": 734003200,
  "duration": 12.5, "width": 3840, "height": 2160, "fps": 25, "codec": "h264",
  "orientation": "horizontal", "resolution_label": "4K",
  "preview_key": "previews/<id>-a1b2.mp4", "poster_key": "posters/<id>-a1b2.jpg", "media_type": "video",
  "uploaded_by": "Анна", "caption_dirty": 0,
  "created_at": 1760000000000, "updated_at": 1760000000000,
  "tags": ["закат", "море"], "collections": [1, 3]
}
```

`orientation` и `resolution_label` сервер всегда вычисляет сам по `width` и `height`.

`caption_dirty: 1` — подпись поста в Telegram устарела: название, описание или теги поменяли на сайте
(сайт не может править посты). Программа-загрузчик находит такие видео, обновляет подписи
и отправляет `PATCH` с `caption_synced: true`, после чего флаг сбрасывается.

## Для загрузчиков (нужен токен)

| Метод и путь | Тело | Ответ |
|---|---|---|
| `GET /api/me` | — | `{ uploader: { id, name } }` — проверка токена |
| `GET /api/videos/check-hash/:sha256` | — | `{ duplicate, videos[] }` |
| `POST /api/videos` | `{ id?, tg_channel, tg_message_id, title, description?, file_name?, file_size?, file_hash?, duration?, width?, height?, fps?, codec?, preview_key?, poster_key?, media_type?: "video" | "photo", tags?: string[], collections?: number[], created_at? }` | `201 { video }`. Повтор с тем же `id` и тем же постом → `200 { video, existing: true }`. Тот же пост под другим id → `409 tg_post_exists`. У фото (`media_type: "photo"`) нет `preview_key`, `duration` и `fps`; по умолчанию `video` |
| `PATCH /api/videos/:id` | любые поля из POST; `tags` и `collections` заменяются целиком; `caption_synced: true` — подпись в Telegram уже обновлена | `{ video }`. Заменённые превью/постеры удаляются из R2. Правка названия, описания или тегов без `caption_synced` ставит `caption_dirty = 1` |
| `DELETE /api/videos/:id` | — | `{ deleted: video }` — запись и файлы в R2 удалены. Пост в Telegram удаляет загрузчик |
| `PUT /api/media/<ключ>` | сырые байты файла (до 8 МБ) | `201 { key, size, url }` |
| `DELETE /api/media/<ключ>` | — | удалить «осиротевший» файл; `409`, если он используется |
| `POST /api/tags` | `{ name }` | создать тег |
| `PATCH /api/tags/:id` | `{ name }` | переименовать → `{ tag, affected_video_ids }`; `409 tag_exists`, если имя занято (тогда слияние) |
| `POST /api/tags/merge` | `{ source_ids: [..], target_id }` | слить теги → `{ tag, merged_ids, affected_video_ids }` |
| `DELETE /api/tags/:id` | — | удалить тег → `{ deleted, affected_video_ids }` |
| `DELETE /api/tags/unused` | — | удалить теги без видео |
| `POST /api/collections` | `{ name, emoji?, sort_order?, cover_key? }` | создать коллекцию |
| `PATCH /api/collections/:id` | `{ name?, emoji?, sort_order?, cover_key? }` | изменить. `cover_key` — картинка, заранее загруженная через `PUT /api/media/covers/<имя>.jpg\|png\|webp`; `null` — убрать (вернуть авто-обложку). Старая картинка удаляется из R2 |
| `PUT /api/collections/order` | `{ ids: [3, 1, 2] }` | новый порядок |
| `DELETE /api/collections/:id` | — | удалить (видео остаются) |
| `POST /api/collections/:id/videos` | `{ add?: [id], remove?: [id] }` | массово добавить/убрать видео |
| `POST /api/ai/tag` | `{ images: [base64 jpeg], prompt, system?, model?, max_tokens? }` | `{ provider: "workers-ai", model, text, json }`. `429 ai_quota` — лимит исчерпан, переходите к следующему провайдеру |

`affected_video_ids` — видео, у которых поменялись теги: им ставится `caption_dirty = 1`, загрузчик обновит подписи их постов в Telegram.

### Ключи файлов

- превью: `previews/<имя>.mp4`
- постер: `posters/<имя>.jpg` или `.webp`

Файлы кэшируются навсегда, поэтому при замене превью используйте **новое имя** (загрузчик добавляет случайный суффикс: `previews/<id>-<8 символов>.mp4`).

## Нормализация

- Теги: нижний регистр, без `#`, `_` превращается в пробел, лишние пробелы убираются, до 64 символов, до 60 тегов на видео.
- Канал: `@name`, `https://t.me/name` и `name` → `name` (нижний регистр).
- Разрешение: считается и по короткой, и по длинной стороне, берётся большая метка
  (SD < 720p ≤ HD < 1080p ≤ FullHD < 1440p ≤ 2K < 2160p ≤ 4K < 4320p ≤ 8K).
- Ориентация: квадрат, если стороны отличаются меньше чем на 5 %.

## Токены загрузчиков

```bash
cd web
npm run uploader:create -- "Анна"          # создать (токен выводится один раз)
npm run uploader:revoke -- "Анна"          # отозвать все активные токены с этим именем
npm run uploader:revoke -- --id 3          # отозвать по id
npm run uploader:list                      # список
```

По умолчанию команды работают с боевой базой в Cloudflare. Для локальной разработки добавьте `--local`.
