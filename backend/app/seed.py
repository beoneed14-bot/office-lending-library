"""Демоданные: куратор, три сотрудника, 12 вещей в трёх категориях, экземпляры и несколько выдач.

Повторный запуск ничего не дублирует: пользователи ищутся по логину, вещи — по названию,
экземпляры — по инвентарному номеру, выдачи создаются только в пустой базе выдач.
--reset возвращает демо к исходному виду: каталог как в списке ниже, выдачи и журнал заново.
Время выдач считается от момента запуска, поэтому одна выдача всегда просрочена.

Запуск: python -m app.seed [--reset]
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import timedelta

from .auth import hash_password
from .db import connect, migrate, write_tx
from .service import iso, now, search_key, title_key

RESET_ROLE = "curator"
DEMO_USERS: list[tuple[str, str, str, str]] = [
    ("curator", "Ирина Смирнова", "curator", "curator-demo"),
    ("anna", "Анна Петрова", "employee", "employee-demo"),
    ("boris", "Борис Ли", "employee", "employee-demo"),
    ("vera", "Вера Ким", "employee", "employee-demo"),
]

# (название, категория, подзаголовок, описание, дней, [(инв. номер, место)])
CATALOG: list[tuple[str, str, str, str, int, list[tuple[str, str]]]] = [
    ("Чистый код", "book", "Роберт Мартин", "Про читаемый код и рефакторинг.", 14, [("К-001", "Шкаф у кухни"), ("К-002", "Шкаф у кухни")]),
    ("Совершенный код", "book", "Стив Макконнелл", "Классика о конструировании программ.", 21, [("К-003", "Шкаф у кухни")]),
    ("Думай медленно… решай быстро", "book", "Даниэль Канеман", "О двух системах мышления.", 14, [("К-004", "Переговорная «Сосна»")]),
    ("Спроси маму", "book", "Роб Фитцпатрик", "Как разговаривать с клиентами.", 14, [("К-005", "Переговорная «Сосна»")]),
    ("Переходник USB-C → HDMI", "adapter", "4K, 60 Гц", "Для ноутбуков с USB-C.", 3, [("П-101", "Стойка ресепшена"), ("П-102", "Стойка ресепшена")]),
    ("Переходник USB-C → Ethernet", "adapter", "1 Гбит/с", "", 3, [("П-103", "Стойка ресепшена")]),
    ("Удлинитель на 5 розеток", "adapter", "3 метра", "", 2, [("П-104", "Склад")]),
    ("Кликер для презентаций", "adapter", "Logitech, USB-приёмник", "", 2, [("П-105", "Стойка ресепшена")]),
    ("Каркассон", "game", "2–5 игроков, 35 мин", "Строим средневековую карту из тайлов.", 7, [("И-201", "Комната отдыха")]),
    ("Кодовые имена", "game", "4–8 игроков, 15 мин", "Командная игра на ассоциации.", 7, [("И-202", "Комната отдыха")]),
    ("Свинтус", "game", "2–10 игроков, 20 мин", "", 7, [("И-203", "Комната отдыха")]),
    ("Шахматы", "game", "дорожный набор", "", 7, [("И-204", "Комната отдыха")]),
]

# (логин, инв. номер, дней назад выдано) — одна из выдач просрочена.
LOANS: list[tuple[str, str, int]] = [
    ("anna", "К-003", 25),  # 21 день → просрочена на 4 дня
    ("boris", "П-101", 1),
    ("vera", "И-201", 2),
]


def seed(conn: sqlite3.Connection, reset: bool = False) -> dict[str, int]:
    migrate(conn)
    with write_tx(conn):
        if reset:
            conn.execute("DELETE FROM events")
            conn.execute("DELETE FROM loans")
            conn.execute("DELETE FROM copies")
            conn.execute("DELETE FROM items")
        ids: dict[str, int] = {}
        for username, name, role, pwd in DEMO_USERS:
            row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if row is None:
                h, salt = hash_password(pwd)
                row = conn.execute(
                    "INSERT INTO users (username, display_name, role, password_hash, salt) VALUES (?, ?, ?, ?, ?) RETURNING id",
                    (username, name, role, h, salt),
                ).fetchone()
            ids[username] = int(row["id"])
        t = now()
        for title, cat, sub, desc, days, copies in CATALOG:
            row = conn.execute("SELECT id FROM items WHERE title = ?", (title,)).fetchone()
            if row is None:
                row = conn.execute(
                    "INSERT INTO items (title, category, subtitle, description, loan_days, title_key, search_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (title, cat, sub, desc, days, title_key(title), search_key(title, sub), iso(t - timedelta(days=60))),
                ).fetchone()
            for code, place in copies:
                if conn.execute("SELECT 1 FROM copies WHERE code = ?", (code,)).fetchone() is None:
                    conn.execute("INSERT INTO copies (item_id, code, location) VALUES (?, ?, ?)", (row["id"], code, place))
        if conn.execute("SELECT COUNT(*) FROM loans").fetchone()[0] == 0:
            for username, code, ago in LOANS:
                c = conn.execute("SELECT c.id, c.item_id, i.loan_days FROM copies c JOIN items i ON i.id = c.item_id WHERE c.code = ?", (code,)).fetchone()
                issued = t - timedelta(days=ago)
                lid = conn.execute(
                    "INSERT INTO loans (copy_id, user_id, issued_at, due_at) VALUES (?, ?, ?, ?) RETURNING id",
                    (c["id"], ids[username], iso(issued), iso(issued + timedelta(days=int(c["loan_days"])))),
                ).fetchone()["id"]
                conn.execute(
                    "INSERT INTO events (at, actor_id, kind, item_id, copy_id, loan_id, details) VALUES (?, ?, 'issue', ?, ?, ?, ?)",
                    (iso(issued), ids[username], c["item_id"], c["id"], lid, code),
                )
    counts = {k: conn.execute(f"SELECT COUNT(*) FROM {k}").fetchone()[0] for k in ("users", "items", "copies", "loans")}
    return counts


def main(argv: list[str]) -> int:
    conn = connect()
    try:
        c = seed(conn, reset="--reset" in argv)
        print(", ".join(f"{k}={v}" for k, v in c.items()))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
