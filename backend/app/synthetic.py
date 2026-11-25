"""Синтетический каталог для замеров: N вещей по 2 экземпляра, каждая третья выдана, каждая десятая выдача просрочена.

Запуск: python -m app.synthetic 2000   (только для демо-базы: добавляет к текущим данным)
"""
from __future__ import annotations

import sys
from datetime import timedelta

from .db import connect, migrate, write_tx
from .service import iso, now, search_key, title_key

WORDS = ["Алгоритмы", "Архитектура", "Дизайн", "Игра", "Кабель", "Переходник", "Практикум", "Справочник", "Сборник", "Набор"]
CATS = ["book", "adapter", "game"]


def main(argv: list[str]) -> int:
    n = int(argv[0]) if argv else 2000
    conn = connect()
    try:
        migrate(conn)
        uid = conn.execute("SELECT id FROM users WHERE role = 'employee' ORDER BY id LIMIT 1").fetchone()["id"]
        t = now()
        # Повторный запуск продолжает нумерацию: инвентарные номера уникальны.
        start = conn.execute("SELECT COUNT(*) FROM items WHERE title LIKE '% синтетический %'").fetchone()[0]
        with write_tx(conn):
            for i in range(start, start + n):
                title = f"{WORDS[i % len(WORDS)]} синтетический {i:05d}"
                iid = conn.execute(
                    "INSERT INTO items (title, category, subtitle, description, loan_days, title_key, search_key, created_at) VALUES (?, ?, ?, '', 14, ?, ?, ?) RETURNING id",
                    (title, CATS[i % 3], f"Серия {i % 37}", title_key(title), search_key(title, f"Серия {i % 37}"), iso(t)),
                ).fetchone()["id"]
                for k in range(2):
                    cid = conn.execute("INSERT INTO copies (item_id, code, location) VALUES (?, ?, 'Склад') RETURNING id", (iid, f"S-{i:05d}-{k}")).fetchone()["id"]
                    if k == 0 and i % 3 == 0:
                        ago = 20 if i % 30 == 0 else 2
                        conn.execute(
                            "INSERT INTO loans (copy_id, user_id, issued_at, due_at) VALUES (?, ?, ?, ?)",
                            (cid, uid, iso(t - timedelta(days=ago)), iso(t - timedelta(days=ago) + timedelta(days=14))),
                        )
        print(f"items+={n}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
