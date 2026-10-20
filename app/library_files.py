import hashlib
import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.config import get_settings

ALLOWED_TYPES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_LIBRARY_BYTES = 50 * 1024 * 1024


def sniffed_type(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def storage_root() -> Path:
    root = Path(get_settings().library_storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", name).strip().strip(".")
    return cleaned[:180] or "document"


async def save_upload(user_id: uuid.UUID, upload: UploadFile) -> tuple[str, str, int, str, str]:
    declared = upload.content_type or ""
    if declared not in ALLOWED_TYPES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Online library accepts PDF, JPG, PNG, and WebP files.")
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_LIBRARY_BYTES:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Online library files must be 50 MB or smaller.")
        chunks.append(chunk)
    data = b"".join(chunks)
    if size == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The file is empty.")
    detected = sniffed_type(data)
    if detected != declared:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="The file contents do not match a supported PDF or image.")
    key = uuid.uuid4().hex
    folder = storage_root() / str(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / key
    if not target.resolve().is_relative_to(folder.resolve()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The file could not be stored.")
    target.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    extension = ALLOWED_TYPES[detected]
    return key, detected, size, safe_filename(upload.filename or f"document{extension}"), digest


def read_owned_file(user_id: uuid.UUID, storage_key: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", storage_key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The file is missing.")
    path = storage_root() / str(user_id) / storage_key
    folder = (storage_root() / str(user_id)).resolve()
    if not path.resolve().is_relative_to(folder) or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The file is missing.")
    return path


def delete_owned_file(user_id: uuid.UUID, storage_key: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{32}", storage_key):
        return
    path = storage_root() / str(user_id) / storage_key
    folder = (storage_root() / str(user_id)).resolve()
    if path.resolve().is_relative_to(folder) and path.is_file():
        path.unlink()


def delete_user_storage(user_id: uuid.UUID) -> None:
    folder = storage_root() / str(user_id)
    if not folder.is_dir():
        return
    resolved = folder.resolve()
    if not resolved.is_relative_to(storage_root().resolve()):
        return
    for child in resolved.iterdir():
        if child.is_file() and child.resolve().is_relative_to(resolved):
            child.unlink()
    folder.rmdir()
