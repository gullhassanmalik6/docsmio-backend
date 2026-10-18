import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite://"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["ACCESS_TOKEN_MINUTES"] = "60"
os.environ["COOKIE_SECURE"] = "false"
os.environ["CORS_ORIGINS"] = "http://127.0.0.1:5173"

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

get_settings.cache_clear()

from app.database import Base, engine  # noqa: E402
import app.models  # noqa: E402, F401
from app.main import app as fastapi_app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(fastapi_app) as test_client:
        yield test_client
