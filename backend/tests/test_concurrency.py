"""Параллельные запросы к настоящему uvicorn (отдельный процесс, пул потоков, SQLite WAL)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import httpx

from .conftest import http_login


def _free_copy(base: str, h: dict[str, str], title: str) -> int:
    items = httpx.get(f"{base}/api/items", params={"q": title}, headers=h).json()["items"]
    card = httpx.get(f"{base}/api/items/{items[0]['id']}", headers=h).json()
    return next(c["id"] for c in card["copies"] if c["status"] == "available")


def test_two_employees_one_copy(live_server: str) -> None:
    """Приёмка ТЗ: два пользователя одновременно запрашивают один экземпляр — выдача подтверждается одному."""
    a, b = http_login(live_server, "anna"), http_login(live_server, "boris")
    cid = _free_copy(live_server, a, "Свинтус")
    with ThreadPoolExecutor(max_workers=2) as pool:
        res = list(pool.map(lambda h: httpx.post(f"{live_server}/api/loans", json={"copy_id": cid}, headers=h, timeout=30), [a, b]))
    assert sorted(r.status_code for r in res) == [201, 409]
    loser = next(r for r in res if r.status_code == 409).json()
    assert loser["code"] == "copy_taken" and loser["card"]["item"]["available"] == 0


def test_eight_parallel_requests(live_server: str) -> None:
    """Восемь одновременных запросов на один экземпляр от трёх сотрудников: ровно одна открытая выдача."""
    users = [http_login(live_server, u) for u in ("anna", "boris", "vera")]
    cid = _free_copy(live_server, users[0], "Шахматы")
    with ThreadPoolExecutor(max_workers=8) as pool:
        res = list(pool.map(lambda i: httpx.post(f"{live_server}/api/loans", json={"copy_id": cid}, headers=users[i % 3], timeout=30), range(8)))
    created = [r for r in res if r.status_code == 201]
    assert len(created) == 1
    winner = created[0].json()["loan"]["borrower"]
    # Повтор победителя — 200 с той же выдачей, остальные — конфликт.
    for r in res:
        if r.status_code == 200:
            assert r.json()["loan"]["borrower"] == winner and r.json()["created"] is False
        elif r.status_code != 201:
            assert r.status_code == 409
    cur = http_login(live_server, "curator")
    ev = [e for e in httpx.get(f"{live_server}/api/events", headers=cur).json()["events"] if e["kind"] == "issue" and e["code"] == "И-204"]
    assert len(ev) == 1


def test_parallel_returns_write_one_event(live_server: str) -> None:
    a = http_login(live_server, "anna")
    cid = _free_copy(live_server, a, "Кликер")
    lid = httpx.post(f"{live_server}/api/loans", json={"copy_id": cid}, headers=a).json()["loan"]["id"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        res = list(pool.map(lambda _: httpx.post(f"{live_server}/api/loans/{lid}/return", headers=a, timeout=30), range(6)))
    assert all(r.status_code == 200 for r in res)
    assert sum(r.json()["changed"] for r in res) == 1
    cur = http_login(live_server, "curator")
    ev = [e for e in httpx.get(f"{live_server}/api/events", headers=cur).json()["events"] if e["kind"] == "return" and e["loan_id"] == lid]
    assert len(ev) == 1
