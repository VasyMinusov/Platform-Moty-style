"""auth-service integration: drop password_hash, drop users id default

Revision ID: 0004_auth_service
Revises: 0003_notifications
Create Date: 2026-10-14

Что делаем:
1. Очищаем таблицу users вместе с зависимыми данными (solves,
   challenge_instances, lessons, competition_*, notifications).
   Причина: теперь источник истины для пользователей — auth-service.
   Старые записи имеют пароли в bcrypt, несовместимые с Argon2id
   auth-service, а их id могут конфликтовать с id из auth-service.
2. Удаляем колонку password_hash (её больше нет в ORM-модели).
3. Убираем DEFAULT у users.id (SERIAL) — id теперь приходит из
   auth-service и устанавливается явно через ORM.

Откат: невозможен без потери данных.
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_auth_service"
down_revision = "0003_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Wipe: удаляем всё, что ссылается на users ─────────────
    # Порядок в списке не важен — CASCADE снесёт связанные таблицы.
    # Перечисляем ЯВНО все таблицы с FK на users (и связанные через
    # них), чтобы:
    #   - было видно, что именно стирается;
    #   - RESTART IDENTITY сбросил sequences на всех затронутых
    #     таблицах (для CASCADE-удалённых sequences сброс тоже
    #     срабатывает, но явность лучше);
    #   - при будущих правках схемы список легко поддерживать.
    op.execute("TRUNCATE TABLE "
               "competition_score_events, "
               "competition_solves, "
               "competition_challenge_hint_purchases, "
               "competition_applications, "
               "competition_team_members, "
               "competition_teams, "
               "competition_moderators, "
               "competition_bans, "
               "competition_appeals, "
               "competition_audit_log, "
               "competition_challenges, "
               "competitions, "
               "challenge_instances, "
               "solves, "
               "lessons, "
               "writeups, "
               "notifications, "
               "users "
               "RESTART IDENTITY CASCADE")

    # ── 2. Удаляем password_hash ─────────────────────────────────
    op.drop_column("users", "password_hash")

    # ── 3. Убираем DEFAULT у users.id (SERIAL) ───────────────────
    # В PostgreSQL AUTOINCREMENT выражается через SEQUENCE + DEFAULT.
    # Мы больше не хотим, чтобы БД генерировала id — он приходит
    # из auth-service. ALTER COLUMN ... DROP DEFAULT убирает
    # default-выражение (nextval). Sequence дропаем отдельно.
    op.execute("ALTER TABLE users ALTER COLUMN id DROP DEFAULT")
    op.execute("DROP SEQUENCE IF EXISTS users_id_seq CASCADE")


def downgrade() -> None:
    # ── Откат (восстанавливаем password_hash как NOT NULL) ───────
    # Восстановить данные невозможно — они стёрты.
    op.add_column(
        "users",
        sa.Column(
            "password_hash",
            sa.String(255),
            nullable=False,
            server_default="!invalid!",
        ),
    )
    op.alter_column("users", "password_hash", server_default=None)

    # Восстанавливаем sequence (без AUTOINCREMENT — просто для совместимости).
    op.execute("CREATE SEQUENCE IF NOT EXISTS users_id_seq")
    op.execute(
        "ALTER TABLE users ALTER COLUMN id "
        "SET DEFAULT nextval('users_id_seq')"
    )
    op.execute("ALTER SEQUENCE users_id_seq OWNED BY users.id")