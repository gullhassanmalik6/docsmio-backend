import uuid

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.reminders import (
    create_reminder,
    dispatch_due,
    list_notifications,
    list_reminders,
    mark_notification,
    parse_lead_days,
    reminder_bucket,
    set_reminder_status,
    snooze_reminder,
    update_reminder,
)
from app.routers.auth import get_current_user
from app.schemas import NotificationPublic, ReminderCreate, ReminderPublic, ReminderUpdate, SnoozeRequest
from datetime import UTC, datetime

from fastapi import HTTPException, status

router = APIRouter(tags=["reminders"])


def reminder_out(reminder) -> ReminderPublic:
    return ReminderPublic(
        id=reminder.id,
        document_id=reminder.document_id,
        title=reminder.title,
        reminder_type=reminder.reminder_type,
        due_at=reminder.due_at,
        timezone_name=reminder.timezone_name,
        lead_days=parse_lead_days(reminder.lead_days),
        status=reminder.status,
        bucket=reminder_bucket(reminder, datetime.now(UTC)),
        snooze_until=reminder.snooze_until,
    )


@router.get("/reminders", response_model=list[ReminderPublic])
def get_reminders(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[ReminderPublic]:
    return [reminder_out(item) for item in list_reminders(db, user)]


@router.post("/reminders", response_model=ReminderPublic, status_code=201)
def post_reminder(body: ReminderCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ReminderPublic:
    reminder = create_reminder(db, user, body.title, body.reminder_type, body.due_at, body.document_id, body.lead_days, body.timezone_name)
    return reminder_out(reminder)


@router.patch("/reminders/{reminder_id}", response_model=ReminderPublic)
def patch_reminder(
    reminder_id: uuid.UUID,
    body: ReminderUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReminderPublic:
    return reminder_out(update_reminder(db, user, reminder_id, body.model_dump(exclude_unset=True)))


@router.post("/reminders/{reminder_id}/dismiss", response_model=ReminderPublic)
def dismiss_reminder(reminder_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ReminderPublic:
    return reminder_out(set_reminder_status(db, user, reminder_id, "dismissed"))


@router.post("/reminders/{reminder_id}/complete", response_model=ReminderPublic)
def complete_reminder(reminder_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ReminderPublic:
    return reminder_out(set_reminder_status(db, user, reminder_id, "completed"))


@router.post("/reminders/{reminder_id}/snooze", response_model=ReminderPublic)
def snooze(reminder_id: uuid.UUID, body: SnoozeRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ReminderPublic:
    return reminder_out(snooze_reminder(db, user, reminder_id, body.until))


@router.delete("/reminders/{reminder_id}", status_code=204)
def delete_reminder(reminder_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    set_reminder_status(db, user, reminder_id, "cancelled")


@router.post("/reminders/dispatch")
def dispatch_mine(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    sent = dispatch_due(db, user_id=user.id)
    return {"sent": sent, "note": "In-app reminders are saved even if this page is closed, as long as the API process is running. Email is sent only when SMTP settings are configured."}


@router.post("/jobs/reminders")
def dispatch_cron(
    db: Session = Depends(get_db),
    x_reminder_token: str | None = Header(default=None),
) -> dict:
    expected = get_settings().reminder_cron_token
    if not expected or x_reminder_token != expected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return {"sent": dispatch_due(db)}


@router.get("/notifications", response_model=list[NotificationPublic])
def get_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[NotificationPublic]:
    return [NotificationPublic.model_validate(item) for item in list_notifications(db, user)]


@router.post("/notifications/{notification_id}/read", response_model=NotificationPublic)
def read_notification(notification_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> NotificationPublic:
    return NotificationPublic.model_validate(mark_notification(db, user, notification_id, True))
