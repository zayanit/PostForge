import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import assert_database_role_privileges, load_settings
from .routes.auth import router as auth_router
from .routes.brands import router as brands_router
from .routes.health import router as health_router
from .routes.me import router as me_router


_VALIDATION_DEADLINE_SECONDS = 15
_VALIDATION_PATH = re.compile(
    r"^/api/v1/brands/[^/]+/keys/[^/]+/validate/?$"
)
_SAFE_ERROR_MESSAGES = {
    (409, "KEY_CLEANUP_REQUIRED"): "Key cleanup is required. Retry deletion.",
    (409, "BRAND_CLEANUP_REQUIRED"): "Brand cleanup is required. Retry deletion.",
    (503, "KEY_CLEANUP_REQUIRED"): "Key cleanup did not complete. Retry deletion.",
    (503, "BRAND_CLEANUP_REQUIRED"): "Brand cleanup did not complete. Retry deletion.",
}


class _JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
        }
        for key in (
            "event",
            "request_id",
            "provider",
            "code",
            "duration_ms",
            "provider_request_id",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload)


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonLogFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    _configure_logging()
    assert_database_role_privileges()
    yield


app = FastAPI(title="PostForge API", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(load_settings().allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error_response(request_id: str, code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
            }
        },
        headers={"X-Request-Id": request_id},
    )


def safe_error_response(request: Request, status_code: int, code: str) -> JSONResponse:
    message = _SAFE_ERROR_MESSAGES[(status_code, code)]
    request_id = getattr(request.state, "request_id", str(uuid4()))
    return _error_response(request_id, code, message, status_code)


def get_validation_deadline(request: Request) -> float | None:
    return getattr(request.state, "validation_deadline", None)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next: Callable):
    request_id = str(uuid4())
    request.state.request_id = request_id
    if _VALIDATION_PATH.fullmatch(request.url.path):
        request.state.validation_deadline = (
            time.monotonic() + _VALIDATION_DEADLINE_SECONDS
        )
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    request_id = getattr(request.state, "request_id", str(uuid4()))
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("code", "HTTP_ERROR")
        message = detail.get("message", "Request failed.")
    else:
        code = "HTTP_ERROR"
        message = str(detail) if detail else "Request failed."
    return _error_response(request_id, code, message, exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
):
    request_id = getattr(request.state, "request_id", str(uuid4()))
    first_error = exc.errors()[0] if exc.errors() else {}
    message = first_error.get("msg", "Invalid request body.")
    return _error_response(request_id, "VALIDATION_ERROR", message, 400)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", str(uuid4()))
    return _error_response(request_id, "INTERNAL_SERVER_ERROR", "Unexpected error.", 500)


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(brands_router)
app.include_router(health_router)
app.include_router(me_router)
