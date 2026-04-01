.PHONY: lint test verify selfcheck

# ── Individual checks ──────────────────────────────────────────────────

lint:
	poetry run ruff check conveyor_belt/ tests/

test:
	poetry run pytest tests/unit/ -q

# ── Full verification (lint + tests) ──────────────────────────────────

verify: lint test
	@echo "✅ All checks passed."

# ── Dogfood: run conveyor-belt on itself ──────────────────────────────

selfcheck:
	poetry run cb run --diff HEAD~1 --repo . --station idiomatic
