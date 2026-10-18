from datetime import UTC, datetime, timedelta

from app.config import secret_is_usable
from app.database import SessionLocal
from app.entitlements import HISTORY_LIMITS
from app.models import SessionToken, User


def register(client, email="ada@example.com", name="Ada Lovelace", password="correct-horse"):
    return client.post("/api/auth/register", json={"name": name, "email": email, "password": password})


def test_register_and_reject_duplicate_email(client):
    created = register(client)
    assert created.status_code == 201
    body = created.json()
    assert body["user"]["email"] == "ada@example.com"
    assert body["user"]["plan"] == "free"
    assert body["user"]["billing_connected"] is False
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]
    duplicate = register(client, email="Ada@Example.com")
    assert duplicate.status_code == 409


def test_login_rejects_invalid_credentials(client):
    register(client)
    wrong = client.post("/api/auth/login", json={"email": "ada@example.com", "password": "wrong-password"})
    assert wrong.status_code == 401
    missing = client.post("/api/auth/login", json={"email": "missing@example.com", "password": "correct-horse"})
    assert missing.status_code == 401


def test_protected_route_requires_a_token(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_login_cookie_and_logout_invalidates_the_session(client):
    register(client)
    client.cookies.clear()
    logged_in = client.post("/api/auth/login", json={"email": "ada@example.com", "password": "correct-horse"})
    assert logged_in.status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    token = client.cookies.get("docufix_session")
    assert token
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.clear()
    again = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert again.status_code == 401
    assert "session" in again.json()["detail"].lower()


def test_expired_token_is_rejected(client):
    register(client)
    db = SessionLocal()
    record = db.query(SessionToken).one()
    record.expires_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()
    db.close()
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


def test_bearer_token_works_and_plan_cannot_be_supplied(client):
    rejected = client.post(
        "/api/auth/register",
        json={"name": "Ada Lovelace", "email": "ada@example.com", "password": "correct-horse", "plan": "business"},
    )
    assert rejected.status_code == 422
    created = register(client)
    token = created.cookies.get("docufix_session")
    client.cookies.clear()
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["plan"] == "free"
    plan = client.get("/api/account/plan", headers={"Authorization": f"Bearer {token}"})
    assert plan.status_code == 200
    assert plan.json()["history_limit"] == HISTORY_LIMITS["free"]


def test_validation_errors_use_the_error_schema(client):
    response = client.post("/api/auth/register", json={"name": "A", "email": "not-an-email", "password": "short"})
    assert response.status_code == 422
    assert "detail" in response.json()


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def history_body(operation="image-resize", status="completed", name="photo.jpg"):
    return {
        "original_filename": name,
        "operation_type": operation,
        "original_size": 1200,
        "output_size": 800,
        "status": status,
    }


def test_history_is_private_to_the_owner(client):
    register(client, email="ada@example.com")
    created = client.post("/api/history", json=history_body())
    assert created.status_code == 201
    assert created.json()["download_available"] is False
    record_id = created.json()["id"]
    client.cookies.clear()
    register(client, email="grace@example.com", name="Grace Hopper")
    assert client.get(f"/api/history/{record_id}").status_code == 404
    assert client.delete(f"/api/history/{record_id}").status_code == 404
    listing = client.get("/api/history")
    assert listing.status_code == 200
    assert listing.json()["total"] == 0


def test_history_filter_and_pagination(client):
    register(client)
    client.post("/api/history", json=history_body("image-resize", "completed", "a.jpg"))
    client.post("/api/history", json=history_body("compress-pdf", "failed", "b.pdf"))
    client.post("/api/history", json=history_body("compress-pdf", "completed", "c.pdf"))
    filtered = client.get("/api/history", params={"operation_type": "compress-pdf", "status": "completed", "page_size": 1})
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["total"] == 1
    assert body["items"][0]["original_filename"] == "c.pdf"
    page = client.get("/api/history", params={"page": 2, "page_size": 2})
    assert page.json()["total"] == 3
    assert len(page.json()["items"]) == 1


def test_free_plan_history_limit_is_enforced(client):
    register(client)
    limit = HISTORY_LIMITS["free"]
    for index in range(limit):
        response = client.post("/api/history", json=history_body(name=f"file-{index}.jpg"))
        assert response.status_code == 201
    blocked = client.post("/api/history", json=history_body(name="one-more.jpg"))
    assert blocked.status_code == 403
    db = SessionLocal()
    user = db.query(User).one()
    user.plan = "pro"
    db.commit()
    db.close()
    allowed = client.post("/api/history", json=history_body(name="after-upgrade.jpg"))
    assert allowed.status_code == 201


def test_history_rejects_bad_input(client):
    register(client)
    response = client.post(
        "/api/history",
        json={"original_filename": "../secret.pdf", "operation_type": "delete-database", "original_size": -1, "status": "done"},
    )
    assert response.status_code == 422


def test_history_strips_path_characters_from_the_filename(client):
    register(client)
    created = client.post(
        "/api/history",
        json={
            "original_filename": "../secret\\notes.pdf",
            "operation_type": "compress-pdf",
            "original_size": 1200,
            "output_size": 800,
            "status": "completed",
        },
    )
    assert created.status_code == 201
    stored = created.json()["original_filename"]
    assert "/" not in stored
    assert "\\" not in stored
    assert stored.endswith("notes.pdf")


def test_placeholder_secret_is_rejected():
    assert secret_is_usable("test-secret-key-not-for-production")
    assert not secret_is_usable("replace-with-a-long-random-string")
    assert not secret_is_usable("short-secret")
