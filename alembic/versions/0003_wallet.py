"""Add wallet profile, search fields, reminders, and share links."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_wallet"
down_revision: str | None = "0002_library"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("audience", sa.String(length=40), nullable=True))
    op.add_column("users", sa.Column("timezone_name", sa.String(length=64), nullable=False, server_default="UTC"))
    op.add_column("users", sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("users", sa.Column("notify_in_app", sa.Boolean(), nullable=False, server_default=sa.text("1")))
    op.add_column("users", sa.Column("notify_email", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("users", sa.Column("quiet_start", sa.String(length=5), nullable=True))
    op.add_column("users", sa.Column("quiet_end", sa.String(length=5), nullable=True))
    op.add_column("library_folders", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("library_documents", sa.Column("classification_confidence", sa.String(length=10), nullable=True))
    op.add_column("library_documents", sa.Column("category", sa.String(length=40), nullable=True))
    op.add_column("library_documents", sa.Column("category_source", sa.String(length=20), nullable=True))
    op.add_column("library_documents", sa.Column("category_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("library_documents", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("library_documents", sa.Column("tags", sa.String(length=400), nullable=False, server_default=""))
    op.add_column("library_documents", sa.Column("content_sha256", sa.String(length=64), nullable=True))
    op.add_column("library_documents", sa.Column("extracted_text", sa.Text(), nullable=True))
    op.add_column("library_documents", sa.Column("text_status", sa.String(length=20), nullable=False, server_default="none"))
    op.add_column("library_documents", sa.Column("date_value", sa.Date(), nullable=True))
    op.add_column("library_documents", sa.Column("date_label", sa.String(length=20), nullable=True))
    op.add_column("library_documents", sa.Column("date_source", sa.String(length=20), nullable=True))
    op.add_column("library_documents", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_library_documents_user_created", "library_documents", ["user_id", "created_at"])
    op.create_index("ix_library_documents_user_hash", "library_documents", ["user_id", "content_sha256"])
    op.create_table(
        "library_categories",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "name", name="uq_library_categories_user_name"),
    )
    op.create_index("ix_library_categories_user_id", "library_categories", ["user_id"])
    op.create_table(
        "reminders",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("library_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("reminder_type", sa.String(length=20), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone_name", sa.String(length=64), nullable=False),
        sa.Column("lead_days", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("snooze_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_reminders_user_id", "reminders", ["user_id"])
    op.create_index("ix_reminders_document_id", "reminders", ["document_id"])
    op.create_table(
        "reminder_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("reminder_id", sa.Uuid(), sa.ForeignKey("reminders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("fire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("detail", sa.String(length=180), nullable=True),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uq_reminder_delivery_key"),
    )
    op.create_index("ix_reminder_deliveries_reminder_id", "reminder_deliveries", ["reminder_id"])
    op.create_index("ix_reminder_deliveries_user_id", "reminder_deliveries", ["user_id"])
    op.create_index("ix_reminder_deliveries_fire_at", "reminder_deliveries", ["fire_at"])
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reminder_id", sa.Uuid(), sa.ForeignKey("reminders.id", ondelete="CASCADE"), nullable=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.String(length=300), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_table(
        "share_links",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("library_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("permission", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_share_links_user_id", "share_links", ["user_id"])
    op.create_index("ix_share_links_document_id", "share_links", ["document_id"])


def downgrade() -> None:
    op.drop_table("share_links")
    op.drop_table("notifications")
    op.drop_table("reminder_deliveries")
    op.drop_table("reminders")
    op.drop_table("library_categories")
    op.drop_index("ix_library_documents_user_hash", table_name="library_documents")
    op.drop_index("ix_library_documents_user_created", table_name="library_documents")
    for column in (
        "deleted_at",
        "date_source",
        "date_label",
        "date_value",
        "text_status",
        "extracted_text",
        "content_sha256",
        "tags",
        "notes",
        "category_confirmed",
        "category_source",
        "category",
        "classification_confidence",
    ):
        op.drop_column("library_documents", column)
    op.drop_column("library_folders", "sort_order")
    for column in ("quiet_end", "quiet_start", "notify_email", "notify_in_app", "onboarding_completed", "timezone_name", "audience"):
        op.drop_column("users", column)
