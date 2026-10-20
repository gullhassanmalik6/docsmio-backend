import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.classify import classify_document, suggest_date
from app.library_files import read_owned_file
from app.main import app as fastapi_app
from app.models import Notification


def register(client, email="ada@example.com"):
    response = client.post("/api/auth/register", json={"name": "Ada Lovelace", "email": email, "password": "correct-horse"})
    assert response.status_code == 201
    return response


def upload(client, folder_id, content=b"%PDF-1.4 receipt", name="receipt.pdf", mime="application/pdf"):
    return client.post(
        "/api/library/documents",
        data={"folder_id": folder_id},
        files={"upload": (name, content, mime)},
    )


def test_filename_rules_do_not_invent_dates():
    result = classify_document("passport-scan.pdf", None)
    assert result["category"] == "Identity"
    assert result["method"] == "filename"
    assert result["date"] is None
    found, label = suggest_date("Passport expiry 2030-04-02. Keep this copy.")
    assert found.isoformat() == "2030-04-02"
    assert label == "expiry"
    assert suggest_date("Meeting notes from 2030-04-02 with no label.")[0] is None


def test_upload_checks_bytes_quota_duplicates_and_isolation(client, monkeypatch):
    register(client)
    folders = client.get("/api/library/folders").json()
    folder_id = folders[0]["id"]
    created = upload(client, folder_id)
    assert created.status_code == 201
    document = created.json()
    assert document["text_status"] in {"failed", "unavailable", "ready"}
    assert "storage_key" not in document
    assert "extracted_text" not in document

    duplicate = upload(client, folder_id)
    assert duplicate.status_code == 409

    spoofed = upload(client, folder_id, b"%PDF-1.4 other", "photo.jpg", "image/jpeg")
    assert spoofed.status_code == 415
    junk = upload(client, folder_id, b"not-a-real-pdf", "notes.pdf", "application/pdf")
    assert junk.status_code == 415

    monkeypatch.setattr("app.library_service.storage_quota", lambda _plan: 4)
    blocked = upload(client, folder_id, b"%PDF-1.7 quota", "quota.pdf")
    assert blocked.status_code == 413

    client.patch(f"/api/library/documents/{document['id']}", json={"notes": "zebra-token", "category": "Academic"})
    found = client.get("/api/library/search", params={"q": "  Zebra-Token  "})
    assert found.status_code == 200
    assert found.json()["total"] == 1
    assert found.json()["items"][0]["category_confirmed"] is True

    reprocessed = client.post(f"/api/library/documents/{document['id']}/reprocess")
    assert reprocessed.json()["category"] == "Academic"
    assert reprocessed.json()["category_source"] == "manual"

    client.cookies.clear()
    register(client, "grace@example.com")
    assert client.get("/api/library/search", params={"q": "zebra-token"}).json()["total"] == 0
    assert client.get(f"/api/library/documents/{document['id']}").status_code == 404
    stolen = client.patch(f"/api/library/documents/{document['id']}", json={"notes": "nope"})
    assert stolen.status_code == 404


def test_trash_restore_and_path_guard(client):
    register(client, "trash@example.com")
    folder_id = client.get("/api/library/folders").json()[0]["id"]
    document_id = upload(client, folder_id, b"%PDF-1.4 trash", "trash.pdf").json()["id"]
    assert client.delete(f"/api/library/documents/{document_id}").status_code == 204
    assert client.get(f"/api/library/documents/{document_id}/file").status_code == 404
    listed = client.get("/api/library/documents", params={"trash": True})
    assert listed.json()[0]["id"] == document_id
    restored = client.post(f"/api/library/documents/{document_id}/restore")
    assert restored.status_code == 200
    assert client.get(f"/api/library/documents/{document_id}/file").status_code == 200
    try:
        read_owned_file(uuid.uuid4(), "../secret")
    except Exception as error:
        assert getattr(error, "status_code", None) == 404
    else:
        raise AssertionError("path traversal was accepted")


def test_reminders_do_not_duplicate_notifications(client):
    register(client, "remind@example.com")
    due = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    created = client.post(
        "/api/reminders",
        json={"title": "Passport renewal", "reminder_type": "passport", "due_at": due, "lead_days": [0], "timezone_name": "UTC"},
    )
    assert created.status_code == 201
    assert created.json()["bucket"] == "overdue"
    assert client.post("/api/reminders/dispatch").json()["sent"] == 1
    assert client.post("/api/reminders/dispatch").json()["sent"] == 0
    notes = client.get("/api/notifications").json()
    assert len(notes) == 1
    assert "Passport renewal" in notes[0]["title"]
    from app.database import SessionLocal

    db = SessionLocal()
    assert db.query(Notification).count() == 1
    db.close()
    client.cookies.clear()
    register(client, "other-remind@example.com")
    assert client.post(f"/api/reminders/{created.json()['id']}/dismiss").status_code == 404
    assert client.get("/api/notifications").json() == []


def test_share_links_are_unguessable_and_revocable(client):
    register(client, "share@example.com")
    folder_id = client.get("/api/library/folders").json()[0]["id"]
    document_id = upload(client, folder_id, b"%PDF-1.4 shared", "shared.pdf").json()["id"]
    created = client.post(f"/api/library/documents/{document_id}/shares", json={"hours": 2, "permission": "download", "password": "correct-horse"})
    assert created.status_code == 201
    token = created.json()["token"]
    assert "token_hash" not in created.json()
    hidden = client.get(f"/api/shared/{token}")
    assert hidden.status_code == 401
    opened = client.post(f"/api/shared/{token}", json={"password": "correct-horse"})
    assert opened.status_code == 200
    assert opened.content == b"%PDF-1.4 shared"
    assert "no-store" in opened.headers["cache-control"]
    assert client.get("/api/shared/not-a-real-token").status_code == 404
    share_id = created.json()["id"]
    assert client.delete(f"/api/library/shares/{share_id}").status_code == 204
    assert client.post(f"/api/shared/{token}", json={"password": "correct-horse"}).status_code == 404
    client.cookies.clear()
    register(client, "thief@example.com")
    assert client.delete(f"/api/library/shares/{share_id}").status_code == 404


def test_onboarding_account_controls_and_csrf(client):
    register(client, "owner@example.com")
    onboarded = client.post("/api/account/onboarding", json={"audience": "university_applicant", "timezone_name": "UTC", "skip": False})
    assert onboarded.status_code == 200
    assert onboarded.json()["onboarding_completed"] is True
    assert onboarded.json()["billing_connected"] is False
    names = {item["name"] for item in client.get("/api/library/folders").json()}
    assert "University Admissions" in names
    assert "Uncategorized" in names
    categories = client.get("/api/library/categories")
    assert categories.status_code == 200
    assert "Academic" in categories.json()["suggested"]
    rejected = client.patch("/api/account/profile", json={"plan": "business"})
    assert rejected.status_code == 422
    exported = client.get("/api/account/export")
    assert exported.status_code == 200
    assert "password" not in exported.text
    sessions = client.get("/api/account/sessions").json()
    assert any(item["current"] for item in sessions)
    token = client.cookies.get("docsmio_session")
    with TestClient(fastapi_app) as raw:
        raw.cookies.set("docsmio_session", token)
        blocked = raw.post("/api/library/folders", json={"name": "Blocked"})
        assert blocked.status_code == 403
        allowed = raw.post(
            "/api/library/folders",
            json={"name": "From bearer"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert allowed.status_code == 201
    removed = client.request("DELETE", "/api/account", json={"password": "correct-horse", "confirm": "DELETE"})
    assert removed.status_code == 204
    assert client.get("/api/auth/me").status_code == 401
