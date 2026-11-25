from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture()
def db_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "test.sqlite3"
    monkeypatch.setenv("DB_PATH", str(path))
    monkeypatch.setenv("SEED_DEMO", "1")
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path / "no-static"))
    return path


@pytest.fixture()
def client(db_file: Path) -> Iterator[httpx.Client]:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def demo_password(username: str) -> str:
    from app.seed import DEMO_USERS

    return next(p for u, _, _, p in DEMO_USERS if u == username)


def login(c: httpx.Client, username: str, password: str | None = None) -> dict[str, str]:
    r = c.post("/api/auth/login", json={"username": username, "password": password or demo_password(username)})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_server(db: Path, port: int) -> subprocess.Popen[bytes]:
    env = {**os.environ, "DB_PATH": str(db), "SEED_DEMO": "1", "DEMO_MODE": "1", "STATIC_DIR": str(db.parent / "none")}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=BACKEND,
        env=env,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(150):
        try:
            if httpx.get(f"{base}/api/health", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    proc.terminate()
    raise RuntimeError("сервер не поднялся")


@pytest.fixture()
def live_server(tmp_path: Path) -> Iterator[str]:
    """Настоящий uvicorn в отдельном процессе: для проверки параллельных запросов и перезапуска."""
    port = free_port()
    proc = start_server(tmp_path / "live.sqlite3", port)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def http_login(base: str, username: str) -> dict[str, str]:
    r = httpx.post(f"{base}/api/auth/login", json={"username": username, "password": demo_password(username)})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
