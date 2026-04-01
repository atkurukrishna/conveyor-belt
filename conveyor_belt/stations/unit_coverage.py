"""Station 1 — Unit Test Coverage (≥ configurable threshold, default 85%)."""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from conveyor_belt.context import StationContext
from conveyor_belt.models import CoverageRecord, Finding, Severity, StationResult
from conveyor_belt.stations.base import Station


class UnitCoverageStation(Station):
    name = "unit_coverage"

    # ── language → (test command, coverage report path) ────────────────

    RUNNERS: dict[str, dict] = {
        "python": {
            "cmd": ["python", "-m", "pytest", "--cov", "--cov-report=xml:coverage.xml", "-q"],
            "report": "coverage.xml",
            "parser": "_parse_cobertura",
        },
        "typescript": {
            "cmd": ["npx", "c8", "--reporter=cobertura", "npx", "vitest", "run"],
            "report": "coverage/cobertura-coverage.xml",
            "parser": "_parse_cobertura",
        },
        "java": {
            # Assumes Maven with JaCoCo plugin configured in the target repo.
            "cmd": ["mvn", "-q", "test", "jacoco:report"],
            "report": "target/site/jacoco/jacoco.xml",
            "parser": "_parse_jacoco",
        },
        "go": {
            "cmd": ["go", "test", "-coverprofile=coverage.out", "./..."],
            "report": "coverage.out",
            "parser": "_parse_go_cover",
        },
    }

    async def run(self, ctx: StationContext) -> StationResult:
        threshold = self.config.stations.unit_coverage.threshold
        all_records: list[CoverageRecord] = []
        findings: list[Finding] = []
        errors: list[str] = []

        for lang in ctx.languages:
            runner = self.RUNNERS.get(lang)
            if runner is None:
                continue

            report_path = Path(ctx.repo_root) / runner["report"]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *runner["cmd"],
                    cwd=ctx.repo_root,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _stdout, stderr = await proc.communicate()

                if not report_path.exists():
                    errors.append(f"{lang}: coverage report not found at {report_path}")
                    continue

                parser_fn = getattr(self, runner["parser"])
                records = parser_fn(report_path)
                all_records.extend(records)
            except FileNotFoundError:
                errors.append(f"{lang}: test runner not found ({runner['cmd'][0]})")
            except Exception as exc:
                errors.append(f"{lang}: {exc}")

        # Filter to changed files only
        changed_paths = {cf.path for cf in ctx.changed_files}
        relevant = [r for r in all_records if r.file_path in changed_paths] or all_records

        failing = [r for r in relevant if r.percent < threshold]
        for rec in failing:
            findings.append(
                Finding(
                    rule="coverage_below_threshold",
                    message=f"{rec.file_path}: {rec.percent}% < {threshold}% threshold",
                    severity=Severity.HIGH,
                    file_path=rec.file_path,
                )
            )

        for err in errors:
            findings.append(
                Finding(rule="coverage_error", message=err, severity=Severity.MEDIUM)
            )

        overall = (
            round(
                sum(r.lines_covered for r in relevant)
                / max(sum(r.lines_total for r in relevant), 1)
                * 100,
                2,
            )
            if relevant
            else 0.0
        )

        return StationResult(
            station_name=self.name,
            passed=len(failing) == 0 and len(errors) == 0,
            summary=f"Overall coverage: {overall}% (threshold: {threshold}%)",
            findings=findings,
            coverage=all_records,
        )

    # ── parsers ────────────────────────────────────────────────────────

    @staticmethod
    def _parse_cobertura(path: Path) -> list[CoverageRecord]:
        """Parse Cobertura XML (pytest-cov, c8, istanbul)."""
        tree = ElementTree.parse(path)
        records: list[CoverageRecord] = []
        for pkg in tree.iter("package"):
            for cls in pkg.iter("class"):
                filename = cls.get("filename", "")
                lines = cls.findall(".//line")
                total = len(lines)
                covered = sum(1 for ln in lines if int(ln.get("hits", "0")) > 0)
                records.append(
                    CoverageRecord(file_path=filename, lines_total=total, lines_covered=covered)
                )
        return records

    @staticmethod
    def _parse_jacoco(path: Path) -> list[CoverageRecord]:
        """Parse JaCoCo XML report."""
        tree = ElementTree.parse(path)
        records: list[CoverageRecord] = []
        for pkg in tree.iter("package"):
            pkg_name = pkg.get("name", "").replace("/", ".")
            for src in pkg.iter("sourcefile"):
                filename = f"{pkg_name}/{src.get('name', '')}"
                missed = covered = 0
                for counter in src.iter("counter"):
                    if counter.get("type") == "LINE":
                        missed = int(counter.get("missed", "0"))
                        covered = int(counter.get("covered", "0"))
                records.append(
                    CoverageRecord(
                        file_path=filename,
                        lines_total=missed + covered,
                        lines_covered=covered,
                    )
                )
        return records

    @staticmethod
    def _parse_go_cover(path: Path) -> list[CoverageRecord]:
        """Parse Go coverage.out profile."""
        file_stats: dict[str, dict[str, int]] = {}
        with open(path) as f:
            for line in f:
                if line.startswith("mode:"):
                    continue
                parts = line.strip().split()
                if len(parts) < 3:
                    continue
                # format: file:startLine.col,endLine.col numStatements count
                file_part = parts[0].split(":")[0]
                num_stmts = int(parts[1])
                count = int(parts[2])
                if file_part not in file_stats:
                    file_stats[file_part] = {"total": 0, "covered": 0}
                file_stats[file_part]["total"] += num_stmts
                if count > 0:
                    file_stats[file_part]["covered"] += num_stmts
        return [
            CoverageRecord(file_path=fp, lines_total=s["total"], lines_covered=s["covered"])
            for fp, s in file_stats.items()
        ]
