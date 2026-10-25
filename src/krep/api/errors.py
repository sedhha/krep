from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, error: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.error = error
        self.message = message
        self.extra = extra


async def _api_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return JSONResponse(
        {"error": exc.error, "message": exc.message, **exc.extra}, status_code=exc.status
    )


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors: list[dict[str, str]] = [
        {
            "field": ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path")),
            "message": e["msg"],
        }
        for e in exc.errors()
    ]
    return JSONResponse(
        {"error": "validation_failed", "message": "request validation failed", "errors": errors},
        status_code=422,
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
