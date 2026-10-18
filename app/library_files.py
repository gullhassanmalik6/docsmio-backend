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


def storage_root() -> Path:
    root = Path(get_settings().library_storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", name).strip().strip(".")
    return cleaned[:180] or "document"


async def save_upload(user_id: uuid.UUID, upload: UploadFile) -> tuple[str, str, int, str]:
    content_type = upload.content_type or ""
    extension = ALLOWED_TYPES.get(content_type)
    if extension is None:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Online library accepts PDF, JPG, PNG, and WebP files.")
    data = await upload.read()
    if len(data) == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The file is empty.")
    if len(data) > MAX_LIBRARY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Online library files must be 50 MB or smaller.")
    key = uuid.uuid4().hex
    folder = storage_root() / str(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / key
    if not target.resolve().is_relative_to(folder.resolve()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The file could not be stored.")
    target.write_bytes(data)
    return key, content_type, len(data), safe_filename(upload.filename or f"document{extension}")


def read_owned_file(user_id: uuid.UUID, storage_key: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", storage_key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The file is missing.")
    path = storage_root() / str(user_id) / storage_key
    folder = (storage_root() / str(user_id)).resolve()
    if not path.resolve().is_relative_to(folder) or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The file is missing.")
    return path


def delete_owned_file(user_id: uuid.UUID, storage_key: str) -> None:
    path = storage_root() / str(user_id) / storage_key
    if path.is_file():
        path.unlink()
