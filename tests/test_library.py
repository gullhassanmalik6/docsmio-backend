def register(client, email="owner@example.com"):
    response = client.post(
        "/api/auth/register",
        json={"name": "Owner", "email": email, "password": "correct-horse"},
    )
    assert response.status_code == 201
    return response


def test_library_requires_auth(client):
    response = client.get("/api/library/documents")
    assert response.status_code == 401


def test_upload_is_private_and_rejects_bad_files(client, monkeypatch):
    register(client)
    folders = client.get("/api/library/folders")
    assert folders.status_code == 200
    assert len(folders.json()) == 7
    folder_id = next(item["id"] for item in folders.json() if item["system_key"] == "financial")

    uploaded = client.post(
        "/api/library/documents",
        data={"folder_id": folder_id, "classification_key": "financial"},
        files={"upload": ("receipt.pdf", b"%PDF-1.4 receipt", "application/pdf")},
    )
    assert uploaded.status_code == 201
    document = uploaded.json()
    assert document["filename"] == "receipt.pdf"
    assert "storage_key" not in document

    duplicate = client.post(
        "/api/library/documents",
        data={"folder_id": folder_id},
        files={"upload": ("receipt.pdf", b"%PDF-1.4 copy", "application/pdf")},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["filename"] == "receipt (2).pdf"

    downloaded = client.get(f"/api/library/documents/{document['id']}/file")
    assert downloaded.status_code == 200
    assert downloaded.content == b"%PDF-1.4 receipt"
    assert "attachment" in downloaded.headers["content-disposition"].lower()

    rejected = client.post(
        "/api/library/documents",
        data={"folder_id": folder_id},
        files={"upload": ("notes.txt", b"hello", "text/plain")},
    )
    assert rejected.status_code == 415

    monkeypatch.setattr("app.library_files.MAX_LIBRARY_BYTES", 4)
    oversized = client.post(
        "/api/library/documents",
        data={"folder_id": folder_id},
        files={"upload": ("big.pdf", b"12345", "application/pdf")},
    )
    assert oversized.status_code == 413

    client.post("/api/auth/logout")
    register(client, "other@example.com")
    stolen = client.get(f"/api/library/documents/{document['id']}/file")
    assert stolen.status_code == 404
    hidden = client.get("/api/library/documents")
    assert hidden.json() == []


def test_folder_cannot_move_into_itself(client):
    register(client, "folders@example.com")
    folders = client.get("/api/library/folders").json()
    parent = next(item for item in folders if item["system_key"] == "personal")
    created = client.post("/api/library/folders", json={"name": "Warranty", "parent_id": parent["id"]})
    assert created.status_code == 201
    folder_id = created.json()["id"]
    moved = client.patch(f"/api/library/folders/{folder_id}", json={"parent_id": folder_id})
    assert moved.status_code == 422
    renamed = client.patch(f"/api/library/folders/{folder_id}", json={"name": "Warranties"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Warranties"
