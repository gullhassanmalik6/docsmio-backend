import re
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.entitlements import PLAN_FREE, features_for, history_limit
from app.models import FileHistory, SessionToken, User
from app.security import as_utc, expiry_from_now, hash_password, hash_token, new_token, verify_password

OPERATIONS = {
    "image-resize",
    "compress-pdf",
    "merge-pdf",
    "split-pdf",
    "image-to-pdf",
    "jpg-to-pdf",
    "convert",
    "watermark",
    "scan",
}
STATUSES = {"completed", "failed"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def normalize_email(email: str) -> str:
    return email.strip().lower()


def sanitize_filename(name: str) -> str:
    cleaned = name.replace("\\", " ").replace("/", " ")
    cleaned = re.sub(r"[\x00-\x1f<>:\"|?*]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    return cleaned[:180] or "document"


def register_user(db: Session, name: str, email: str, password: str) -> User:
    normalized = normalize_email(email)
    existing = db.scalar(select(User).where(User.email == normalized))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.")
    user = User(name=name.strip(), email=normalized, password_hash=hash_password(password), plan=PLAN_FREE, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email or password is incorrect.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled.")
    return user


def issue_session(db: Session, user: User) -> str:
    token = new_token()
    record = SessionToken(user_id=user.id, token_hash=hash_token(token), expires_at=expiry_from_now())
    db.add(record)
    db.commit()
    return token


def resolve_session(db: Session, token: str) -> User:
    record = db.scalar(select(SessionToken).where(SessionToken.token_hash == hash_token(token)))
    if record is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
    if record.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This session has ended. Sign in again.")
    if as_utc(record.expires_at) <= datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired.")
    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
    return user


def revoke_session(db: Session, token: str) -> None:
    record = db.scalar(select(SessionToken).where(SessionToken.token_hash == hash_token(token)))
    if record is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
    if record.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This session has ended. Sign in again.")
    if as_utc(record.expires_at) <= datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired.")
    record.revoked_at = datetime.now(UTC)
    db.commit()


def public_user(user: User) -> dict:
    from sqlalchemy.orm import object_session

    from app.entitlements import storage_quota
    from app.library_service import storage_used

    database = object_session(user)
    used = storage_used(database, user) if database is not None else 0
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "plan": user.plan,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "history_limit": history_limit(user.plan),
        "features": features_for(user.plan),
        "billing_connected": False,
        "audience": user.audience,
        "timezone_name": user.timezone_name,
        "onboarding_completed": user.onboarding_completed,
        "notify_in_app": user.notify_in_app,
        "notify_email": user.notify_email,
        "quiet_start": user.quiet_start,
        "quiet_end": user.quiet_end,
        "storage_used_bytes": used,
        "storage_quota_bytes": storage_quota(user.plan),
    }


def create_history(
    db: Session,
    user: User,
    filename: str,
    operation_type: str,
    original_size: int,
    output_size: int | None,
    status_value: str,
) -> FileHistory:
    if operation_type not in OPERATIONS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That operation is not supported.")
    if status_value not in STATUSES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Status must be completed or failed.")
    if original_size < 0 or original_size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Original size is outside the allowed range.")
    if output_size is not None and (output_size < 0 or output_size > MAX_UPLOAD_BYTES):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Output size is outside the allowed range.")
    count = db.scalar(select(func.count()).select_from(FileHistory).where(FileHistory.user_id == user.id)) or 0
    limit = history_limit(user.plan)
    if count >= limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"The {user.plan} plan stores {limit} history records. This account has reached that limit. Billing is not connected, so the plan cannot be changed here.",
        )
    record = FileHistory(
        user_id=user.id,
        original_filename=sanitize_filename(filename),
        operation_type=operation_type,
        original_size=original_size,
        output_size=output_size,
        status=status_value,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_history(
    db: Session,
    user: User,
    page: int,
    page_size: int,
    operation_type: str | None,
    status_value: str | None,
) -> tuple[list[FileHistory], int]:
    filters = [FileHistory.user_id == user.id]
    if operation_type:
        if operation_type not in OPERATIONS:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That operation is not supported.")
        filters.append(FileHistory.operation_type == operation_type)
    if status_value:
        if status_value not in STATUSES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Status must be completed or failed.")
        filters.append(FileHistory.status == status_value)
    total = db.scalar(select(func.count()).select_from(FileHistory).where(*filters)) or 0
    rows = db.scalars(
        select(FileHistory)
        .where(*filters)
        .order_by(FileHistory.created_at.desc(), FileHistory.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), total


def get_owned_history(db: Session, user: User, record_id: uuid.UUID) -> FileHistory:
    record = db.get(FileHistory, record_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="History record not found.")
    return record


def delete_history(db: Session, user: User, record_id: uuid.UUID) -> None:
    record = get_owned_history(db, user, record_id)
    db.delete(record)
    db.commit()
