"""Предметные ошибки. Обработчик в web.py превращает их в JSON {code, message, field?, ...}."""
from __future__ import annotations


class DomainError(Exception):
    status = 400

    def __init__(self, code: str, message: str, field: str | None = None, **extra: object) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra: dict[str, object] = dict(extra)
        if field:
            self.extra["field"] = field


class BadRequest(DomainError):
    status = 400


class Unauthorized(DomainError):
    status = 401


class Forbidden(DomainError):
    status = 403


class NotFound(DomainError):
    status = 404


class Conflict(DomainError):
    status = 409
