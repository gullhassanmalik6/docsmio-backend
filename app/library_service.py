import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.library_files import delete_owned_file, safe_filename
from app.models import LibraryDocument, LibraryFolder, User

DEFAULT_FOLDERS = [
    ("educational", "Educational Documents"),
    ("identification", "Identification Documents"),
    ("career", "Career & Work"),
    ("financial", "Financial Documents"),
    ("medical", "Medical Documents"),
    ("personal", "Personal Documents"),
    ("uncategorized", "Uncategorized"),
]


def ensure_folders(db: Session, user: User) -> list[LibraryFolder]:
    rows = list(db.scalars(select(LibraryFolder).where(LibraryFolder.user_id == user.id)))
    if rows:
        return rows
    now = datetime.now(UTC)
    created = [
        LibraryFolder(user_id=user.id, name=name, system_key=key, created_at=now, updated_at=now)
        for key, name in DEFAULT_FOLDERS
    ]
    db.add_all(created)
    db.commit()
    for folder in created:
        db.refresh(folder)
    return created


def owned_folder(db: Session, user: User, folder_id: uuid.UUID) -> LibraryFolder:
    folder = db.get(LibraryFolder, folder_id)
    if folder is None or folder.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found.")
    return folder


def owned_document(db: Session, user: User, document_id: uuid.UUID) -> LibraryDocument:
    document = db.get(LibraryDocument, document_id)
    if document is None or document.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return document


def unique_name(db: Session, user: User, filename: str, ignore_id: uuid.UUID | None = None) -> str:
    names = {
        row.filename.lower()
        for row in db.scalars(select(LibraryDocument).where(LibraryDocument.user_id == user.id))
        if row.id != ignore_id
    }
    candidate = safe_filename(filename)
    if candidate.lower() not in names:
        return candidate
    dot = candidate.rfind(".")
    stem = candidate[:dot] if dot > 0 else candidate
    extension = candidate[dot:] if dot > 0 else ""
    count = 2
    while f"{stem} ({count}){extension}".lower() in names:
        count += 1
    return f"{stem} ({count}){extension}"


def create_folder(db: Session, user: User, name: str, parent_id: uuid.UUID | None) -> LibraryFolder:
    ensure_folders(db, user)
    if parent_id is not None:
        owned_folder(db, user, parent_id)
    cleaned = name.strip()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Enter a folder name.")
    now = datetime.now(UTC)
    folder = LibraryFolder(user_id=user.id, name=cleaned[:80], parent_id=parent_id, created_at=now, updated_at=now)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


def rename_folder(db: Session, user: User, folder_id: uuid.UUID, name: str) -> LibraryFolder:
    folder = owned_folder(db, user, folder_id)
    cleaned = name.strip()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Enter a folder name.")
    folder.name = cleaned[:80]
    folder.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(folder)
    return folder


def move_folder(db: Session, user: User, folder_id: uuid.UUID, parent_id: uuid.UUID | None) -> LibraryFolder:
    folder = owned_folder(db, user, folder_id)
    if parent_id == folder.id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="A folder cannot be moved into itself.")
    current = parent_id
    seen: set[uuid.UUID] = set()
    while current is not None:
        if current == folder.id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="A folder cannot be moved into one of its subfolders.")
        if current in seen:
            break
        seen.add(current)
        parent = owned_folder(db, user, current)
        current = parent.parent_id
    folder.parent_id = parent_id
    folder.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(folder)
    return folder


def delete_folder(db: Session, user: User, folder_id: uuid.UUID, disposition: str) -> None:
    folder = owned_folder(db, user, folder_id)
    if folder.system_key == "uncategorized":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Uncategorized cannot be deleted.")
    child = db.scalar(select(LibraryFolder).where(LibraryFolder.parent_id == folder.id, LibraryFolder.user_id == user.id))
    if child is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Move or delete the subfolders first.")
    documents = list(db.scalars(select(LibraryDocument).where(LibraryDocument.folder_id == folder.id, LibraryDocument.user_id == user.id)))
    if disposition == "delete":
        for document in documents:
            delete_owned_file(user.id, document.storage_key)
            db.delete(document)
    else:
        uncategorized = db.scalar(
            select(LibraryFolder).where(LibraryFolder.user_id == user.id, LibraryFolder.system_key == "uncategorized")
        )
        if uncategorized is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Uncategorized is missing.")
        for document in documents:
            document.folder_id = uncategorized.id
            document.updated_at = datetime.now(UTC)
    db.delete(folder)
    db.commit()


def add_document(
    db: Session,
    user: User,
    folder_id: uuid.UUID,
    filename: str,
    mime_type: str,
    size: int,
    storage_key: str,
    classification_key: str | None,
) -> LibraryDocument:
    owned_folder(db, user, folder_id)
    now = datetime.now(UTC)
    document = LibraryDocument(
        user_id=user.id,
        folder_id=folder_id,
        filename=unique_name(db, user, filename),
        mime_type=mime_type,
        size=size,
        storage_key=storage_key,
        favorite=False,
        classification_key=classification_key,
        classification_method="filename" if classification_key else None,
        created_at=now,
        updated_at=now,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def update_document(
    db: Session,
    user: User,
    document_id: uuid.UUID,
    filename: str | None,
    folder_id: uuid.UUID | None,
    favorite: bool | None,
) -> LibraryDocument:
    document = owned_document(db, user, document_id)
    if folder_id is not None:
        owned_folder(db, user, folder_id)
        document.folder_id = folder_id
    if filename is not None:
        document.filename = unique_name(db, user, filename, ignore_id=document.id)
    if favorite is not None:
        document.favorite = favorite
    document.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(document)
    return document


def remove_document(db: Session, user: User, document_id: uuid.UUID) -> None:
    document = owned_document(db, user, document_id)
    delete_owned_file(user.id, document.storage_key)
    db.delete(document)
    db.commit()


def list_documents(
    db: Session,
    user: User,
    folder_id: uuid.UUID | None,
    favorite: bool | None,
    query: str | None,
    sort: str,
) -> list[LibraryDocument]:
    rows = list(db.scalars(select(LibraryDocument).where(LibraryDocument.user_id == user.id)))
    if folder_id is not None:
        rows = [row for row in rows if row.folder_id == folder_id]
    if favorite:
        rows = [row for row in rows if row.favorite]
    if query:
        needle = query.strip().lower()
        rows = [row for row in rows if needle in row.filename.lower()]
    if sort == "name":
        rows.sort(key=lambda row: row.filename.lower())
    elif sort == "size":
        rows.sort(key=lambda row: row.size, reverse=True)
    elif sort == "type":
        rows.sort(key=lambda row: row.mime_type)
    elif sort == "updated":
        rows.sort(key=lambda row: row.updated_at, reverse=True)
    else:
        rows.sort(key=lambda row: row.created_at, reverse=True)
    return rows
