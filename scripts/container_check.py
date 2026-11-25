#!/usr/bin/env python3
"""Сквозная проверка запущенного контейнера без сторонних библиотек.

    python3 scripts/container_check.py                 # http://127.0.0.1:8204
    python3 scripts/container_check.py --restart       # + docker compose restart и проверка сохранности
    python3 scripts/container_check.py --base http://127.0.0.1:9000

Шаги: готовность /api/health → вход куратора и двух сотрудников → сброс демо → 8 одновременных
запросов на один экземпляр (ровно одна выдача) → повторный возврат без второй записи в журнале →
второй сотрудник забирает вещь → [перезапуск → открытая выдача и журнал сохранены].
Демо-режим (DEMO_MODE=1) обязателен: используется /api/demo/reset.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import quote


class Session:
    def __init__(self, base: str) -> None:
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
        try:
            with self.opener.open(req, timeout=15) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")


def wait_ready(base: str, timeout: float = 90) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=2) as r:
                h = json.loads(r.read())
                if h.get("status") == "ok":
                    return h
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(1)
    raise SystemExit("FAIL: сервер не стал готов")


def step(ok: bool, text: str) -> None:
    print(("ok   " if ok else "FAIL ") + text)
    if not ok:
        sys.exit(1)


def login(base: str, user: str, pwd: str) -> Session:
    s = Session(base)
    code, _ = s.call("POST", "/api/auth/login", {"username": user, "password": pwd})
    step(code == 200, f"вход {user}")
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8204")
    ap.add_argument("--restart", action="store_true")
    args = ap.parse_args()

    h = wait_ready(args.base)
    step(h["schema_version"] >= 1 and h["demo"] is True, f"готовность: {h}")
    cur = login(args.base, "curator", "curator-demo")
    staff = [login(args.base, u, "employee-demo") for u in ("anna", "boris", "vera")]
    step(cur.call("POST", "/api/demo/reset")[0] == 200, "сброс демо")
    _, items = staff[0].call("GET", "/api/items?q=" + quote("Свинтус"))
    _, card = staff[0].call("GET", f"/api/items/{items['items'][0]['id']}")
    cid = card["copies"][0]["id"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        res = list(pool.map(lambda i: staff[i % 3].call("POST", "/api/loans", {"copy_id": cid}), range(8)))
    created = [r for r in res if r[0] == 201]
    step(len(created) == 1, f"8 одновременных запросов: выдач {len(created)}, остальные {sorted(r[0] for r in res if r[0] != 201)}")
    loan = created[0][1]["loan"]
    owner = next(s for s in staff if s.call("GET", "/api/loans?status=active")[1]["loans"] and any(x["id"] == loan["id"] for x in s.call("GET", "/api/loans?status=active")[1]["loans"]))
    r1 = owner.call("POST", f"/api/loans/{loan['id']}/return")
    r2 = owner.call("POST", f"/api/loans/{loan['id']}/return")
    step(r1[1]["changed"] is True and r2[1]["changed"] is False, "повторный возврат не меняет запись")
    other = next(s for s in staff if s is not owner)
    code, taken = other.call("POST", "/api/loans", {"copy_id": cid})
    step(code == 201, "после возврата вещь забирает другой сотрудник")
    _, ev = cur.call("GET", "/api/events")
    kinds = [e["kind"] for e in ev["events"] if e["code"] == "И-203"]
    step(kinds == ["issue", "return", "issue"], f"журнал по экземпляру: {kinds}")

    if args.restart:
        root = Path(__file__).resolve().parent.parent
        subprocess.run(["docker", "compose", "restart", "app"], cwd=root, check=True)
        wait_ready(args.base)
        cur = login(args.base, "curator", "curator-demo")
        _, active = cur.call("GET", "/api/loans?status=active")
        step(any(x["id"] == taken["loan"]["id"] for x in active["loans"]), "после перезапуска открытая выдача на месте")
        _, ev2 = cur.call("GET", "/api/events")
        step(len(ev2["events"]) == len(ev["events"]), "журнал сохранился")
    print("Все проверки пройдены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
