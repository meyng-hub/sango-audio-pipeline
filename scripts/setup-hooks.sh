#!/bin/sh
# Point this clone at the tracked hooks directory (relative path: survives a folder move).
cd "$(git rev-parse --show-toplevel)" || exit 1
git config core.hooksPath .githooks
echo "core.hooksPath = $(git config core.hooksPath)"
python3 scripts/ci/secret-scan-gate.py --self-test 2>/dev/null || python scripts/ci/secret-scan-gate.py --self-test
