import uuid
from datetime import datetime

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
