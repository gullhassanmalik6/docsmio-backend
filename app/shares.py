import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.library_service import owned_document
from app.models import LibraryDocument, ShareLink, User
from app.security import as_utc, hash_password, hash_token, new_token, verify_password

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,200}$")


def create_share(
    db: Session,
    user: User,
    document_id: uuid.UUID,
    hours: int,
    permission: str,
    password: str | None,
) -> tuple[ShareLink, str]:
    if hours < 1 or hours > 24 * 30:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Choose an expiry between 1 hour and 30 days.")
    if permission not in {"view", "download"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Permission must be view or download.")
    owned_document(db, user, document_id)
    if password is not None and password.strip() and len(password) < 8:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="A share password needs at least 8 characters.")
    token = new_token()
    now = datetime.now(UTC)
    share = ShareLink(
        user_id=user.id,
        document_id=document_id,
        token_hash=hash_token(token),
        expires_at=now + timedelta(hours=hours),
        permission=permission,
        password_hash=hash_password(password) if password and password.strip() else None,
        created_at=now,
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    return share, token


def list_shares(db: Session, user: User) -> list[ShareLink]:
    return list(db.scalars(select(ShareLink).where(ShareLink.user_id == user.id).order_by(ShareLink.created_at.desc())))


def revoke_share(db: Session, user: User, share_id: uuid.UUID) -> None:
    share = db.get(ShareLink, share_id)
    if share is None or share.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share link not found.")
    if share.revoked_at is None:
        share.revoked_at = datetime.now(UTC)
        db.commit()


def open_share(db: Session, token: str, password: str | None) -> tuple[ShareLink, LibraryDocument]:
    if not TOKEN_PATTERN.fullmatch(token or ""):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This link is not available.")
    share = db.scalar(select(ShareLink).where(ShareLink.token_hash == hash_token(token)))
    if share is None or share.revoked_at is not None or as_utc(share.expires_at) <= datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This link is not available.")
    document = db.get(LibraryDocument, share.document_id)
    if document is None or document.deleted_at is not None or document.user_id != share.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This link is not available.")
    if share.password_hash:
        if not password or not verify_password(password, share.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This link needs the correct password.")
    return share, document
