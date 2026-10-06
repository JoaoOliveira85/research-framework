#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "ERROR: ${VENV_PYTHON} not found. Run ./install.sh first." >&2
    exit 2
fi

if [[ $# -lt 1 ]]; then
    echo "Usage: ./generate_vault.sh <spec.md> [research-framework args...]" >&2
    echo "Example: ./generate_vault.sh my-vault-spec.md --output ~/vaults/my-vault --dry-run" >&2
    exit 2
fi

SPEC_PATH="$1"
shift

exec "${VENV_PYTHON}" -m research_framework.cli generate --spec "${SPEC_PATH}" "$@"
