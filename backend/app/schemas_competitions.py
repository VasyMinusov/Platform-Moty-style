"""Pydantic-схемы модуля «Соревнования».

Здесь только то, что нужно для Фазы 1:
- scoring_config
- network_config
- manifest + metadata по типам заданий
- базовые Out-схемы
"""
from datetime import datetime
from typing import Any, Literal, Optional, Union

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


# ══════════════════════════════════════════════════════════════════════
# Network config
# ══════════════════════════════════════════════════════════════════════

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
        schema = METADATA_SCHEMAS.get(self.type, MiscMeta)
        return schema.model_validate(self.metadata)


# ══════════════════════════════════════════════════════════════════════
# Out-схемы (минимальные, для Фазы 1)
# ══════════════════════════════════════════════════════════════════════

class CompetitionOut(BaseModel):
    id: int
    slug: str
    title: str
    summary: str
    visibility: str
    mode: str
    status: str
    registration_opens_at: Optional[datetime] = None
    registration_closes_at: Optional[datetime] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    created_at: datetime

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
    port_range_start: Optional[int] = None
    port_range_end: Optional[int] = None
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