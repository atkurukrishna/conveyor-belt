"""Tests for Station 4 — Idiomatic / Style enforcement."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from conveyor_belt.config import ConveyorBeltConfig
from conveyor_belt.context import ChangedFile, StationContext
from conveyor_belt.models import Severity
from conveyor_belt.stations.idiomatic import IdiomaticStation


@pytest.fixture
def station() -> IdiomaticStation:
    return IdiomaticStation(config=ConveyorBeltConfig())


def _make_ctx(tmp_path: Path, files: list[ChangedFile], languages: list[str]) -> StationContext:
    return StationContext(
        repo_root=str(tmp_path),
        languages=languages,
        changed_files=files,
    )


def _mock_exec(return_code: int = 0, stdout: str = "", stderr: str = ""):
    """Return an async mock for _exec()."""

    async def _fake_exec(cmd, cwd):
        return return_code, stdout, stderr

    return _fake_exec


# ── Basic dispatch tests ──────────────────────────────────────────────


class TestIdiomaticStationBasics:
    @pytest.mark.asyncio
    async def test_no_changed_files(self, station: IdiomaticStation, tmp_path: Path):
        ctx = _make_ctx(tmp_path, [], ["python"])
        result = await station.run(ctx)
        assert result.passed is True
        assert "No changed files" in result.summary

    @pytest.mark.asyncio
    async def test_deleted_files_are_skipped(self, station: IdiomaticStation, tmp_path: Path):
        ctx = _make_ctx(
            tmp_path,
            [ChangedFile(path="old.py", status="deleted")],
            ["python"],
        )
        result = await station.run(ctx)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_unknown_extension_skipped(self, station: IdiomaticStation, tmp_path: Path):
        ctx = _make_ctx(
            tmp_path,
            [ChangedFile(path="data.csv", status="modified")],
            ["python"],
        )
        result = await station.run(ctx)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_language_not_in_context_skipped(
        self, station: IdiomaticStation, tmp_path: Path
    ):
        """A .go file is ignored if 'go' isn't in ctx.languages."""
        ctx = _make_ctx(
            tmp_path,
            [ChangedFile(path="main.go", status="modified")],
            ["python"],  # no go
        )
        result = await station.run(ctx)
        assert result.passed is True


# ── Python linting ────────────────────────────────────────────────────


class TestPythonLinting:
    @pytest.mark.asyncio
    async def test_ruff_findings_parsed(self, station: IdiomaticStation, tmp_path: Path):
        ruff_output = json.dumps(
            [
                {
                    "code": "F401",
                    "message": "'os' imported but unused",
                    "filename": "app.py",
                    "location": {"row": 3, "column": 1},
                },
                {
                    "code": "E501",
                    "message": "Line too long (120 > 100)",
                    "filename": "app.py",
                    "location": {"row": 15, "column": 1},
                },
            ]
        )

        call_count = 0

        async def mock_exec(cmd, cwd):
            nonlocal call_count
            call_count += 1
            if "ruff" in cmd:
                return 1, ruff_output, ""
            # yapf returns no diff → clean
            return 0, "", ""

        ctx = _make_ctx(
            tmp_path,
            [ChangedFile(path="app.py", status="modified")],
            ["python"],
        )

        with patch("conveyor_belt.stations.idiomatic._exec", side_effect=mock_exec):
            result = await station.run(ctx)

        assert len(result.findings) == 2
        assert result.findings[0].rule == "F401"
        assert result.findings[0].line == 3
        assert result.findings[1].rule == "E501"

    @pytest.mark.asyncio
    async def test_yapf_diff_adds_finding(self, station: IdiomaticStation, tmp_path: Path):
        async def mock_exec(cmd, cwd):
            if "yapf" in cmd:
                return 1, "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x=1\n+x = 1\n", ""
            return 0, "[]", ""  # ruff clean

        ctx = _make_ctx(
            tmp_path,
            [ChangedFile(path="app.py", status="modified")],
            ["python"],
        )

        with patch("conveyor_belt.stations.idiomatic._exec", side_effect=mock_exec):
            result = await station.run(ctx)

        yapf_findings = [f for f in result.findings if "yapf" in f.rule]
        assert len(yapf_findings) == 1
        assert yapf_findings[0].severity == Severity.LOW

    @pytest.mark.asyncio
    async def test_clean_code_passes(self, station: IdiomaticStation, tmp_path: Path):
        async def mock_exec(cmd, cwd):
            return 0, "[]" if "ruff" in cmd else "", ""

        ctx = _make_ctx(
            tmp_path,
            [ChangedFile(path="clean.py", status="added")],
            ["python"],
        )

        with patch("conveyor_belt.stations.idiomatic._exec", side_effect=mock_exec):
            result = await station.run(ctx)

        assert result.passed is True
        assert len(result.findings) == 0


# ── Go linting ────────────────────────────────────────────────────────


class TestGoLinting:
    @pytest.mark.asyncio
    async def test_golangci_findings(self, station: IdiomaticStation, tmp_path: Path):
        golangci_output = json.dumps(
            {
                "Issues": [
                    {
                        "FromLinter": "govet",
                        "Text": "printf: non-constant format string",
                        "Pos": {"Filename": "cmd/main.go", "Line": 42},
                    }
                ]
            }
        )

        async def mock_exec(cmd, cwd):
            return 1, golangci_output, ""

        ctx = _make_ctx(
            tmp_path,
            [ChangedFile(path="cmd/main.go", status="modified")],
            ["go"],
        )

        with patch("conveyor_belt.stations.idiomatic._exec", side_effect=mock_exec):
            result = await station.run(ctx)

        assert len(result.findings) == 1
        assert result.findings[0].rule == "govet"
        assert result.findings[0].line == 42


# ── TypeScript linting ────────────────────────────────────────────────


class TestTypeScriptLinting:
    @pytest.mark.asyncio
    async def test_gts_findings(self, station: IdiomaticStation, tmp_path: Path):
        gts_output = "src/index.ts:10:5: error Missing semicolons @typescript-eslint/semi\n"

        async def mock_exec(cmd, cwd):
            return 1, gts_output, ""

        ctx = _make_ctx(
            tmp_path,
            [ChangedFile(path="src/index.ts", status="modified")],
            ["typescript"],
        )

        with patch("conveyor_belt.stations.idiomatic._exec", side_effect=mock_exec):
            result = await station.run(ctx)

        assert len(result.findings) == 1
        assert result.findings[0].file_path == "src/index.ts"
        assert result.findings[0].line == 10
        assert result.findings[0].severity == Severity.HIGH


# ── Java linting ──────────────────────────────────────────────────────


class TestJavaLinting:
    @pytest.mark.asyncio
    async def test_google_java_format_findings(
        self, station: IdiomaticStation, tmp_path: Path
    ):
        async def mock_exec(cmd, cwd):
            if "google-java-format" in cmd:
                return 1, "App.java\n", ""
            # checkstyle clean
            return 0, "", ""

        ctx = _make_ctx(
            tmp_path,
            [ChangedFile(path="App.java", status="modified")],
            ["java"],
        )

        with patch("conveyor_belt.stations.idiomatic._exec", side_effect=mock_exec):
            result = await station.run(ctx)

        fmt_findings = [f for f in result.findings if f.rule == "google-java-format"]
        assert len(fmt_findings) == 1

    @pytest.mark.asyncio
    async def test_checkstyle_findings(self, station: IdiomaticStation, tmp_path: Path):
        checkstyle_out = (
            "[WARN] App.java:15:3: Missing Javadoc comment.\n"
            "[ERROR] App.java:22:1: Line is longer than 100 characters.\n"
        )

        async def mock_exec(cmd, cwd):
            if "google-java-format" in cmd:
                return 0, "", ""
            return 1, checkstyle_out, ""

        ctx = _make_ctx(
            tmp_path,
            [ChangedFile(path="App.java", status="modified")],
            ["java"],
        )

        with patch("conveyor_belt.stations.idiomatic._exec", side_effect=mock_exec):
            result = await station.run(ctx)

        assert len(result.findings) == 2
        warn_f = [f for f in result.findings if f.line == 15][0]
        assert warn_f.severity == Severity.MEDIUM
        err_f = [f for f in result.findings if f.line == 22][0]
        assert err_f.severity == Severity.HIGH


# ── Multi-language in single run ──────────────────────────────────────


class TestMultiLanguage:
    @pytest.mark.asyncio
    async def test_mixed_languages(self, station: IdiomaticStation, tmp_path: Path):
        ruff_json = json.dumps(
            [{"code": "F401", "message": "unused", "filename": "svc.py", "location": {"row": 1}}]
        )
        golangci_json = json.dumps(
            {"Issues": [{
                "FromLinter": "errcheck",
                "Text": "error not checked",
                "Pos": {"Filename": "main.go", "Line": 5},
            }]}
        )

        async def mock_exec(cmd, cwd):
            if "ruff" in cmd:
                return 1, ruff_json, ""
            if "yapf" in cmd:
                return 0, "", ""
            if "golangci-lint" in cmd:
                return 1, golangci_json, ""
            return 0, "", ""

        ctx = _make_ctx(
            tmp_path,
            [
                ChangedFile(path="svc.py", status="modified"),
                ChangedFile(path="main.go", status="modified"),
            ],
            ["python", "go"],
        )

        with patch("conveyor_belt.stations.idiomatic._exec", side_effect=mock_exec):
            result = await station.run(ctx)

        assert len(result.findings) == 2
        rules = {f.rule for f in result.findings}
        assert "F401" in rules
        assert "errcheck" in rules
