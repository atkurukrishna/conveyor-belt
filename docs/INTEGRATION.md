# Integrating Conveyor Belt with Your CI/CD System

## The Interface

Conveyor Belt is a CLI tool. Every CI/CD integration follows the same pattern:

```
install → set env vars → cb run → check exit code
```

That's the entire contract. If your build system can run a shell command and read its exit code, it can run conveyor-belt.

## CLI Reference

```bash
# PR mode — uses `gh` CLI to fetch diff and PR metadata
cb run --pr <pr_number> --repo /path/to/repo

# Diff mode — uses local git diff (works everywhere, no GitHub dependency)
cb run --diff HEAD~1 --repo /path/to/repo

# Run specific stations only
cb run --diff HEAD~1 --repo . --station idiomatic --station security

# Custom config file
cb run --diff HEAD~1 --repo . --config /path/to/conveyor-belt.yaml
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Gate passed — all stations within policy thresholds |
| 1 | Gate failed — findings exceed configured severity threshold |

### Output

Markdown report to stdout. Capture it to post as a PR comment, store as an artifact, or pipe to any reporting tool.

## Environment Variables

Set these as secrets in your CI system:

| Variable | Required By | Purpose |
|----------|------------|---------|
| `ANTHROPIC_API_KEY` | Stations 2, 3, 6 | Primary LLM for test generation and security analysis |
| `GOOGLE_API_KEY` | Stations 2, 3, 6 | Fallback LLM (Gemini) |
| `LINEAR_API_KEY` | Stations 2, 3 | Fetches issues/PRDs from Linear |
| `SNYK_TOKEN` | Station 5 | Snyk vulnerability scanning (SCA, SAST, container) |

Stations gracefully degrade when keys are missing — they report `info`-level findings instead of failing.

## Configuration

Drop a `conveyor-belt.yaml` in your repo root:

```yaml
project:
  languages: [python, go, typescript, java]  # which languages to check
  linear:
    team_key: ENG                             # Linear team for issue lookups

stations:
  unit_coverage:
    enabled: true
    threshold: 85          # minimum line coverage %
  feature_validation:
    enabled: true
    epic_tags_from_pr: true  # parse [ENG-123] from PR body
  regression:
    enabled: true
    lookback_epics: 20     # how many historical issues to consider
  idiomatic:
    enabled: true
    style_baseline: google
  vulnerability:
    enabled: true
    snyk:
      enabled: true
      severity_threshold: high
  security:
    enabled: true
    block_on: [critical, high]

agent:
  primary:
    provider: anthropic
    model: claude-opus-4.6
  fallback:
    provider: google
    model: gemini-3.1-pro

gate:
  policy: hard_fail        # hard_fail | soft_fail
  allow_override: false
```

Disable any station by setting `enabled: false`. The pipeline only runs what's enabled.

## Adding to a New Build System

### Step-by-step

1. **Install Python 3.11+ and Poetry**
2. **Install conveyor-belt**: `poetry install` (or `pip install .`)
3. **Inject secrets** as environment variables (see table above)
4. **Determine the diff source**:
   - If your CI has PR numbers: use `--pr <number>`
   - Otherwise: use `--diff HEAD~1` (or `--diff origin/main...HEAD`)
5. **Run**: `cb run --pr <N> --repo .`
6. **Check exit code**: 0 = pass, 1 = fail
7. **Optionally capture stdout** and post as a comment/artifact

### Minimal example (any shell-based CI)

```bash
#!/bin/bash
set -euo pipefail

# 1. Install
pip install poetry
poetry install --no-interaction

# 2. Run
poetry run cb run --diff HEAD~1 --repo .
# Exit code 0 = pass, 1 = fail — CI handles the rest
```

That's it. Everything below is convenience for specific platforms.

---

## Pre-built Adapters

Ready-to-use configs live in `ci_adapters/`. Copy the relevant one into your repo.

### GitHub Actions

Copy `ci_adapters/github_actions/conveyor-belt.yml` to `.github/workflows/`:

```bash
cp ci_adapters/github_actions/conveyor-belt.yml .github/workflows/conveyor-belt.yml
```

**What it does:**
- Triggers on `pull_request` to `main`/`master`
- Runs `cb run --pr <number>`
- Posts the Markdown report as a PR comment

**Secrets needed:** `SNYK_TOKEN`, `LINEAR_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`

### Jenkins

Copy `ci_adapters/jenkins/Jenkinsfile` to your repo root (or reference it in your Jenkins job config).

**What it does:**
- Declarative pipeline with a `Conveyor Belt QA` stage
- Auto-detects PR number from `CHANGE_ID` (Multibranch Pipeline)
- Falls back to `--diff HEAD~1` for branch builds
- Archives the report as a build artifact

**Credentials needed:** Configure in Jenkins credentials store as `snyk-token`, `linear-api-key`, `anthropic-api-key`, `google-api-key`.

### CircleCI

Copy `ci_adapters/circleci/config.yml` to `.circleci/`:

```bash
mkdir -p .circleci
cp ci_adapters/circleci/config.yml .circleci/config.yml
```

**What it does:**
- Caches Poetry dependencies between runs
- Extracts PR number from `CIRCLE_PULL_REQUEST`
- Stores the report as a build artifact

**Secrets needed:** Create a context called `conveyor-belt-secrets` with the env vars above.

### Bazel

Load the rule in your `BUILD` file:

```python
load("//ci_adapters/bazel:defs.bzl", "cb_qa_test")

cb_qa_test(
    name = "qa_check",
    diff_ref = "HEAD~1",
    stations = ["idiomatic", "unit_coverage"],
)
```

Then: `bazel test //path/to:qa_check`

---

## Customizing for Your System

### GitLab CI

```yaml
conveyor-belt:
  image: python:3.11
  stage: test
  script:
    - pip install poetry
    - poetry install --no-interaction
    - poetry run cb run --diff origin/$CI_MERGE_REQUEST_TARGET_BRANCH_NAME...HEAD --repo .
  only:
    - merge_requests
  variables:
    SNYK_TOKEN: $SNYK_TOKEN
    LINEAR_API_KEY: $LINEAR_API_KEY
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
    GOOGLE_API_KEY: $GOOGLE_API_KEY
```

### Azure DevOps

```yaml
trigger: none
pr:
  branches:
    include: [main]

pool:
  vmImage: ubuntu-latest

steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.11'
  - script: |
      pip install poetry
      poetry install --no-interaction
      poetry run cb run --diff HEAD~1 --repo .
    env:
      SNYK_TOKEN: $(SNYK_TOKEN)
      LINEAR_API_KEY: $(LINEAR_API_KEY)
      ANTHROPIC_API_KEY: $(ANTHROPIC_API_KEY)
      GOOGLE_API_KEY: $(GOOGLE_API_KEY)
```

### Buildkite

```yaml
steps:
  - label: ":conveyor_belt: QA Pipeline"
    command: |
      pip install poetry
      poetry install --no-interaction
      poetry run cb run --diff HEAD~1 --repo .
    env:
      SNYK_TOKEN: "${SNYK_TOKEN}"
      LINEAR_API_KEY: "${LINEAR_API_KEY}"
      ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY}"
      GOOGLE_API_KEY: "${GOOGLE_API_KEY}"
    timeout_in_minutes: 15
```

---

## Troubleshooting

**Pipeline hangs**: Stations have a 300s timeout. If a station consistently times out, disable it in `conveyor-belt.yaml` or check if the target repo's tests require external services (databases, etc.).

**"Command not found" findings**: These are `info`-level and don't block the gate. They mean an external tool (snyk, golangci-lint, bandit, etc.) isn't installed in the CI environment. Install it or disable the station.

**Coverage below threshold**: The `unit_coverage` station runs the target repo's test suite. If coverage is low, either write more tests or lower `stations.unit_coverage.threshold` in the config.

**LLM agent failures**: Stations 2, 3, and 6 need `ANTHROPIC_API_KEY`. If both primary and fallback LLMs fail, those stations report an error finding but don't crash the pipeline.
