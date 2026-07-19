from collections.abc import Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


app = FastAPI(title="PostForge API")


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


@app.middleware("http")
async def request_id_middleware(request: Request, call_next: Callable):
    request_id = str(uuid4())
    request.state.request_id = request_id
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
