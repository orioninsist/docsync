#!/usr/bin/env bash
set -euo pipefail

printf '\n===== ruff check =====\n'
ruff check .

printf '\n===== ruff format check =====\n'
ruff format --check .

printf '\n===== mypy =====\n'
mypy .

printf '\n===== pyright =====\n'
pyright .

printf '\n===== pytest =====\n'
set +e
python -m pytest -q
pytest_status=$?
set -e

if [[ "$pytest_status" -eq 5 ]]; then
    printf '\npytest: no tests collected; treating as pass for empty-test-safe quality gate.\n'
elif [[ "$pytest_status" -ne 0 ]]; then
    printf '\npytest failed with exit code %s.\n' "$pytest_status"
    exit "$pytest_status"
fi

printf '\n===== quality gate passed =====\n'
