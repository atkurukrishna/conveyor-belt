"""Tests for Station 1 — Unit Test Coverage."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from conveyor_belt.config import ConveyorBeltConfig
from conveyor_belt.context import ChangedFile, StationContext
from conveyor_belt.stations.unit_coverage import UnitCoverageStation


# ── Fixtures: sample report content ───────────────────────────────────


COBERTURA_XML = textwrap.dedent("""\
    <?xml version="1.0" ?>
    <coverage version="5.5" timestamp="1234" lines-valid="100" lines-covered="90"
              line-rate="0.9" branches-valid="0" branches-covered="0" branch-rate="0"
              complexity="0">
        <packages>
            <package name="conveyor_belt" line-rate="0.9" branch-rate="0" complexity="0">
                <classes>
                    <class name="models.py" filename="conveyor_belt/models.py"
                           line-rate="0.95" branch-rate="0" complexity="0">
                        <lines>
                            <line number="1" hits="1"/>
                            <line number="2" hits="1"/>
                            <line number="3" hits="1"/>
                            <line number="4" hits="1"/>
                            <line number="5" hits="0"/>
                            <line number="6" hits="1"/>
                            <line number="7" hits="1"/>
                            <line number="8" hits="1"/>
                            <line number="9" hits="1"/>
                            <line number="10" hits="1"/>
                            <line number="11" hits="1"/>
                            <line number="12" hits="1"/>
                            <line number="13" hits="1"/>
                            <line number="14" hits="1"/>
                            <line number="15" hits="1"/>
                            <line number="16" hits="1"/>
                            <line number="17" hits="1"/>
                            <line number="18" hits="1"/>
                            <line number="19" hits="1"/>
                            <line number="20" hits="1"/>
                        </lines>
                    </class>
                    <class name="cli.py" filename="conveyor_belt/cli.py"
                           line-rate="0.5" branch-rate="0" complexity="0">
                        <lines>
                            <line number="1" hits="1"/>
                            <line number="2" hits="0"/>
                            <line number="3" hits="0"/>
                            <line number="4" hits="0"/>
                            <line number="5" hits="0"/>
                            <line number="6" hits="0"/>
                            <line number="7" hits="0"/>
                            <line number="8" hits="0"/>
                            <line number="9" hits="0"/>
                            <line number="10" hits="1"/>
                        </lines>
                    </class>
                </classes>
            </package>
        </packages>
    </coverage>
""")


JACOCO_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <!DOCTYPE report PUBLIC "-//JACOCO//DTD Report 1.1//EN" "report.dtd">
    <report name="example">
        <package name="com/example/service">
            <sourcefile name="UserService.java">
                <counter type="LINE" missed="5" covered="45"/>
                <counter type="BRANCH" missed="2" covered="8"/>
            </sourcefile>
            <sourcefile name="AuthService.java">
                <counter type="LINE" missed="20" covered="30"/>
                <counter type="BRANCH" missed="5" covered="5"/>
            </sourcefile>
        </package>
    </report>
""")


GO_COVER_OUT = textwrap.dedent("""\
    mode: set
    github.com/example/pkg/handler.go:10.30,15.2 3 1
    github.com/example/pkg/handler.go:17.30,22.2 3 0
    github.com/example/pkg/handler.go:24.30,29.2 3 1
    github.com/example/pkg/util.go:5.20,10.2 4 1
    github.com/example/pkg/util.go:12.20,18.2 5 1
""")


@pytest.fixture
def station() -> UnitCoverageStation:
    return UnitCoverageStation(config=ConveyorBeltConfig())


# ── Parser tests ──────────────────────────────────────────────────────


class TestCoberturaParsing:
    def test_parses_files(self, station: UnitCoverageStation, tmp_path: Path):
        report = tmp_path / "coverage.xml"
        report.write_text(COBERTURA_XML)
        records = station._parse_cobertura(report)
        assert len(records) == 2

    def test_coverage_values(self, station: UnitCoverageStation, tmp_path: Path):
        report = tmp_path / "coverage.xml"
        report.write_text(COBERTURA_XML)
        records = station._parse_cobertura(report)
        by_file = {r.file_path: r for r in records}

        models = by_file["conveyor_belt/models.py"]
        assert models.lines_total == 20
        assert models.lines_covered == 19
        assert models.percent == 95.0

        cli = by_file["conveyor_belt/cli.py"]
        assert cli.lines_total == 10
        assert cli.lines_covered == 2
        assert cli.percent == 20.0


class TestJacocoParsing:
    def test_parses_files(self, station: UnitCoverageStation, tmp_path: Path):
        report = tmp_path / "jacoco.xml"
        report.write_text(JACOCO_XML)
        records = station._parse_jacoco(report)
        assert len(records) == 2

    def test_coverage_values(self, station: UnitCoverageStation, tmp_path: Path):
        report = tmp_path / "jacoco.xml"
        report.write_text(JACOCO_XML)
        records = station._parse_jacoco(report)
        by_file = {r.file_path: r for r in records}

        user_svc = by_file["com.example.service/UserService.java"]
        assert user_svc.lines_total == 50
        assert user_svc.lines_covered == 45
        assert user_svc.percent == 90.0

        auth_svc = by_file["com.example.service/AuthService.java"]
        assert auth_svc.lines_total == 50
        assert auth_svc.lines_covered == 30
        assert auth_svc.percent == 60.0


class TestGoCoverParsing:
    def test_parses_files(self, station: UnitCoverageStation, tmp_path: Path):
        report = tmp_path / "coverage.out"
        report.write_text(GO_COVER_OUT)
        records = station._parse_go_cover(report)
        assert len(records) == 2

    def test_coverage_values(self, station: UnitCoverageStation, tmp_path: Path):
        report = tmp_path / "coverage.out"
        report.write_text(GO_COVER_OUT)
        records = station._parse_go_cover(report)
        by_file = {r.file_path: r for r in records}

        handler = by_file["github.com/example/pkg/handler.go"]
        assert handler.lines_total == 9
        assert handler.lines_covered == 6  # 3 + 0 + 3 covered
        assert handler.percent == 66.67

        util = by_file["github.com/example/pkg/util.go"]
        assert util.lines_total == 9
        assert util.lines_covered == 9
        assert util.percent == 100.0


# ── Integration-style async run test ──────────────────────────────────


class TestUnitCoverageStationRun:
    @pytest.mark.asyncio
    async def test_passes_when_above_threshold(
        self, station: UnitCoverageStation, tmp_path: Path
    ):
        """Mock subprocess so it doesn't actually run pytest, but the report exists."""
        report = tmp_path / "coverage.xml"
        report.write_text(COBERTURA_XML)

        ctx = StationContext(
            repo_root=str(tmp_path),
            languages=["python"],
            changed_files=[
                ChangedFile(path="conveyor_belt/models.py", status="modified"),
            ],
        )

        # Patch the runner config to point at the tmp_path report
        station.RUNNERS["python"]["report"] = "coverage.xml"

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await station.run(ctx)

        assert result.passed is True
        assert "95.0%" in result.summary or "Overall coverage" in result.summary

    @pytest.mark.asyncio
    async def test_fails_when_below_threshold(
        self, station: UnitCoverageStation, tmp_path: Path
    ):
        report = tmp_path / "coverage.xml"
        report.write_text(COBERTURA_XML)

        ctx = StationContext(
            repo_root=str(tmp_path),
            languages=["python"],
            changed_files=[
                ChangedFile(path="conveyor_belt/cli.py", status="modified"),
            ],
        )

        station.RUNNERS["python"]["report"] = "coverage.xml"

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await station.run(ctx)

        assert result.passed is False
        assert any("coverage_below_threshold" == f.rule for f in result.findings)

    @pytest.mark.asyncio
    async def test_handles_missing_runner(self, station: UnitCoverageStation, tmp_path: Path):
        """If language has no runner configured, it should gracefully skip."""
        ctx = StationContext(
            repo_root=str(tmp_path),
            languages=["rust"],  # no runner for rust
            changed_files=[],
        )
        result = await station.run(ctx)
        assert result.passed is True
