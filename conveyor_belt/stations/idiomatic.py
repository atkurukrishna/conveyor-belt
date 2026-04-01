"""Station 4 — Idiomatic / Style enforcement (Google Style Guides baseline)."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from conveyor_belt.context import StationContext
from conveyor_belt.models import Finding, Severity, StationResult
from conveyor_belt.stations.base import Station

# File extension → language mapping
EXT_MAP: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",  # lint JS with same TS tooling
    ".java": "java",
    ".go": "go",
}

SEVERITY_MAP: dict[str, Severity] = {
    "error": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "convention": Severity.LOW,
    "refactor": Severity.LOW,
    "info": Severity.INFO,
}


async def _exec(cmd: list[str], cwd: str, timeout: float = 60.0) -> tuple[int, str, str]:
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
        return 1, "", f"Command timed out after {timeout}s: {' '.join(cmd)}"


class IdiomaticStation(Station):
    name = "idiomatic"

    async def run(self, ctx: StationContext) -> StationResult:
        changed = {cf.path for cf in ctx.changed_files if cf.status != "deleted"}
        if not changed:
            return StationResult(
                station_name=self.name, passed=True, summary="No changed files to lint."
            )

        # Group files by language
        by_lang: dict[str, list[str]] = {}
        for fp in changed:
            ext = Path(fp).suffix
            lang = EXT_MAP.get(ext)
            if lang and lang in ctx.languages:
                by_lang.setdefault(lang, []).append(fp)

        findings: list[Finding] = []
        tasks = []
        for lang, files in by_lang.items():
            tasks.append(self._lint(lang, files, ctx.repo_root))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                findings.append(
                    Finding(
                        rule="lint_error",
                        message=str(result),
                        severity=Severity.MEDIUM,
                    )
                )
            else:
                findings.extend(result)

        return StationResult(
            station_name=self.name,
            passed=all(f.severity not in (Severity.CRITICAL, Severity.HIGH) for f in findings),
            summary=(
                f"{len(findings)} style violation(s) across "
                f"{sum(len(v) for v in by_lang.values())} file(s)."
            ),
            findings=findings,
        )

    async def _lint(self, lang: str, files: list[str], repo_root: str) -> list[Finding]:
        dispatch = {
            "python": self._lint_python,
            "typescript": self._lint_typescript,
            "java": self._lint_java,
            "go": self._lint_go,
        }
        fn = dispatch.get(lang)
        if fn is None:
            return []
        findings = await fn(files, repo_root)
        return findings

    # ── Python: ruff + yapf ────────────────────────────────────────────

    async def _lint_python(self, files: list[str], cwd: str) -> list[Finding]:
        findings: list[Finding] = []

        # ruff check (fast, Google-aligned rules)
        rc, stdout, _ = await _exec(
            ["ruff", "check", "--output-format=json", "--select=E,W,F,I,N,UP,B,SIM", *files],
            cwd,
        )
        if stdout.strip():
            try:
                for item in json.loads(stdout):
                    findings.append(
                        Finding(
                            rule=item.get("code", "ruff"),
                            message=item.get("message", ""),
                            severity=Severity.MEDIUM,
                            file_path=item.get("filename"),
                            line=item.get("location", {}).get("row"),
                        )
                    )
            except json.JSONDecodeError:
                pass

        # yapf --style google --diff (formatting check)
        rc, stdout, _ = await _exec(
            ["yapf", "--style=google", "--diff", *files],
            cwd,
        )
        if stdout.strip():
            findings.append(
                Finding(
                    rule="yapf/google-format",
                    message="Files require reformatting per Google Python style.",
                    severity=Severity.LOW,
                )
            )

        return findings

    # ── TypeScript: gts ────────────────────────────────────────────────

    async def _lint_typescript(self, files: list[str], cwd: str) -> list[Finding]:
        findings: list[Finding] = []

        # Prefer the project's own eslint (already installed) over gts
        # Find the nearest directory with node_modules to run from
        lint_cwd, resolved_files = self._resolve_ts_cwd(cwd, files)
        eslint_cmd = self._find_ts_lint_cmd(lint_cwd, resolved_files)
        rc, stdout, stderr = await _exec(eslint_cmd, lint_cwd)

        if rc == 127 or "Command not found" in stderr or "timed out" in stderr:
            findings.append(
                Finding(
                    rule="ts-lint/unavailable",
                    message=stderr.strip(),
                    severity=Severity.INFO,
                )
            )
            return findings

        output = stdout + stderr
        # Try JSON output first (eslint --format json)
        if eslint_cmd and "--format" in eslint_cmd and "json" in eslint_cmd:
            try:
                for entry in json.loads(stdout):
                    for msg in entry.get("messages", []):
                        findings.append(
                            Finding(
                                rule=msg.get("ruleId", "eslint") or "eslint",
                                message=msg.get("message", ""),
                                severity=(
                                    Severity.HIGH if msg.get("severity", 1) >= 2
                                    else Severity.MEDIUM
                                ),
                                file_path=entry.get("filePath"),
                                line=msg.get("line"),
                            )
                        )
                return findings
            except json.JSONDecodeError:
                pass

        # Fallback: parse eslint-style text lines
        for match in re.finditer(
            r"^(.+?):(\d+):\d+:\s+(error|warning)\s+(.+?)\s+(\S+)$", output, re.MULTILINE
        ):
            findings.append(
                Finding(
                    rule=match.group(5),
                    message=match.group(4),
                    severity=SEVERITY_MAP.get(match.group(3), Severity.MEDIUM),
                    file_path=match.group(1),
                    line=int(match.group(2)),
                )
            )
        return findings

    @staticmethod
    def _resolve_ts_cwd(repo_root: str, files: list[str]) -> tuple[str, list[str]]:
        """Find the nearest parent with node_modules and resolve file paths relative to it."""
        # Group by the nearest package.json parent
        for f in files:
            full = Path(repo_root) / f
            for parent in [full.parent, *full.parent.parents]:
                if (parent / "node_modules").exists():
                    resolved = [str((Path(repo_root) / fp).relative_to(parent)) for fp in files]
                    return str(parent), resolved
                if parent == Path(repo_root):
                    break
        # Fallback: use repo root with original paths
        return repo_root, files

    @staticmethod
    def _find_ts_lint_cmd(cwd: str, files: list[str]) -> list[str]:
        """Pick the best available TS/JS linter command for this project."""
        # Check if the project (or a parent with node_modules) has eslint
        for search_dir in [cwd, *[str(p) for p in Path(cwd).parents]]:
            if (Path(search_dir) / "node_modules" / ".bin" / "eslint").exists():
                return [
                    "npx", "eslint", "--format", "json", "--no-error-on-unmatched-pattern",
                    *files,
                ]
            if (Path(search_dir) / "node_modules" / ".bin" / "next").exists():
                # Next.js projects: use `npx eslint` which picks up eslint-config-next
                return [
                    "npx", "eslint", "--format", "json", "--no-error-on-unmatched-pattern",
                    *files,
                ]
        # Fall back to gts
        return ["npx", "gts", "lint", *files]

    # ── Java: google-java-format + checkstyle ──────────────────────────

    async def _lint_java(self, files: list[str], cwd: str) -> list[Finding]:
        findings: list[Finding] = []

        # google-java-format --dry-run --set-exit-if-changed
        rc, stdout, stderr = await _exec(
            ["google-java-format", "--dry-run", "--set-exit-if-changed", *files],
            cwd,
        )
        if rc != 0:
            for line in (stdout + stderr).splitlines():
                if line.strip():
                    findings.append(
                        Finding(
                            rule="google-java-format",
                            message=f"Needs reformatting: {line.strip()}",
                            severity=Severity.LOW,
                            file_path=line.strip(),
                        )
                    )

        # checkstyle with Google checks
        rc, stdout, _ = await _exec(
            [
                "checkstyle",
                "-c", "/google_checks.xml",
                *files,
            ],
            cwd,
        )
        for match in re.finditer(
            r"\[(\w+)\]\s+(.+?):(\d+)(?::\d+)?:\s+(.+)", stdout
        ):
            sev = match.group(1).lower()
            findings.append(
                Finding(
                    rule="checkstyle/" + sev,
                    message=match.group(4),
                    severity=SEVERITY_MAP.get(sev, Severity.MEDIUM),
                    file_path=match.group(2),
                    line=int(match.group(3)),
                )
            )
        return findings

    # ── Go: golangci-lint ──────────────────────────────────────────────

    async def _lint_go(self, files: list[str], cwd: str) -> list[Finding]:
        findings: list[Finding] = []
        # golangci-lint operates on packages, not individual files.
        # Determine unique package dirs from changed files.
        pkg_dirs = list({str(Path(f).parent) for f in files})
        rc, stdout, stderr = await _exec(
            ["golangci-lint", "run", "--out-format=json", *[f"./{d}/..." for d in pkg_dirs]],
            cwd,
        )
        if rc == 127 or "Command not found" in stderr or "timed out" in stderr:
            findings.append(
                Finding(
                    rule="golangci-lint/unavailable",
                    message=stderr.strip(),
                    severity=Severity.INFO,
                )
            )
            return findings
        if stdout.strip():
            try:
                data = json.loads(stdout)
                for issue in data.get("Issues", []):
                    findings.append(
                        Finding(
                            rule=issue.get("FromLinter", "golangci-lint"),
                            message=issue.get("Text", ""),
                            severity=Severity.MEDIUM,
                            file_path=issue.get("Pos", {}).get("Filename"),
                            line=issue.get("Pos", {}).get("Line"),
                        )
                    )
            except json.JSONDecodeError:
                pass
        return findings
