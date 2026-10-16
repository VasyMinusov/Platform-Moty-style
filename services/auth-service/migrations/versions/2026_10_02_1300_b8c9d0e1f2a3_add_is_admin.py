"""add is_admin to users

Добавляет флаг администратора в users.

Использование:
    python -m app.scripts.promote_admin --email admin@example.com

server_default='false' + NOT NULL:
- существующие строки получают false (иначе NOT NULL violation);
- новые INSERT'ы без явного указания — тоже false (defense in depth:
  модель имеет default=False, но и БД подстрахует).

down_revision = "a7b8c9d0e1f2" (jsonb audit metadata).

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-02 13:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")