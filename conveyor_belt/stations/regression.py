"""Station 3 — Regression Testing (historical issues → agent → regression tests)."""

from __future__ import annotations

from conveyor_belt.agents.regression_agent import RegressionAgent
from conveyor_belt.context import StationContext
from conveyor_belt.integrations.linear import fetch_team_issues
from conveyor_belt.models import Finding, Severity, StationResult
from conveyor_belt.stations.base import Station


class RegressionStation(Station):
    name = "regression"

    async def run(self, ctx: StationContext) -> StationResult:
        findings: list[Finding] = []
        cfg = self.config.stations.regression

        # ── 1. Fetch historical issues ─────────────────────────────────
        historical = ctx.historical_issues
        if not historical:
            try:
                historical = await fetch_team_issues(
                    team_key=self.config.project.linear.team_key,
                    limit=cfg.lookback_epics,
                    states=["Done", "Closed", "Completed"],
                )
            except Exception as exc:
                findings.append(
                    Finding(
                        rule="linear/fetch_error",
                        message=f"Failed to fetch historical issues: {exc}",
                        severity=Severity.INFO,
                    )
                )

        if not historical:
            return StationResult(
                station_name=self.name,
                passed=True,
                summary="No historical issues available — skipping.",
                findings=findings,
            )

        # ── 2. Build diff context ──────────────────────────────────────
        diff_text = "\n".join(
            cf.patch for cf in ctx.changed_files if cf.patch
        )
        changed_files = [cf.path for cf in ctx.changed_files]

        # ── 3. Call the regression agent ───────────────────────────────
        agent = RegressionAgent(self.config.agent)
        try:
            result = await agent.generate_regression_tests(
                historical, diff_text, changed_files, ctx.languages
            )
        except RuntimeError as exc:
            return StationResult(
                station_name=self.name,
                passed=False,
                summary=f"LLM agent failed: {exc}",
                findings=[
                    Finding(
                        rule="agent/error",
                        message=str(exc),
                        severity=Severity.MEDIUM,
                    )
                ],
            )

        # ── 4. Report results ─────────────────────────────────────────
        at_risk = result.get("at_risk_requirements", [])
        risk_score = result.get("risk_score", 0)
        regression_tests = result.get("regression_tests", [])

        for req in at_risk:
            sev = Severity.HIGH if risk_score >= 60 else Severity.MEDIUM
            findings.append(
                Finding(
                    rule="regression/at_risk",
                    message=(
                        f"{req.get('identifier', '?')}: "
                        f"{req.get('title', '?')} — "
                        f"{req.get('risk_reason', 'potentially affected')}"
                    ),
                    severity=sev,
                )
            )

        summary = result.get(
            "risk_summary",
            f"Risk score: {risk_score}/100 | "
            f"{len(at_risk)} at risk | "
            f"{len(regression_tests)} test(s) generated",
        )

        return StationResult(
            station_name=self.name,
            passed=risk_score < 70,
            summary=summary,
            findings=findings,
        )
