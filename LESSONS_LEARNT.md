# Lessons Learnt

Issues discovered during live testing against `weight-wise` (Go + TypeScript monorepo) that required iteration on the initial approach.

---

## 1. Config auto-discovery was broken

**Problem:** The CLI loaded `conveyor-belt.yaml` from `Path.cwd()` (where the user runs the command), not from the target `--repo` path. Running `cb run --repo /path/to/weight-wise` from the conveyor-belt project directory ignored the config file in weight-wise entirely, falling back to defaults (all 4 languages, `hard_fail` gate).

**Symptom:** The pipeline reported `languages: java, go, typescript, python` and `hard_fail` policy even though the weight-wise config specified `[go, typescript]` and `soft_fail`.

**Fix:** When `--config` is not explicitly passed, the CLI now checks `{repo_root}/conveyor-belt.yaml` before falling back to cwd.

**Lesson:** CLI tools that operate on a target directory must resolve config relative to the target, not the invocation directory.

---

## 2. No subprocess timeouts caused full pipeline hangs

**Problem:** The initial implementation used bare `asyncio.create_subprocess_exec` with no timeout. When `go test` hung (waiting for a database), the entire pipeline hung indefinitely. Similarly, `npx gts lint` hung for 5+ minutes trying to download gts on first use.

**Symptom:** `cb run` would never return. Had to Ctrl-C.

**Fix:** Added timeouts at two levels:
- **Per-subprocess:** 60s timeout in `_exec()` with `asyncio.wait_for()`, killing the process on timeout
- **Per-station:** 300s timeout in `Station.execute()` wrapping the entire `run()` call

**Lesson:** Any pipeline that shells out to external tools _must_ have timeouts at every layer. External tools can hang for countless reasons (missing services, network, interactive prompts). Default to strict timeouts and let users override.

---

## 3. Command-not-found errors were silently swallowed

**Problem:** When `golangci-lint` wasn't installed, `_exec()` returned `(127, "", "Command not found: golangci-lint")` via the `FileNotFoundError` catch. But the linter methods (e.g. `_lint_go`) only inspected `stdout` for JSON output. Since stdout was empty, `json.loads("")` raised `JSONDecodeError`, which was caught with `pass` — so the error vanished completely.

**Symptom:** Station reported "0 style violations" even though it never actually ran the linter.

**Fix:** Each linter method now checks for `rc == 127` or error keywords in `stderr` _before_ attempting to parse stdout. Missing tools are reported as `info`-severity findings (e.g. `golangci-lint/unavailable`) so users can see exactly what happened.

**Lesson:** Silent failure is the worst kind of failure in a QA pipeline. Every external tool invocation must have explicit error reporting. A pipeline that reports "all clean" when it didn't actually run any checks is worse than no pipeline at all.

---

## 4. TypeScript linter ran from wrong working directory

**Problem:** `npx gts lint frontend/web/app/page.tsx` was executed from the repo root. But `node_modules` (containing eslint, gts, etc.) lives in `frontend/web/`. `npx` couldn't find the local eslint installation, so it tried to download gts globally — resulting in a 60s timeout.

**Symptom:** TypeScript linting always timed out even though eslint was already installed in the project.

**Fix:** Added `_resolve_ts_cwd()` which walks up from each TS file's directory to find the nearest parent containing `node_modules`, then runs the linter from that directory with file paths resolved relative to it.

**Lesson:** Monorepos with multiple package.json files (e.g. `frontend/web/`, `frontend/mobile/`) need linters to run from the correct sub-project root. Never assume the repo root is the right cwd for Node.js tooling.

---

## 5. npx cold-start is too slow for CI-style usage

**Problem:** The initial approach used `npx gts lint` for TypeScript. On first run, npx downloads gts + all its dependencies, which took 60+ seconds and hit the timeout. Even subsequent runs were slower than using the project's already-installed eslint.

**Symptom:** TypeScript linting consistently timed out at 60s.

**Fix:** Added `_find_ts_lint_cmd()` which checks if the project already has eslint in `node_modules/.bin/`. If found, it uses `npx eslint --format json` directly (instant startup). Falls back to `npx gts lint` only if no local eslint exists.

**Lesson:** Prefer using a project's existing toolchain over installing new tools at runtime. The project has already made linter choices — respect them and use what's there. This also gives more accurate results since the project's eslint config reflects their actual style preferences.

---

## 6. `go test` hangs without backing services

**Problem:** The weight-wise backend's integration tests require a PostgreSQL database. Running `go test ./...` without the database causes the test runner to hang on connection attempts rather than failing fast.

**Symptom:** `unit_coverage` station timed out at 300s.

**Impact:** This is not a bug in conveyor-belt, but it exposed a design gap — there's no way to configure per-language test commands or skip languages where the runtime isn't available.

**Future improvement:** Allow config to override test commands per-language, and/or add a pre-flight check that verifies required services are available before running tests.

---

## 7. Pre-commit hook allowed new code without tests

**Problem:** Stations 2, 3, and 6 were added (feature_validation.py, regression.py, security.py) along with orchestrator registration, staged, and committed — all without any corresponding test files. The pre-commit hook passed because:
- `ruff check` — the new code had no lint violations
- `pytest` — the 46 existing tests still passed (new code didn't break anything)
- `cb run --station idiomatic` — only checks style, not test existence

None of these checks enforce that new modules have test coverage.

**Symptom:** Commit `ba495af` went through with 3 new station files and 0 tests for them. The pipeline that's supposed to enforce quality on itself had a blind spot.

**Fix:** Added a step to the pre-commit hook that scans staged *new* files (via `git diff --cached --diff-filter=A`) under `conveyor_belt/stations/`, `agents/`, and `integrations/`, and checks that at least one test file under `tests/` references the module name. If not, the commit is blocked.

**Lesson:** Lint + passing tests + style checks are necessary but not sufficient. A QA pipeline must also enforce that new code *has* tests — otherwise it's validating the old code, not the new code. This is the "test coverage for the test coverage tool" problem: who watches the watchers?

---

## 8. Grep-based test existence check had false negatives

**Iteration count: 2nd fix to the same pre-commit check (lesson 7 → 7a → 8)**

**Problem:** The first fix for lesson 7 used `grep -l "$basename"` to check if a test file references a module. This matched on *any substring*. The module `security` appeared inside `test_station_vulnerability.py` in Snyk SARIF test data (strings like `"go/HardcodedPassword"`), so `security.py` falsely appeared to have test coverage.

**Symptom:** Pre-commit caught `feature_validation.py` and `regression.py` but let `security.py` through.

**Fix:** Tightened the grep to `grep -rl "import.*${basename}\|from.*${basename}"` so it matches import statements, not arbitrary substrings.

**Lesson:** When checking for test coverage by grepping filenames, match on the *import pattern* (`from X import` / `import X`), not just the module name as a substring. Substring matching in a codebase full of domain terms ("security", "auth", "test") will always produce false matches.

---

## 9. "Test file exists" check is not the same as "code is tested"

**Iteration count: 3rd approach to the same problem (grep existence → grep import → actual coverage)**

**Problem:** Even after fixing the grep (lesson 8), the check only verified that a test file *imports* the module — not that the tests actually *exercise* the code. Running `pytest --cov` revealed 39% overall coverage. Modules like `cli.py`, `orchestrator.py`, `integrations/git.py`, and all three agent files had 0% line coverage despite the project having 46 passing tests.

**Symptom:** `make coverage` showed the real picture:
- `feature_validation.py`: 0%
- `regression.py`: 0%
- `security.py`: 0%
- `agents/base.py`: 0%
- `cli.py`: 0%
- `orchestrator.py`: 0%
- Overall: 39%

**Fix:** Replaced the grep-based check with `pytest --cov=conveyor_belt --cov-fail-under=85` in the pre-commit hook. This runs actual tests and measures real line coverage. The commit is blocked if overall coverage drops below 85%.

**Lesson:** There are three levels of "has tests", each progressively more honest:
1. **File exists** — a test file with the right name exists (meaningless)
2. **Import exists** — a test file imports the module (slightly better, still meaningless)
3. **Lines are covered** — pytest-cov measures which lines actually execute during tests (the only one that matters)

Don't settle for proxy metrics when you can measure the real thing. We built a coverage station (Station 1) that does exactly this for target repos — we just weren't using it on ourselves.
