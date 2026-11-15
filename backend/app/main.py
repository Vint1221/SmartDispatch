from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.routes import router as v1_router
from app.config import settings
from app.database.session import init_db
from app.schemas.common import make_error
from app.services.dispatch_service import ApiDomainError


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Smart Dispatch — Умная диспетчеризация выездных бригад",
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > settings.max_body_bytes:
                return JSONResponse(
                    status_code=400,
                    content=make_error("BAD_REQUEST", "Размер тела запроса превышает 100 МБ"),
                )
        except ValueError:
            return JSONResponse(
                status_code=400,
                content=make_error("BAD_REQUEST", "Некорректный заголовок Content-Length"),
            )
    return await call_next(request)


@app.exception_handler(ApiDomainError)
async def domain_error_handler(_: Request, exc: ApiDomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=make_error(exc.code, exc.message, exc.details),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = []
    for err in exc.errors():
        loc = [str(part) for part in err.get("loc", []) if part != "body"]
        field = ".".join(loc) if loc else None
        details.append({"field": field, "message": err.get("msg", "invalid value")})
    first_msg = details[0]["message"] if details else "Ошибка валидации входных данных"
    return JSONResponse(
        status_code=400,
        content=make_error("BAD_REQUEST", f"Нарушение схемы: {first_msg}", details),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "NOT_FOUND" if exc.status_code == 404 else "BAD_REQUEST"
    return JSONResponse(
        status_code=exc.status_code,
        content=make_error(code, str(exc.detail)),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=make_error("INTERNAL_ERROR", f"Внутренняя ошибка сервера: {type(exc).__name__}"),
    )


app.include_router(v1_router, prefix=settings.api_prefix)
