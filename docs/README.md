# Conveyor Belt

Agentic conveyor-belt QA pipeline for code check-ins.

[![CI](https://github.com/atkurukrishna/conveyor-belt/actions/workflows/conveyor-belt.yml/badge.svg)](https://github.com/atkurukrishna/conveyor-belt/actions)

## Quick Start

```bash
# Install
poetry install

# Run against a PR
cb run --pr 42

# Run against a local diff
cb run --diff HEAD~1

# Validate config
cb validate-config
```
