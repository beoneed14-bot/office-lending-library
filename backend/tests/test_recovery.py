"""Повторный запуск с существующей базой, миграции, сохранность данных между процессами."""
from __future__ import annotations

from pathlib import Path

import httpx

from app.db import connect, latest_migration, migrate, schema_version

from .conftest import free_port, http_login, start_server


def test_restart_keeps_loans_and_does_not_reseed(tmp_path: Path) -> None:
    db = tmp_path / "keep.sqlite3"
    port = free_port()
    proc = start_server(db, port)
    base = f"http://127.0.0.1:{port}"
    try:
        h = http_login(base, "vera")
        items = httpx.get(f"{base}/api/items", params={"q": "Шахматы"}, headers=h).json()["items"]
        card = httpx.get(f"{base}/api/items/{items[0]['id']}", headers=h).json()
        lid = httpx.post(f"{base}/api/loans", json={"copy_id": card["copies"][0]["id"]}, headers=h).json()["loan"]["id"]
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    proc = start_server(db, port)
    try:
        h = http_login(base, "vera")
        mine = httpx.get(f"{base}/api/loans", params={"status": "active"}, headers=h).json()["loans"]
        assert lid in [x["id"] for x in mine]
        assert httpx.get(f"{base}/api/items", headers=h).json()["total"] == 12  # демо не задвоилось
        assert httpx.get(f"{base}/api/health").json()["schema_version"] == latest_migration()
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    conn = connect(str(tmp_path / "m.sqlite3"))
    try:
        assert migrate(conn) == latest_migration()
        assert migrate(conn) == latest_migration()
        assert schema_version(conn) == latest_migration()
        # Уникальный индекс открытой выдачи есть в схеме.
        idx = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")]
        assert "loans_one_open_per_copy" in idx
    finally:
        conn.close()


def test_unique_index_blocks_second_open_loan_even_without_service(tmp_path: Path) -> None:
    """Защита на уровне базы: вторая открытая выдача экземпляра невозможна даже в обход service.issue."""
    import sqlite3

    import pytest

    from app.seed import seed

    conn = connect(str(tmp_path / "u.sqlite3"))
    try:
        seed(conn)
        cid = conn.execute("SELECT id FROM copies WHERE code = 'И-204'").fetchone()[0]
        conn.execute("INSERT INTO loans (copy_id, user_id, issued_at, due_at) VALUES (?, 2, 'a', 'b')", (cid,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO loans (copy_id, user_id, issued_at, due_at) VALUES (?, 3, 'a', 'b')", (cid,))
        conn.execute("UPDATE loans SET returned_at = 'c' WHERE copy_id = ?", (cid,))
        conn.execute("INSERT INTO loans (copy_id, user_id, issued_at, due_at) VALUES (?, 3, 'a', 'b')", (cid,))  # после возврата — можно
    finally:
        conn.close()
