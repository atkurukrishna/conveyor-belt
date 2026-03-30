"""Tests for core models and config loading."""

import textwrap
from pathlib import Path

import pytest
import yaml

from conveyor_belt.config import ConveyorBeltConfig, load_config
from conveyor_belt.models import CoverageRecord, Finding, Severity, StationResult


# ── Models ─────────────────────────────────────────────────────────────


class TestSeverity:
    def test_ordering(self):
        assert Severity.CRITICAL.value == "critical"
        assert Severity.INFO.value == "info"

    def test_string_enum(self):
        assert Severity("high") == Severity.HIGH


class TestCoverageRecord:
    def test_percent_normal(self):
        rec = CoverageRecord(file_path="a.py", lines_total=100, lines_covered=87)
        assert rec.percent == 87.0

    def test_percent_zero_total(self):
        rec = CoverageRecord(file_path="empty.py", lines_total=0, lines_covered=0)
        assert rec.percent == 100.0

    def test_percent_full(self):
        rec = CoverageRecord(file_path="b.py", lines_total=50, lines_covered=50)
        assert rec.percent == 100.0


class TestFinding:
    def test_defaults(self):
        f = Finding(rule="test_rule", message="oops")
        assert f.severity == Severity.MEDIUM
        assert f.file_path is None

    def test_all_fields(self):
        f = Finding(
            rule="CVE-2024-001",
            message="vuln found",
            severity=Severity.CRITICAL,
            file_path="lib.go",
            line=42,
            cve_id="CVE-2024-001",
            cwe_id="CWE-79",
            remediation="Upgrade to v2",
        )
        assert f.cve_id == "CVE-2024-001"


class TestStationResult:
    def test_basic(self):
        r = StationResult(station_name="test", passed=True)
        assert r.findings == []
        assert r.coverage == []
        assert r.duration_seconds == 0.0

    def test_with_findings(self):
        f = Finding(rule="r1", message="m1")
        r = StationResult(station_name="test", passed=False, findings=[f])
        assert len(r.findings) == 1


# ── Config ─────────────────────────────────────────────────────────────


class TestConfig:
    def test_defaults(self):
        cfg = ConveyorBeltConfig()
        assert cfg.project.languages == ["java", "go", "typescript", "python"]
        assert cfg.agent.primary.provider == "anthropic"
        assert cfg.agent.primary.model == "claude-opus-4.6"
        assert cfg.agent.fallback.provider == "google"
        assert cfg.agent.fallback.model == "gemini-3.1-pro"
        assert cfg.gate.policy == "hard_fail"
        assert cfg.stations.unit_coverage.threshold == 85.0

    def test_load_from_yaml(self, tmp_path: Path):
        config_file = tmp_path / "conveyor-belt.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "project": {"languages": ["python"]},
                    "stations": {"unit_coverage": {"threshold": 90}},
                    "gate": {"policy": "soft_fail"},
                }
            )
        )
        cfg = load_config(config_file)
        assert cfg.project.languages == ["python"]
        assert cfg.stations.unit_coverage.threshold == 90.0
        assert cfg.gate.policy == "soft_fail"

    def test_load_missing_file_uses_defaults(self, tmp_path: Path):
        cfg = load_config(tmp_path / "nonexistent.yaml")
        assert cfg.project.languages == ["java", "go", "typescript", "python"]

    def test_partial_override(self, tmp_path: Path):
        config_file = tmp_path / "conveyor-belt.yaml"
        config_file.write_text(yaml.dump({"stations": {"security": {"block_on": ["critical"]}}}))
        cfg = load_config(config_file)
        assert cfg.stations.security.block_on == ["critical"]
        # other defaults preserved
        assert cfg.stations.idiomatic.style_baseline == "google"
