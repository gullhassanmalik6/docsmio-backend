import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.classify import classify_document
from app.entitlements import storage_quota
from app.library_files import delete_owned_file, read_owned_file, safe_filename
from app.models import LibraryCategory, LibraryDocument, LibraryFolder, ShareLink, User
from app.text_extract import extract_for_mime, sanitize_text

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
        return sorted(rows, key=lambda folder: (folder.sort_order, folder.name.lower()))
    now = datetime.now(UTC)
    created = [
        LibraryFolder(user_id=user.id, name=name, system_key=key, sort_order=index, created_at=now, updated_at=now)
        for index, (key, name) in enumerate(DEFAULT_FOLDERS)
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


def owned_document(db: Session, user: User, document_id: uuid.UUID, include_deleted: bool = False) -> LibraryDocument:
    document = db.get(LibraryDocument, document_id)
    if document is None or document.user_id != user.id or (document.deleted_at is not None and not include_deleted):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return document


def storage_used(db: Session, user: User) -> int:
    value = db.scalar(
        select(func.coalesce(func.sum(LibraryDocument.size), 0)).where(
            LibraryDocument.user_id == user.id,
            LibraryDocument.deleted_at.is_(None),
        )
    )
    return int(value or 0)


def assert_storage_room(db: Session, user: User, extra: int) -> None:
    used = storage_used(db, user)
    quota = storage_quota(user.plan)
    if used + extra > quota:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"This upload would pass the {user.plan} storage limit. {used} of {quota} bytes are in use. Billing is not connected, so the plan cannot be changed here.",
        )


def find_duplicate(db: Session, user: User, digest: str) -> LibraryDocument | None:
    return db.scalar(
        select(LibraryDocument).where(
            LibraryDocument.user_id == user.id,
            LibraryDocument.content_sha256 == digest,
            LibraryDocument.deleted_at.is_(None),
        )
    )


def clean_notes(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = sanitize_text(value, 2000)
    return cleaned or None


def clean_tags(value: str | None) -> str:
    if not value:
        return ""
    tags: list[str] = []
    for part in value.split(","):
        tag = " ".join(part.strip().lower().split())
        if not tag or tag in tags:
            continue
        tags.append(tag[:30])
        if len(tags) == 12:
            break
    return ",".join(tags)


def clean_category(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned[:40] or None


def unique_name(db: Session, user: User, filename: str, ignore_id: uuid.UUID | None = None) -> str:
    names = {
        row.filename.lower()
        for row in db.scalars(
            select(LibraryDocument).where(LibraryDocument.user_id == user.id, LibraryDocument.deleted_at.is_(None))
        )
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
    current = db.scalar(select(func.max(LibraryFolder.sort_order)).where(LibraryFolder.user_id == user.id)) or 0
    folder = LibraryFolder(user_id=user.id, name=cleaned[:80], parent_id=parent_id, sort_order=int(current) + 1, created_at=now, updated_at=now)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


def reorder_folder(db: Session, user: User, folder_id: uuid.UUID, sort_order: int) -> LibraryFolder:
    folder = owned_folder(db, user, folder_id)
    folder.sort_order = max(0, min(sort_order, 10000))
    folder.updated_at = datetime.now(UTC)
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
            revoke_document_shares(db, document.id)
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


def revoke_document_shares(db: Session, document_id: uuid.UUID) -> None:
    now = datetime.now(UTC)
    shares = db.scalars(select(ShareLink).where(ShareLink.document_id == document_id, ShareLink.revoked_at.is_(None)))
    for share in shares:
        share.revoked_at = now


def apply_extracted_suggestion(document: LibraryDocument, text: str | None, status_value: str, overwrite_category: bool) -> None:
    document.extracted_text = text
    document.text_status = status_value
    suggestion = classify_document(document.filename, text)
    if overwrite_category and not document.category_confirmed:
        document.category = suggestion["category"]
        document.category_source = suggestion["method"]
        document.classification_confidence = suggestion["confidence"]
        if document.classification_method != "manual":
            document.classification_method = suggestion["method"]
        if not document.classification_key:
            document.classification_key = suggestion["folder_key"]
    if document.date_source != "manual":
        document.date_value = suggestion["date"]
        document.date_label = suggestion["date_label"]
        document.date_source = "suggested" if suggestion["date"] else None


def add_document(
    db: Session,
    user: User,
    folder_id: uuid.UUID,
    filename: str,
    mime_type: str,
    size: int,
    storage_key: str,
    classification_key: str | None,
    content_sha256: str,
    notes: str | None = None,
    tags: str | None = None,
    category: str | None = None,
) -> LibraryDocument:
    owned_folder(db, user, folder_id)
    manual_category = clean_category(category)
    text, text_status = extract_for_mime(mime_type, read_owned_file(user.id, storage_key))
    suggestion = classify_document(filename, text)
    now = datetime.now(UTC)
    document = LibraryDocument(
        user_id=user.id,
        folder_id=folder_id,
        filename=unique_name(db, user, filename),
        mime_type=mime_type,
        size=size,
        storage_key=storage_key,
        favorite=False,
        classification_key=classification_key or suggestion["folder_key"],
        classification_method="manual" if manual_category else ("filename" if classification_key else suggestion["method"]),
        classification_confidence=suggestion["confidence"],
        category=manual_category or suggestion["category"],
        category_source="manual" if manual_category else suggestion["method"],
        category_confirmed=manual_category is not None,
        notes=clean_notes(notes),
        tags=clean_tags(tags),
        content_sha256=content_sha256,
        extracted_text=text,
        text_status=text_status,
        date_value=suggestion["date"],
        date_label=suggestion["date_label"],
        date_source="suggested" if suggestion["date"] else None,
        created_at=now,
        updated_at=now,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def update_document(db: Session, user: User, document_id: uuid.UUID, changes: dict) -> LibraryDocument:
    document = owned_document(db, user, document_id)
    if "folder_id" in changes and changes["folder_id"] is not None:
        owned_folder(db, user, changes["folder_id"])
        document.folder_id = changes["folder_id"]
    if "filename" in changes and changes["filename"] is not None:
        document.filename = unique_name(db, user, changes["filename"], ignore_id=document.id)
    if "favorite" in changes and changes["favorite"] is not None:
        document.favorite = changes["favorite"]
    if "notes" in changes:
        document.notes = clean_notes(changes["notes"])
    if "tags" in changes:
        document.tags = clean_tags(changes["tags"])
    if "category" in changes:
        category = clean_category(changes["category"])
        if category:
            document.category = category
            document.category_source = "manual"
            document.category_confirmed = True
            document.classification_method = "manual"
    if changes.get("confirm_category") and document.category:
        document.category_confirmed = True
        document.category_source = "manual"
        document.classification_method = "manual"
    if changes.get("clear_date"):
        document.date_value = None
        document.date_label = None
        document.date_source = None
    elif "date_value" in changes and changes["date_value"] is not None:
        document.date_value = changes["date_value"]
        document.date_label = changes.get("date_label") or document.date_label or "expiry"
        if document.date_label not in {"expiry", "deadline", "issued", "renewal"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Use expiry, deadline, issued, or renewal as the date label.")
        document.date_source = "manual"
    document.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(document)
    return document


def store_document_text(db: Session, user: User, document_id: uuid.UUID, text: str) -> LibraryDocument:
    document = owned_document(db, user, document_id)
    cleaned = sanitize_text(text)
    apply_extracted_suggestion(document, cleaned or None, "ready" if cleaned else "unavailable", overwrite_category=True)
    document.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(document)
    return document


def reprocess_document(db: Session, user: User, document_id: uuid.UUID) -> LibraryDocument:
    document = owned_document(db, user, document_id)
    text, text_status = extract_for_mime(document.mime_type, read_owned_file(user.id, document.storage_key))
    if text_status == "pending" and document.extracted_text:
        text = document.extracted_text
        text_status = "ready"
    apply_extracted_suggestion(document, text, text_status, overwrite_category=True)
    document.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(document)
    return document


def remove_document(db: Session, user: User, document_id: uuid.UUID) -> None:
    document = owned_document(db, user, document_id)
    document.deleted_at = datetime.now(UTC)
    document.updated_at = document.deleted_at
    revoke_document_shares(db, document.id)
    db.commit()


def restore_document(db: Session, user: User, document_id: uuid.UUID) -> LibraryDocument:
    document = owned_document(db, user, document_id, include_deleted=True)
    if document.deleted_at is None:
        return document
    if document.content_sha256 and find_duplicate(db, user, document.content_sha256) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A copy of this file is already in your library.")
    assert_storage_room(db, user, document.size)
    document.deleted_at = None
    document.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(document)
    return document


def purge_document(db: Session, user: User, document_id: uuid.UUID) -> None:
    document = owned_document(db, user, document_id, include_deleted=True)
    revoke_document_shares(db, document.id)
    delete_owned_file(user.id, document.storage_key)
    db.delete(document)
    db.commit()


def _like(value: str):
    cleaned = " ".join(value.split()).lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{cleaned}%"


def query_documents(
    db: Session,
    user: User,
    folder_id: uuid.UUID | None,
    favorite: bool | None,
    query: str | None,
    sort: str,
    limit: int,
    offset: int,
    trash: bool = False,
    category: str | None = None,
    mime: str | None = None,
) -> tuple[list[LibraryDocument], int]:
    filters = [LibraryDocument.user_id == user.id, LibraryFolder.user_id == user.id]
    filters.append(LibraryDocument.deleted_at.is_not(None) if trash else LibraryDocument.deleted_at.is_(None))
    if folder_id is not None:
        filters.append(LibraryDocument.folder_id == folder_id)
    if favorite:
        filters.append(LibraryDocument.favorite.is_(True))
    if category:
        filters.append(func.lower(LibraryDocument.category) == category.strip().lower())
    if mime == "pdf":
        filters.append(LibraryDocument.mime_type == "application/pdf")
    elif mime == "image":
        filters.append(LibraryDocument.mime_type.like("image/%"))
    needle = " ".join((query or "").split()).lower()
    search = []
    if needle:
        pattern = _like(needle)
        search.append(
            or_(
                func.lower(LibraryDocument.filename).like(pattern, escape="\\"),
                func.lower(func.coalesce(LibraryDocument.notes, "")).like(pattern, escape="\\"),
                func.lower(func.coalesce(LibraryDocument.tags, "")).like(pattern, escape="\\"),
                func.lower(func.coalesce(LibraryDocument.extracted_text, "")).like(pattern, escape="\\"),
                func.lower(func.coalesce(LibraryDocument.category, "")).like(pattern, escape="\\"),
                func.lower(func.coalesce(LibraryDocument.classification_key, "")).like(pattern, escape="\\"),
                func.lower(LibraryFolder.name).like(pattern, escape="\\"),
            )
        )
    total = db.scalar(
        select(func.count())
        .select_from(LibraryDocument)
        .join(LibraryFolder, LibraryDocument.folder_id == LibraryFolder.id)
        .where(*filters, *search)
    ) or 0
    order = {
        "name": LibraryDocument.filename.asc(),
        "size": LibraryDocument.size.desc(),
        "type": LibraryDocument.mime_type.asc(),
        "updated": LibraryDocument.updated_at.desc(),
    }.get(sort, LibraryDocument.created_at.desc())
    rows = list(
        db.scalars(
            select(LibraryDocument)
            .join(LibraryFolder, LibraryDocument.folder_id == LibraryFolder.id)
            .where(*filters, *search)
            .order_by(order, LibraryDocument.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return rows, int(total)


def list_categories(db: Session, user: User) -> list[LibraryCategory]:
    return list(db.scalars(select(LibraryCategory).where(LibraryCategory.user_id == user.id).order_by(LibraryCategory.name.asc())))


def create_category(db: Session, user: User, name: str) -> LibraryCategory:
    cleaned = clean_category(name)
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Enter a category name.")
    existing = db.scalar(select(LibraryCategory).where(LibraryCategory.user_id == user.id, func.lower(LibraryCategory.name) == cleaned.lower()))
    if existing:
        return existing
    category = LibraryCategory(user_id=user.id, name=cleaned, created_at=datetime.now(UTC))
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def delete_category(db: Session, user: User, category_id: uuid.UUID) -> None:
    category = db.get(LibraryCategory, category_id)
    if category is None or category.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    db.delete(category)
    db.commit()
