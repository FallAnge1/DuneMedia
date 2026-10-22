-- Подпись поста в Telegram устарела: название, описание или теги изменили на сайте
-- (сайт не может править посты). Загрузчик обновляет такие подписи и сбрасывает флаг.
ALTER TABLE videos ADD COLUMN caption_dirty INTEGER NOT NULL DEFAULT 0;
CREATE INDEX idx_videos_caption_dirty ON videos (caption_dirty) WHERE caption_dirty = 1;
