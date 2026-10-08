"""ORM-модели модуля «Соревнования».

Не трогают существующие модели из models.py.
Используют ту же БД и Base.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Enum, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from .database import Base


# ── Enum'ы ────────────────────────────────────────────────────────────

class CompetitionVisibility(str, enum.Enum):
    public = "public"
    private = "private"
    hidden = "hidden"


class CompetitionMode(str, enum.Enum):
    individual = "individual"
    team = "team"
    both = "both"


class CompetitionStatus(str, enum.Enum):
    draft = "draft"
    announced = "announced"
    registration_open = "registration_open"
    registration_closed = "registration_closed"
    running = "running"
    paused = "paused"
    finished = "finished"
    cancelled = "cancelled"


class LeaderboardVisibility(str, enum.Enum):
    public = "public"
    participants = "participants"
    hidden = "hidden"


class TieBreaker(str, enum.Enum):
    last_solve_time = "last_solve_time"
    first_solve_time = "first_solve_time"
    solves_count = "solves_count"
    alphabetic = "alphabetic"


class ModeratorRole(str, enum.Enum):
    responsible = "responsible"
    helper = "helper"


class ApplicationStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    withdrawn = "withdrawn"
    waitlist = "waitlist"
    team_pending = "team_pending"
    team_rejected = "team_rejected"


class TeamStatus(str, enum.Enum):
    forming = "forming"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    disqualified = "disqualified"


class TeamMemberRole(str, enum.Enum):
    captain = "captain"
    member = "member"


class TeamMemberStatus(str, enum.Enum):
    invited = "invited"
    accepted = "accepted"
    declined = "declined"
    removed = "removed"


class BanReason(str, enum.Enum):
    cheating = "cheating"
    abuse = "abuse"
    rule_violation = "rule_violation"
    other = "other"


class ChallengeKind(str, enum.Enum):
    docker = "docker"
    static = "static"


class ChallengeType(str, enum.Enum):
    web = "web"
    pwn = "pwn"
    crypto = "crypto"
    stego = "stego"
    osint = "osint"
    forensics = "forensics"
    reversing = "reversing"
    misc = "misc"
    pentest = "pentest"
    network = "network"
    hardware = "hardware"
    other = "other"


class ChallengeDifficulty(str, enum.Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"
    insane = "insane"


class ChallengeVisibility(str, enum.Enum):
    hidden = "hidden"
    visible_after_start = "visible_after_start"
    visible = "visible"


class BuildStatus(str, enum.Enum):
    pending = "pending"
    validating = "validating"
    building = "building"
    ready = "ready"
    failed = "failed"
    disabled = "disabled"


class DynamicFlagStrategy(str, enum.Enum):
    static = "static"
    per_user = "per_user"
    per_team = "per_team"
    per_instance = "per_instance"


class ScoreEventReason(str, enum.Enum):
    solve = "solve"
    hint_penalty = "hint_penalty"
    bonus = "bonus"
    manual = "manual"
    placement = "placement"


class AppealStatus(str, enum.Enum):
    open = "open"
    accepted = "accepted"
    rejected = "rejected"


# ── Ядро ──────────────────────────────────────────────────────────────

class Competition(Base):
    __tablename__ = "competitions"

    id = Column(Integer, primary_key=True)
    slug = Column(String(128), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    summary = Column(String(500), default="")
    description_md = Column(Text, default="")
    rules_md = Column(Text, default="")

    visibility = Column(Enum(CompetitionVisibility), default=CompetitionVisibility.hidden, nullable=False)
    mode = Column(Enum(CompetitionMode), default=CompetitionMode.individual, nullable=False)
    status = Column(Enum(CompetitionStatus), default=CompetitionStatus.draft, nullable=False, index=True)

    registration_opens_at = Column(DateTime, nullable=True)
    registration_closes_at = Column(DateTime, nullable=True)
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)

    allow_late_application = Column(Boolean, default=False, nullable=False)
    allow_late_withdraw = Column(Boolean, default=False, nullable=False)

    max_participants = Column(Integer, nullable=True)
    max_teams = Column(Integer, nullable=True)
    min_team_size = Column(Integer, nullable=True)
    max_team_size = Column(Integer, nullable=True)
    public_team_roster = Column(Boolean, default=False, nullable=False)

    leaderboard_visibility = Column(Enum(LeaderboardVisibility), default=LeaderboardVisibility.participants, nullable=False)
    tie_breaker = Column(Enum(TieBreaker), default=TieBreaker.last_solve_time, nullable=False)

    scoring_config = Column(JSONB, default=dict, nullable=False)
    network_config = Column(JSONB, default=dict, nullable=False)

    port_range_start = Column(Integer, nullable=True)
    port_range_end = Column(Integer, nullable=True)
    instance_ttl_seconds = Column(Integer, default=3600, nullable=False)
    max_instances_per_user = Column(Integer, nullable=True)
    max_instances_per_team = Column(Integer, nullable=True)
    max_instances_per_competition = Column(Integer, nullable=True)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    moderators = relationship("CompetitionModerator", back_populates="competition", cascade="all, delete-orphan")
    applications = relationship("CompetitionApplication", back_populates="competition", cascade="all, delete-orphan")
    teams = relationship("CompetitionTeam", back_populates="competition", cascade="all, delete-orphan")
    challenges = relationship("CompetitionChallenge", back_populates="competition", cascade="all, delete-orphan")
    bans = relationship("CompetitionBan", back_populates="competition", cascade="all, delete-orphan")
    appeals = relationship("CompetitionAppeal", back_populates="competition", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_competitions_status_visibility", "status", "visibility"),
        Index("ix_competitions_dates", "starts_at", "ends_at"),
    )


class CompetitionModerator(Base):
    __tablename__ = "competition_moderators"

    competition_id = Column(Integer, ForeignKey("competitions.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role = Column(Enum(ModeratorRole), default=ModeratorRole.helper, nullable=False)
    added_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    competition = relationship("Competition", back_populates="moderators")


class CompetitionAuditLog(Base):
    __tablename__ = "competition_audit_log"

    id = Column(BigInteger, primary_key=True)
    competition_id = Column(Integer, ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(64), nullable=False)
    target_type = Column(String(64), nullable=True)
    target_id = Column(String(128), nullable=True)
    payload_json = Column(JSONB, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


# ── Заявки и команды ──────────────────────────────────────────────────

class CompetitionApplication(Base):
    __tablename__ = "competition_applications"

    id = Column(Integer, primary_key=True)
    competition_id = Column(Integer, ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(Integer, ForeignKey("competition_teams.id", ondelete="SET NULL"), nullable=True)

    motivation = Column(Text, nullable=True)
    comment = Column(Text, nullable=True)
    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.pending, nullable=False, index=True)

    applied_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    decided_at = Column(DateTime, nullable=True)
    decided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    decision_comment = Column(Text, nullable=True)

    competition = relationship("Competition", back_populates="applications")

    __table_args__ = (
        UniqueConstraint("competition_id", "user_id", name="uq_application_comp_user"),
        Index("ix_applications_comp_status", "competition_id", "status"),
    )


class CompetitionTeam(Base):
    __tablename__ = "competition_teams"

    id = Column(Integer, primary_key=True)
    competition_id = Column(Integer, ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(128), nullable=False)
    captain_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(Enum(TeamStatus), default=TeamStatus.forming, nullable=False)
    invite_code = Column(String(32), unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    competition = relationship("Competition", back_populates="teams")
    members = relationship("CompetitionTeamMember", back_populates="team", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("competition_id", "name", name="uq_team_comp_name"),
    )


class CompetitionTeamMember(Base):
    __tablename__ = "competition_team_members"

    team_id = Column(Integer, ForeignKey("competition_teams.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role = Column(Enum(TeamMemberRole), default=TeamMemberRole.member, nullable=False)
    status = Column(Enum(TeamMemberStatus), default=TeamMemberStatus.invited, nullable=False)
    invited_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    joined_at = Column(DateTime, nullable=True)

    team = relationship("CompetitionTeam", back_populates="members")


class CompetitionBan(Base):
    __tablename__ = "competition_bans"

    id = Column(Integer, primary_key=True)
    competition_id = Column(Integer, ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reason = Column(Enum(BanReason), nullable=False)
    comment = Column(Text, nullable=False)
    banned_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    banned_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)

    competition = relationship("Competition", back_populates="bans")

    __table_args__ = (
        UniqueConstraint("competition_id", "user_id", name="uq_ban_comp_user"),
    )


# ── Задания соревнования ──────────────────────────────────────────────

class CompetitionChallenge(Base):
    __tablename__ = "competition_challenges"

    id = Column(Integer, primary_key=True)
    competition_id = Column(Integer, ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False)
    slug = Column(String(128), nullable=False)
    title = Column(String(255), nullable=False)

    kind = Column(Enum(ChallengeKind), nullable=False, default=ChallengeKind.docker)
    type = Column(Enum(ChallengeType), nullable=False, default=ChallengeType.other)
    category = Column(String(64), nullable=False, default="misc")
    difficulty = Column(Enum(ChallengeDifficulty), nullable=False, default=ChallengeDifficulty.easy)

    description_md = Column(Text, default="")
    points = Column(Integer, nullable=False, default=100)
    flag_hash = Column(String(255), nullable=True)
    dynamic_flag_strategy = Column(Enum(DynamicFlagStrategy), default=DynamicFlagStrategy.static, nullable=False)

    container_port = Column(Integer, nullable=True)
    order_index = Column(Integer, default=0, nullable=False)
    visibility = Column(Enum(ChallengeVisibility), default=ChallengeVisibility.visible_after_start, nullable=False)

    hints_json = Column(JSONB, default=list, nullable=False)
    dependencies_json = Column(JSONB, default=list, nullable=False)
    metadata_json = Column(JSONB, default=dict, nullable=False)

    enabled = Column(Boolean, default=True, nullable=False)
    build_status = Column(Enum(BuildStatus), default=BuildStatus.pending, nullable=False)
    build_log = Column(Text, default="")

    source_global_challenge_id = Column(Integer, ForeignKey("challenges.id", ondelete="SET NULL"), nullable=True)

    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    competition = relationship("Competition", back_populates="challenges")
    files = relationship("CompetitionChallengeFile", back_populates="challenge", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("competition_id", "slug", name="uq_comp_challenge_slug"),
        Index("ix_comp_challenge_comp_order", "competition_id", "order_index"),
    )


class CompetitionChallengeFile(Base):
    __tablename__ = "competition_challenge_files"

    id = Column(Integer, primary_key=True)
    challenge_id = Column(Integer, ForeignKey("competition_challenges.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(255), nullable=False)
    size = Column(BigInteger, nullable=False)
    mime = Column(String(128), nullable=True)
    sha256 = Column(String(64), nullable=False)
    stored_path = Column(Text, nullable=False)
    is_public = Column(Boolean, default=True, nullable=False)

    challenge = relationship("CompetitionChallenge", back_populates="files")


class CompetitionChallengeHintPurchase(Base):
    __tablename__ = "competition_challenge_hint_purchases"

    id = Column(Integer, primary_key=True)
    competition_id = Column(Integer, ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False)
    challenge_id = Column(Integer, ForeignKey("competition_challenges.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    team_id = Column(Integer, ForeignKey("competition_teams.id", ondelete="CASCADE"), nullable=True)
    hint_index = Column(Integer, nullable=False)
    cost_paid = Column(Integer, nullable=False)
    purchased_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_hint_purchases_challenge", "challenge_id"),
        Index("ix_hint_purchases_team", "team_id"),
        Index("ix_hint_purchases_user", "user_id"),
        CheckConstraint(
            "(user_id IS NOT NULL) OR (team_id IS NOT NULL)",
            name="ck_hint_purchase_owner",
        ),
    )


# ── Решения и очки ────────────────────────────────────────────────────

class CompetitionSolve(Base):
    __tablename__ = "competition_solves"

    id = Column(Integer, primary_key=True)
    competition_id = Column(Integer, ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False)
    challenge_id = Column(Integer, ForeignKey("competition_challenges.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    team_id = Column(Integer, ForeignKey("competition_teams.id", ondelete="CASCADE"), nullable=True)
    solved_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    points_awarded = Column(Integer, nullable=False, default=0)
    rank_at_solve = Column(Integer, nullable=True)
    flag_used_hash = Column(String(255), nullable=False)
    is_first_blood = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL) OR (team_id IS NOT NULL)",
            name="ck_comp_solve_owner",
        ),
        Index("ix_comp_solves_comp", "competition_id"),
        Index("ix_comp_solves_challenge", "challenge_id"),
    )


class CompetitionScoreEvent(Base):
    __tablename__ = "competition_score_events"

    id = Column(BigInteger, primary_key=True)
    competition_id = Column(Integer, ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    team_id = Column(Integer, ForeignKey("competition_teams.id", ondelete="CASCADE"), nullable=True)
    delta = Column(Integer, nullable=False)
    reason = Column(Enum(ScoreEventReason), nullable=False)
    related_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class CompetitionScoreSnapshot(Base):
    __tablename__ = "competition_score_snapshots"

    id = Column(Integer, primary_key=True)
    competition_id = Column(Integer, ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False, index=True)
    taken_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    data_json = Column(JSONB, nullable=False, default=dict)


class CompetitionAppeal(Base):
    __tablename__ = "competition_appeals"

    id = Column(Integer, primary_key=True)
    competition_id = Column(Integer, ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    challenge_id = Column(Integer, ForeignKey("competition_challenges.id", ondelete="SET NULL"), nullable=True)
    message = Column(Text, nullable=False)
    status = Column(Enum(AppealStatus), default=AppealStatus.open, nullable=False, index=True)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    competition = relationship("Competition", back_populates="appeals")