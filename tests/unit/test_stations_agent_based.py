"""Tests for agent-based stations (2, 3, 6) with mocked LLM responses."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from conveyor_belt.config import ConveyorBeltConfig
from conveyor_belt.context import ChangedFile, LinearIssue, StationContext
from conveyor_belt.models import Severity
from conveyor_belt.stations.feature_validation import FeatureValidationStation
from conveyor_belt.stations.regression import RegressionStation
from conveyor_belt.stations.security import SecurityStation


@pytest.fixture
def cfg() -> ConveyorBeltConfig:
    return ConveyorBeltConfig()


SAMPLE_ISSUE = LinearIssue(
    identifier="ENG-100",
    title="Add user authentication",
    description="Users must log in with email/password.",
)


def _make_ctx(
    tmp_path: Path,
    *,
    issues: list[LinearIssue] | None = None,
    historical: list[LinearIssue] | None = None,
    pr_body: str = "",
) -> StationContext:
    return StationContext(
        repo_root=str(tmp_path),
        languages=["python", "go"],
        pr_body=pr_body,
        changed_files=[
            ChangedFile(
                path="main.py",
                status="modified",
                patch="+ password = 'hunter2'",
            )
        ],
        linear_issues=issues or [],
        historical_issues=historical or [],
    )


# ── Station 2: Feature Validation ──────────────────────────────────────


class TestFeatureValidationStation:
    @pytest.mark.asyncio
    async def test_skips_when_no_issues(self, cfg, tmp_path):
        station = FeatureValidationStation(cfg)
        ctx = _make_ctx(tmp_path)
        result = await station.run(ctx)
        assert result.passed is True
        assert "No Linear issues" in result.summary

    @pytest.mark.asyncio
    async def test_all_ac_covered(self, cfg, tmp_path):
        station = FeatureValidationStation(cfg)
        ctx = _make_ctx(tmp_path, issues=[SAMPLE_ISSUE])

        mock_response = json.dumps({
            "acceptance_criteria": [
                {"id": "AC-1", "description": "Login works", "covered": True}
            ],
            "test_cases": [{"name": "test_login", "language": "python"}],
            "coverage_summary": "1 of 1 AC covered",
        })

        with patch(
            "conveyor_belt.agents.base.BaseAgent.invoke",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await station.run(ctx)

        assert result.passed is True
        assert len(result.findings) == 0

    @pytest.mark.asyncio
    async def test_uncovered_ac_fails(self, cfg, tmp_path):
        station = FeatureValidationStation(cfg)
        ctx = _make_ctx(tmp_path, issues=[SAMPLE_ISSUE])

        mock_response = json.dumps({
            "acceptance_criteria": [
                {"id": "AC-1", "description": "Login works", "covered": True},
                {"id": "AC-2", "description": "Password reset", "covered": False},
            ],
            "test_cases": [{"name": "test_login", "language": "python"}],
            "coverage_summary": "1 of 2 AC covered",
        })

        with patch(
            "conveyor_belt.agents.base.BaseAgent.invoke",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await station.run(ctx)

        assert result.passed is False
        uncovered = [
            f for f in result.findings if f.rule == "feature/uncovered_ac"
        ]
        assert len(uncovered) == 1
        assert "Password reset" in uncovered[0].message

    @pytest.mark.asyncio
    async def test_issue_tags_from_pr_body(self, cfg, tmp_path):
        station = FeatureValidationStation(cfg)
        ctx = _make_ctx(tmp_path, pr_body="Implements [ENG-100]")

        mock_response = json.dumps({
            "acceptance_criteria": [],
            "test_cases": [],
            "coverage_summary": "0 of 0",
        })

        with (
            patch(
                "conveyor_belt.stations.feature_validation.fetch_issues",
                new_callable=AsyncMock,
                return_value=[SAMPLE_ISSUE],
            ),
            patch(
                "conveyor_belt.agents.base.BaseAgent.invoke",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
        ):
            result = await station.run(ctx)

        assert result.passed is True

    @pytest.mark.asyncio
    async def test_agent_failure(self, cfg, tmp_path):
        station = FeatureValidationStation(cfg)
        ctx = _make_ctx(tmp_path, issues=[SAMPLE_ISSUE])

        with patch(
            "conveyor_belt.agents.base.BaseAgent.invoke",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM down"),
        ):
            result = await station.run(ctx)

        assert result.passed is False
        assert "LLM agent failed" in result.summary

    @pytest.mark.asyncio
    async def test_linear_fetch_failure(self, cfg, tmp_path):
        station = FeatureValidationStation(cfg)
        ctx = _make_ctx(tmp_path, pr_body="Implements [ENG-999]")

        with patch(
            "conveyor_belt.stations.feature_validation.fetch_issues",
            new_callable=AsyncMock,
            side_effect=Exception("API error"),
        ):
            result = await station.run(ctx)

        assert result.passed is True
        assert "Could not fetch" in result.summary


# ── Station 3: Regression ──────────────────────────────────────────────


class TestRegressionStation:
    @pytest.mark.asyncio
    async def test_skips_when_no_history(self, cfg, tmp_path):
        station = RegressionStation(cfg)
        ctx = _make_ctx(tmp_path)

        with patch(
            "conveyor_belt.stations.regression.fetch_team_issues",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await station.run(ctx)

        assert result.passed is True
        assert "No historical issues" in result.summary

    @pytest.mark.asyncio
    async def test_low_risk_passes(self, cfg, tmp_path):
        station = RegressionStation(cfg)
        ctx = _make_ctx(tmp_path, historical=[SAMPLE_ISSUE])

        mock_response = json.dumps({
            "at_risk_requirements": [],
            "regression_tests": [],
            "risk_score": 15,
            "risk_summary": "Low risk",
        })

        with patch(
            "conveyor_belt.agents.base.BaseAgent.invoke",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await station.run(ctx)

        assert result.passed is True

    @pytest.mark.asyncio
    async def test_high_risk_fails(self, cfg, tmp_path):
        station = RegressionStation(cfg)
        ctx = _make_ctx(tmp_path, historical=[SAMPLE_ISSUE])

        mock_response = json.dumps({
            "at_risk_requirements": [{
                "identifier": "ENG-100",
                "title": "Auth",
                "risk_reason": "Login endpoint modified",
            }],
            "regression_tests": [{"name": "test_login", "language": "python"}],
            "risk_score": 80,
            "risk_summary": "High risk",
        })

        with patch(
            "conveyor_belt.agents.base.BaseAgent.invoke",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await station.run(ctx)

        assert result.passed is False
        assert len(result.findings) == 1
        assert result.findings[0].severity == Severity.HIGH

    @pytest.mark.asyncio
    async def test_agent_failure(self, cfg, tmp_path):
        station = RegressionStation(cfg)
        ctx = _make_ctx(tmp_path, historical=[SAMPLE_ISSUE])

        with patch(
            "conveyor_belt.agents.base.BaseAgent.invoke",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM down"),
        ):
            result = await station.run(ctx)

        assert result.passed is False

    @pytest.mark.asyncio
    async def test_linear_fetch_failure(self, cfg, tmp_path):
        station = RegressionStation(cfg)
        ctx = _make_ctx(tmp_path)

        with patch(
            "conveyor_belt.stations.regression.fetch_team_issues",
            new_callable=AsyncMock,
            side_effect=Exception("API error"),
        ):
            result = await station.run(ctx)

        assert result.passed is True
        assert any(f.rule == "linear/fetch_error" for f in result.findings)


# ── Station 6: Security ────────────────────────────────────────────────


class TestSecurityStation:
    @pytest.mark.asyncio
    async def test_agent_findings_mapped(self, cfg, tmp_path):
        station = SecurityStation(cfg)
        ctx = _make_ctx(tmp_path)

        mock_response = json.dumps({
            "findings": [{
                "rule": "hardcoded-secret",
                "cwe_id": "CWE-798",
                "severity": "high",
                "file_path": "main.py",
                "line": 1,
                "message": "Hardcoded password",
                "remediation": "Use env var",
            }],
            "summary": "1 issue",
        })

        with patch(
            "conveyor_belt.agents.base.BaseAgent.invoke",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await station.run(ctx)

        agent_findings = [
            f for f in result.findings if "security-agent" in f.rule
        ]
        assert len(agent_findings) == 1
        assert agent_findings[0].cwe_id == "CWE-798"
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_clean_diff_passes(self, cfg, tmp_path):
        station = SecurityStation(cfg)
        ctx = _make_ctx(tmp_path)

        mock_response = json.dumps({
            "findings": [],
            "summary": "No issues",
        })

        with patch(
            "conveyor_belt.agents.base.BaseAgent.invoke",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await station.run(ctx)

        assert result.passed is True

    @pytest.mark.asyncio
    async def test_bandit_findings_parsed(self, cfg, tmp_path):
        station = SecurityStation(cfg)
        ctx = _make_ctx(tmp_path)

        bandit_json = json.dumps({
            "results": [{
                "test_id": "B105",
                "issue_text": "Possible hardcoded password",
                "issue_severity": "LOW",
                "filename": "main.py",
                "line_number": 1,
                "issue_cwe": {"id": "CWE-259"},
            }]
        })

        async def mock_exec(cmd, cwd, timeout=60.0):
            if "bandit" in cmd:
                return 1, bandit_json, ""
            return 127, "", f"Command not found: {cmd[0]}"

        mock_agent = json.dumps({"findings": [], "summary": "clean"})

        with (
            patch(
                "conveyor_belt.agents.base.BaseAgent.invoke",
                new_callable=AsyncMock,
                return_value=mock_agent,
            ),
            patch(
                "conveyor_belt.stations.security._exec",
                side_effect=mock_exec,
            ),
        ):
            result = await station.run(ctx)

        bandit_findings = [
            f for f in result.findings if "bandit" in f.rule
        ]
        assert len(bandit_findings) == 1
        assert bandit_findings[0].cwe_id == "CWE-259"

    @pytest.mark.asyncio
    async def test_gosec_findings_parsed(self, cfg, tmp_path):
        station = SecurityStation(cfg)
        ctx = StationContext(
            repo_root=str(tmp_path),
            languages=["go"],
            changed_files=[
                ChangedFile(path="cmd/main.go", status="modified", patch="+x")
            ],
        )

        gosec_json = json.dumps({
            "Issues": [{
                "rule_id": "G201",
                "details": "SQL string formatting",
                "severity": "MEDIUM",
                "file": "cmd/main.go",
                "line": "10",
                "cwe": {"id": "CWE-89"},
            }]
        })

        async def mock_exec(cmd, cwd, timeout=60.0):
            if "gosec" in cmd:
                return 1, gosec_json, ""
            return 127, "", f"Command not found: {cmd[0]}"

        with patch(
            "conveyor_belt.stations.security._exec",
            side_effect=mock_exec,
        ):
            result = await station.run(ctx)

        gosec_findings = [
            f for f in result.findings if "gosec" in f.rule
        ]
        assert len(gosec_findings) == 1
        assert gosec_findings[0].cwe_id == "CWE-89"

    @pytest.mark.asyncio
    async def test_semgrep_findings_parsed(self, cfg, tmp_path):
        station = SecurityStation(cfg)
        ctx = StationContext(
            repo_root=str(tmp_path),
            languages=["typescript"],
            changed_files=[
                ChangedFile(path="src/app.ts", status="modified", patch="+x")
            ],
        )

        semgrep_json = json.dumps({
            "results": [{
                "check_id": "typescript.xss.raw-html",
                "path": "src/app.ts",
                "start": {"line": 5},
                "extra": {
                    "severity": "WARNING",
                    "message": "Potential XSS",
                },
            }]
        })

        async def mock_exec(cmd, cwd, timeout=60.0):
            if "semgrep" in cmd:
                return 0, semgrep_json, ""
            return 127, "", f"Command not found: {cmd[0]}"

        with patch(
            "conveyor_belt.stations.security._exec",
            side_effect=mock_exec,
        ):
            result = await station.run(ctx)

        semgrep_findings = [
            f for f in result.findings if "semgrep" in f.rule
        ]
        assert len(semgrep_findings) == 1

    @pytest.mark.asyncio
    async def test_no_diff_skips_agent(self, cfg, tmp_path):
        station = SecurityStation(cfg)
        ctx = StationContext(
            repo_root=str(tmp_path),
            languages=["python"],
            changed_files=[
                ChangedFile(path="main.py", status="modified", patch="")
            ],
        )
        result = await station.run(ctx)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_sast_tool_unavailable(self, cfg, tmp_path):
        station = SecurityStation(cfg)
        ctx = _make_ctx(tmp_path)

        async def mock_exec(cmd, cwd, timeout=60.0):
            return 127, "", f"Command not found: {cmd[0]}"

        mock_agent = json.dumps({"findings": [], "summary": "clean"})

        with (
            patch(
                "conveyor_belt.agents.base.BaseAgent.invoke",
                new_callable=AsyncMock,
                return_value=mock_agent,
            ),
            patch(
                "conveyor_belt.stations.security._exec",
                side_effect=mock_exec,
            ),
        ):
            result = await station.run(ctx)

        info_findings = [
            f for f in result.findings if f.severity == Severity.INFO
        ]
        assert len(info_findings) >= 1
        assert result.passed is True
