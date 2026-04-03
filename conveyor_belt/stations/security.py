"""Station 6 — Security Testing (agent + language-specific SAST tools)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from conveyor_belt.agents.security_agent import SecurityAgent
from conveyor_belt.context import StationContext
from conveyor_belt.models import Finding, Severity, StationResult
from conveyor_belt.stations.base import Station

SEVERITY_MAP = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "low": Severity.LOW,
}


async def _exec(
    cmd: list[str], cwd: str, timeout: float = 60.0
) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return proc.returncode or 0, stdout.decode(), stderr.decode()
    except FileNotFoundError:
        return 127, "", f"Command not found: {cmd[0]}"
    except TimeoutError:
        proc.kill()
        return 1, "", f"Command timed out after {timeout}s"


class SecurityStation(Station):
    name = "security"

    async def run(self, ctx: StationContext) -> StationResult:
        all_findings: list[Finding] = []
        tasks: list = []

        # ── 1. LLM-based security analysis ────────────────────────────
        diff_text = "\n".join(
            cf.patch for cf in ctx.changed_files if cf.patch
        )
        if diff_text.strip():
            tasks.append(self._agent_analysis(diff_text, ctx.languages))

        # ── 2. Language-specific SAST tools ────────────────────────────
        changed_by_lang = self._group_by_lang(ctx)
        if "python" in changed_by_lang:
            tasks.append(
                self._run_bandit(changed_by_lang["python"], ctx.repo_root)
            )
        if "go" in changed_by_lang:
            tasks.append(
                self._run_gosec(changed_by_lang["go"], ctx.repo_root)
            )
        if "typescript" in changed_by_lang:
            tasks.append(
                self._run_semgrep(
                    changed_by_lang["typescript"], ctx.repo_root
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                all_findings.append(
                    Finding(
                        rule="security/error",
                        message=str(result),
                        severity=Severity.MEDIUM,
                    )
                )
            elif isinstance(result, list):
                all_findings.extend(result)

        # ── 3. Determine pass/fail ─────────────────────────────────────
        block_on = {
            Severity(sev) for sev in self.config.stations.security.block_on
        }
        has_blocking = any(f.severity in block_on for f in all_findings)

        return StationResult(
            station_name=self.name,
            passed=not has_blocking,
            summary=f"{len(all_findings)} security finding(s)",
            findings=all_findings,
        )

    async def _agent_analysis(
        self, diff_text: str, languages: list[str]
    ) -> list[Finding]:
        """Use the security LLM agent to analyze the diff."""
        agent = SecurityAgent(self.config.agent)
        try:
            result = await agent.analyze_diff(diff_text, languages)
        except RuntimeError:
            return []

        findings: list[Finding] = []
        for item in result.get("findings", []):
            findings.append(
                Finding(
                    rule=f"security-agent/{item.get('rule', 'unknown')}",
                    message=item.get("message", ""),
                    severity=SEVERITY_MAP.get(
                        item.get("severity", "medium"), Severity.MEDIUM
                    ),
                    file_path=item.get("file_path"),
                    line=item.get("line"),
                    cwe_id=item.get("cwe_id"),
                    remediation=item.get("remediation"),
                )
            )
        return findings

    # ── SAST tool runners ──────────────────────────────────────────────

    async def _run_bandit(
        self, files: list[str], cwd: str
    ) -> list[Finding]:
        """Run bandit (Python security linter)."""
        rc, stdout, stderr = await _exec(
            ["bandit", "-f", "json", "-ll", *files], cwd
        )
        if rc == 127 or "Command not found" in stderr:
            return [
                Finding(
                    rule="bandit/unavailable",
                    message=stderr.strip(),
                    severity=Severity.INFO,
                )
            ]
        findings: list[Finding] = []
        try:
            data = json.loads(stdout)
            for item in data.get("results", []):
                cwe_raw = item.get("issue_cwe")
                cwe_id = (
                    cwe_raw.get("id")
                    if isinstance(cwe_raw, dict)
                    else None
                )
                findings.append(
                    Finding(
                        rule=f"bandit/{item.get('test_id', 'unknown')}",
                        message=item.get("issue_text", ""),
                        severity=SEVERITY_MAP.get(
                            item.get("issue_severity", "").lower(),
                            Severity.MEDIUM,
                        ),
                        file_path=item.get("filename"),
                        line=item.get("line_number"),
                        cwe_id=cwe_id,
                    )
                )
        except json.JSONDecodeError:
            pass
        return findings

    async def _run_gosec(
        self, files: list[str], cwd: str
    ) -> list[Finding]:
        """Run gosec (Go security linter)."""
        pkg_dirs = list({str(Path(fp).parent) for fp in files})
        rc, stdout, stderr = await _exec(
            [
                "gosec",
                "-fmt=json",
                *[f"./{d}/..." for d in pkg_dirs],
            ],
            cwd,
        )
        if rc == 127 or "Command not found" in stderr:
            return [
                Finding(
                    rule="gosec/unavailable",
                    message=stderr.strip(),
                    severity=Severity.INFO,
                )
            ]
        findings: list[Finding] = []
        try:
            data = json.loads(stdout)
            for issue in data.get("Issues", []):
                cwe_raw = issue.get("cwe")
                cwe_id = (
                    cwe_raw.get("id")
                    if isinstance(cwe_raw, dict)
                    else None
                )
                findings.append(
                    Finding(
                        rule=f"gosec/{issue.get('rule_id', 'unknown')}",
                        message=issue.get("details", ""),
                        severity=SEVERITY_MAP.get(
                            issue.get("severity", "").lower(),
                            Severity.MEDIUM,
                        ),
                        file_path=issue.get("file"),
                        line=int(issue.get("line", 0)) or None,
                        cwe_id=cwe_id,
                    )
                )
        except json.JSONDecodeError:
            pass
        return findings

    async def _run_semgrep(
        self, files: list[str], cwd: str
    ) -> list[Finding]:
        """Run semgrep with security rulesets for TypeScript."""
        rc, stdout, stderr = await _exec(
            ["semgrep", "--config=auto", "--json", *files], cwd
        )
        if rc == 127 or "Command not found" in stderr:
            return [
                Finding(
                    rule="semgrep/unavailable",
                    message=stderr.strip(),
                    severity=Severity.INFO,
                )
            ]
        findings: list[Finding] = []
        try:
            data = json.loads(stdout)
            for item in data.get("results", []):
                sev = (
                    item.get("extra", {})
                    .get("severity", "WARNING")
                    .lower()
                )
                findings.append(
                    Finding(
                        rule=f"semgrep/{item.get('check_id', 'unknown')}",
                        message=item.get("extra", {}).get("message", ""),
                        severity=SEVERITY_MAP.get(sev, Severity.MEDIUM),
                        file_path=item.get("path"),
                        line=item.get("start", {}).get("line"),
                    )
                )
        except json.JSONDecodeError:
            pass
        return findings

    @staticmethod
    def _group_by_lang(ctx: StationContext) -> dict[str, list[str]]:
        ext_map = {
            ".py": "python",
            ".go": "go",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".java": "java",
        }
        by_lang: dict[str, list[str]] = {}
        for cf in ctx.changed_files:
            if cf.status == "deleted":
                continue
            lang = ext_map.get(Path(cf.path).suffix)
            if lang and lang in ctx.languages:
                by_lang.setdefault(lang, []).append(cf.path)
        return by_lang
