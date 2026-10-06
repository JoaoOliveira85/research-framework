#!/usr/bin/env bash
# Point git at the tracked .git-hooks/ directory (issue #278). Run once per
# clone/worktree — `git config` is local to each .git directory, so this
# does not propagate on its own.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

git config core.hooksPath .git-hooks
chmod +x .git-hooks/*

echo "[install-git-hooks] core.hooksPath -> .git-hooks (pre-commit runs scripts/guards/run_all.py)"
