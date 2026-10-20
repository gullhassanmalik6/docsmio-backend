import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.config import get_settings, secret_is_usable
from app.routers import account, auth, health, history, library, reminders, sharing

settings = get_settings()
if not secret_is_usable(settings.secret_key):
    raise RuntimeError("Set SECRET_KEY to a random string of at least 24 characters. The example value is not safe to run.")
if settings.app_env == "production" and not settings.cookie_secure:
    raise RuntimeError("COOKIE_SECURE must be true when APP_ENV is production.")


def _dispatch_once() -> None:
    from app.database import SessionLocal
    from app.reminders import dispatch_due

    database = SessionLocal()
    try:
        dispatch_due(database)
    except Exception:
        database.rollback()
    finally:
        database.close()


async def _reminder_loop() -> None:
    while True:
        await asyncio.to_thread(_dispatch_once)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_reminder_loop()) if get_settings().reminder_loop else None
    yield
    if task is not None:
        task.cancel()


app = FastAPI(title="Docsmio API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Docsmio-Request", "X-Reminder-Token"],
)


@app.middleware("http")
async def protect_cookie_requests(request: Request, call_next):
    if request.method in {"POST", "PATCH", "PUT", "DELETE"} and request.cookies.get(settings.cookie_name):
        bearer = request.headers.get("authorization", "").lower().startswith("bearer ")
        if not bearer and request.headers.get("x-docsmio-request") != "1":
            return JSONResponse(status_code=403, content={"detail": "This request was rejected. Refresh the page and try again."})
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return JSONResponse(status_code=exc.status_code, content={"detail": detail})


@app.exception_handler(OperationalError)
async def database_error(_request: Request, _exc: OperationalError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "The account database is not available."})


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    messages = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", []) if part != "body")
        messages.append(f"{location}: {error.get('msg')}" if location else str(error.get("msg")))
    return JSONResponse(status_code=422, content={"detail": messages[0] if messages else "Invalid request.", "errors": messages})


app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(account.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(library.router, prefix="/api")
app.include_router(reminders.router, prefix="/api")
app.include_router(sharing.router, prefix="/api")
