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
