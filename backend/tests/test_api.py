"""Сценарии API: каталог, выдача, конфликт, возврат, просрочки, журнал, права."""
from __future__ import annotations

import httpx

from .conftest import login


def _item(c: httpx.Client, h: dict[str, str], title: str) -> dict:
    r = c.get("/api/items", params={"q": title}, headers=h)
    return next(i for i in r.json()["items"] if i["title"] == title)


def _card(c: httpx.Client, h: dict[str, str], title: str) -> dict:
    return c.get(f"/api/items/{_item(c, h, title)['id']}", headers=h).json()


def test_requires_login(client: httpx.Client) -> None:
    assert client.get("/api/items").status_code == 401
    assert client.post("/api/loans", json={"copy_id": 1}).status_code == 401


def test_catalog_search_and_availability(client: httpx.Client) -> None:
    h = login(client, "anna")
    r = client.get("/api/items", headers=h).json()
    assert r["total"] == 12
    # Поиск без учёта регистра и «ё», по названию и подзаголовку (автору).
    assert [i["title"] for i in client.get("/api/items", params={"q": "ЧИСТЫЙ"}, headers=h).json()["items"]] == ["Чистый код"]
    assert [i["title"] for i in client.get("/api/items", params={"q": "макконнелл"}, headers=h).json()["items"]] == ["Совершенный код"]
    games = client.get("/api/items", params={"category": "game"}, headers=h).json()
    assert games["total"] == 4
    # «Каркассон» выдан Вере: в списке доступных его нет.
    avail = client.get("/api/items", params={"category": "game", "available": True}, headers=h).json()["items"]
    assert "Каркассон" not in [i["title"] for i in avail]
    k = _item(client, h, "Каркассон")
    assert (k["copies"], k["available"]) == (1, 0) and k["next_due"]
    hdmi = _item(client, h, "Переходник USB-C → HDMI")
    assert (hdmi["copies"], hdmi["available"]) == (2, 1)
    assert client.get("/api/items", params={"category": "bad"}, headers=h).status_code == 400


def test_issue_conflict_return_and_history(client: httpx.Client) -> None:
    anna, boris, cur = login(client, "anna"), login(client, "boris"), login(client, "curator")
    card = _card(client, anna, "Каркассон")
    assert card["copies"][0]["status"] == "on_loan" and card["copies"][0]["borrower"] is None  # чужой заёмщик скрыт
    card = _card(client, anna, "Кодовые имена")
    cid = card["copies"][0]["id"]
    r = client.post("/api/loans", json={"copy_id": cid}, headers=anna)
    assert r.status_code == 201, r.text
    loan = r.json()["loan"]
    assert loan["borrower"] == "Анна Петрова" and loan["status"] == "active"
    # Второй сотрудник на тот же экземпляр — конфликт со свежей карточкой.
    r = client.post("/api/loans", json={"copy_id": cid}, headers=boris)
    assert r.status_code == 409 and r.json()["code"] == "copy_taken"
    assert r.json()["card"]["copies"][0]["status"] == "on_loan"
    # Повтор Анны (потерянный ответ) — та же выдача, без новой записи.
    r2 = client.post("/api/loans", json={"copy_id": cid}, headers=anna)
    assert r2.status_code == 200 and r2.json()["created"] is False and r2.json()["loan"]["id"] == loan["id"]
    # Вернуть чужую нельзя, свою — да; повтор возврата не пишет журнал.
    assert client.post(f"/api/loans/{loan['id']}/return", headers=boris).status_code == 403
    r = client.post(f"/api/loans/{loan['id']}/return", headers=anna)
    assert r.json()["changed"] is True and r.json()["loan"]["status"] == "returned"
    returned_at = r.json()["loan"]["returned_at"]
    r = client.post(f"/api/loans/{loan['id']}/return", headers=anna)
    assert r.status_code == 200 and r.json()["changed"] is False and r.json()["loan"]["returned_at"] == returned_at
    # Теперь может взять Борис; в журнале обе операции и один возврат.
    assert client.post("/api/loans", json={"copy_id": cid}, headers=boris).status_code == 201
    ev = [e for e in client.get("/api/events", headers=cur).json()["events"] if e["code"] == card["copies"][0]["code"]]
    assert [e["kind"] for e in ev] == ["issue", "return", "issue"]
    hist = client.get("/api/loans", params={"status": "all"}, headers=cur).json()["loans"]
    mine = [x for x in hist if x["code"] == card["copies"][0]["code"]]
    assert [(x["borrower"], x["status"]) for x in mine] == [("Борис Ли", "active"), ("Анна Петрова", "returned")]


def test_overdue_and_roles(client: httpx.Client) -> None:
    anna, cur = login(client, "anna"), login(client, "curator")
    od = client.get("/api/loans", params={"status": "overdue"}, headers=cur).json()["loans"]
    assert [(x["title"], x["borrower"]) for x in od] == [("Совершенный код", "Анна Петрова")]
    # Сотрудник видит только свои выдачи, журнал ему недоступен.
    mine = client.get("/api/loans", params={"status": "active"}, headers=anna).json()["loans"]
    assert {x["borrower"] for x in mine} == {"Анна Петрова"}
    assert client.get("/api/events", headers=anna).status_code == 403
    assert client.post("/api/items", json={"title": "X", "category": "book", "loan_days": 7}, headers=anna).status_code == 403
    # Куратор возвращает просроченную за сотрудника.
    r = client.post(f"/api/loans/{od[0]['id']}/return", headers=cur)
    assert r.json()["changed"] is True
    assert client.get("/api/loans", params={"status": "overdue"}, headers=cur).json()["loans"] == []


def test_curator_catalog_editing(client: httpx.Client) -> None:
    cur, anna = login(client, "curator"), login(client, "anna")
    r = client.post("/api/items", json={"title": "  Мифический   человеко-месяц ", "category": "book", "subtitle": "Фредерик Брукс", "loan_days": 14}, headers=cur)
    assert r.status_code == 201 and r.json()["item"]["title"] == "Мифический человеко-месяц"
    iid = r.json()["item"]["id"]
    r = client.post(f"/api/items/{iid}/copies", json={"code": "к-006", "location": "Шкаф у кухни"}, headers=cur)
    assert r.json()["copies"][0]["code"] == "К-006"
    assert client.post(f"/api/items/{iid}/copies", json={"code": "К-006"}, headers=cur).status_code == 409
    cid = r.json()["copies"][0]["id"]
    assert client.post("/api/loans", json={"copy_id": cid}, headers=anna).status_code == 201
    # Выданный экземпляр не списать; после возврата — можно, и списанный не выдаётся.
    assert client.patch(f"/api/copies/{cid}", json={"retired": True}, headers=cur).json()["code"] == "copy_on_loan"
    lid = next(x["id"] for x in client.get("/api/loans", params={"status": "active"}, headers=anna).json()["loans"] if x["code"] == "К-006")
    client.post(f"/api/loans/{lid}/return", headers=anna)
    assert client.patch(f"/api/copies/{cid}", json={"retired": True}, headers=cur).json()["copies"][0]["status"] == "retired"
    r = client.post("/api/loans", json={"copy_id": cid}, headers=anna)
    assert r.status_code == 409 and r.json()["code"] == "copy_retired"
    assert client.get(f"/api/items/{iid}", headers=anna).json()["item"]["copies"] == 0
    # Поля проверяются.
    r = client.post("/api/items", json={"title": "   ", "category": "book", "loan_days": 7}, headers=cur)
    assert r.status_code == 422
    r = client.post("/api/items", json={"title": "Y", "category": "book", "loan_days": 0}, headers=cur)
    assert r.status_code == 422


def test_demo_reset_and_seed_idempotent(client: httpx.Client) -> None:
    cur = login(client, "curator")
    from app.db import connect
    from app.seed import seed

    conn = connect()
    try:
        assert seed(conn) == {"users": 4, "items": 12, "copies": 14, "loans": 3}
        assert seed(conn) == {"users": 4, "items": 12, "copies": 14, "loans": 3}
    finally:
        conn.close()
    assert client.post("/api/demo/reset", headers=login(client, "anna")).status_code == 403
    assert client.post("/api/demo/reset", headers=cur).status_code == 200


def test_search_ignores_yo_and_case_for_new_items(client: httpx.Client) -> None:
    h = login(client, "curator")
    r = client.post("/api/items", json={"title": "Ёжик в тумане", "category": "game", "subtitle": "Сергей Козлов, ЁЛКА", "loan_days": 7}, headers=h)
    assert r.status_code == 201
    for q in ("ежик", "ЁЖИК", "елка", "козлов"):
        titles = [i["title"] for i in client.get("/api/items", params={"q": q}, headers=h).json()["items"]]
        assert titles == ["Ёжик в тумане"], q
    # После правки названия ключи пересчитываются.
    client.patch(f"/api/items/{r.json()['item']['id']}", json={"title": "Ёлочные игрушки"}, headers=h)
    assert [i["title"] for i in client.get("/api/items", params={"q": "елочн"}, headers=h).json()["items"]] == ["Ёлочные игрушки"]
    assert client.get("/api/items", params={"q": "ежик"}, headers=h).json()["total"] == 0
