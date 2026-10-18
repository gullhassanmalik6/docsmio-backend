import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class FileHistory(Base):
    __tablename__ = "file_history"
    __table_args__ = (
        Index("ix_file_history_user_created", "user_id", "created_at"),
        Index("ix_file_history_user_operation", "user_id", "operation_type"),
        Index("ix_file_history_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(180), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    original_size: Mapped[int] = mapped_column(Integer, nullable=False)
    output_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="history")
