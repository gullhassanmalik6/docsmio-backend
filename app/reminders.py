import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Notification, Reminder, ReminderDelivery, User
from app.security import as_utc

REMINDER_TYPES = {"expiry", "passport", "visa", "identity", "certificate", "scholarship", "admission", "custom", "renewal"}
CHANNELS = ("in_app", "email")


def require_zone(name: str) -> str:
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Choose a valid time zone.") from error
    return name


def parse_lead_days(values: list[int] | str) -> list[int]:
    if isinstance(values, str):
        raw = [part for part in values.split(",") if part.strip()]
        try:
            numbers = [int(part) for part in raw]
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Reminder days must be whole numbers.") from error
    else:
        numbers = list(values)
    if not numbers or len(numbers) > 8 or any(number < 0 or number > 3650 for number in numbers):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Choose between 1 and 8 reminder days, from 0 to 3650.")
    seen: list[int] = []
    for number in numbers:
        if number not in seen:
            seen.append(number)
    return seen


def lead_text(values: list[int]) -> str:
    return ",".join(str(value) for value in values)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def reminder_bucket(reminder: Reminder, now: datetime) -> str:
    if reminder.status != "active":
        return reminder.status
    zone = _zone(reminder.timezone_name)
    due = as_utc(reminder.due_at).astimezone(zone).date()
    today = now.astimezone(zone).date()
    if due < today:
        return "overdue"
    if due == today:
        return "today"
    return "upcoming"


def _quiet(user: User, now: datetime) -> bool:
    if not user.quiet_start or not user.quiet_end or user.quiet_start == user.quiet_end:
        return False
    start_h, start_m = (int(part) for part in user.quiet_start.split(":"))
    end_h, end_m = (int(part) for part in user.quiet_end.split(":"))
    local = now.astimezone(_zone(user.timezone_name))
    minutes = local.hour * 60 + local.minute
    start = start_h * 60 + start_m
    end = end_h * 60 + end_m
    if start < end:
        return start <= minutes < end
    return minutes >= start or minutes < end


def _key(reminder_id, channel: str, fire_at: datetime) -> str:
    return f"{reminder_id}:{channel}:{as_utc(fire_at).strftime('%Y%m%d%H%M')}"


def ensure_deliveries(db: Session, reminder: Reminder) -> None:
    if reminder.status != "active":
        return
    leads = parse_lead_days(reminder.lead_days)
    moments = [as_utc(reminder.due_at) - timedelta(days=day) for day in leads]
    if reminder.snooze_until is not None:
        moments.append(as_utc(reminder.snooze_until))
    for moment in moments:
        for channel in CHANNELS:
            key = _key(reminder.id, channel, moment)
            existing = db.scalar(select(ReminderDelivery).where(ReminderDelivery.idempotency_key == key))
            if existing is not None:
                continue
            db.add(
                ReminderDelivery(
                    reminder_id=reminder.id,
                    user_id=reminder.user_id,
                    channel=channel,
                    fire_at=moment,
                    state="scheduled",
                    attempt=0,
                    idempotency_key=key,
                    created_at=datetime.now(UTC),
                )
            )


def cancel_pending(db: Session, reminder: Reminder) -> None:
    rows = db.scalars(
        select(ReminderDelivery).where(
            ReminderDelivery.reminder_id == reminder.id,
            ReminderDelivery.state.in_(("scheduled", "failed")),
        )
    )
    for row in rows:
        row.state = "cancelled"
        row.detail = "Cancelled because the reminder changed."


def owned_reminder(db: Session, user: User, reminder_id) -> Reminder:
    reminder = db.get(Reminder, reminder_id)
    if reminder is None or reminder.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reminder not found.")
    return reminder


def create_reminder(db: Session, user: User, title: str, reminder_type: str, due_at: datetime, document_id, lead_days: list[int], timezone_name: str) -> Reminder:
    if reminder_type not in REMINDER_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="That reminder type is not supported.")
    if due_at.tzinfo is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Include a time zone with the reminder date.")
    if document_id is not None:
        from app.library_service import owned_document

        owned_document(db, user, document_id)
    now = datetime.now(UTC)
    reminder = Reminder(
        user_id=user.id,
        document_id=document_id,
        title=" ".join(title.split())[:120],
        reminder_type=reminder_type,
        due_at=due_at.astimezone(UTC),
        timezone_name=require_zone(timezone_name),
        lead_days=lead_text(parse_lead_days(lead_days)),
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(reminder)
    db.flush()
    ensure_deliveries(db, reminder)
    db.commit()
    db.refresh(reminder)
    return reminder


def update_reminder(db: Session, user: User, reminder_id, changes: dict) -> Reminder:
    reminder = owned_reminder(db, user, reminder_id)
    if reminder.status != "active":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="This reminder is no longer active.")
    if "title" in changes and changes["title"]:
        reminder.title = " ".join(changes["title"].split())[:120]
    if "due_at" in changes and changes["due_at"] is not None:
        if changes["due_at"].tzinfo is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Include a time zone with the reminder date.")
        reminder.due_at = changes["due_at"].astimezone(UTC)
    if "lead_days" in changes and changes["lead_days"] is not None:
        reminder.lead_days = lead_text(parse_lead_days(changes["lead_days"]))
    if "timezone_name" in changes and changes["timezone_name"]:
        reminder.timezone_name = require_zone(changes["timezone_name"])
    reminder.updated_at = datetime.now(UTC)
    cancel_pending(db, reminder)
    ensure_deliveries(db, reminder)
    db.commit()
    db.refresh(reminder)
    return reminder


def set_reminder_status(db: Session, user: User, reminder_id, status_value: str) -> Reminder:
    reminder = owned_reminder(db, user, reminder_id)
    reminder.status = status_value
    reminder.updated_at = datetime.now(UTC)
    cancel_pending(db, reminder)
    db.commit()
    db.refresh(reminder)
    return reminder


def snooze_reminder(db: Session, user: User, reminder_id, until: datetime) -> Reminder:
    reminder = owned_reminder(db, user, reminder_id)
    if until.tzinfo is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Include a time zone with the snooze time.")
    if as_utc(until) <= datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Choose a snooze time in the future.")
    reminder.status = "active"
    reminder.snooze_until = until.astimezone(UTC)
    reminder.updated_at = datetime.now(UTC)
    ensure_deliveries(db, reminder)
    db.commit()
    db.refresh(reminder)
    return reminder


def list_reminders(db: Session, user: User) -> list[Reminder]:
    return list(db.scalars(select(Reminder).where(Reminder.user_id == user.id).order_by(Reminder.due_at.asc())))


def _smtp_ready() -> bool:
    settings = get_settings()
    return bool(settings.smtp_host and settings.smtp_from)


def _send_email(recipient: str, title: str, due_at: datetime) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["Subject"] = f"Docsmio reminder: {title}"
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(
        f"{title} is due {due_at.isoformat()}.\n\nOpen Docsmio to review the reminder. Email delivery is not guaranteed if the mail server delays or rejects it.\n"
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
        if settings.smtp_tls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)


def _deliver(db: Session, user: User, reminder: Reminder, delivery: ReminderDelivery, now: datetime) -> None:
    if delivery.channel == "in_app":
        if not user.notify_in_app:
            delivery.state = "skipped"
            delivery.detail = "In-app notifications are turned off."
        else:
            db.add(
                Notification(
                    user_id=user.id,
                    reminder_id=reminder.id,
                    title=reminder.title[:120],
                    body=f"{reminder.reminder_type} reminder for {as_utc(reminder.due_at).date().isoformat()}.",
                    created_at=now,
                )
            )
            delivery.state = "sent"
        delivery.sent_at = now
        return
    if not user.notify_email:
        delivery.state = "skipped"
        delivery.detail = "Email notifications are turned off."
        delivery.sent_at = now
        return
    if not _smtp_ready():
        delivery.state = "skipped"
        delivery.detail = "Email delivery is not configured on this server."
        delivery.sent_at = now
        return
    try:
        _send_email(user.email, reminder.title, as_utc(reminder.due_at))
    except Exception:
        delivery.state = "failed"
        delivery.attempt += 1
        delivery.detail = "Email could not be sent."
        return
    delivery.state = "sent"
    delivery.sent_at = now
    delivery.detail = None


def dispatch_due(db: Session, now: datetime | None = None, user_id=None) -> int:
    moment = now or datetime.now(UTC)
    reminders = db.scalars(select(Reminder).where(Reminder.status == "active", *([Reminder.user_id == user_id] if user_id else [])))
    for reminder in reminders:
        ensure_deliveries(db, reminder)
    db.commit()
    filters = [
        ReminderDelivery.state.in_(("scheduled", "failed")),
        ReminderDelivery.fire_at <= moment,
        ReminderDelivery.attempt < 3,
    ]
    if user_id is not None:
        filters.append(ReminderDelivery.user_id == user_id)
    sent = 0
    for delivery in list(db.scalars(select(ReminderDelivery).where(*filters))):
        reminder = db.get(Reminder, delivery.reminder_id)
        user = db.get(User, delivery.user_id)
        if reminder is None or user is None or reminder.status != "active":
            delivery.state = "cancelled"
            db.commit()
            continue
        if _quiet(user, moment):
            continue
        _deliver(db, user, reminder, delivery, moment)
        if delivery.state == "sent":
            sent += 1
        db.commit()
    return sent


def list_notifications(db: Session, user: User) -> list[Notification]:
    return list(
        db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(100))
    )


def mark_notification(db: Session, user: User, notification_id, read: bool) -> Notification:
    item = db.get(Notification, notification_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found.")
    item.read_at = datetime.now(UTC) if read else None
    db.commit()
    db.refresh(item)
    return item
