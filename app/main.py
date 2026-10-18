from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.config import get_settings, secret_is_usable
from app.routers import account, auth, health, history, library

settings = get_settings()
if not secret_is_usable(settings.secret_key):
    raise RuntimeError("Set SECRET_KEY to a random string of at least 24 characters. The example value is not safe to run.")
app = FastAPI(title="DocuFix API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


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
