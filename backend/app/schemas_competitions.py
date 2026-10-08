"""Pydantic-схемы модуля «Соревнования»."""
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ══════════════════════════════════════════════════════════════════════
# Scoring config
# ══════════════════════════════════════════════════════════════════════

class DynamicDecayConfig(BaseModel):
    decay_type: Literal["step", "linear", "logarithmic"] = "step"
    decay_step: int = Field(default=5, ge=0)
    decay_interval: int = Field(default=5, ge=1)
    min_points: int = Field(default=50, ge=0)
    max_points: int = Field(default=1000, ge=0)
    compute_at: Literal["on_solve", "dynamic"] = "on_solve"

    @model_validator(mode="after")
    def _check_bounds(self):
        if self.min_points > self.max_points:
            raise ValueError("min_points cannot exceed max_points")
        return self


class PlacementEntry(BaseModel):
    place: int = Field(ge=1)
    points: int = Field(ge=0)


class PlacementConfig(BaseModel):
    places: list[PlacementEntry] = Field(default_factory=list)
    default_points: int = Field(default=100, ge=0)
    apply_at: Literal["finish"] = "finish"


class BonusConfig(BaseModel):
    type: Literal["first_blood", "all_category", "custom"]
    points: int = Field(ge=0)
    category: Optional[str] = None
    label: Optional[str] = None


class PerChallengeOverride(BaseModel):
    mode: Literal["fixed", "dynamic_decay", "placement"]
    points: Optional[int] = None


class ScoringConfig(BaseModel):
    mode: Literal["fixed", "dynamic_decay", "placement"] = "fixed"
    default_points: int = Field(default=100, ge=0)
    per_challenge_override: dict[str, PerChallengeOverride] = Field(default_factory=dict)
    dynamic_decay: DynamicDecayConfig = Field(default_factory=DynamicDecayConfig)
    placement: PlacementConfig = Field(default_factory=PlacementConfig)
    hint_penalty: dict[str, Any] = Field(default_factory=lambda: {"apply": True})
    bonuses: list[BonusConfig] = Field(default_factory=list)
    team_scoring: Literal["sum_of_members", "team_only"] = "team_only"


class NetworkConfig(BaseModel):
    isolated: bool = True
    allow_internet: bool = False
    extra_hosts: list[str] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════
# Metadata по типам заданий
# ══════════════════════════════════════════════════════════════════════

class DockerMeta(BaseModel):
    dockerfile_path: str = "Dockerfile"
    build_args: dict[str, str] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)
    healthcheck_path: Optional[str] = None


class WebMeta(BaseModel):
    docker: DockerMeta = Field(default_factory=DockerMeta)


class PwnMeta(BaseModel):
    docker: DockerMeta = Field(default_factory=DockerMeta)
    has_source: bool = False
    has_binary: bool = True
    download_path: Optional[str] = None
    has_libc: bool = False


class PentestMeta(BaseModel):
    docker: DockerMeta = Field(default_factory=DockerMeta)
    scope: Literal["single_container", "network"] = "single_container"
    extra_containers: list[dict[str, Any]] = Field(default_factory=list)


class CryptoMeta(BaseModel):
    cipher_type: Optional[str] = None
    files: list[str] = Field(default_factory=list)
    description_extra: Optional[str] = None


class StegoMeta(BaseModel):
    media_type: Literal["image", "audio", "video", "archive", "other"] = "other"
    files: list[str] = Field(default_factory=list)
    hint_about_tool: Optional[str] = None


class OsintMeta(BaseModel):
    target_type: Literal["person", "company", "domain", "image", "other"] = "other"
    starting_material: list[str] = Field(default_factory=list)
    external_links: list[str] = Field(default_factory=list)


class ForensicsMeta(BaseModel):
    artifact_type: Literal["pcap", "memory_dump", "disk_image", "log", "other"] = "other"
    files: list[str] = Field(default_factory=list)


class MiscMeta(BaseModel):
    files: list[str] = Field(default_factory=list)
    description_extra: Optional[str] = None


class HardwareMeta(BaseModel):
    artifact_type: Literal["firmware", "schematic", "log", "other"] = "other"
    files: list[str] = Field(default_factory=list)


METADATA_SCHEMAS: dict[str, type[BaseModel]] = {
    "web": WebMeta,
    "network": WebMeta,
    "pwn": PwnMeta,
    "reversing": PwnMeta,
    "pentest": PentestMeta,
    "crypto": CryptoMeta,
    "stego": StegoMeta,
    "osint": OsintMeta,
    "forensics": ForensicsMeta,
    "misc": MiscMeta,
    "hardware": HardwareMeta,
    "other": MiscMeta,
}


# ══════════════════════════════════════════════════════════════════════
# Manifest YAML
# ══════════════════════════════════════════════════════════════════════

class HintEntry(BaseModel):
    text: str
    cost: int = Field(default=0, ge=0)


class Manifest(BaseModel):
    title: str
    type: Literal[
        "web", "pwn", "crypto", "stego", "osint", "forensics",
        "reversing", "misc", "pentest", "network", "hardware", "other",
    ]
    kind: Literal["docker", "static"]
    category: str = "misc"
    difficulty: Literal["easy", "medium", "hard", "insane"] = "easy"
    description: str = ""
    points: int = Field(default=100, ge=0)
    flag: Optional[str] = None
    flag_hash: Optional[str] = None
    container_port: Optional[int] = None
    dynamic_flag_strategy: Literal["static", "per_user", "per_team", "per_instance"] = "static"
    hints: list[HintEntry] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    visibility: Literal["hidden", "visible_after_start", "visible"] = "visible_after_start"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_kind(self):
        if self.kind == "docker" and not self.container_port:
            raise ValueError("container_port required for kind=docker")
        if self.kind == "static" and self.container_port:
            raise ValueError("container_port must be empty for kind=static")
        if not self.flag and not self.flag_hash:
            raise ValueError("either flag or flag_hash required")
        return self

    def validate_metadata(self) -> BaseModel:
        schema = METADATA_CLASS = METADATA_SCHEMAS.get(self.type, MiscMeta)
        return schema.model_validate(self.metadata)


# ══════════════════════════════════════════════════════════════════════
# Competition: In / Out / Update
# ══════════════════════════════════════════════════════════════════════

class CompetitionOut(BaseModel):
    id: int
    slug: str
    title: str
    summary: str
    description_md: str
    rules_md: str
    visibility: str
    mode: str
    status: str
    registration_opens_at: Optional[datetime] = None
    registration_closes_at: Optional[datetime] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    allow_late_application: bool
    allow_late_withdraw: bool
    max_participants: Optional[int] = None
    max_teams: Optional[int] = None
    min_team_size: Optional[int] = None
    max_team_size: Optional[int] = None
    public_team_roster: bool
    leaderboard_visibility: str
    tie_breaker: str
    scoring_config: dict
    network_config: dict
    port_range_start: Optional[int] = None
    port_range_end: Optional[int] = None
    instance_ttl_seconds: int
    max_instances_per_user: Optional[int] = None
    max_instances_per_team: Optional[int] = None
    max_instances_per_competition: Optional[int] = None
    created_by: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CompetitionListItem(BaseModel):
    """Короткая карточка анонса."""
    id: int
    slug: str
    title: str
    summary: str
    visibility: str
    mode: str
    status: str
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    registration_opens_at: Optional[datetime] = None
    registration_closes_at: Optional[datetime] = None
    min_team_size: Optional[int] = None
    max_team_size: Optional[int] = None
    max_participants: Optional[int] = None

    class Config:
        from_attributes = True


class CompetitionCreate(BaseModel):
    slug: str
    title: str
    summary: str = ""
    description_md: str = ""
    rules_md: str = ""
    visibility: Literal["public", "private", "hidden"] = "hidden"
    mode: Literal["individual", "team", "both"] = "individual"
    registration_opens_at: Optional[datetime] = None
    registration_closes_at: Optional[datetime] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    allow_late_application: bool = False
    allow_late_withdraw: bool = False
    max_participants: Optional[int] = None
    max_teams: Optional[int] = None
    min_team_size: Optional[int] = None
    max_team_size: Optional[int] = None
    public_team_roster: bool = False
    leaderboard_visibility: Literal["public", "participants", "hidden"] = "participants"
    tie_breaker: Literal["last_solve_time", "first_solve_time", "solves_count", "alphabetic"] = "last_solve_time"
    scoring_config: ScoringConfig = Field(default_factory=ScoringConfig)
    network_config: NetworkConfig = Field(default_factory=NetworkConfig)
    instance_ttl_seconds: int = 3600
    max_instances_per_user: Optional[int] = None
    max_instances_per_team: Optional[int] = None
    max_instances_per_competition: Optional[int] = None

    @field_validator("slug")
    @classmethod
    def _slug_format(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", v or ""):
            raise ValueError("slug must be kebab-case")
        return v

    @model_validator(mode="after")
    def _check_dates(self):
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValueError("starts_at must be before ends_at")
        if self.registration_opens_at and self.registration_closes_at \
                and self.registration_opens_at >= self.registration_closes_at:
            raise ValueError("registration_opens_at must be before registration_closes_at")
        if self.mode in ("team", "both"):
            if self.min_team_size is not None and self.max_team_size is not None \
                    and self.min_team_size > self.max_team_size:
                raise ValueError("min_team_size cannot exceed max_team_size")
        return self


class CompetitionUpdate(BaseModel):
    """Все поля опциональны. Менять можно только в статусах draft/announced.
    После старта — только отдельными endpoint'ами (pause/resume/finish)."""
    title: Optional[str] = None
    summary: Optional[str] = None
    description_md: Optional[str] = None
    rules_md: Optional[str] = None
    visibility: Optional[Literal["public", "private", "hidden"]] = None
    mode: Optional[Literal["individual", "team", "both"]] = None
    registration_opens_at: Optional[datetime] = None
    registration_closes_at: Optional[datetime] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    allow_late_application: Optional[bool] = None
    allow_late_withdraw: Optional[bool] = None
    max_participants: Optional[int] = None
    max_teams: Optional[int] = None
    min_team_size: Optional[int] = None
    max_team_size: Optional[int] = None
    public_team_roster: Optional[bool] = None
    leaderboard_visibility: Optional[Literal["public", "participants", "hidden"]] = None
    tie_breaker: Optional[Literal["last_solve_time", "first_solve_time", "solves_count", "alphabetic"]] = None
    scoring_config: Optional[ScoringConfig] = None
    network_config: Optional[NetworkConfig] = None
    instance_ttl_seconds: Optional[int] = None
    max_instances_per_user: Optional[int] = None
    max_instances_per_team: Optional[int] = None
    max_instances_per_competition: Optional[int] = None


# ══════════════════════════════════════════════════════════════════════
# Moderators
# ══════════════════════════════════════════════════════════════════════

class ModeratorAdd(BaseModel):
    user_id: int
    role: Literal["responsible", "helper"] = "helper"


class ModeratorOut(BaseModel):
    user_id: int
    username: str
    role: str
    added_by: int
    added_at: datetime

    class Config:
        from_attributes = True


# ══════════════════════════════════════════════════════════════════════
# Applications
# ══════════════════════════════════════════════════════════════════════

class ApplicationCreate(BaseModel):
    motivation: Optional[str] = None
    comment: Optional[str] = None


class ApplicationDecision(BaseModel):
    status: Literal["approved", "rejected", "waitlist"]
    comment: Optional[str] = None


class ApplicationOut(BaseModel):
    id: int
    competition_id: int
    user_id: int
    username: str
    team_id: Optional[int] = None
    motivation: Optional[str] = None
    comment: Optional[str] = None
    status: str
    applied_at: datetime
    decided_at: Optional[datetime] = None
    decided_by: Optional[int] = None
    decision_comment: Optional[str] = None

    class Config:
        from_attributes = True


# ══════════════════════════════════════════════════════════════════════
# Audit
# ══════════════════════════════════════════════════════════════════════

class AuditOut(BaseModel):
    id: int
    competition_id: int
    actor_id: Optional[int] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    payload_json: dict
    created_at: datetime

    class Config:
        from_attributes = True

# ══════════════════════════════════════════════════════════════════════
# Teams
# ══════════════════════════════════════════════════════════════════════

class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=128)


class TeamUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=128)


class TeamInvite(BaseModel):
    username: str


class TeamJoinByCode(BaseModel):
    invite_code: str


class TeamMemberOut(BaseModel):
    user_id: int
    username: str
    role: str
    status: str
    invited_at: datetime
    joined_at: Optional[datetime] = None


class TeamOut(BaseModel):
    id: int
    competition_id: int
    name: str
    captain_id: int
    captain_username: str
    status: str
    invite_code: Optional[str] = None   # только для участников команды
    created_at: datetime
    members: list[TeamMemberOut] = []
    member_count: int = 0
    min_team_size: Optional[int] = None
    max_team_size: Optional[int] = None


class TeamSummary(BaseModel):
    """Короткая карточка для списка команд."""
    id: int
    name: str
    captain_username: str
    status: str
    member_count: int

# ══════════════════════════════════════════════════════════════════════
# Competition challenges
# ══════════════════════════════════════════════════════════════════════

class CompetitionChallengeFileOut(BaseModel):
    id: int
    filename: str
    size: int
    mime: Optional[str] = None
    sha256: str
    is_public: bool

    class Config:
        from_attributes = True


class CompetitionChallengeOut(BaseModel):
    id: int
    competition_id: int
    slug: str
    title: str
    kind: str
    type: str
    category: str
    difficulty: str
    description_md: str
    points: int
    dynamic_flag_strategy: str
    container_port: Optional[int] = None
    order_index: int
    visibility: str
    hints_json: list
    dependencies_json: list
    metadata_json: dict
    enabled: bool
    build_status: str
    build_log: str
    uploaded_at: datetime
    # Для фронта: сколько подсказок уже куплено текущим пользователем
    purchased_hints: list[int] = []
    # Для фронта: решено ли текущим пользователем/командой
    solved: bool = False

    class Config:
        from_attributes = True


class CompetitionChallengeUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[Literal["easy", "medium", "hard", "insane"]] = None
    description_md: Optional[str] = None
    points: Optional[int] = None
    dynamic_flag_strategy: Optional[
        Literal["static", "per_user", "per_team", "per_instance"]
    ] = None
    container_port: Optional[int] = None
    order_index: Optional[int] = None
    visibility: Optional[Literal["hidden", "visible_after_start", "visible"]] = None
    hints_json: Optional[list] = None
    dependencies_json: Optional[list] = None
    metadata_json: Optional[dict] = None
    enabled: Optional[bool] = None
    # Новый флаг (опционально) — перехэшируется на сервере.
    flag: Optional[str] = None


class PromoteChallengeRequest(BaseModel):
    """Промоушен задания соревнования в глобальное.
    Новый slug опционален — если не указан, используется slug задания."""
    new_slug: Optional[str] = None
    points: Optional[int] = None
    enabled: bool = True


class BuildStatusOut(BaseModel):
    challenge_id: int
    slug: str
    build_status: str
    build_log: str
    updated_at: datetime

# ══════════════════════════════════════════════════════════════════════
# Instances / submit / hints
# ══════════════════════════════════════════════════════════════════════

class CompetitionInstanceOut(BaseModel):
    challenge_slug: str
    url: str
    expires_at: datetime


class CompetitionFlagSubmit(BaseModel):
    flag: str


class CompetitionSubmitResult(BaseModel):
    correct: bool
    message: str
    points_awarded: Optional[int] = None
    is_first_blood: bool = False


class HintPurchaseOut(BaseModel):
    hint_index: int
    text: str
    cost_paid: int
    purchased_at: datetime

# ══════════════════════════════════════════════════════════════════════
# Leaderboard
# ══════════════════════════════════════════════════════════════════════

class LeaderboardRowOut(BaseModel):
    rank: int
    id: int
    name: str
    score: int
    solves_count: int
    last_solve_at: Optional[datetime] = None
    first_solve_at: Optional[datetime] = None
    is_team: bool = False
    members: list[str] = []


class LeaderboardSnapshotOut(BaseModel):
    competition_id: int
    competition_slug: str
    mode: str
    generated_at: datetime
    individuals: list[LeaderboardRowOut] = []
    teams: list[LeaderboardRowOut] = []


# ══════════════════════════════════════════════════════════════════════
# Dashboard
# ══════════════════════════════════════════════════════════════════════

class DashboardOut(BaseModel):
    competition_id: int
    slug: str
    generated_at: datetime
    participants: dict
    challenges: dict
    solves: dict
    score_distribution: list[dict]
    solves_timeline: list[dict]
    first_bloods: list[dict]
    top_solvers: list[dict]
    category_activity: list[dict]
    anomalies: list[dict]


class ScoreAdjustRequest(BaseModel):
    user_id: Optional[int] = None
    team_id: Optional[int] = None
    delta: int
    comment: Optional[str] = None

    @model_validator(mode="after")
    def _check_owner(self):
        if (self.user_id is None) == (self.team_id is None):
            raise ValueError("Specify exactly one of user_id / team_id")
        return self


class ScoreAdjustResult(BaseModel):
    delta: int
    total: int


# ══════════════════════════════════════════════════════════════════════
# Appeals
# ══════════════════════════════════════════════════════════════════════

class AppealCreate(BaseModel):
    message: str = Field(min_length=5, max_length=4000)
    challenge_id: Optional[int] = None


class AppealResolve(BaseModel):
    status: Literal["accepted", "rejected"]
    resolution: Optional[str] = None


class AppealOut(BaseModel):
    id: int
    competition_id: int
    user_id: int
    username: str
    challenge_id: Optional[int] = None
    message: str
    status: str
    resolved_by: Optional[int] = None
    resolved_at: Optional[datetime] = None
    resolution: Optional[str] = None
    created_at: datetime