"""Tests for the CLI entry point."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from conveyor_belt.cli import main


class TestCLI:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_validate_config_defaults(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["validate-config", "--config", str(tmp_path / "nonexistent.yaml")],
        )
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_validate_config_with_file(self, tmp_path):
        cfg_file = tmp_path / "conveyor-belt.yaml"
        cfg_file.write_text("project:\n  languages: [python]\n")
        runner = CliRunner()
        result = runner.invoke(
            main, ["validate-config", "--config", str(cfg_file)]
        )
        assert result.exit_code == 0
        assert "python" in result.output

    def test_run_with_diff(self, tmp_path):
        """Test that `cb run --diff` invokes the orchestrator."""
        from conveyor_belt.models import StationResult
        from conveyor_belt.orchestrator import PipelineReport

        mock_report = PipelineReport(
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

        with patch(
            "conveyor_belt.orchestrator.Orchestrator"
        ) as mock_orch_cls:
            mock_instance = mock_orch_cls.return_value
            mock_instance.run = AsyncMock(return_value=mock_report)

            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "run",
                    "--diff", "HEAD~1",
                    "--repo", str(tmp_path),
                ],
            )

        assert result.exit_code == 0
        assert "PASS" in result.output

    def test_run_exits_1_on_gate_fail(self, tmp_path):
        from conveyor_belt.models import StationResult
        from conveyor_belt.orchestrator import PipelineReport

        mock_report = PipelineReport(
            gate_passed=False,
            policy="hard_fail",
            results=[
                StationResult(
                    station_name="security",
                    passed=False,
                    summary="1 finding",
                )
            ],
        )

        with patch(
            "conveyor_belt.orchestrator.Orchestrator"
        ) as mock_orch_cls:
            mock_instance = mock_orch_cls.return_value
            mock_instance.run = AsyncMock(return_value=mock_report)

            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "run",
                    "--diff", "HEAD~1",
                    "--repo", str(tmp_path),
                ],
            )

        assert result.exit_code == 1

    def test_run_with_pr(self, tmp_path):
        from conveyor_belt.models import StationResult
        from conveyor_belt.orchestrator import PipelineReport

        mock_report = PipelineReport(gate_passed=True, policy="soft_fail", results=[
            StationResult(station_name="idiomatic", passed=True, summary="ok"),
        ])

        with patch("conveyor_belt.orchestrator.Orchestrator") as mock_orch_cls:
            mock_orch_cls.return_value.run = AsyncMock(return_value=mock_report)
            runner = CliRunner()
            result = runner.invoke(main, ["run", "--pr", "42", "--repo", str(tmp_path)])

        assert result.exit_code == 0
        assert "PR #42" in result.output

    def test_run_no_pr_or_diff(self, tmp_path):
        from conveyor_belt.models import StationResult
        from conveyor_belt.orchestrator import PipelineReport

        mock_report = PipelineReport(gate_passed=True, policy="soft_fail", results=[
            StationResult(station_name="idiomatic", passed=True, summary="ok"),
        ])

        with patch("conveyor_belt.orchestrator.Orchestrator") as mock_orch_cls:
            mock_orch_cls.return_value.run = AsyncMock(return_value=mock_report)
            runner = CliRunner()
            result = runner.invoke(main, ["run", "--repo", str(tmp_path)])

        assert result.exit_code == 0
        assert "staged" in result.output.lower()

    def test_run_picks_up_repo_config(self, tmp_path):
        from conveyor_belt.models import StationResult
        from conveyor_belt.orchestrator import PipelineReport

        (tmp_path / "conveyor-belt.yaml").write_text("project:\n  languages: [python]\n")
        mock_report = PipelineReport(gate_passed=True, policy="soft_fail", results=[
            StationResult(station_name="idiomatic", passed=True, summary="ok"),
        ])

        with patch("conveyor_belt.orchestrator.Orchestrator") as mock_orch_cls:
            mock_orch_cls.return_value.run = AsyncMock(return_value=mock_report)
            runner = CliRunner()
            result = runner.invoke(main, ["run", "--diff", "HEAD~1", "--repo", str(tmp_path)])

        assert result.exit_code == 0


class TestServeCLI:
    def test_serve_calls_uvicorn(self):
        with patch("uvicorn.run") as mock_run:
            runner = CliRunner()
            result = runner.invoke(main, ["serve", "--host", "0.0.0.0", "--port", "9000"])

        assert result.exit_code == 0
        mock_run.assert_called_once_with(
            "conveyor_belt.server:app",
            host="0.0.0.0",
            port=9000,
            reload=False,
        )

    def test_serve_defaults(self):
        with patch("uvicorn.run") as mock_run:
            runner = CliRunner()
            runner.invoke(main, ["serve"])

        mock_run.assert_called_once_with(
            "conveyor_belt.server:app",
            host="127.0.0.1",
            port=8000,
            reload=False,
        )

    def test_serve_with_reload(self):
        with patch("uvicorn.run") as mock_run:
            runner = CliRunner()
            runner.invoke(main, ["serve", "--reload"])

        _, kwargs = mock_run.call_args
        assert kwargs["reload"] is True
