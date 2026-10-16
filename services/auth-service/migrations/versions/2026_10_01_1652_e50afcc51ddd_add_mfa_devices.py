"""add mfa devices

Revision ID: a1b2c3d4e5f6
Revises: 4613e3607c37
Create Date: 2026-10-02 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '4613e3607c37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создаём таблицу mfa_devices."""
    op.create_table(
        'mfa_devices',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('secret_encrypted', sa.Text(), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('backup_codes_hash', sa.Text(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    # UNIQUE на user_id — один активный MFA-девайс на пользователя.
    op.create_index(
        op.f('ix_mfa_devices_user_id'),
        'mfa_devices',
        ['user_id'],
        unique=True,
    )


def downgrade() -> None:
    """Удаляем таблицу mfa_devices."""
    op.drop_index(op.f('ix_mfa_devices_user_id'), table_name='mfa_devices')
    op.drop_table('mfa_devices')