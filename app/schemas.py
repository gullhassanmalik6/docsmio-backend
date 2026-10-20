import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ErrorResponse(BaseModel):
    detail: str


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: EmailStr
    plan: str
    is_active: bool
    created_at: datetime
    history_limit: int
    features: list[str]
    billing_connected: bool
    audience: str | None = None
    timezone_name: str = "UTC"
    onboarding_completed: bool = False
    notify_in_app: bool = True
    notify_email: bool = False
    quiet_start: str | None = None
    quiet_end: str | None = None
    storage_used_bytes: int = 0
    storage_quota_bytes: int = 0


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class AuthResponse(BaseModel):
    user: UserPublic
    token_type: str = "bearer"


class HistoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_filename: str = Field(min_length=1, max_length=180)
    operation_type: str = Field(min_length=1, max_length=40)
    original_size: int = Field(ge=0, le=50 * 1024 * 1024)
    output_size: int | None = Field(default=None, ge=0, le=50 * 1024 * 1024)
    status: str = Field(pattern="^(completed|failed)$")


class HistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    operation_type: str
    original_size: int
    output_size: int | None
    status: str
    created_at: datetime
    download_available: bool = False


class HistoryPage(BaseModel):
    items: list[HistoryItem]
    page: int
    page_size: int
    total: int
    download_available: bool = False
    note: str = "These records describe completed work. The processed file stays in this browser and is not stored on the server."


class LibraryFolderPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    system_key: str | None
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime


class LibraryFolderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    parent_id: uuid.UUID | None = None


class LibraryFolderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    parent_id: uuid.UUID | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10000)


class LibraryDocumentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    folder_id: uuid.UUID
    filename: str
    mime_type: str
    size: int
    favorite: bool
    classification_key: str | None
    classification_method: str | None
    classification_confidence: str | None = None
    category: str | None = None
    category_source: str | None = None
    category_confirmed: bool = False
    notes: str | None = None
    tags: str = ""
    text_status: str = "none"
    has_text: bool = False
    date_value: date | None = None
    date_label: str | None = None
    date_source: str | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class LibraryDocumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str | None = Field(default=None, min_length=1, max_length=180)
    folder_id: uuid.UUID | None = None
    favorite: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)
    tags: str | None = Field(default=None, max_length=400)
    category: str | None = Field(default=None, max_length=40)
    confirm_category: bool | None = None
    date_value: date | None = None
    date_label: str | None = Field(default=None, max_length=20)
    clear_date: bool | None = None


class LibraryDocumentDetail(LibraryDocumentPublic):
    extracted_text: str | None = None


class LibrarySearchPage(BaseModel):
    items: list[LibraryDocumentPublic]
    page: int
    page_size: int
    total: int
    note: str = "Search checks names, folders, categories, tags, notes, and extracted text for this account. Pending or failed extraction is marked on each document."


class TextSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=20000)


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)


class CategoryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime


class CategoryList(BaseModel):
    suggested: list[str]
    custom: list[CategoryPublic]


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=80)
    audience: str | None = None
    timezone_name: str | None = Field(default=None, min_length=1, max_length=64)
    notify_in_app: bool | None = None
    notify_email: bool | None = None
    quiet_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class OnboardingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audience: str | None = None
    timezone_name: str = Field(min_length=1, max_length=64)
    skip: bool = False


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class AccountDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=8, max_length=128)
    confirm: str = Field(min_length=6, max_length=16)


class SessionPublic(BaseModel):
    id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    current: bool


class ReminderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    reminder_type: str = Field(pattern="^(expiry|passport|visa|identity|certificate|scholarship|admission|custom|renewal)$")
    due_at: datetime
    document_id: uuid.UUID | None = None
    lead_days: list[int] = Field(default_factory=lambda: [30, 7, 1])
    timezone_name: str = "UTC"


class ReminderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=120)
    due_at: datetime | None = None
    lead_days: list[int] | None = None
    timezone_name: str | None = None


class ReminderPublic(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID | None
    title: str
    reminder_type: str
    due_at: datetime
    timezone_name: str
    lead_days: list[int]
    status: str
    bucket: str
    snooze_until: datetime | None


class SnoozeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    until: datetime


class ShareCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: int = Field(ge=1, le=24 * 30)
    permission: str = Field(pattern="^(view|download)$")
    password: str | None = Field(default=None, max_length=128)


class ShareCreated(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    expires_at: datetime
    permission: str
    password_protected: bool
    token: str


class SharePublic(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    expires_at: datetime
    revoked_at: datetime | None
    permission: str
    password_protected: bool
    created_at: datetime


class ShareOpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str | None = Field(default=None, max_length=128)


class NotificationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reminder_id: uuid.UUID | None
    title: str
    body: str
    read_at: datetime | None
    created_at: datetime
