# Программа-загрузчик

Python 3.11+, PySide6, Telethon. Делает превью и постеры через ffmpeg, загружает видео в Telegram-канал
**документом** (без сжатия) от имени вашего аккаунта и публикует запись на сайте.

## Запуск из исходников

```bash
cd uploader
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt      # Windows: .venv\Scripts\pip ...
.venv/bin/python -m videoarchive                    # --verbose — подробный лог в консоль
```

Нужен ffmpeg: в собранной программе он лежит рядом, при запуске из исходников берётся из PATH
(или из папки `uploader/ffmpeg/`, или из переменных `VIDEOARCHIVE_FFMPEG` / `VIDEOARCHIVE_FFPROBE`).

## Где лежат данные

| Система | Папка |
|---|---|
| Windows | `%APPDATA%\VideoArchive` |
| macOS | `~/Library/Application Support/VideoArchive` |
| Linux | `~/.local/share/VideoArchive` |

Там `config.json` (настройки, ключи ИИ, токен), `telegram.session` (вход в Telegram — не передавайте никому),
`queue.json` (очередь), `work/` (временные превью) и `logs/app.log`.

## Как устроено

```
videoarchive/
  core/        без интерфейса, покрыто тестами
    media.py     ffprobe, превью (4 фрагмента по 2 с, ≤1,5 МБ), постер без тёмных кадров, кадры для ИИ
    textutil.py  название из имени файла, теги, подпись поста, хеш для дубликатов
    telegram.py  Telethon в отдельном потоке: вход, проверка канала, отправка, правка, удаление
    api.py       клиент сайта с повторами
    queue.py     очередь в queue.json (переживает перезапуск)
    pipeline.py  шаги обработки одного файла; каждый результат сохраняется сразу
    manager.py   подготовка в 2 потока + последовательная загрузка
  ui/          окна PySide6
  ai/          цепочка ИИ-провайдеров
```

Главная гарантия: id поста в Telegram сохраняется сразу после отправки. Если потом упал сайт или сеть,
повтор продолжит со следующего шага и **не загрузит видео в Telegram второй раз**. Если связь оборвалась
во время отправки, перед повтором программа ищет файл с тем же именем и размером среди последних постов канала.

## Тесты

```bash
.venv/bin/python -m pytest                  # ~40 тестов, нужен ffmpeg в PATH
# связка с локальным сайтом (в web/: npm run dev):
VIDEOARCHIVE_TEST_SITE=http://localhost:8787 VIDEOARCHIVE_TEST_TOKEN=va_... .venv/bin/python -m pytest tests/test_integration.py
```
