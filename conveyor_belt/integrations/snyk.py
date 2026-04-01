"""Snyk CLI wrapper — SCA, SAST, and container scanning."""

from __future__ import annotations

import asyncio
import json

from conveyor_belt.models import Finding, Severity

SEVERITY_MAP = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "low": Severity.LOW,
}


async def _exec(cmd: list[str], cwd: str, timeout: float = 120.0) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, stdout.decode(), stderr.decode()
    except FileNotFoundError:
        return 127, "", f"Command not found: {cmd[0]}"
    except TimeoutError:
        proc.kill()
        return 1, "", f"Command timed out after {timeout}s"


async def snyk_test(repo_root: str, severity_threshold: str = "high") -> list[Finding]:
    """Run `snyk test` — dependency/SCA vulnerability scan."""
    rc, stdout, stderr = await _exec(
        ["snyk", "test", "--json", f"--severity-threshold={severity_threshold}"],
        cwd=repo_root,
    )
    if rc == 127:
        return [Finding(rule="snyk/unavailable", message=stderr.strip(), severity=Severity.INFO)]
    return _parse_snyk_json(stdout, source="snyk-opensource")


async def snyk_code_test(repo_root: str, severity_threshold: str = "high") -> list[Finding]:
    """Run `snyk code test` — static analysis / SAST."""
    rc, stdout, stderr = await _exec(
        ["snyk", "code", "test", "--json", f"--severity-threshold={severity_threshold}"],
        cwd=repo_root,
    )
    if rc == 127:
        return [Finding(rule="snyk/unavailable", message=stderr.strip(), severity=Severity.INFO)]
    return _parse_snyk_code_json(stdout)


async def snyk_container_test(
    repo_root: str, image: str, severity_threshold: str = "high"
) -> list[Finding]:
    """Run `snyk container test` — container image scanning."""
    rc, stdout, stderr = await _exec(
        [
            "snyk", "container", "test", image,
            "--json", f"--severity-threshold={severity_threshold}",
        ],
        cwd=repo_root,
    )
    if rc == 127:
        return [Finding(rule="snyk/unavailable", message=stderr.strip(), severity=Severity.INFO)]
    return _parse_snyk_json(stdout, source="snyk-container")


# ── Parsers ────────────────────────────────────────────────────────────


def _parse_snyk_json(raw: str, source: str) -> list[Finding]:
    """Parse `snyk test --json` output."""
    findings: list[Finding] = []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return findings

    vulns = data.get("vulnerabilities", [])
    for v in vulns:
        sev_str = v.get("severity", "medium").lower()
        findings.append(
            Finding(
                rule=f"{source}/{v.get('id', 'unknown')}",
                message=v.get("title", v.get("description", "")),
                severity=SEVERITY_MAP.get(sev_str, Severity.MEDIUM),
                file_path=v.get("from", [None])[0] if v.get("from") else None,
                cve_id=_first_cve(v.get("identifiers", {})),
                cwe_id=_first_cwe(v.get("identifiers", {})),
                remediation=v.get("fixedIn", [None])[0] if v.get("fixedIn") else None,
            )
        )
    return findings


def _parse_snyk_code_json(raw: str) -> list[Finding]:
    """Parse `snyk code test --json` output."""
    findings: list[Finding] = []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return findings

    runs = data.get("runs", [])
    for run in runs:
        for result in run.get("results", []):
            sev_str = result.get("level", "warning")
            sev_map = {"error": Severity.HIGH, "warning": Severity.MEDIUM, "note": Severity.LOW}
            locations = result.get("locations", [])
            file_path = None
            line = None
            if locations:
                phys = locations[0].get("physicalLocation", {})
                file_path = phys.get("artifactLocation", {}).get("uri")
                line = phys.get("region", {}).get("startLine")

            findings.append(
                Finding(
                    rule=f"snyk-code/{result.get('ruleId', 'unknown')}",
                    message=result.get("message", {}).get("text", ""),
                    severity=sev_map.get(sev_str, Severity.MEDIUM),
                    file_path=file_path,
                    line=line,
                    cwe_id=_extract_cwe_from_rule(result.get("ruleId", "")),
                )
            )
    return findings


def _first_cve(identifiers: dict) -> str | None:
    cves = identifiers.get("CVE", [])
    return cves[0] if cves else None


def _first_cwe(identifiers: dict) -> str | None:
    cwes = identifiers.get("CWE", [])
    return cwes[0] if cwes else None


def _extract_cwe_from_rule(rule_id: str) -> str | None:
    """Snyk code ruleIds sometimes embed CWE, e.g. 'python/SqlInjection'."""
    return None  # Snyk code doesn't embed CWE in ruleId; requires lookup
