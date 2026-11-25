"""Общая HTTP-обвязка: соединение на запрос, сессия, вход и выход, готовность, демо-входы, статика.

Предметные маршруты — в main.py, правила — в service.py.
"""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth
from .db import connect, latest_migration, schema_version
from .errors import DomainError, Forbidden, NotFound, Unauthorized

COOKIE = "ol_session"


def env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def _token(cookie: str | None, authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return cookie


def current_user(
    conn: Conn,
    ol_session: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> auth.User:
    user = auth.user_by_token(conn, _token(ol_session, authorization))
    if user is None:
        raise Unauthorized("unauthorized", "Нужно войти")
    return user


CurrentUser = Annotated[auth.User, Depends(current_user)]


def require_role(user: auth.User, *roles: str, message: str = "Недостаточно прав") -> None:
    if user.role not in roles:
        raise Forbidden("forbidden", message)


def user_json(u: auth.User) -> dict[str, object]:
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role}


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


router = APIRouter()


@router.get("/api/health")
def health(conn: Conn) -> dict[str, object]:
    conn.execute("SELECT 1").fetchone()
    version = schema_version(conn)
    return {"status": "ok" if version >= latest_migration() else "migrating", "schema_version": version, "demo": env_flag("DEMO_MODE")}


@router.post("/api/auth/login")
def login(body: LoginIn, conn: Conn, response: Response) -> dict[str, object]:
    res = auth.login(conn, body.username, body.password)
    if res is None:
        raise Unauthorized("bad_credentials", "Неверный логин или пароль", field="password")
    user, token = res
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=env_flag("COOKIE_SECURE"), max_age=auth.SESSION_DAYS * 86400, path="/")
    return {"user": user_json(user), "token": token}


@router.post("/api/auth/logout")
def logout(
    conn: Conn,
    response: Response,
    ol_session: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    auth.logout(conn, _token(ol_session, authorization))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/api/me")
def me(user: CurrentUser) -> dict[str, object]:
    return {"user": user_json(user)}


@router.get("/api/demo/users")
def demo_users() -> dict[str, object]:
    """Подсказка логинов на экране входа. Только в демо-режиме."""
    if not env_flag("DEMO_MODE"):
        raise NotFound("not_found", "Нет такого адреса")
    from .seed import DEMO_USERS

    return {"users": [{"username": u, "display_name": n, "role": r, "password": p} for u, n, r, p in DEMO_USERS]}


@router.post("/api/demo/reset")
def demo_reset(conn: Conn, user: CurrentUser) -> dict[str, bool]:
    """Вернуть демо к исходному виду (для показа и автотестов). Только в демо-режиме и только старшей роли."""
    if not env_flag("DEMO_MODE"):
        raise NotFound("not_found", "Нет такого адреса")
    from .seed import RESET_ROLE, seed

    require_role(user, RESET_ROLE, message="Сбросить демо может только старшая роль")
    seed(conn, reset=True)
    return {"ok": True}


def install(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message, **exc.extra})

    app.include_router(router)


def mount_static(app: FastAPI) -> None:
    """Собранный интерфейс на том же адресе, что и API (последним, чтобы не перекрывать /api)."""
    static = Path(os.environ.get("STATIC_DIR", str(Path(__file__).resolve().parent.parent / "static")))
    if static.is_dir() and (static / "index.html").exists():
        app.mount("/", StaticFiles(directory=static, html=True), name="ui")
