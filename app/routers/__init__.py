from app.routers.account import router as account_router
from app.routers.auth import router as auth_router
from app.routers.health import router as health_router
from app.routers.history import router as history_router

__all__ = ["account_router", "auth_router", "health_router", "history_router"]
