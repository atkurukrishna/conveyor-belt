"""Feature validation agent — generates test cases from PRDs/issues + PR diff."""

from __future__ import annotations

import json
import re

from conveyor_belt.agents.base import BaseAgent
from conveyor_belt.config import AgentConfig
from conveyor_belt.context import LinearIssue

SYSTEM_PROMPT = """\
You are a QA engineer that generates executable test cases from product requirements.

Given:
1. A set of Linear issues (with acceptance criteria / descriptions)
2. A code diff from a pull request

Your job:
- Identify the acceptance criteria from the issues.
- Map each criterion to concrete test cases that validate the PR implements it.
- Output test cases in the language appropriate for the changed code:
  - Python → pytest functions
  - Go → Go test functions (table-driven)
  - TypeScript → Jest/Vitest test blocks
  - Java → JUnit test methods

IMPORTANT: Output ONLY valid JSON in this exact format:
{
  "acceptance_criteria": [
    {"id": "AC-1", "description": "...", "covered": true}
  ],
  "test_cases": [
    {
      "name": "test_...",
      "language": "python",
      "description": "...",
      "code": "def test_...():\\n    ..."
    }
  ],
  "coverage_summary": "X of Y acceptance criteria covered"
}
"""


class FeatureAgent(BaseAgent):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config, system_prompt=SYSTEM_PROMPT)

    async def generate_test_cases(
        self,
        issues: list[LinearIssue],
        diff_text: str,
        languages: list[str],
    ) -> dict:
        """Generate feature validation test cases from issues + diff."""
        issues_text = "\n\n".join(
            f"### {i.identifier}: {i.title}\n{i.description}"
            + (
                "\nSub-issues:\n"
                + "\n".join(f"  - {s.identifier}: {s.title}" for s in i.sub_issues)
                if i.sub_issues
                else ""
            )
            for i in issues
        )

        prompt = (
            f"## Linear Issues / PRD\n{issues_text}\n\n"
            f"## Code Diff\n```\n{diff_text[:8000]}\n```\n\n"
            f"## Target Languages: {', '.join(languages)}\n\n"
            "Generate feature validation test cases. Output ONLY the JSON."
        )

        raw = await self.invoke(prompt)
        return _parse_json_response(raw)


def _parse_json_response(raw: str) -> dict:
    """Extract JSON from LLM response, handling markdown code fences."""
    # Strip markdown code fences if present
    match = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
    if match:
        raw = match.group(1)
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return {
            "acceptance_criteria": [],
            "test_cases": [],
            "coverage_summary": "Failed to parse LLM response",
            "raw_response": raw[:500],
        }
