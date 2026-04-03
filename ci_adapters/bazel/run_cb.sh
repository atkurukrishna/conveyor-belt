#!/usr/bin/env bash
# Bazel test wrapper for conveyor-belt QA pipeline.
# Invoked by the cb_qa_test rule in defs.bzl.

set -euo pipefail

DIFF_REF="${CB_DIFF_REF:-HEAD~1}"
REPO="${CB_REPO:-.}"
STATIONS="${CB_STATIONS:-}"

CB_ARGS="--diff ${DIFF_REF} --repo ${REPO}"

if [[ -n "$STATIONS" ]]; then
    for station in $STATIONS; do
        CB_ARGS="${CB_ARGS} --station ${station}"
    done
fi

# Ensure poetry + conveyor-belt are installed
if ! command -v poetry &>/dev/null; then
    pip install poetry
fi
poetry install --no-interaction --quiet

# Run the pipeline
eval "poetry run cb run ${CB_ARGS}"
