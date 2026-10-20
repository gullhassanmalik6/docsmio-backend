import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

from app.config import get_settings

_hits: dict[str, list[float]] = defaultdict(list)


def enforce_rate_limit(request: Request, bucket: str) -> None:
    settings = get_settings()
    limit = settings.auth_rate_limit
    window = settings.auth_rate_window_seconds
    if limit <= 0:
        return
    host = request.client.host if request.client else "unknown"
    key = f"{bucket}:{host}"
    now = time.monotonic()
    recent = [stamp for stamp in _hits[key] if now - stamp < window]
    if len(recent) >= limit:
        _hits[key] = recent
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts. Wait a few minutes and try again.")
    recent.append(now)
    _hits[key] = recent


def reset_rate_limits() -> None:
    _hits.clear()
