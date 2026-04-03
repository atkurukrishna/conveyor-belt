.PHONY: lint test coverage verify selfcheck

# ── Individual checks ──────────────────────────────────────────────────────

lint:
	poetry run ruff check conveyor_belt/ tests/

test:
	poetry run pytest tests/unit/ -q

coverage:
	poetry run pytest tests/unit/ -q \
		--cov=conveyor_belt --cov-report=term-missing

# ── Full verification (lint + tests + coverage) ─────────────────────────────

verify: lint
	poetry run pytest tests/unit/ -q \
		--cov=conveyor_belt --cov-report=term-missing --cov-fail-under=85
	@echo "✅ All checks passed."

# ── Dogfood: run conveyor-belt on itself ──────────────────────────────────

selfcheck:
	poetry run cb run --diff HEAD~1 --repo . --station idiomatic
