# Conveyor Belt

Agentic conveyor-belt QA pipeline for code check-ins.

[![CI](https://github.com/atkurukrishna/conveyor-belt/actions/workflows/conveyor-belt.yml/badge.svg)](https://github.com/atkurukrishna/conveyor-belt/actions)

Conveyor Belt is a multi-language CLI QA pipeline designed to evaluate your code quality and security against a robust set of "stations". Combining traditional linting and security scanning with powerful LLM agents, it checks test coverage, enforces language-specific styles, generates feature and regression tests derived from tools like Linear, and executes deep vulnerability analysis.

## Features & QA Stations
Each pipeline step is a modular "station":
- **Station 1 (Unit Coverage)**: Enforces ≥85% test coverage directly atop your project's test suite.
- **Station 2 (Feature Validation)**: Fetches PRDs/Issues from your issue tracker (e.g., Linear) and uses an agent to validate the implementation.
- **Station 3 (Regression)**: Analyzes historical issues and dynamically tests that the new code has not broken existing functionality.
- **Station 4 (Idiomatic Guidelines)**: Runs standard style suite linters (e.g. Google code style checks) for various languages.
- **Station 5 (Vulnerability)**: Static Application Security Testing (SAST) and container vulnerability scanning using Snyk and OWASP.
- **Station 6 (Agentic Security)**: LLM-powered review specifically assessing patches for logical security vulnerabilities.

---

## 🚀 Quick Start (Users)

### 1. Installation

Requires Python 3.11+.

```bash
git clone https://github.com/atkurukrishna/conveyor-belt.git
cd conveyor-belt
pip install poetry
poetry install
```

### 2. Environment Variables
Conveyor Belt heavily relies on external services for a robust QA pipeline. Set these locally or in your CI secrets:
- `ANTHROPIC_API_KEY`: Primary LLM integration for test generation and security analysis (Stations 2, 3, 6).
- `GOOGLE_API_KEY`: Fallback LLM (Gemini).
- `LINEAR_API_KEY`: Required for fetching contextual issues/PRDs from Linear (Stations 2, 3).
- `SNYK_TOKEN`: Used for vulnerability scanning integration (Station 5).

> Missing keys will typically gracefully degrade into `info`-severity findings rather than blocking the pipeline.

### 3. Usage & Configuration

Drop a YAML config file into your target repository root as `conveyor-belt.yaml`.

```yaml
project:
  languages: [python, go, typescript, java]
  linear:
    team_key: ENG

stations:
  unit_coverage:
    enabled: true
    threshold: 85
  idiomatic:
    enabled: true
    style_baseline: google

agent:
  primary:
    provider: anthropic
    model: claude-opus-4.6

gate:
  policy: hard_fail        # hard_fail | soft_fail
```

**Commands:**
```bash
# Run against a GitHub PR
cb run --pr 42 --repo /path/to/repo

# Run against a local git diff
cb run --diff HEAD~1 --repo /path/to/repo

# Run only specific stations
cb run --diff HEAD~1 --repo . --station idiomatic --station security

# Validate your yaml config
cb validate-config
```

### 4. CI/CD Integration
Conveyor Belt is made for CI systems. Your CI essentially executes `cb run` and parses the output or `echo $?`. Pre-built adapters can be found under `ci_adapters/` for GitHub Actions, Jenkins, CircleCI, and Bazel rules. Read [INTEGRATION.md](docs/INTEGRATION.md) for deeper instructions.

---

## 🛠️ Contributing & Development (Developers)

We welcome PRs to expand the capability of Conveyor Belt! When developing, there are essential project idioms and code standards you must abide by.

### Prerequisites & Getting Started
```bash
poetry install
poetry shell
```

### Adding or Modifying Stations
- **Station Base Class:** Every station inherits from `Station` (located in `stations/base.py`). 
- **The Execution Wrapper:** Implement the async logic explicitly in `async def run(self, ctx: StationContext) -> StationResult`. Do NOT override the `execute()` method; it strictly controls timing and timeouts (default 300s).
- **Subprocess Utilities:** Always execute shell and system processes using the `_exec()` helper method. Bare `asyncio.create_subprocess_exec` ignores safety bounds and can cause full pipeline hangs if a subprocess (like network I/O or `go test` without a DB) stalls.

```python
# A conceptual example of a Station's run method
from conveyor_belt.stations.base import Station
from conveyor_belt.context import StationContext
from conveyor_belt.models import StationResult

class CustomStation(Station):
    async def run(self, ctx: StationContext) -> StationResult:
        # Perform testing logic...
        return StationResult(passed=True, findings=[])
```

### Error Tracking and Silent Bugs
The rule is simple: **Silent failure is the worst kind of failure in a QA pipeline.**
- Before scanning linters and tools (TS `eslint`, `go test`, `snyk`), capture tool-not-found errors (`rc == 127` or `"command not found"`).
- Surface tool absences or timeouts as `info`-level findings instead of silently suppressing them and giving a false clean pass. 

### Architecture Guidelines
- **Pydantic**: Utilize Pydantic `v2` `BaseModel`. For mutable defaults, use `Field(default_factory=...)`.
- **Asynchronous Execution:** Ensure no synchronous heavy I/O operations block the core `asyncio` event loop.

### Testing Checklist
For tests, execute:
```bash
poetry run pytest tests/unit/ -q --cov=conveyor_belt --cov-fail-under=85
```
- A strict `< 85%` coverage triggers a CI gate drop. Adding new logic dictates bringing up line coverage alongside it.
- **Gotcha alert (Deferred Imports):** Sometimes files will lazily import dependencies within the scope of a function (e.g. `langchain_anthropic`). To mock this correctly for tests, ensure you are patching them directly at the **source module**, NOT at their use.
    - _Incorrect_: `patch("conveyor_belt.agents.base.ChatAnthropic")`
    - _Correct_: `patch("langchain_anthropic.ChatAnthropic")`

### Linting Standard Checklist
This repository strictly relies on `ruff` logic defined in the `pyproject.toml`.

```bash
poetry run ruff check conveyor_belt/ tests/
# Apply autobot suggestions
poetry run ruff check --fix conveyor_belt/ tests/
```
_Common violations:_
- **Unsorted Imports (I001):** The #1 most recurring lint failure during dev check-in. Rely heavily on `--fix` prior to your commits.
- **Unused variables (F841) & Imports (F401):** Remove unused pieces immediately, do not leave them hanging.
- **Modern Python conventions:** Favor `datetime.UTC`, `OSError`, and `TimeoutError`.
