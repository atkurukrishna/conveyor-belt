"""Regression testing agent — generates regression tests from historical requirements."""

from __future__ import annotations

import json
import re

from conveyor_belt.agents.base import BaseAgent
from conveyor_belt.config import AgentConfig
from conveyor_belt.context import LinearIssue

SYSTEM_PROMPT = """\
You are a QA engineer specializing in regression testing.

Given:
1. A list of historical requirements (completed Linear issues / epics)
2. A code diff from a current pull request
3. The list of files changed

Your job:
- Identify which historical requirements could be affected by the changes.
- For each at-risk requirement, generate regression test cases.
- Assign a risk score (0-100) indicating how likely the PR is to break existing behavior.

IMPORTANT: Output ONLY valid JSON in this exact format:
{
  "at_risk_requirements": [
    {"identifier": "ENG-45", "title": "...", "risk_reason": "..."}
  ],
  "regression_tests": [
    {
      "name": "test_...",
      "language": "python",
      "requirement_ref": "ENG-45",
      "description": "...",
      "code": "def test_...():\\n    ..."
    }
  ],
  "risk_score": 35,
  "risk_summary": "..."
}
"""


class RegressionAgent(BaseAgent):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config, system_prompt=SYSTEM_PROMPT)

    async def generate_regression_tests(
        self,
        historical_issues: list[LinearIssue],
        diff_text: str,
        changed_files: list[str],
        languages: list[str],
    ) -> dict:
        """Generate regression tests based on historical requirements + current diff."""
        history_text = "\n".join(
            f"- {i.identifier}: {i.title} — {i.description[:200]}"
            for i in historical_issues
        )

        files_text = "\n".join(f"  - {f}" for f in changed_files)

        prompt = (
            f"## Historical Requirements (completed)\n{history_text}\n\n"
            f"## Changed Files\n{files_text}\n\n"
            f"## Code Diff\n```\n{diff_text[:8000]}\n```\n\n"
            f"## Target Languages: {', '.join(languages)}\n\n"
            "Identify at-risk requirements and generate regression tests. Output ONLY the JSON."
        )

        raw = await self.invoke(prompt)
        return _parse_json_response(raw)


def _parse_json_response(raw: str) -> dict:
    """Extract JSON from LLM response, handling markdown code fences."""
    match = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
    if match:
        raw = match.group(1)
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return {
            "at_risk_requirements": [],
            "regression_tests": [],
            "risk_score": 0,
            "risk_summary": "Failed to parse LLM response",
            "raw_response": raw[:500],
        }
