from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.library_files import delete_user_storage
from app.library_service import create_folder
from app.models import LibraryDocument, LibraryFolder, Reminder, SessionToken, ShareLink, User
from app.reminders import require_zone
from app.security import hash_password, verify_password

AUDIENCES = {
    "secondary_student": "Intermediate or high-school student",
    "university_applicant": "University applicant",
    "university_student": "University student",
    "graduate": "Graduate or job seeker",
    "international": "International student or expatriate",
    "family": "Family or personal use",
    "other": "Other",
}

SUGGESTED_FOLDERS = {
    "secondary_student": ["Personal Identity", "Academic Records", "Matriculation / Secondary School", "Intermediate / Higher Secondary", "Transcripts and Marksheets", "Certificates"],
    "university_applicant": ["Personal Identity", "University Admissions", "Transcripts and Marksheets", "Degrees and Certificates", "Scholarships and Fellowships", "Financial Documents"],
    "university_student": ["Personal Identity", "Academic Records", "Transcripts and Marksheets", "Degrees and Certificates", "Financial Documents", "Housing and Campus"],
    "graduate": ["Personal Identity", "CV and Employment", "Degrees and Certificates", "Financial Documents", "References"],
    "international": ["Personal Identity", "Passport and Visa", "Residence Permits", "Academic Records", "Financial Documents", "Medical Documents"],
    "family": ["Personal Identity", "Medical Documents", "Financial Documents", "Household", "Other Documents"],
    "other": ["Personal Identity", "Financial Documents", "Other Documents"],
}


def update_profile(db: Session, user: User, changes: dict) -> User:
    if "name" in changes and changes["name"]:
        user.name = changes["name"].strip()[:80]
    if "audience" in changes:
        audience = changes["audience"]
        if audience is not None and audience not in AUDIENCES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Choose one of the listed profiles.")
        user.audience = audience
    if "timezone_name" in changes and changes["timezone_name"]:
        user.timezone_name = require_zone(changes["timezone_name"])
    if "notify_in_app" in changes and changes["notify_in_app"] is not None:
        user.notify_in_app = changes["notify_in_app"]
    if "notify_email" in changes and changes["notify_email"] is not None:
        user.notify_email = changes["notify_email"]
    if "quiet_start" in changes or "quiet_end" in changes:
        start = changes.get("quiet_start", user.quiet_start)
        end = changes.get("quiet_end", user.quiet_end)
        if (start is None) != (end is None):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Set both quiet hours, or clear both.")
        user.quiet_start = start
        user.quiet_end = end
    db.commit()
    db.refresh(user)
    return user


def complete_onboarding(db: Session, user: User, audience: str | None, timezone_name: str, skip: bool) -> User:
    user.timezone_name = require_zone(timezone_name)
    if audience is not None:
        if audience not in AUDIENCES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Choose one of the listed profiles.")
        user.audience = audience
    if not skip and audience:
        for name in SUGGESTED_FOLDERS[audience]:
            existing = db.scalar(
                select(LibraryFolder).where(LibraryFolder.user_id == user.id, func.lower(LibraryFolder.name) == name.lower())
            )
            if existing is None:
                create_folder(db, user, name, None)
    user.onboarding_completed = True
    db.commit()
    db.refresh(user)
    return user


def export_account(db: Session, user: User) -> dict:
    folders = list(db.scalars(select(LibraryFolder).where(LibraryFolder.user_id == user.id)))
    documents = list(db.scalars(select(LibraryDocument).where(LibraryDocument.user_id == user.id)))
    reminders = list(db.scalars(select(Reminder).where(Reminder.user_id == user.id)))
    shares = list(db.scalars(select(ShareLink).where(ShareLink.user_id == user.id)))
    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "account": {"name": user.name, "email": user.email, "plan": user.plan, "audience": user.audience, "timezone_name": user.timezone_name},
        "folders": [{"id": str(folder.id), "name": folder.name, "parent_id": str(folder.parent_id) if folder.parent_id else None} for folder in folders],
        "documents": [
            {
                "id": str(document.id),
                "filename": document.filename,
                "folder_id": str(document.folder_id),
                "mime_type": document.mime_type,
                "size": document.size,
                "category": document.category,
                "category_source": document.category_source,
                "notes": document.notes,
                "tags": document.tags,
                "text_status": document.text_status,
                "extracted_text": document.extracted_text,
                "date_value": document.date_value.isoformat() if document.date_value else None,
                "date_label": document.date_label,
                "date_source": document.date_source,
                "deleted_at": document.deleted_at.isoformat() if document.deleted_at else None,
            }
            for document in documents
        ],
        "reminders": [
            {"id": str(item.id), "title": item.title, "reminder_type": item.reminder_type, "due_at": item.due_at.isoformat(), "status": item.status}
            for item in reminders
        ],
        "share_links": [
            {
                "id": str(item.id),
                "document_id": str(item.document_id),
                "expires_at": item.expires_at.isoformat(),
                "revoked_at": item.revoked_at.isoformat() if item.revoked_at else None,
                "permission": item.permission,
                "password_protected": item.password_hash is not None,
            }
            for item in shares
        ],
        "notes": [
            "This export contains account metadata and extracted text. Download each file separately while the account is open.",
            "Files stored by the service are not end-to-end encrypted. The server can read them to show previews, extract PDF text, and enforce access rules.",
            "Deleting an account removes database rows and the current stored files. A backup system, if one is added later, can keep copies until its own retention window ends.",
        ],
    }


def delete_account(db: Session, user: User, password: str, confirm: str) -> None:
    if confirm != "DELETE":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Type DELETE to confirm account deletion.")
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="The password is incorrect.")
    delete_user_storage(user.id)
    db.delete(user)
    db.commit()


def list_sessions(db: Session, user: User) -> list[SessionToken]:
    return list(db.scalars(select(SessionToken).where(SessionToken.user_id == user.id).order_by(SessionToken.created_at.desc())))


def revoke_other_sessions(db: Session, user: User, current_session_id) -> int:
    now = datetime.now(UTC)
    count = 0
    for record in list_sessions(db, user):
        if record.id != current_session_id and record.revoked_at is None:
            record.revoked_at = now
            count += 1
    db.commit()
    return count


def change_password(db: Session, user: User, current_password: str, new_password: str, current_session_id) -> None:
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="The password is incorrect.")
    if len(new_password) < 8 or len(new_password) > 128:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Use a password between 8 and 128 characters.")
    user.password_hash = hash_password(new_password)
    db.commit()
    revoke_other_sessions(db, user, current_session_id)
