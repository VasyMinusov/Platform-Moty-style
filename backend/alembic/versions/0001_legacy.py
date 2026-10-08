"""legacy schema: users, challenges, challenge_instances, solves, writeups, lessons

Revision ID: 0001_legacy
Revises:
Create Date: 2026-10-08

Создаёт схему, которая до появления модуля «Соревнования» создавалась через
Base.metadata.create_all. На существующих БД эта ревизия НЕ выполняется —
main.py делает `alembic stamp 0001_legacy` (bootstrap), чтобы Alembic знал,
что эти таблицы уже есть.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_legacy"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    userrole = postgresql.ENUM(
        "student", "moderator", "admin",
        name="userrole", create_type=False,
    )
    userrole.create(bind, checkfirst=True)

    # ── users ────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", userrole, nullable=False, server_default="student"),
        sa.Column("points", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("is_blocked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── challenges ───────────────────────────────────────────────
    op.create_table(
        "challenges",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("difficulty", sa.String(32), nullable=False, server_default="easy"),
        sa.Column("points", sa.Integer, nullable=False, server_default="100"),
        sa.Column("description", sa.String(4000), server_default=""),
        sa.Column("flag_hash", sa.String(255), nullable=False),
        sa.Column("container_port", sa.Integer, nullable=False, server_default="80"),
        sa.Column("enabled", sa.Boolean, server_default=sa.true()),
    )
    op.create_index("ix_challenges_slug", "challenges", ["slug"], unique=True)

    # ── challenge_instances (БЕЗ соревновательных полей) ─────────
    op.create_table(
        "challenge_instances",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("challenge_id", sa.Integer, sa.ForeignKey("challenges.id"), nullable=False),
        sa.Column("container_id", sa.String(128), nullable=False),
        sa.Column("host_port", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), server_default="running"),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("user_id", "challenge_id", name="uq_user_challenge"),
    )

    # ── solves ───────────────────────────────────────────────────
    op.create_table(
        "solves",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("challenge_id", sa.Integer, sa.ForeignKey("challenges.id"), nullable=False),
        sa.Column("solved_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("user_id", "challenge_id", name="uq_solve_once"),
    )

    # ── writeups ─────────────────────────────────────────────────
    op.create_table(
        "writeups",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("challenge_slug", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_writeups_slug", "writeups", ["challenge_slug"], unique=True)

    # ── lessons ──────────────────────────────────────────────────
    op.create_table(
        "lessons",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.String(500), server_default=""),
        sa.Column("content_md", sa.Text, nullable=False, server_default=""),
        sa.Column("author_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_lessons_slug", "lessons", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_lessons_slug", "lessons")
    op.drop_table("lessons")
    op.drop_index("ix_writeups_slug", "writeups")
    op.drop_table("writeups")
    op.drop_table("solves")
    op.drop_table("challenge_instances")
    op.drop_index("ix_challenges_slug", "challenges")
    op.drop_table("challenges")
    op.drop_index("ix_users_email", "users")
    op.drop_index("ix_users_username", "users")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS userrole")