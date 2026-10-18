"""Add private document library tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_library"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "library_folders",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("library_folders.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("system_key", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_library_folders_user_id", "library_folders", ["user_id"])
    op.create_table(
        "library_documents",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("folder_id", sa.Uuid(), sa.ForeignKey("library_folders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("filename", sa.String(length=180), nullable=False),
        sa.Column("mime_type", sa.String(length=80), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=80), nullable=False),
        sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("classification_key", sa.String(length=40), nullable=True),
        sa.Column("classification_method", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_library_documents_user_id", "library_documents", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_library_documents_user_id", table_name="library_documents")
    op.drop_table("library_documents")
    op.drop_index("ix_library_folders_user_id", table_name="library_folders")
    op.drop_table("library_folders")
