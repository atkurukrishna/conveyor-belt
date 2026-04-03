"""Orchestrator — runs stations, collects results, applies gate policy."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from rich.console import Console

from conveyor_belt.config import ConveyorBeltConfig
from conveyor_belt.context import StationContext
from conveyor_belt.integrations.git import (
    changed_files_from_diff,
    changed_files_from_pr,
    changed_files_from_staged,
    get_pr_body,
)
from conveyor_belt.models import StationResult
from conveyor_belt.stations.base import Station

console = Console(stderr=True)


class PipelineReport(BaseModel):
    """Aggregated results from all stations."""

    gate_passed: bool = True
    policy: str = "hard_fail"
    results: list[StationResult] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_markdown(self) -> str:
        gate_icon = "✅" if self.gate_passed else "❌"
        lines = [
            f"## {gate_icon} Conveyor Belt QA Report",
            "",
            f"**Gate policy:** `{self.policy}`"
            f" | **Result:** {'PASS' if self.gate_passed else 'FAIL'}",
            "",
        ]
        for r in self.results:
            icon = "✅" if r.passed else "❌"
            lines.append(f"### {icon} {r.station_name}")
            lines.append(f"*{r.summary}* ({r.duration_seconds}s)")
            if r.findings:
                lines.append("")
                lines.append("| Severity | Rule | Message | File | Line |")
                lines.append("|----------|------|---------|------|------|")
                for f in r.findings[:25]:  # cap at 25 per station
                    lines.append(
                        f"| {f.severity.value} | `{f.rule}` | {f.message[:80]} "
                        f"| {f.file_path or '-'} | {f.line or '-'} |"
                    )
                if len(r.findings) > 25:
                    lines.append(f"| ... | | +{len(r.findings) - 25} more findings | | |")
            lines.append("")
        return "\n".join(lines)


# ── Station registry ───────────────────────────────────────────────────

def _available_stations(config: ConveyorBeltConfig) -> dict[str, Station]:
    """Lazily import and instantiate only the stations that are enabled."""
    registry: dict[str, Station] = {}

    if config.stations.unit_coverage.enabled:
        from conveyor_belt.stations.unit_coverage import UnitCoverageStation
        registry["unit_coverage"] = UnitCoverageStation(config)

    if config.stations.idiomatic.enabled:
        from conveyor_belt.stations.idiomatic import IdiomaticStation
        registry["idiomatic"] = IdiomaticStation(config)

    if config.stations.vulnerability.enabled:
        from conveyor_belt.stations.vulnerability import VulnerabilityStation
        registry["vulnerability"] = VulnerabilityStation(config)

    if config.stations.feature_validation.enabled:
        from conveyor_belt.stations.feature_validation import FeatureValidationStation
        registry["feature_validation"] = FeatureValidationStation(config)

    if config.stations.regression.enabled:
        from conveyor_belt.stations.regression import RegressionStation
        registry["regression"] = RegressionStation(config)

    if config.stations.security.enabled:
        from conveyor_belt.stations.security import SecurityStation
        registry["security"] = SecurityStation(config)

    return registry


# ── Orchestrator ───────────────────────────────────────────────────────

class Orchestrator:
    def __init__(self, config: ConveyorBeltConfig, repo_root: str) -> None:
        self.config = config
        self.repo_root = repo_root

    async def run(
        self,
        pr_number: int | None = None,
        diff_ref: str | None = None,
        only_stations: list[str] | None = None,
    ) -> PipelineReport:
        # ── 1. Build context ───────────────────────────────────────────
        console.print("[dim]Building station context…[/]")
        ctx = await self._build_context(pr_number, diff_ref)

        console.print(
            f"[dim]  {len(ctx.changed_files)} changed file(s), "
            f"languages: {ctx.languages}[/]"
        )

        # ── 2. Select stations ─────────────────────────────────────────
        all_stations = _available_stations(self.config)
        if only_stations:
            stations = {k: v for k, v in all_stations.items() if k in only_stations}
        else:
            stations = all_stations

        if not stations:
            return PipelineReport(
                gate_passed=True,
                policy=self.config.gate.policy,
                results=[
                    StationResult(
                        station_name="orchestrator",
                        passed=True,
                        summary="No stations to run.",
                    )
                ],
            )

        # ── 3. Run stations concurrently ───────────────────────────────
        console.print(f"[dim]Running {len(stations)} station(s): {list(stations.keys())}[/]")

        async def _run_station(name: str, station: Station) -> StationResult:
            try:
                return await station.execute(ctx)
            except Exception as exc:
                return StationResult(
                    station_name=name,
                    passed=False,
                    summary=f"Station crashed: {exc}",
                )

        tasks = [_run_station(name, st) for name, st in stations.items()]
        results: list[StationResult] = await asyncio.gather(*tasks)

        # ── 4. Apply gate policy ───────────────────────────────────────
        gate_passed = self._apply_gate(results)

        return PipelineReport(
            gate_passed=gate_passed,
            policy=self.config.gate.policy,
            results=results,
        )

    async def _build_context(
        self,
        pr_number: int | None,
        diff_ref: str | None,
    ) -> StationContext:
        pr_title = ""
        pr_body = ""

        if pr_number:
            changed = await changed_files_from_pr(self.repo_root, pr_number)
            pr_title, pr_body = await get_pr_body(self.repo_root, pr_number)
        elif diff_ref:
            changed = await changed_files_from_diff(self.repo_root, diff_ref)
        else:
            changed = await changed_files_from_staged(self.repo_root)

        return StationContext(
            repo_root=self.repo_root,
            pr_number=pr_number,
            pr_title=pr_title,
            pr_body=pr_body,
            languages=self.config.project.languages,
            changed_files=changed,
        )

    def _apply_gate(self, results: list[StationResult]) -> bool:
        policy = self.config.gate.policy

        if policy == "soft_fail":
            return True  # always pass, just warn

        # hard_fail: any station failure → gate fails
        return all(r.passed for r in results)
