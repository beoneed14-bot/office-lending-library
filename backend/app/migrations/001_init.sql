-- 001: исходная схема Библиотека вещей для офиса.
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('employee', 'curator')),
  password_hash TEXT NOT NULL,
  salt TEXT NOT NULL
);

CREATE TABLE sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL
);

-- Каталог: что это за вещь. Физические экземпляры — отдельно (copies).
CREATE TABLE items (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  category TEXT NOT NULL CHECK (category IN ('book', 'adapter', 'game')),
  subtitle TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  loan_days INTEGER NOT NULL CHECK (loan_days BETWEEN 1 AND 90),
  -- Ключи поиска считаются в Python: lower() в SQLite меняет регистр только у латиницы.
  title_key TEXT NOT NULL,
  search_key TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX items_category ON items(category, title_key);
CREATE INDEX items_title ON items(title_key, id);

CREATE TABLE copies (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  code TEXT NOT NULL UNIQUE,
  location TEXT NOT NULL DEFAULT '',
  retired_at TEXT
);
CREATE INDEX copies_item ON copies(item_id);

-- Выдача экземпляра. Открытая — returned_at IS NULL.
CREATE TABLE loans (
  id INTEGER PRIMARY KEY,
  copy_id INTEGER NOT NULL REFERENCES copies(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  issued_at TEXT NOT NULL,
  due_at TEXT NOT NULL,
  returned_at TEXT,
  returned_by INTEGER REFERENCES users(id)
);
-- Одна открытая выдача на экземпляр: параллельная вторая выдача упирается в индекс.
CREATE UNIQUE INDEX loans_one_open_per_copy ON loans(copy_id) WHERE returned_at IS NULL;
CREATE INDEX loans_user ON loans(user_id, returned_at);
CREATE INDEX loans_open_due ON loans(due_at) WHERE returned_at IS NULL;

-- Журнал операций: кто, что и когда сделал. Пишется в той же транзакции, что и само изменение.
CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  actor_id INTEGER NOT NULL REFERENCES users(id),
  kind TEXT NOT NULL CHECK (kind IN ('issue', 'return', 'item_create', 'item_update', 'copy_add', 'copy_retire', 'copy_restore')),
  item_id INTEGER REFERENCES items(id) ON DELETE SET NULL,
  copy_id INTEGER REFERENCES copies(id) ON DELETE SET NULL,
  loan_id INTEGER REFERENCES loans(id) ON DELETE SET NULL,
  details TEXT NOT NULL DEFAULT ''
);
CREATE INDEX events_at ON events(at DESC, id DESC);
