"""Правила библиотеки: каталог, экземпляры, выдачи, возвраты, просрочки, журнал.

Доступность считается по экземплярам без открытой выдачи. Просрочка — по сроку открытой выдачи.
Выдача и возврат идут в транзакции BEGIN IMMEDIATE, журнал пишется в ней же.
Вторая параллельная выдача экземпляра упирается в уникальный индекс loans_one_open_per_copy.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from .db import write_tx
from .errors import BadRequest, Conflict, Forbidden, NotFound

CATEGORIES = {"book": "Книги", "adapter": "Переходники", "game": "Игры"}
MAX_PAGE = 200


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def title_key(s: str) -> str:
    """Ключ поиска: нижний регистр, «ё» → «е», без лишних пробелов."""
    return " ".join(s.lower().replace("ё", "е").split())


def search_key(title: str, subtitle: str) -> str:
    """Поиск идёт по названию и подзаголовку (автор, характеристики)."""
    return title_key(f"{title} {subtitle}")


def _event(conn: sqlite3.Connection, actor: int, kind: str, item_id: int | None = None, copy_id: int | None = None, loan_id: int | None = None, details: str = "") -> None:
    conn.execute(
        "INSERT INTO events (at, actor_id, kind, item_id, copy_id, loan_id, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (iso(now()), actor, kind, item_id, copy_id, loan_id, details),
    )


# ---------- каталог ----------


def list_items(conn: sqlite3.Connection, q: str = "", category: str | None = None, available_only: bool = False, limit: int = 50, offset: int = 0) -> dict[str, object]:
    """Страница каталога. Сначала отбираются id страницы (индекс по названию), потом наличие считается
    только для них: на 20 000 вещей агрегировать весь каталог ради 50 строк — 100 мс на запрос."""
    where = ["1 = 1"]
    args: list[object] = []
    for w in title_key(q).split()[:6]:
        where.append("i.search_key LIKE ? ESCAPE '\\'")
        args.append("%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if category:
        if category not in CATEGORIES:
            raise BadRequest("bad_category", "Неизвестная категория", field="category")
        where.append("i.category = ?")
        args.append(category)
    if available_only:
        # Есть экземпляр в фонде без открытой выдачи (проверка открытой выдачи — по частичному уникальному индексу).
        where.append(
            "EXISTS (SELECT 1 FROM copies c WHERE c.item_id = i.id AND c.retired_at IS NULL"
            " AND NOT EXISTS (SELECT 1 FROM loans l WHERE l.copy_id = c.id AND l.returned_at IS NULL))"
        )
    cond = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM items i WHERE {cond}", args).fetchone()[0]
    ids = [r[0] for r in conn.execute(f"SELECT i.id FROM items i WHERE {cond} ORDER BY i.title_key, i.id LIMIT ? OFFSET ?", (*args, min(limit, MAX_PAGE), offset))]
    if not ids:
        return {"total": total, "items": []}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""SELECT i.id, i.title, i.category, i.subtitle, i.loan_days, i.title_key,
               COUNT(c.id) AS copies,
               SUM(CASE WHEN c.id IS NOT NULL AND l.id IS NULL THEN 1 ELSE 0 END) AS available,
               MIN(l.due_at) AS next_due
            FROM items i
            LEFT JOIN copies c ON c.item_id = i.id AND c.retired_at IS NULL
            LEFT JOIN loans l ON l.copy_id = c.id AND l.returned_at IS NULL
            WHERE i.id IN ({marks})
            GROUP BY i.id
            ORDER BY i.title_key, i.id""",
        ids,
    ).fetchall()
    return {"total": total, "items": [_item_row(r) for r in rows]}


def _item_row(r: sqlite3.Row) -> dict[str, object]:
    return {
        "id": r["id"],
        "title": r["title"],
        "category": r["category"],
        "subtitle": r["subtitle"],
        "loan_days": r["loan_days"],
        "copies": r["copies"] or 0,
        "available": r["available"] or 0,
        "next_due": r["next_due"],
    }


def item_card(conn: sqlite3.Connection, item_id: int, viewer_id: int, viewer_is_curator: bool) -> dict[str, object]:
    it = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if it is None:
        raise NotFound("not_found", "Такой вещи нет в каталоге")
    t = iso(now())
    copies = []
    for c in conn.execute(
        """SELECT c.*, l.id AS loan_id, l.user_id, l.due_at, l.issued_at, u.display_name AS borrower
           FROM copies c LEFT JOIN loans l ON l.copy_id = c.id AND l.returned_at IS NULL
           LEFT JOIN users u ON u.id = l.user_id
           WHERE c.item_id = ? ORDER BY c.code""",
        (item_id,),
    ):
        status = "retired" if c["retired_at"] else ("on_loan" if c["loan_id"] else "available")
        mine = c["user_id"] == viewer_id
        copies.append(
            {
                "id": c["id"],
                "code": c["code"],
                "location": c["location"],
                "status": status,
                "due_at": c["due_at"],
                "overdue": bool(c["loan_id"] and c["due_at"] < t),
                "mine": bool(c["loan_id"] and mine),
                "loan_id": c["loan_id"] if (mine or viewer_is_curator) else None,
                # Кто держит экземпляр, видит только куратор и сам заёмщик.
                "borrower": c["borrower"] if (viewer_is_curator or mine) else None,
            }
        )
    active = [c for c in copies if c["status"] != "retired"]
    return {
        "item": {
            "id": it["id"],
            "title": it["title"],
            "category": it["category"],
            "subtitle": it["subtitle"],
            "description": it["description"],
            "loan_days": it["loan_days"],
            "copies": len(active),
            "available": sum(1 for c in active if c["status"] == "available"),
        },
        "copies": copies,
    }


def create_item(conn: sqlite3.Connection, actor: int, title: str, category: str, subtitle: str, description: str, loan_days: int) -> int:
    if category not in CATEGORIES:
        raise BadRequest("bad_category", "Неизвестная категория", field="category")
    with write_tx(conn):
        iid = int(
            conn.execute(
                "INSERT INTO items (title, category, subtitle, description, loan_days, title_key, search_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (title, category, subtitle, description, loan_days, title_key(title), search_key(title, subtitle), iso(now())),
            ).lastrowid
            or 0
        )
        _event(conn, actor, "item_create", item_id=iid, details=title)
    return iid


def update_item(conn: sqlite3.Connection, actor: int, item_id: int, fields: dict[str, object]) -> None:
    if not fields:
        return
    if "category" in fields and fields["category"] not in CATEGORIES:
        raise BadRequest("bad_category", "Неизвестная категория", field="category")
    with write_tx(conn):
        if conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone() is None:
            raise NotFound("not_found", "Такой вещи нет в каталоге")
        sets = [f"{k} = ?" for k in fields]
        vals = list(fields.values())
        conn.execute(f"UPDATE items SET {', '.join(sets)} WHERE id = ?", (*vals, item_id))
        r = conn.execute("SELECT title, subtitle FROM items WHERE id = ?", (item_id,)).fetchone()
        conn.execute("UPDATE items SET title_key = ?, search_key = ? WHERE id = ?", (title_key(r["title"]), search_key(r["title"], r["subtitle"]), item_id))
        _event(conn, actor, "item_update", item_id=item_id, details=", ".join(sorted(fields)))


def add_copy(conn: sqlite3.Connection, actor: int, item_id: int, code: str, location: str) -> int:
    with write_tx(conn):
        if conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone() is None:
            raise NotFound("not_found", "Такой вещи нет в каталоге")
        if conn.execute("SELECT 1 FROM copies WHERE code = ?", (code,)).fetchone():
            raise Conflict("code_taken", f"Инвентарный номер {code} уже занят", field="code")
        cid = int(conn.execute("INSERT INTO copies (item_id, code, location) VALUES (?, ?, ?)", (item_id, code, location)).lastrowid or 0)
        _event(conn, actor, "copy_add", item_id=item_id, copy_id=cid, details=code)
    return cid


def set_copy_retired(conn: sqlite3.Connection, actor: int, copy_id: int, retired: bool) -> int:
    with write_tx(conn):
        c = conn.execute("SELECT * FROM copies WHERE id = ?", (copy_id,)).fetchone()
        if c is None:
            raise NotFound("not_found", "Нет такого экземпляра")
        if retired and conn.execute("SELECT 1 FROM loans WHERE copy_id = ? AND returned_at IS NULL", (copy_id,)).fetchone():
            raise Conflict("copy_on_loan", "Экземпляр сейчас выдан: списать можно после возврата")
        if bool(c["retired_at"]) != retired:
            conn.execute("UPDATE copies SET retired_at = ? WHERE id = ?", (iso(now()) if retired else None, copy_id))
            _event(conn, actor, "copy_retire" if retired else "copy_restore", item_id=c["item_id"], copy_id=copy_id, details=c["code"])
        return int(c["item_id"])


# ---------- выдачи ----------


def _loan_json(r: sqlite3.Row) -> dict[str, object]:
    t = iso(now())
    return {
        "id": r["id"],
        "copy_id": r["copy_id"],
        "code": r["code"],
        "item_id": r["item_id"],
        "title": r["title"],
        "category": r["category"],
        "user_id": r["user_id"],
        "borrower": r["borrower"],
        "issued_at": r["issued_at"],
        "due_at": r["due_at"],
        "returned_at": r["returned_at"],
        "status": "returned" if r["returned_at"] else ("overdue" if r["due_at"] < t else "active"),
    }


LOAN_SQL = """SELECT l.*, c.code, c.item_id, i.title, i.category, u.display_name AS borrower
  FROM loans l JOIN copies c ON c.id = l.copy_id JOIN items i ON i.id = c.item_id JOIN users u ON u.id = l.user_id"""


def loan(conn: sqlite3.Connection, loan_id: int) -> dict[str, object]:
    r = conn.execute(LOAN_SQL + " WHERE l.id = ?", (loan_id,)).fetchone()
    if r is None:
        raise NotFound("not_found", "Нет такой выдачи")
    return _loan_json(r)


def issue(conn: sqlite3.Connection, user_id: int, copy_id: int) -> tuple[dict[str, object], bool]:
    """Выдать экземпляр. Повтор того же запроса тем же сотрудником возвращает его открытую выдачу."""
    with write_tx(conn):
        c = conn.execute("SELECT c.*, i.loan_days, i.title FROM copies c JOIN items i ON i.id = c.item_id WHERE c.id = ?", (copy_id,)).fetchone()
        if c is None:
            raise NotFound("not_found", "Нет такого экземпляра")
        if c["retired_at"]:
            raise Conflict("copy_retired", "Экземпляр списан и не выдаётся", item_id=c["item_id"])
        open_loan = conn.execute("SELECT id, user_id FROM loans WHERE copy_id = ? AND returned_at IS NULL", (copy_id,)).fetchone()
        if open_loan is not None:
            if open_loan["user_id"] == user_id:
                return loan(conn, int(open_loan["id"])), False
            raise Conflict("copy_taken", "Этот экземпляр уже выдан другому сотруднику", item_id=c["item_id"])
        t = now()
        try:
            lid = int(
                conn.execute(
                    "INSERT INTO loans (copy_id, user_id, issued_at, due_at) VALUES (?, ?, ?, ?)",
                    (copy_id, user_id, iso(t), iso(t + timedelta(days=int(c["loan_days"])))),
                ).lastrowid
                or 0
            )
        except sqlite3.IntegrityError as exc:  # страховка: уникальный индекс открытой выдачи
            raise Conflict("copy_taken", "Этот экземпляр уже выдан другому сотруднику", item_id=c["item_id"]) from exc
        _event(conn, user_id, "issue", item_id=c["item_id"], copy_id=copy_id, loan_id=lid, details=c["code"])
        return loan(conn, lid), True


def return_loan(conn: sqlite3.Connection, actor_id: int, actor_is_curator: bool, loan_id: int) -> tuple[dict[str, object], bool]:
    """Закрыть выдачу фактическим временем. Повтор возвращает текущее состояние без новой записи в журнале."""
    with write_tx(conn):
        r = conn.execute("SELECT l.*, c.item_id, c.code FROM loans l JOIN copies c ON c.id = l.copy_id WHERE l.id = ?", (loan_id,)).fetchone()
        if r is None:
            raise NotFound("not_found", "Нет такой выдачи")
        if r["user_id"] != actor_id and not actor_is_curator:
            raise Forbidden("forbidden", "Вернуть вещь может тот, кто её взял, или куратор")
        if r["returned_at"]:
            return loan(conn, loan_id), False
        conn.execute("UPDATE loans SET returned_at = ?, returned_by = ? WHERE id = ?", (iso(now()), actor_id, loan_id))
        _event(conn, actor_id, "return", item_id=r["item_id"], copy_id=r["copy_id"], loan_id=loan_id, details=r["code"])
        return loan(conn, loan_id), True


def list_loans(conn: sqlite3.Connection, status: str, user_id: int | None, limit: int = 100) -> list[dict[str, object]]:
    t = iso(now())
    where, args = [], []  # type: ignore[var-annotated]
    if user_id is not None:
        where.append("l.user_id = ?")
        args.append(user_id)
    if status == "active":
        where.append("l.returned_at IS NULL")
    elif status == "overdue":
        where.append("l.returned_at IS NULL AND l.due_at < ?")
        args.append(t)
    elif status == "returned":
        where.append("l.returned_at IS NOT NULL")
    elif status != "all":
        raise BadRequest("bad_status", "Статус: active, overdue, returned или all", field="status")
    # Открытые — по сроку (ближайший сверху), история — новые сверху. id разводит записи с одной секундой.
    order = {"active": "l.due_at ASC, l.id ASC", "overdue": "l.due_at ASC, l.id ASC", "returned": "l.returned_at DESC, l.id DESC"}.get(status, "l.issued_at DESC, l.id DESC")
    sql = LOAN_SQL + (" WHERE " + " AND ".join(where) if where else "") + f" ORDER BY {order} LIMIT ?"
    return [_loan_json(r) for r in conn.execute(sql, (*args, min(limit, MAX_PAGE)))]


EVENT_TEXT = {
    "issue": "выдача",
    "return": "возврат",
    "item_create": "новая вещь",
    "item_update": "правка карточки",
    "copy_add": "новый экземпляр",
    "copy_retire": "списание",
    "copy_restore": "возврат в фонд",
}


def list_events(conn: sqlite3.Connection, item_id: int | None = None, limit: int = 100) -> list[dict[str, object]]:
    sql = """SELECT e.*, u.display_name AS actor, i.title, c.code FROM events e JOIN users u ON u.id = e.actor_id
             LEFT JOIN items i ON i.id = e.item_id LEFT JOIN copies c ON c.id = e.copy_id"""
    args: list[object] = []
    if item_id is not None:
        sql += " WHERE e.item_id = ?"
        args.append(item_id)
    sql += " ORDER BY e.id DESC LIMIT ?"
    args.append(min(limit, MAX_PAGE))
    return [
        {"id": r["id"], "at": r["at"], "actor": r["actor"], "kind": r["kind"], "text": EVENT_TEXT[r["kind"]], "title": r["title"], "code": r["code"], "loan_id": r["loan_id"], "details": r["details"]}
        for r in conn.execute(sql, args)
    ]
