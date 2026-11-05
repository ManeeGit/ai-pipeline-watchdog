from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamps must include a timezone")
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class Pipeline:
    name: str
    path: str
    schema: dict[str, str]
    timestamp_column: str
    key_columns: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    max_age_minutes: float = 90
    max_null_rate: float = 0.02
    max_duplicate_rate: float = 0
    allow_extra_columns: bool = False
    run_status_path: str | None = None


@dataclass
class Snapshot:
    pipeline: str
    observed_at: str
    row_count: int = 0
    columns: list[str] = field(default_factory=list)
    null_rates: dict[str, float] = field(default_factory=dict)
    type_errors: dict[str, int] = field(default_factory=dict)
    duplicate_rate: float = 0
    freshness_minutes: float | None = None
    timestamp_errors: int = 0
    run_status: str = "unknown"
    error: str | None = None
    duration_ms: float = 0
    snapshot_id: int | None = None
    evaluated_checks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Finding:
    pipeline: str
    check: str
    severity: str
    title: str
    evidence: dict[str, Any]
    runbook: str

    @property
    def fingerprint(self) -> str:
        return f"{self.pipeline}:{self.check}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
