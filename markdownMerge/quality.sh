#!/usr/bin/env bash
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

mkdir -p logs

TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
LOG_FILE="logs/quality_${TIMESTAMP}.log"
STATUS=0

run_check() {
    local title="$1"
    shift

    printf '\n============================================================\n' | tee -a "$LOG_FILE"
    printf '%s\n' "$title" | tee -a "$LOG_FILE"
    printf 'Command: %q ' "$@" | tee -a "$LOG_FILE"
    printf '\n============================================================\n' | tee -a "$LOG_FILE"

    if "$@" 2>&1 | tee -a "$LOG_FILE"; then
        printf '[PASS] %s\n' "$title" | tee -a "$LOG_FILE"
    else
        printf '[FAIL] %s\n' "$title" | tee -a "$LOG_FILE"
        STATUS=1
    fi
}

run_check "Ruff formatting verification" uv run ruff format --check .
run_check "Ruff lint verification" uv run ruff check .
run_check "Mypy strict type checking" uv run mypy
run_check "Pytest and coverage" uv run --group dev python -m pytest
run_check "CLI help smoke test" uv run mdmerge --help
run_check "Direct entry-point smoke test" uv run python main.py --help

printf '\nQuality log: %s\n' "$PROJECT_ROOT/$LOG_FILE"

exit "$STATUS"
