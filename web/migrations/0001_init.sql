-- Видеоархив: начальная схема

CREATE TABLE videos (
  id               TEXT PRIMARY KEY,            -- uuid
  tg_channel       TEXT NOT NULL,               -- username канала без @
  tg_message_id    INTEGER NOT NULL,
  title            TEXT NOT NULL,
  description      TEXT,
  file_name        TEXT,
  file_size        INTEGER,                     -- байты
  file_hash        TEXT,                        -- sha256(размер + первые 4 МБ + последние 4 МБ)
  duration         REAL,                        -- секунды
  width            INTEGER,
  height           INTEGER,
  orientation      TEXT CHECK (orientation IN ('horizontal', 'vertical', 'square')),
  resolution_label TEXT CHECK (resolution_label IN ('SD', 'HD', 'FullHD', '2K', '4K', '8K')),
  fps              REAL,
  codec            TEXT,
  preview_key      TEXT,                        -- ключ в R2 (mp4 превью)
  poster_key       TEXT,                        -- ключ в R2 (jpg постер)
  uploaded_by      TEXT,                        -- имя загрузчика
  created_at       INTEGER NOT NULL,            -- unix ms
  updated_at       INTEGER NOT NULL,
  UNIQUE (tg_channel, tg_message_id)
);

CREATE INDEX idx_videos_created_at  ON videos (created_at);
CREATE INDEX idx_videos_updated_at  ON videos (updated_at);
CREATE INDEX idx_videos_duration    ON videos (duration);
CREATE INDEX idx_videos_orientation ON videos (orientation);
CREATE INDEX idx_videos_file_hash   ON videos (file_hash);

CREATE TABLE tags (
  id   INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL                     -- нижний регистр, без #
);

CREATE TABLE video_tags (
  video_id TEXT    NOT NULL REFERENCES videos (id) ON DELETE CASCADE,
  tag_id   INTEGER NOT NULL REFERENCES tags (id)   ON DELETE CASCADE,
  PRIMARY KEY (video_id, tag_id)
);
CREATE INDEX idx_video_tags_tag ON video_tags (tag_id);

CREATE TABLE collections (
  id         INTEGER PRIMARY KEY,
  name       TEXT UNIQUE NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  emoji      TEXT
);

CREATE TABLE video_collections (
  video_id      TEXT    NOT NULL REFERENCES videos (id)      ON DELETE CASCADE,
  collection_id INTEGER NOT NULL REFERENCES collections (id) ON DELETE CASCADE,
  PRIMARY KEY (video_id, collection_id)
);
CREATE INDEX idx_video_collections_collection ON video_collections (collection_id);

CREATE TABLE uploaders (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  token_hash TEXT UNIQUE NOT NULL,              -- sha256 от токена, сам токен не хранится
  created_at INTEGER NOT NULL,
  revoked    INTEGER NOT NULL DEFAULT 0
);

-- Служебные значения. library_rev растёт при любом изменении архива:
-- по нему строится ETag для /api/library (max(updated_at) не ловит удаления).
CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT INTO meta (key, value) VALUES ('library_rev', '1');

-- Полнотекстовый поиск по названию, описанию и тегам.
-- Заполняется кодом Worker'а (теги лежат в другой таблице, поэтому без триггеров).
CREATE VIRTUAL TABLE videos_fts USING fts5 (
  video_id UNINDEXED,
  title,
  description,
  tags,
  tokenize = 'unicode61 remove_diacritics 2',
  prefix = '2 3 4'
);
