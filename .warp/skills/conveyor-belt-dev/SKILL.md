---
name: conveyor-belt-dev
description: >
  Coding standards and development conventions for the conveyor-belt QA pipeline project.
  Use this skill BEFORE writing or editing any code in the conveyor-belt repository.
  Also use this skill after making code changes, to run lint and test validation.
  Trigger whenever working in ~/code/conveyor-belt or when the user mentions
  conveyor-belt, cb pipeline, QA stations, or any of the station names
  (unit_coverage, idiomatic, vulnerability, feature_validation, regression, security).
---

# Conveyor Belt Development Standards

## Pre-flight: Read Before Writing Code

Before generating or editing any Python code in this project, internalize these rules.
They exist because violations were caught in live review — see LESSONS_LEARNT.md for backstory.

## Coding Standards (enforced by ruff)

The project uses `ruff` with rules configured in `pyproject.toml`:
- **Line length**: 100 characters max (E501)
- **Import sorting**: isort-compatible, `from __future__` first (I001)
- **No unused imports** (F401) — remove them, don't comment them out
- **No unused variables** (F841) — if a return value is unused, use `_` or omit assignment
- **Modern Python idioms** (UP series):
  - `TimeoutError` not `asyncio.TimeoutError`
  - `datetime.UTC` not `datetime.timezone.utc`
  - `OSError` not `EnvironmentError`
- **Simplifications** (SIM series):
  - `all(x for x in items)` not for-loop-with-early-return
  - Ternary where appropriate (SIM108)
  - No Yoda conditions — `x == 5` not `5 == x`
- **No ambiguous variable names** (E741) — `label` not `l`, `item` not `I`
- **CamelCase imports**: use full name not acronym — `ElementTree` not `ET` (N817)

## Architecture Conventions

### Station pattern
Every station inherits from `Station` (in `stations/base.py`) and implements:
```python
async def run(self, ctx: StationContext) -> StationResult
```
The `execute()` wrapper adds timing + timeout automatically. Never override `execute()`.

### Subprocess execution
Always use the `_exec()` helper with timeout (default 60s). Never use bare `asyncio.create_subprocess_exec`.
Always check for `rc == 127` (command not found) and `"timed out" in stderr` BEFORE parsing stdout.
Report missing tools as `info`-severity findings — never silently swallow errors.

### TypeScript/Node.js tooling
When running TS linters, resolve the working directory to the nearest parent containing `node_modules/`.
Prefer the project's installed eslint over downloading tools via npx cold-start.

### Config resolution
When `--config` is not specified, look for `conveyor-belt.yaml` in the `--repo` root, not `cwd`.

### Pydantic models
All data classes use Pydantic v2 `BaseModel`. Use `Field(default_factory=...)` for mutable defaults.

### Async patterns
Stations run concurrently via `asyncio.gather`. Never block the event loop with synchronous I/O.

## Post-Edit Checklist

After writing or editing code, ALWAYS run these commands before presenting the result:

1. **Lint**: `poetry run ruff check conveyor_belt/ tests/`
   - If violations found, fix them immediately
   - Do NOT present code that has lint violations
2. **Tests**: `poetry run pytest tests/unit/ -q`
   - All tests must pass
   - If a test fails, fix the code — not the test (unless the test itself is wrong)

If either check fails, fix the issues before telling the user the work is done.

## Project Structure Reference

```
conveyor_belt/
  cli.py              — Click CLI (cb run / cb validate-config)
  config.py           — YAML config schema (Pydantic)
  context.py          — StationContext, ChangedFile, LinearIssue
  models.py           — Finding, StationResult, CoverageRecord, Severity
  orchestrator.py     — Concurrent station runner + gate logic
  agents/             — LLM agents (Anthropic Opus 4.6 / Gemini 3.1 Pro)
    base.py           — BaseAgent with primary/fallback LLM
    feature_agent.py  — Generates feature validation tests from PRDs
    regression_agent.py — Generates regression tests from historical issues
    security_agent.py — Analyzes diffs for security vulnerabilities
  integrations/
    git.py            — PR diff extraction (gh CLI + git)
    linear.py         — Linear GraphQL API client
    snyk.py           — Snyk CLI wrapper (SCA/SAST/container)
  stations/
    base.py           — Abstract Station with timeout
    unit_coverage.py  — Station 1: ≥85% coverage enforcement
    idiomatic.py      — Station 4: Google Style Guide linters
    vulnerability.py  — Station 5: Snyk + OWASP scanning
    feature_validation.py — Station 2: PRD → agent → test generation
    regression.py     — Station 3: Historical issues → regression tests
    security.py       — Station 6: Agent + SAST tools
```
