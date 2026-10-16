"""add email action tokens

Revision ID: 889e318d15ce
Revises: 9e2d917016d9
Create Date: 2026-10-01 17:49:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "889e318d15ce"
down_revision: Union[str, Sequence[str], None] = "9e2d917016d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ВАЖНО: create_type=False — мы создаём тип ЯВНО ниже, а не через create_table.
# Без этого SQLAlchemy попытается создать тип повторно внутри create_table
# и упадёт с DuplicateObjectError.
_email_action_type = postgresql.ENUM(
    "EMAIL_VERIFICATION",
    "PASSWORD_RESET",
    name="email_action_type",
    create_type=False,
)


def upgrade() -> None:
    # 1. Новые значения в enum audit_action.
    #    IF NOT EXISTS — идемпотентность (полезно при recovery после падения).
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'EMAIL_VERIFICATION_SENT'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'EMAIL_VERIFIED'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'PASSWORD_RESET_REQUESTED'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'PASSWORD_RESET_COMPLETED'")

    # 2. Явно создаём enum с checkfirst=True (пропустит, если уже есть).
    _email_action_type.create(op.get_bind(), checkfirst=True)

    # 3. Создаём таблицу. create_type=False на _email_action_type
    #    гарантирует, что SQLAlchemy НЕ будет создавать тип повторно.
    op.create_table(
        "email_action_tokens",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("action", _email_action_type, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_email_action_tokens_user_id"),
        "email_action_tokens", ["user_id"], unique=False,
    )
    op.create_index(
        op.f("ix_email_action_tokens_token_hash"),
        "email_action_tokens", ["token_hash"], unique=True,
    )
    op.create_index(
        op.f("ix_email_action_tokens_action"),
        "email_action_tokens", ["action"], unique=False,
    )
    op.create_index(
        op.f("ix_email_action_tokens_expires_at"),
        "email_action_tokens", ["expires_at"], unique=False,
    )
    op.create_index(
        "ix_email_action_tokens_user_action",
        "email_action_tokens", ["user_id", "action"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_email_action_tokens_user_action", table_name="email_action_tokens")
    op.drop_index(op.f("ix_email_action_tokens_expires_at"), table_name="email_action_tokens")
    op.drop_index(op.f("ix_email_action_tokens_action"), table_name="email_action_tokens")
    op.drop_index(op.f("ix_email_action_tokens_token_hash"), table_name="email_action_tokens")
    op.drop_index(op.f("ix_email_action_tokens_user_id"), table_name="email_action_tokens")
    op.drop_table("email_action_tokens")

    _email_action_type.drop(op.get_bind(), checkfirst=True)

    # Значения из audit_action не откатываем — PostgreSQL не поддерживает
    # удаление значений enum нативно. Лишние значения не мешают.