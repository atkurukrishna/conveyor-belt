"""Core data models shared across all stations."""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class Severity(enum.StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Finding(BaseModel):
    """A single issue discovered by a station."""

    rule: str
    message: str
    severity: Severity = Severity.MEDIUM
    file_path: str | None = None
    line: int | None = None
    cve_id: str | None = None
    cwe_id: str | None = None
    remediation: str | None = None


class CoverageRecord(BaseModel):
    """Per-file coverage metrics."""

    file_path: str
    lines_total: int
    lines_covered: int

    @property
    def percent(self) -> float:
        if self.lines_total == 0:
            return 100.0
        return round(self.lines_covered / self.lines_total * 100, 2)


class StationResult(BaseModel):
    """Unified output of any station."""

    station_name: str
    passed: bool
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    coverage: list[CoverageRecord] = Field(default_factory=list)
    duration_seconds: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
