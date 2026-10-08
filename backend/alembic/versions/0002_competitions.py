"""competitions initial: таблицы соревнований + расширение challenge_instances

Revision ID: 0002_competitions
Revises: 0001_legacy
Create Date: 2026-10-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_competitions"
down_revision = "0001_legacy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # ── Enum-типы (Postgres) ─────────────────────────────────────
    competition_visibility = postgresql.ENUM(
        "public", "private", "hidden", name="competitionvisibility", create_type=False,
    )
    competition_mode = postgresql.ENUM(
        "individual", "team", "both", name="competitionmode", create_type=False,
    )
    competition_status = postgresql.ENUM(
        "draft", "announced", "registration_open", "registration_closed",
        "running", "paused", "finished", "cancelled",
        name="competitionstatus", create_type=False,
    )
    leaderboard_visibility = postgresql.ENUM(
        "public", "participants", "hidden", name="leaderboardvisibility", create_type=False,
    )
    tie_breaker = postgresql.ENUM(
        "last_solve_time", "first_solve_time", "solves_count", "alphabetic",
        name="tiebreaker", create_type=False,
    )
    moderator_role = postgresql.ENUM(
        "responsible", "helper", name="moderatorrole", create_type=False,
    )
    application_status = postgresql.ENUM(
        "pending", "approved", "rejected", "withdrawn", "waitlist",
        "team_pending", "team_rejected", name="applicationstatus", create_type=False,
    )
    team_status = postgresql.ENUM(
        "forming", "pending", "approved", "rejected", "disqualified",
        name="teamstatus", create_type=False,
    )
    team_member_role = postgresql.ENUM(
        "captain", "member", name="teammemberrole", create_type=False,
    )
    team_member_status = postgresql.ENUM(
        "invited", "accepted", "declined", "removed", name="teammemberstatus", create_type=False,
    )
    ban_reason = postgresql.ENUM(
        "cheating", "abuse", "rule_violation", "other", name="banreason", create_type=False,
    )
    challenge_kind = postgresql.ENUM(
        "docker", "static", name="challengekind", create_type=False,
    )
    challenge_type = postgresql.ENUM(
        "web", "pwn", "crypto", "stego", "osint", "forensics",
        "reversing", "misc", "pentest", "network", "hardware", "other",
        name="challengetype", create_type=False,
    )
    challenge_difficulty = postgresql.ENUM(
        "easy", "medium", "hard", "insane", name="challengedifficulty", create_type=False,
    )
    challenge_visibility = postgresql.ENUM(
        "hidden", "visible_after_start", "visible", name="challengevisibility", create_type=False,
    )
    build_status = postgresql.ENUM(
        "pending", "validating", "building", "ready", "failed", "disabled",
        name="buildstatus", create_type=False,
    )
    dynamic_flag_strategy = postgresql.ENUM(
        "static", "per_user", "per_team", "per_instance", name="dynamicflagstrategy", create_type=False,
    )
    score_event_reason = postgresql.ENUM(
        "solve", "hint_penalty", "bonus", "manual", "placement",
        name="scoreeventreason", create_type=False,
    )
    appeal_status = postgresql.ENUM(
        "open", "accepted", "rejected", name="appealstatus", create_type=False,
    )

    for enum_type in [
        competition_visibility, competition_mode, competition_status,
        leaderboard_visibility, tie_breaker, moderator_role, application_status,
        team_status, team_member_role, team_member_status, ban_reason,
        challenge_kind, challenge_type, challenge_difficulty, challenge_visibility,
        build_status, dynamic_flag_strategy, score_event_reason, appeal_status,
    ]:
        enum_type.create(bind, checkfirst=True)

    # ── competitions ─────────────────────────────────────────────
    op.create_table(
        "competitions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(128), unique=True, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.String(500), server_default=""),
        sa.Column("description_md", sa.Text, server_default=""),
        sa.Column("rules_md", sa.Text, server_default=""),
        sa.Column("visibility", competition_visibility, nullable=False, server_default="hidden"),
        sa.Column("mode", competition_mode, nullable=False, server_default="individual"),
        sa.Column("status", competition_status, nullable=False, server_default="draft"),
        sa.Column("registration_opens_at", sa.DateTime, nullable=True),
        sa.Column("registration_closes_at", sa.DateTime, nullable=True),
        sa.Column("starts_at", sa.DateTime, nullable=True),
        sa.Column("ends_at", sa.DateTime, nullable=True),
        sa.Column("allow_late_application", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("allow_late_withdraw", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("max_participants", sa.Integer, nullable=True),
        sa.Column("max_teams", sa.Integer, nullable=True),
        sa.Column("min_team_size", sa.Integer, nullable=True),
        sa.Column("max_team_size", sa.Integer, nullable=True),
        sa.Column("public_team_roster", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("leaderboard_visibility", leaderboard_visibility, nullable=False, server_default="participants"),
        sa.Column("tie_breaker", tie_breaker, nullable=False, server_default="last_solve_time"),
        sa.Column("scoring_config", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("network_config", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("port_range_start", sa.Integer, nullable=True),
        sa.Column("port_range_end", sa.Integer, nullable=True),
        sa.Column("instance_ttl_seconds", sa.Integer, nullable=False, server_default="3600"),
        sa.Column("max_instances_per_user", sa.Integer, nullable=True),
        sa.Column("max_instances_per_team", sa.Integer, nullable=True),
        sa.Column("max_instances_per_competition", sa.Integer, nullable=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_competitions_slug", "competitions", ["slug"])
    op.create_index("ix_competitions_status", "competitions", ["status"])
    op.create_index("ix_competitions_status_visibility", "competitions", ["status", "visibility"])
    op.create_index("ix_competitions_dates", "competitions", ["starts_at", "ends_at"])

    # ── moderators ───────────────────────────────────────────────
    op.create_table(
        "competition_moderators",
        sa.Column("competition_id", sa.Integer, sa.ForeignKey("competitions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", moderator_role, nullable=False, server_default="helper"),
        sa.Column("added_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("added_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # ── audit log ────────────────────────────────────────────────
    op.create_table(
        "competition_audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("competition_id", sa.Integer, sa.ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=True),
        sa.Column("target_id", sa.String(128), nullable=True),
        sa.Column("payload_json", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_comp", "competition_audit_log", ["competition_id"])
    op.create_index("ix_audit_created", "competition_audit_log", ["created_at"])

    # ── teams ────────────────────────────────────────────────────
    op.create_table(
        "competition_teams",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("competition_id", sa.Integer, sa.ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("captain_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", team_status, nullable=False, server_default="forming"),
        sa.Column("invite_code", sa.String(32), unique=True, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("competition_id", "name", name="uq_team_comp_name"),
    )

    op.create_table(
        "competition_team_members",
        sa.Column("team_id", sa.Integer, sa.ForeignKey("competition_teams.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", team_member_role, nullable=False, server_default="member"),
        sa.Column("status", team_member_status, nullable=False, server_default="invited"),
        sa.Column("invited_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("joined_at", sa.DateTime, nullable=True),
    )

    # ── applications ─────────────────────────────────────────────
    op.create_table(
        "competition_applications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("competition_id", sa.Integer, sa.ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("team_id", sa.Integer, sa.ForeignKey("competition_teams.id", ondelete="SET NULL"), nullable=True),
        sa.Column("motivation", sa.Text, nullable=True),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("status", application_status, nullable=False, server_default="pending"),
        sa.Column("applied_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime, nullable=True),
        sa.Column("decided_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decision_comment", sa.Text, nullable=True),
        sa.UniqueConstraint("competition_id", "user_id", name="uq_application_comp_user"),
    )
    op.create_index("ix_applications_comp_status", "competition_applications", ["competition_id", "status"])

    # ── bans ─────────────────────────────────────────────────────
    op.create_table(
        "competition_bans",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("competition_id", sa.Integer, sa.ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", ban_reason, nullable=False),
        sa.Column("comment", sa.Text, nullable=False),
        sa.Column("banned_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("banned_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("competition_id", "user_id", name="uq_ban_comp_user"),
    )

    # ── challenges ───────────────────────────────────────────────
    op.create_table(
        "competition_challenges",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("competition_id", sa.Integer, sa.ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("kind", challenge_kind, nullable=False, server_default="docker"),
        sa.Column("type", challenge_type, nullable=False, server_default="other"),
        sa.Column("category", sa.String(64), nullable=False, server_default="misc"),
        sa.Column("difficulty", challenge_difficulty, nullable=False, server_default="easy"),
        sa.Column("description_md", sa.Text, server_default=""),
        sa.Column("points", sa.Integer, nullable=False, server_default="100"),
        sa.Column("flag_hash", sa.String(255), nullable=True),
        sa.Column("dynamic_flag_strategy", dynamic_flag_strategy, nullable=False, server_default="static"),
        sa.Column("container_port", sa.Integer, nullable=True),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("visibility", challenge_visibility, nullable=False, server_default="visible_after_start"),
        sa.Column("hints_json", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("dependencies_json", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("metadata_json", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("build_status", build_status, nullable=False, server_default="pending"),
        sa.Column("build_log", sa.Text, server_default=""),
        sa.Column("source_global_challenge_id", sa.Integer, sa.ForeignKey("challenges.id", ondelete="SET NULL"), nullable=True),
        sa.Column("uploaded_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("competition_id", "slug", name="uq_comp_challenge_slug"),
    )
    op.create_index("ix_comp_challenge_comp_order", "competition_challenges", ["competition_id", "order_index"])

    op.create_table(
        "competition_challenge_files",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("challenge_id", sa.Integer, sa.ForeignKey("competition_challenges.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.Column("mime", sa.String(128), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("stored_path", sa.Text, nullable=False),
        sa.Column("is_public", sa.Boolean, nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "competition_challenge_hint_purchases",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("competition_id", sa.Integer, sa.ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("challenge_id", sa.Integer, sa.ForeignKey("competition_challenges.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("team_id", sa.Integer, sa.ForeignKey("competition_teams.id", ondelete="CASCADE"), nullable=True),
        sa.Column("hint_index", sa.Integer, nullable=False),
        sa.Column("cost_paid", sa.Integer, nullable=False),
        sa.Column("purchased_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("(user_id IS NOT NULL) OR (team_id IS NOT NULL)", name="ck_hint_purchase_owner"),
    )
    op.create_index("ix_hint_purchases_challenge", "competition_challenge_hint_purchases", ["challenge_id"])
    op.create_index("ix_hint_purchases_team", "competition_challenge_hint_purchases", ["team_id"])
    op.create_index("ix_hint_purchases_user", "competition_challenge_hint_purchases", ["user_id"])

    # ── solves / scores ──────────────────────────────────────────
    op.create_table(
        "competition_solves",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("competition_id", sa.Integer, sa.ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("challenge_id", sa.Integer, sa.ForeignKey("competition_challenges.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("team_id", sa.Integer, sa.ForeignKey("competition_teams.id", ondelete="CASCADE"), nullable=True),
        sa.Column("solved_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("points_awarded", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rank_at_solve", sa.Integer, nullable=True),
        sa.Column("flag_used_hash", sa.String(255), nullable=False),
        sa.Column("is_first_blood", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.CheckConstraint("(user_id IS NOT NULL) OR (team_id IS NOT NULL)", name="ck_comp_solve_owner"),
    )
    op.create_index("ix_comp_solves_comp", "competition_solves", ["competition_id"])
    op.create_index("ix_comp_solves_challenge", "competition_solves", ["challenge_id"])
    op.create_index("ix_comp_solves_solved_at", "competition_solves", ["solved_at"])

    op.create_table(
        "competition_score_events",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("competition_id", sa.Integer, sa.ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("team_id", sa.Integer, sa.ForeignKey("competition_teams.id", ondelete="CASCADE"), nullable=True),
        sa.Column("delta", sa.Integer, nullable=False),
        sa.Column("reason", score_event_reason, nullable=False),
        sa.Column("related_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_score_events_comp", "competition_score_events", ["competition_id"])
    op.create_index("ix_score_events_created", "competition_score_events", ["created_at"])

    op.create_table(
        "competition_score_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("competition_id", sa.Integer, sa.ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("taken_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("data_json", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("ix_score_snapshots_comp", "competition_score_snapshots", ["competition_id"])

    op.create_table(
        "competition_appeals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("competition_id", sa.Integer, sa.ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("challenge_id", sa.Integer, sa.ForeignKey("competition_challenges.id", ondelete="SET NULL"), nullable=True),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("status", appeal_status, nullable=False, server_default="open"),
        sa.Column("resolved_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.Column("resolution", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_appeals_status", "competition_appeals", ["status"])

    # ── Расширение challenge_instances ───────────────────────────
    op.add_column("challenge_instances", sa.Column("competition_id", sa.Integer, nullable=True))
    op.add_column("challenge_instances", sa.Column("team_id", sa.Integer, nullable=True))
    op.add_column("challenge_instances", sa.Column("challenge_kind", sa.String(16), nullable=False, server_default="docker"))
    op.add_column("challenge_instances", sa.Column("dynamic_flag_hash", sa.String(255), nullable=True))
    op.create_foreign_key("fk_ci_competition", "challenge_instances", "competitions", ["competition_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_ci_team", "challenge_instances", "competition_teams", ["team_id"], ["id"], ondelete="SET NULL")

    # Снимаем старый UNIQUE(user_id, challenge_id) — он мешает соревнованиям
    op.drop_constraint("uq_user_challenge", "challenge_instances", type_="unique")

    # Partial unique indexes
    op.create_index(
        "uq_ci_global", "challenge_instances",
        ["user_id", "challenge_id"],
        unique=True,
        postgresql_where=sa.text("competition_id IS NULL"),
    )
    op.create_index(
        "uq_ci_comp_user", "challenge_instances",
        ["competition_id", "challenge_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("competition_id IS NOT NULL AND team_id IS NULL"),
    )
    op.create_index(
        "uq_ci_comp_team", "challenge_instances",
        ["competition_id", "challenge_id", "team_id"],
        unique=True,
        postgresql_where=sa.text("competition_id IS NOT NULL AND team_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_ci_comp_team", "challenge_instances")
    op.drop_index("uq_ci_comp_user", "challenge_instances")
    op.drop_index("uq_ci_global", "challenge_instances")
    op.create_unique_constraint("uq_user_challenge", "challenge_instances", ["user_id", "challenge_id"])
    op.drop_constraint("fk_ci_team", "challenge_instances", type_="foreignkey")
    op.drop_constraint("fk_ci_competition", "challenge_instances", type_="foreignkey")
    op.drop_column("challenge_instances", "dynamic_flag_hash")
    op.drop_column("challenge_instances", "challenge_kind")
    op.drop_column("challenge_instances", "team_id")
    op.drop_column("challenge_instances", "competition_id")

    for table in [
        "competition_appeals", "competition_score_snapshots",
        "competition_score_events", "competition_solves",
        "competition_challenge_hint_purchases", "competition_challenge_files",
        "competition_challenges", "competition_bans", "competition_applications",
        "competition_team_members", "competition_teams",
        "competition_audit_log", "competition_moderators", "competitions",
    ]:
        op.drop_table(table)

    for name in [
        "competitionvisibility", "competitionmode", "competitionstatus",
        "leaderboardvisibility", "tiebreaker", "moderatorrole", "applicationstatus",
        "teamstatus", "teammemberrole", "teammemberstatus", "banreason",
        "challengekind", "challengetype", "challengedifficulty", "challengevisibility",
        "buildstatus", "dynamicflagstrategy", "scoreeventreason", "appealstatus",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {name}")