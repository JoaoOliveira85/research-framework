#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# `pip install -e ".[dev]"` below resolves "." against the cwd; without this a
# call from anywhere else installs whatever project the caller is standing in.
cd "${ROOT_DIR}"
VENV_DIR="${ROOT_DIR}/.venv"

if [[ ! -d "${VENV_DIR}" ]]; then
    python3 -m venv "${VENV_DIR}"
fi

# The venv is created at runtime, so shellcheck cannot follow it.
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

echo "Installed research-framework into ${VENV_DIR}"
echo "Activate with: source ${VENV_DIR}/bin/activate"
