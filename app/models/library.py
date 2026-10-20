import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LibraryFolder(Base):
    __tablename__ = "library_folders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("library_folders.id", ondelete="RESTRICT"), nullable=True)
    system_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=func.now())


class LibraryDocument(Base):
    __tablename__ = "library_documents"
    __table_args__ = (
        Index("ix_library_documents_user_created", "user_id", "created_at"),
        Index("ix_library_documents_user_hash", "user_id", "content_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    folder_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("library_folders.id", ondelete="RESTRICT"), nullable=False)
    filename: Mapped[str] = mapped_column(String(180), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(80), nullable=False)
    favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    classification_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    classification_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    classification_confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    category_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    category_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[str] = mapped_column(String(400), nullable=False, default="", server_default="")
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_status: Mapped[str] = mapped_column(String(20), nullable=False, default="none", server_default="none")
    date_value: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_label: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=func.now())

    @property
    def has_text(self) -> bool:
        return bool(self.extracted_text)
