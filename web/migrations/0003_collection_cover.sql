-- Своя обложка доски (картинка в R2: covers/<имя>.jpg|png|webp). NULL — обложка собирается из постеров видео.
ALTER TABLE collections ADD COLUMN cover_key TEXT;
