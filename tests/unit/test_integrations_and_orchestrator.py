"""Tests for integrations (git, linear, snyk) and orchestrator."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from conveyor_belt.config import ConveyorBeltConfig
from conveyor_belt.context import LinearIssue
from conveyor_belt.integrations.git import (
    _attach_patches,
    changed_files_from_diff,
    changed_files_from_pr,
    changed_files_from_staged,
    get_pr_body,
    parse_issue_tags,
)
from conveyor_belt.integrations.linear import (
    _to_linear_issue,
    fetch_issue,
    fetch_issues,
    fetch_team_issues,
)
from conveyor_belt.integrations.snyk import (
    snyk_code_test,
    snyk_container_test,
    snyk_test,
)
from conveyor_belt.models import Severity, StationResult
from conveyor_belt.orchestrator import Orchestrator, PipelineReport

# ── Git integration ────────────────────────────────────────────────────


class TestParseIssueTags:
    def test_extracts_tags(self):
        assert parse_issue_tags("Fixes [ENG-123] and [PROJ-45]") == [
            "ENG-123",
            "PROJ-45",
        ]

    def test_no_tags(self):
        assert parse_issue_tags("Just a normal PR") == []

    def test_from_multiline(self):
        text = "Title\n\nBody with [ENG-1] reference"
        assert parse_issue_tags(text) == ["ENG-1"]


class TestAttachPatches:
    def test_attaches_to_matching_files(self):
        from conveyor_belt.context import ChangedFile

        files = [
            ChangedFile(path="a.py", status="modified"),
            ChangedFile(path="b.py", status="modified"),
        ]
        patch_text = (
            "diff --git a/a.py b/a.py\n"
            "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n"
            "diff --git a/b.py b/b.py\n"
            "--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-x\n+y\n"
        )
        _attach_patches(files, patch_text)
        assert "a.py" in files[0].patch
        assert "b.py" in files[1].patch


class TestChangedFilesFromDiff:
    @pytest.mark.asyncio
    async def test_parses_numstat(self, tmp_path):
        async def mock_run(cmd, cwd):
            if "--numstat" in cmd:
                return 0, "10\t2\tsrc/main.py\n5\t0\tREADME.md\n"
            return 0, ""

        with patch("conveyor_belt.integrations.git._run", side_effect=mock_run):
            files = await changed_files_from_diff(str(tmp_path), "HEAD~1")

        assert len(files) == 2
        assert files[0].path == "src/main.py"
        assert files[0].additions == 10
        assert files[0].deletions == 2


class TestChangedFilesFromPR:
    @pytest.mark.asyncio
    async def test_parses_gh_output(self, tmp_path):
        async def mock_run(cmd, cwd):
            if "diff" in cmd and "--name-only" in cmd:
                return 0, "src/main.py\n"
            if "--json" in cmd and "files" in cmd:
                return 0, json.dumps({
                    "files": [{
                        "path": "src/main.py",
                        "status": "modified",
                        "additions": 5,
                        "deletions": 1,
                    }]
                })
            return 0, ""

        with patch("conveyor_belt.integrations.git._run", side_effect=mock_run):
            files = await changed_files_from_pr(str(tmp_path), 42)

        assert len(files) == 1
        assert files[0].additions == 5


class TestGetPRBody:
    @pytest.mark.asyncio
    async def test_returns_title_body(self, tmp_path):
        async def mock_run(cmd, cwd):
            return 0, json.dumps({"title": "My PR", "body": "Fixes [ENG-1]"})

        with patch("conveyor_belt.integrations.git._run", side_effect=mock_run):
            title, body = await get_pr_body(str(tmp_path), 42)

        assert title == "My PR"
        assert "ENG-1" in body

    @pytest.mark.asyncio
    async def test_handles_invalid_json(self, tmp_path):
        async def mock_run(cmd, cwd):
            return 1, "error"

        with patch("conveyor_belt.integrations.git._run", side_effect=mock_run):
            title, body = await get_pr_body(str(tmp_path), 99)

        assert title == ""
        assert body == ""


class TestChangedFilesFromStaged:
    @pytest.mark.asyncio
    async def test_reads_staged(self, tmp_path):
        async def mock_run(cmd, cwd):
            if "--cached" in cmd:
                return 0, "3\t1\tstaged.py\n"
            return 0, ""

        with patch("conveyor_belt.integrations.git._run", side_effect=mock_run):
            files = await changed_files_from_staged(str(tmp_path))

        assert len(files) == 1
        assert files[0].path == "staged.py"

    @pytest.mark.asyncio
    async def test_falls_back_to_unstaged(self, tmp_path):
        call_count = 0

        async def mock_run(cmd, cwd):
            nonlocal call_count
            call_count += 1
            if "--cached" in cmd:
                return 0, ""
            return 0, "2\t0\tunstaged.py\n"

        with patch("conveyor_belt.integrations.git._run", side_effect=mock_run):
            files = await changed_files_from_staged(str(tmp_path))

        assert len(files) == 1
        assert files[0].path == "unstaged.py"


# ── Linear integration ─────────────────────────────────────────────────


class TestToLinearIssue:
    def test_maps_full_issue(self):
        raw = {
            "identifier": "ENG-42",
            "title": "Add auth",
            "description": "Implement OAuth",
            "state": {"name": "In Progress"},
            "labels": {"nodes": [{"name": "backend"}, {"name": "auth"}]},
            "children": {
                "nodes": [
                    {
                        "identifier": "ENG-43",
                        "title": "Sub-task",
                        "description": "detail",
                        "state": {"name": "Todo"},
                    }
                ]
            },
        }
        issue = _to_linear_issue(raw)
        assert issue.identifier == "ENG-42"
        assert issue.labels == ["backend", "auth"]
        assert len(issue.sub_issues) == 1
        assert issue.sub_issues[0].identifier == "ENG-43"

    def test_handles_empty_fields(self):
        issue = _to_linear_issue({})
        assert issue.identifier == ""
        assert issue.labels == []
        assert issue.sub_issues == []


class TestFetchIssue:
    @pytest.mark.asyncio
    async def test_returns_issue(self):
        mock_data = {
            "issueSearch": {
                "nodes": [{
                    "identifier": "ENG-1",
                    "title": "Test",
                    "description": "desc",
                    "state": {"name": "Done"},
                    "labels": {"nodes": []},
                    "children": {"nodes": []},
                }]
            }
        }
        with patch(
            "conveyor_belt.integrations.linear._query",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            issue = await fetch_issue("ENG-1")
        assert issue.identifier == "ENG-1"

    @pytest.mark.asyncio
    async def test_raises_on_not_found(self):
        with (
            patch(
                "conveyor_belt.integrations.linear._query",
                new_callable=AsyncMock,
                return_value={"issueSearch": {"nodes": []}},
            ),
            pytest.raises(ValueError, match="not found"),
        ):
            await fetch_issue("ENG-999")


class TestFetchIssues:
    @pytest.mark.asyncio
    async def test_skips_missing(self):
        async def mock_fetch(ident):
            if ident == "ENG-1":
                return LinearIssue(identifier="ENG-1", title="OK")
            raise ValueError("not found")

        with patch(
            "conveyor_belt.integrations.linear.fetch_issue",
            side_effect=mock_fetch,
        ):
            results = await fetch_issues(["ENG-1", "ENG-999"])
        assert len(results) == 1


class TestFetchTeamIssues:
    @pytest.mark.asyncio
    async def test_returns_issues(self):
        mock_data = {
            "issues": {
                "nodes": [{
                    "identifier": "ENG-10",
                    "title": "Old feature",
                    "description": "desc",
                    "state": {"name": "Done"},
                    "labels": {"nodes": []},
                    "children": {"nodes": []},
                }]
            }
        }
        with patch(
            "conveyor_belt.integrations.linear._query",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            issues = await fetch_team_issues("ENG", limit=5)
        assert len(issues) == 1

    @pytest.mark.asyncio
    async def test_with_state_filter(self):
        with patch(
            "conveyor_belt.integrations.linear._query",
            new_callable=AsyncMock,
            return_value={"issues": {"nodes": []}},
        ):
            issues = await fetch_team_issues(
                "ENG", limit=5, states=["Done"]
            )
        assert issues == []

class TestLinearQuery:
    @pytest.mark.asyncio
    async def test_query_success(self):
        from unittest.mock import AsyncMock, MagicMock

        from conveyor_belt.integrations.linear import _query
        mock_resp = AsyncMock()
        mock_resp.json = MagicMock(return_value={"data": {"foo": "bar"}})

        @pytest.fixture(autouse=True)
        def mock_env(monkeypatch):
            monkeypatch.setenv("LINEAR_API_KEY", "test_key")

        with (
            patch("os.environ.get", return_value="test_key"),
            patch("httpx.AsyncClient.post", return_value=mock_resp),
        ):
            data = await _query("query { foo }")
            assert data == {"foo": "bar"}

    @pytest.mark.asyncio
    async def test_query_graphql_error(self):
        from unittest.mock import AsyncMock, MagicMock

        from conveyor_belt.integrations.linear import _query
        mock_resp = AsyncMock()
        mock_resp.json = MagicMock(return_value={"errors": [{"message": "Bad request"}]})

        with (
            patch("os.environ.get", return_value="test_key"),
            patch("httpx.AsyncClient.post", return_value=mock_resp),
            pytest.raises(RuntimeError, match="Linear API errors"),
        ):
            await _query("query { foo }")


# ── Snyk integration (missing coverage) ────────────────────────────────


class TestSnykFunctions:
    @pytest.mark.asyncio
    async def test_snyk_test_unavailable(self):
        async def mock_exec(cmd, cwd, timeout=120.0):
            return 127, "", "Command not found: snyk"

        with patch("conveyor_belt.integrations.snyk._exec", side_effect=mock_exec):
            findings = await snyk_test("/tmp", "high")
        assert len(findings) == 1
        assert findings[0].rule == "snyk/unavailable"

    @pytest.mark.asyncio
    async def test_snyk_code_test_unavailable(self):
        async def mock_exec(cmd, cwd, timeout=120.0):
            return 127, "", "Command not found: snyk"

        with patch("conveyor_belt.integrations.snyk._exec", side_effect=mock_exec):
            findings = await snyk_code_test("/tmp", "high")
        assert findings[0].severity == Severity.INFO

    @pytest.mark.asyncio
    async def test_snyk_container_test_unavailable(self):
        async def mock_exec(cmd, cwd, timeout=120.0):
            return 127, "", "Command not found: snyk"

        with patch("conveyor_belt.integrations.snyk._exec", side_effect=mock_exec):
            findings = await snyk_container_test("/tmp", "myimg:latest", "high")
        assert findings[0].rule == "snyk/unavailable"

    @pytest.mark.asyncio
    async def test_snyk_test_parses_results(self):
        output = json.dumps({
            "vulnerabilities": [{
                "id": "SNYK-1",
                "title": "Vuln",
                "severity": "high",
                "from": ["pkg@1.0"],
                "identifiers": {"CVE": ["CVE-2024-1"], "CWE": []},
                "fixedIn": ["2.0"],
            }]
        })

        async def mock_exec(cmd, cwd, timeout=120.0):
            return 1, output, ""

        with patch("conveyor_belt.integrations.snyk._exec", side_effect=mock_exec):
            findings = await snyk_test("/tmp", "high")
        assert len(findings) == 1
        assert findings[0].severity == Severity.HIGH

    @pytest.mark.asyncio
    async def test_snyk_code_test_parses_sarif(self):
        output = json.dumps({
            "runs": [{
                "results": [{
                    "ruleId": "python/Sqli",
                    "level": "error",
                    "message": {"text": "SQL injection"},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": "app.py"},
                            "region": {"startLine": 10},
                        }
                    }],
                }]
            }]
        })

        async def mock_exec(cmd, cwd, timeout=120.0):
            return 1, output, ""

        with patch("conveyor_belt.integrations.snyk._exec", side_effect=mock_exec):
            findings = await snyk_code_test("/tmp", "high")
        assert len(findings) == 1
        assert findings[0].file_path == "app.py"


# ── Orchestrator ───────────────────────────────────────────────────────


class TestPipelineReport:
    def test_to_markdown_pass(self):
        report = PipelineReport(
            gate_passed=True,
            policy="soft_fail",
            results=[
                StationResult(
                    station_name="idiomatic",
                    passed=True,
                    summary="0 violations",
                )
            ],
        )
        md = report.to_markdown()
        assert "PASS" in md
        assert "idiomatic" in md

    def test_to_markdown_fail_with_findings(self):
        from conveyor_belt.models import Finding

        report = PipelineReport(
            gate_passed=False,
            policy="hard_fail",
            results=[
                StationResult(
                    station_name="security",
                    passed=False,
                    summary="1 finding",
                    findings=[
                        Finding(
                            rule="test", message="bad code", severity=Severity.HIGH
                        )
                    ],
                )
            ],
        )
        md = report.to_markdown()
        assert "FAIL" in md
        assert "bad code" in md


class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_runs_stations_concurrently(self, tmp_path):
        cfg = ConveyorBeltConfig()
        cfg.stations.unit_coverage.enabled = False
        cfg.stations.vulnerability.enabled = False
        cfg.stations.feature_validation.enabled = False
        cfg.stations.regression.enabled = False
        cfg.stations.security.enabled = False
        # Only idiomatic enabled

        async def mock_diff(repo_root, diff_ref):
            from conveyor_belt.context import ChangedFile
            return [ChangedFile(path="test.py", status="modified")]

        async def mock_exec(cmd, cwd, timeout=60.0):
            return 0, "[]", ""

        orch = Orchestrator(cfg, repo_root=str(tmp_path))

        with (
            patch(
                "conveyor_belt.orchestrator.changed_files_from_diff",
                side_effect=mock_diff,
            ),
            patch(
                "conveyor_belt.stations.idiomatic._exec",
                side_effect=mock_exec,
            ),
        ):
            report = await orch.run(diff_ref="HEAD~1")

        assert report.gate_passed is True
        assert len(report.results) == 1
        assert report.results[0].station_name == "idiomatic"

    @pytest.mark.asyncio
    async def test_no_stations_selected(self, tmp_path):
        cfg = ConveyorBeltConfig()
        cfg.stations.unit_coverage.enabled = False
        cfg.stations.idiomatic.enabled = False
        cfg.stations.vulnerability.enabled = False
        cfg.stations.feature_validation.enabled = False
        cfg.stations.regression.enabled = False
        cfg.stations.security.enabled = False

        async def mock_staged(repo_root):
            return []

        orch = Orchestrator(cfg, repo_root=str(tmp_path))

        with patch(
            "conveyor_belt.orchestrator.changed_files_from_staged",
            side_effect=mock_staged,
        ):
            report = await orch.run()

        assert report.gate_passed is True
        assert "No stations to run" in report.results[0].summary

    @pytest.mark.asyncio
    async def test_hard_fail_gate(self, tmp_path):
        cfg = ConveyorBeltConfig()
        cfg.gate.policy = "hard_fail"
        orch = Orchestrator(cfg, repo_root=str(tmp_path))
        assert orch._apply_gate([
            StationResult(station_name="a", passed=True),
            StationResult(station_name="b", passed=False),
        ]) is False

    @pytest.mark.asyncio
    async def test_soft_fail_gate(self, tmp_path):
        cfg = ConveyorBeltConfig()
        cfg.gate.policy = "soft_fail"
        orch = Orchestrator(cfg, repo_root=str(tmp_path))
        assert orch._apply_gate([
            StationResult(station_name="a", passed=False),
        ]) is True

    @pytest.mark.asyncio
    async def test_only_stations_filter(self, tmp_path):
        cfg = ConveyorBeltConfig()

        async def mock_diff(repo_root, diff_ref):
            return []

        async def mock_exec(cmd, cwd, timeout=60.0):
            return 0, "[]", ""

        orch = Orchestrator(cfg, repo_root=str(tmp_path))

        with (
            patch(
                "conveyor_belt.orchestrator.changed_files_from_diff",
                side_effect=mock_diff,
            ),
            patch(
                "conveyor_belt.stations.idiomatic._exec",
                side_effect=mock_exec,
            ),
        ):
            report = await orch.run(
                diff_ref="HEAD~1", only_stations=["idiomatic"]
            )

        assert len(report.results) == 1

    @pytest.mark.asyncio
    async def test_pr_mode(self, tmp_path):
        cfg = ConveyorBeltConfig()
        cfg.stations.unit_coverage.enabled = False
        cfg.stations.idiomatic.enabled = False
        cfg.stations.vulnerability.enabled = False
        cfg.stations.feature_validation.enabled = False
        cfg.stations.regression.enabled = False
        cfg.stations.security.enabled = False

        async def mock_pr(repo_root, pr_number):
            return []

        async def mock_body(repo_root, pr_number):
            return "PR Title", "Body [ENG-1]"

        orch = Orchestrator(cfg, repo_root=str(tmp_path))

        with (
            patch(
                "conveyor_belt.orchestrator.changed_files_from_pr",
                side_effect=mock_pr,
            ),
            patch(
                "conveyor_belt.orchestrator.get_pr_body",
                side_effect=mock_body,
            ),
        ):
            report = await orch.run(pr_number=42)

        assert report.gate_passed is True
