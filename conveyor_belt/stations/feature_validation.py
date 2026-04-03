"""Station 2 — Feature Validation (PRD/Epic → agent → generated tests)."""

from __future__ import annotations

from conveyor_belt.agents.feature_agent import FeatureAgent
from conveyor_belt.context import StationContext
from conveyor_belt.integrations.git import parse_issue_tags
from conveyor_belt.integrations.linear import fetch_issues
from conveyor_belt.models import Finding, Severity, StationResult
from conveyor_belt.stations.base import Station


class FeatureValidationStation(Station):
    name = "feature_validation"

    async def run(self, ctx: StationContext) -> StationResult:
        findings: list[Finding] = []

        # ── 1. Resolve Linear issues ───────────────────────────────────
        issue_ids = list(
            {tag for tag in parse_issue_tags(f"{ctx.pr_title} {ctx.pr_body}")}
        )
        if not issue_ids and not ctx.linear_issues:
            return StationResult(
                station_name=self.name,
                passed=True,
                summary="No Linear issues linked — skipping feature validation.",
            )

        issues = ctx.linear_issues
        if not issues and issue_ids:
            try:
                issues = await fetch_issues(issue_ids)
            except Exception as exc:
                findings.append(
                    Finding(
                        rule="linear/fetch_error",
                        message=f"Failed to fetch Linear issues: {exc}",
                        severity=Severity.INFO,
                    )
                )

        if not issues:
            return StationResult(
                station_name=self.name,
                passed=True,
                summary=f"Could not fetch Linear issues {issue_ids} — skipping.",
                findings=findings,
            )

        # ── 2. Build diff text ─────────────────────────────────────────
        diff_text = "\n".join(cf.patch for cf in ctx.changed_files if cf.patch)

        # ── 3. Call the feature agent ──────────────────────────────────
        agent = FeatureAgent(self.config.agent)
        try:
            result = await agent.generate_test_cases(
                issues, diff_text, ctx.languages
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
        test_cases = result.get("test_cases", [])
        criteria = result.get("acceptance_criteria", [])
        uncovered = [ac for ac in criteria if not ac.get("covered", False)]

        for ac in uncovered:
            findings.append(
                Finding(
                    rule="feature/uncovered_ac",
                    message=(
                        f"Acceptance criterion not covered: "
                        f"{ac.get('description', ac.get('id', '?'))}"
                    ),
                    severity=Severity.HIGH,
                )
            )

        covered_count = len(criteria) - len(uncovered)
        summary = result.get(
            "coverage_summary",
            f"{len(test_cases)} test(s) generated, "
            f"{covered_count}/{len(criteria)} AC covered",
        )

        return StationResult(
            station_name=self.name,
            passed=len(uncovered) == 0,
            summary=summary,
            findings=findings,
        )
