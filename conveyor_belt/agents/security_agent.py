"""Security testing agent — analyzes PR diff for security vulnerabilities."""

from __future__ import annotations

import json
import re

from conveyor_belt.agents.base import BaseAgent
from conveyor_belt.config import AgentConfig

SYSTEM_PROMPT = """\
You are a security engineer performing code review on a pull request.

Analyze the code diff for the following classes of vulnerabilities:
1. **Authentication/Authorization**: missing auth checks, unauthenticated endpoints
   broken access control
2. **Injection**: SQL injection, command injection, LDAP injection, XSS
3. **Cryptography**: weak primitives (MD5, SHA1 for signing, DES, RC4), hardcoded keys/secrets
4. **Data exposure**: sensitive data in logs, hardcoded credentials, PII leaks
5. **Insecure deserialization**: unsafe unmarshalling of untrusted data
6. **Dependency risks**: known-vulnerable patterns, unsafe use of libraries
7. **Configuration**: debug mode in production, permissive CORS, missing security headers

For each finding, provide:
- The CWE identifier (e.g. CWE-89 for SQL injection)
- Severity: critical, high, medium, low
- The specific file and line range
- A remediation suggestion

IMPORTANT: Output ONLY valid JSON in this exact format:
{
  "findings": [
    {
      "rule": "hardcoded-secret",
      "cwe_id": "CWE-798",
      "severity": "high",
      "file_path": "config/db.go",
      "line": 15,
      "message": "Database password is hardcoded",
      "remediation": "Use environment variable or secrets manager"
    }
  ],
  "summary": "Found X security issue(s): ..."
}

If the diff looks clean, return: {"findings": [], "summary": "No security issues found"}
"""


class SecurityAgent(BaseAgent):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config, system_prompt=SYSTEM_PROMPT)

    async def analyze_diff(self, diff_text: str, languages: list[str]) -> dict:
        """Analyze a PR diff for security vulnerabilities."""
        prompt = (
            f"## Languages: {', '.join(languages)}\n\n"
            f"## Code Diff\n```\n{diff_text[:12000]}\n```\n\n"
            "Analyze this diff for security vulnerabilities. Output ONLY the JSON."
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
            "findings": [],
            "summary": "Failed to parse LLM response",
            "raw_response": raw[:500],
        }
