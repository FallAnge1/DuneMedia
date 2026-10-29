-- Архив хранит не только видео, но и фото. У фото нет превью-ролика, длительности и fps;
-- постер — уменьшенная копия снимка. Все уже загруженные записи — видео.
ALTER TABLE videos ADD COLUMN media_type TEXT NOT NULL DEFAULT 'video' CHECK (media_type IN ('video', 'photo'));
