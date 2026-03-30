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
