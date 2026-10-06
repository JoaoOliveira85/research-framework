#!/usr/bin/env bash
# research-framework — end-user update/resume wrapper.
# Runs another research pass against an existing vault. Expects the vault
# directory to contain its own `research.spec.md` (dropped there at generate
# time by the scaffold step).
#
# Usage (zero-arg, recommended):
#   ./update.sh
#     Resolves the vault from `output_dir:` in ./settings.yaml and re-runs
#     in --resume mode against that vault's research.spec.md.
#
# Usage (classic positional form — still supported):
#   ./update.sh <vault-dir> [extra research-framework args...]
#   ./update.sh ~/Documents/my-vault
#   ./update.sh ~/Documents/my-vault --cycle 2

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "ERROR: virtualenv not found. Run ./install.sh first." >&2
    exit 2
fi

DEFAULT_SETTINGS="${ROOT_DIR}/settings.yaml"

vault_dir=""
extra_args=()

# Resolve the vault directory:
#   1. First non-flag positional argument wins.
#   2. Otherwise read `output_dir:` from ./settings.yaml via the CLI helper.
if [[ $# -ge 1 && "${1:-}" != -* ]]; then
    vault_dir="$1"
    shift
elif [[ -f "${DEFAULT_SETTINGS}" ]]; then
    # The settings path reaches Python through the environment and the heredoc
    # is quoted. Pasted into the source, the name of the directory this bundle
    # was unpacked into was Python: a double quote in it was a SyntaxError, a
    # backslash an escape.
    vault_dir="$(
        RV_UPDATE_SETTINGS="${DEFAULT_SETTINGS}" "${VENV_PYTHON}" - <<'PY'
import os
from pathlib import Path
from research_framework._assets import load_output_dir_from_settings
p = load_output_dir_from_settings(Path(os.environ["RV_UPDATE_SETTINGS"]))
print(str(p) if p is not None else "")
PY
    )"
fi

while [[ $# -gt 0 ]]; do
    extra_args+=("$1")
    shift
done

if [[ -z "${vault_dir}" ]]; then
    cat >&2 <<USAGE
ERROR: could not resolve the vault to update.

Either:
  1. Pass it explicitly: ./update.sh path/to/vault, or
  2. Set output_dir: in ${DEFAULT_SETTINGS} so zero-arg update.sh knows
     which vault to re-run.
USAGE
    exit 2
fi

SPEC_PATH="${vault_dir}/research.spec.md"
if [[ ! -f "${SPEC_PATH}" ]]; then
    echo "ERROR: ${SPEC_PATH} not found." >&2
    echo "This vault wasn't generated with the self-contained scaffold." >&2
    exit 2
fi

cmd=(
    "${VENV_PYTHON}" -m research_framework.cli generate
    --spec "${SPEC_PATH}"
    --output "${vault_dir}"
    --resume
)
if [[ ${#extra_args[@]} -gt 0 ]]; then
    cmd+=("${extra_args[@]}")
fi

exec "${cmd[@]}"
