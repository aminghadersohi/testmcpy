#!/usr/bin/env bash
# mypy ratchet: the codebase has a known backlog of type errors, so mypy
# can't be a hard gate yet. Instead, fail CI only when the error count
# GROWS past the baseline below. When you fix type errors, lower the
# baseline to lock in the progress.
#
# The baseline is calibrated against the CI environment (ubuntu,
# pip install ".[dev,server]"); local counts can differ slightly because
# installed extras change what mypy can resolve.
set -uo pipefail

MAX_ERRORS=599

cd "$(dirname "$0")/.."

output=$(mypy testmcpy 2>&1 || true)
summary=$(echo "$output" | tail -1)

count=$(echo "$summary" | grep -oE 'Found [0-9]+ error' | grep -oE '[0-9]+' || echo "")
if [ -z "$count" ]; then
    if echo "$summary" | grep -q "no issues found"; then
        count=0
    else
        echo "Could not parse mypy output:"
        echo "$output" | tail -20
        exit 1
    fi
fi

delta=$((count - MAX_ERRORS))
echo "mypy errors: $count (baseline: $MAX_ERRORS, delta: $delta)"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
        echo "### mypy ratchet"
        echo ""
        echo "| errors | baseline | delta |"
        echo "|--------|----------|-------|"
        echo "| $count | $MAX_ERRORS | $delta |"
    } >> "$GITHUB_STEP_SUMMARY"
fi

if [ "$count" -gt "$MAX_ERRORS" ]; then
    echo ""
    echo "FAIL: mypy error count grew from $MAX_ERRORS to $count."
    echo "Sample of current errors (the new one(s) are somewhere in the full"
    echo "set — run 'mypy testmcpy' locally and diff against main to find them):"
    echo "$output" | grep "error:" | tail -20
    echo ""
    echo "Fix the new type errors (or, if pre-existing errors surfaced,"
    echo "raise MAX_ERRORS in scripts/check_mypy_ratchet.sh with a comment)."
    exit 1
fi

if [ "$count" -lt "$MAX_ERRORS" ]; then
    echo "NOTE: error count dropped below baseline — consider lowering"
    echo "MAX_ERRORS to $count in scripts/check_mypy_ratchet.sh to lock it in."
fi
