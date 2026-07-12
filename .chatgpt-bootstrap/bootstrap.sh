#!/usr/bin/env bash
set -euo pipefail

echo "===== UV ====="
command -v uv || true
uv --version 2>/dev/null || true

echo
echo "===== PYTHON ====="
python3 --version || true

echo
echo "===== EZA ====="
command -v eza || true

echo
echo "===== EXISTING .venv ====="
find . -type d -name ".venv" -print

echo
echo "===== REQUIREMENTS FILES ====="
find . -type f \( -name "requirements.txt" -o -name "requirements-*.txt" \) -print

echo
echo "===== PYPROJECT ====="
find . -maxdepth 2 -name "pyproject.toml" -print

echo
echo "===== TODO.md ====="
cat > TODO.md <<'TODOMD'
Score: 0 / 100
Current Step: 1 / 4
Kalan Adım: 4

[/] Step 1 — Environment audit
[ ] Step 2 — uv environment migration
[ ] Step 3 — Lockfile verification
[ ] Step 4 — Validation & cleanup
TODOMD

echo
echo "===== PROJECT TREE ====="
if command -v eza >/dev/null 2>&1; then
    eza -T -L 2
else
    find . -maxdepth 2
fi

echo
echo "BOOTSTRAP COMPLETE"
