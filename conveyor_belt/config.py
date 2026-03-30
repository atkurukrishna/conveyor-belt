"""YAML configuration loader and schema for conveyor-belt.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


# ── station-level configs ──────────────────────────────────────────────

class UnitCoverageConfig(BaseModel):
    enabled: bool = True
    threshold: float = 85.0


class FeatureValidationConfig(BaseModel):
    enabled: bool = True
    epic_tags_from_pr: bool = True


class RegressionConfig(BaseModel):
    enabled: bool = True
    lookback_epics: int = 20


class IdiomaticConfig(BaseModel):
    enabled: bool = True
    style_baseline: str = "google"


class SnykConfig(BaseModel):
    enabled: bool = True
    severity_threshold: str = "high"


class VulnerabilityConfig(BaseModel):
    enabled: bool = True
    snyk: SnykConfig = Field(default_factory=SnykConfig)
    asan: bool = False


class SecurityConfig(BaseModel):
    enabled: bool = True
    block_on: list[str] = Field(default_factory=lambda: ["critical", "high"])


class StationsConfig(BaseModel):
    unit_coverage: UnitCoverageConfig = Field(default_factory=UnitCoverageConfig)
    feature_validation: FeatureValidationConfig = Field(default_factory=FeatureValidationConfig)
    regression: RegressionConfig = Field(default_factory=RegressionConfig)
    idiomatic: IdiomaticConfig = Field(default_factory=IdiomaticConfig)
    vulnerability: VulnerabilityConfig = Field(default_factory=VulnerabilityConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)


# ── project & agent configs ────────────────────────────────────────────

class LinearConfig(BaseModel):
    team_key: str = "ENG"


class ProjectConfig(BaseModel):
    languages: list[str] = Field(default_factory=lambda: ["java", "go", "typescript", "python"])
    linear: LinearConfig = Field(default_factory=LinearConfig)


class LLMProviderConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-opus-4.6"


class AgentConfig(BaseModel):
    primary: LLMProviderConfig = Field(
        default_factory=lambda: LLMProviderConfig(provider="anthropic", model="claude-opus-4.6")
    )
    fallback: LLMProviderConfig = Field(
        default_factory=lambda: LLMProviderConfig(provider="google", model="gemini-3.1-pro")
    )


class GateConfig(BaseModel):
    policy: str = "hard_fail"  # hard_fail | soft_fail
    allow_override: bool = False


# ── top-level ──────────────────────────────────────────────────────────

class ConveyorBeltConfig(BaseModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    stations: StationsConfig = Field(default_factory=StationsConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    gate: GateConfig = Field(default_factory=GateConfig)


def load_config(config_path: str | Path | None = None) -> ConveyorBeltConfig:
    """Load and validate conveyor-belt.yaml.  Falls back to defaults if missing."""
    if config_path is None:
        config_path = Path.cwd() / "conveyor-belt.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        return ConveyorBeltConfig()

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    return ConveyorBeltConfig.model_validate(raw)
