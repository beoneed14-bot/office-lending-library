"""HTTP API офисной библиотеки и раздача собранного интерфейса."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from . import service, web
from .db import connect, migrate
from .errors import Conflict
from .web import Conn, CurrentUser, require_role


@asynccontextmanager
async def lifespan(_: FastAPI):
    conn = connect()
    try:
        migrate(conn)
        if web.env_flag("SEED_DEMO"):
            from .seed import seed

            seed(conn)
    finally:
        conn.close()
    yield


app = FastAPI(title="Библиотека вещей для офиса", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
web.install(app)


def is_curator(u: object) -> bool:
    return getattr(u, "role", "") == "curator"


def _strip(v: str) -> str:
    return " ".join(v.split())


class ItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    category: Literal["book", "adapter", "game"]
    subtitle: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=2000)
    loan_days: int = Field(ge=1, le=90)

    @field_validator("title", "subtitle")
    @classmethod
    def strip(cls, v: str) -> str:
        return _strip(v)

    @field_validator("title")
    @classmethod
    def title_required(cls, v: str) -> str:
        if not v:
            raise ValueError("Введите название")
        return v


class ItemPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    category: Literal["book", "adapter", "game"] | None = None
    subtitle: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    loan_days: int | None = Field(default=None, ge=1, le=90)


class CopyIn(BaseModel):
    code: str = Field(min_length=1, max_length=20, pattern=r"^[\w\-./]+$")
    location: str = Field(default="", max_length=120)


class CopyPatch(BaseModel):
    retired: bool


class LoanIn(BaseModel):
    copy_id: int = Field(ge=1)


@app.get("/api/categories")
def categories() -> dict[str, object]:
    return {"categories": [{"id": k, "label": v} for k, v in service.CATEGORIES.items()]}


@app.get("/api/items")
def items(
    conn: Conn,
    user: CurrentUser,
    q: Annotated[str, Query(max_length=100)] = "",
    category: Annotated[str | None, Query()] = None,
    available: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    return service.list_items(conn, q, category or None, available, limit, offset)


@app.get("/api/items/{item_id}")
def item(item_id: int, conn: Conn, user: CurrentUser) -> dict[str, object]:
    return service.item_card(conn, item_id, user.id, is_curator(user))


@app.post("/api/items", status_code=201)
def create_item(body: ItemIn, conn: Conn, user: CurrentUser) -> dict[str, object]:
    require_role(user, "curator", message="Каталог ведёт куратор")
    iid = service.create_item(conn, user.id, body.title, body.category, body.subtitle, body.description.strip(), body.loan_days)
    return service.item_card(conn, iid, user.id, True)


@app.patch("/api/items/{item_id}")
def patch_item(item_id: int, body: ItemPatch, conn: Conn, user: CurrentUser) -> dict[str, object]:
    require_role(user, "curator", message="Каталог ведёт куратор")
    fields = {k: (_strip(v) if isinstance(v, str) and k != "description" else v) for k, v in body.model_dump(exclude_none=True).items()}
    service.update_item(conn, user.id, item_id, fields)
    return service.item_card(conn, item_id, user.id, True)


@app.post("/api/items/{item_id}/copies", status_code=201)
def add_copy(item_id: int, body: CopyIn, conn: Conn, user: CurrentUser) -> dict[str, object]:
    require_role(user, "curator", message="Экземпляры добавляет куратор")
    service.add_copy(conn, user.id, item_id, body.code.strip().upper(), _strip(body.location))
    return service.item_card(conn, item_id, user.id, True)


@app.patch("/api/copies/{copy_id}")
def patch_copy(copy_id: int, body: CopyPatch, conn: Conn, user: CurrentUser) -> dict[str, object]:
    require_role(user, "curator", message="Списывает экземпляры куратор")
    item_id = service.set_copy_retired(conn, user.id, copy_id, body.retired)
    return service.item_card(conn, item_id, user.id, True)


@app.post("/api/loans", status_code=201, response_model=None)
def create_loan(body: LoanIn, conn: Conn, user: CurrentUser, response: Response) -> dict[str, object] | JSONResponse:
    """Выдача экземпляра. Заёмщик — пользователь сессии. Конфликт отдаёт свежую карточку вещи."""
    try:
        res, created = service.issue(conn, user.id, body.copy_id)
    except Conflict as exc:
        iid = exc.extra.get("item_id")
        card = service.item_card(conn, int(iid), user.id, is_curator(user)) if isinstance(iid, int) else None
        return JSONResponse(status_code=409, content={"code": exc.code, "message": exc.message, "card": card})
    if not created:
        response.status_code = 200
    return {"loan": res, "created": created}


@app.post("/api/loans/{loan_id}/return")
def return_loan(loan_id: int, conn: Conn, user: CurrentUser) -> dict[str, object]:
    res, changed = service.return_loan(conn, user.id, is_curator(user), loan_id)
    return {"loan": res, "changed": changed}


@app.get("/api/loans")
def loans(
    conn: Conn,
    user: CurrentUser,
    status: Annotated[str, Query()] = "active",
    mine: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> dict[str, object]:
    """Сотрудник видит только свои выдачи. Куратор — все или свои (mine=1)."""
    who = user.id if (mine or not is_curator(user)) else None
    return {"loans": service.list_loans(conn, status, who, limit)}


@app.get("/api/events")
def events(conn: Conn, user: CurrentUser, item_id: Annotated[int | None, Query()] = None, limit: Annotated[int, Query(ge=1, le=200)] = 100) -> dict[str, object]:
    require_role(user, "curator", message="Журнал операций видит куратор")
    return {"events": service.list_events(conn, item_id, limit)}


web.mount_static(app)
