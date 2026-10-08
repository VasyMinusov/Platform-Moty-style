"""notifications

Revision ID: 0003_notifications
Revises: 0002_competitions
Create Date: 2026-10-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_notifications"
down_revision = "0002_competitions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    level = postgresql.ENUM(
        "info", "success", "warning", "danger",
        name="notificationlevel", create_type=False,
    )
    level.create(bind, checkfirst=True)

    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("message", sa.Text, nullable=False, server_default=""),
        sa.Column("level", level, nullable=False, server_default="info"),
        sa.Column("link", sa.String(512), nullable=True),
        sa.Column("payload_json", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("read", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
    op.create_index(
        "ix_notifications_user_read_created",
        "notifications",
        ["user_id", "read", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_read_created", "notifications")
    op.drop_index("ix_notifications_created_at", "notifications")
    op.drop_index("ix_notifications_user_id", "notifications")
    op.drop_table("notifications")
    op.execute("DROP TYPE IF EXISTS notificationlevel")