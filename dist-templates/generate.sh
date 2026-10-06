#!/usr/bin/env bash
# research-framework — end-user generate wrapper.
# Thin wrapper around `research-framework generate`. Auto-activates the bundled
# virtualenv and, when invoked without arguments, runs against the spec +
# settings already sitting next to this script.
#
# Usage (zero-arg, recommended):
#   ./generate.sh
#     Uses ./research.spec.md and ./settings.yaml from the bundle directory.
#     The vault destination is read from `output_dir:` inside settings.yaml.
#
# Usage (classic positional args — still supported):
#   ./generate.sh <spec-file> <output-dir> [extra args]
#   ./generate.sh examples/research.spec.md ~/Documents/my-vault
#
# Optional flags (any position, also usable with the zero-arg form):
#   --spec <path>        override ./research.spec.md
#   --output <dir>       override output_dir from settings.yaml
#   --settings <path>    override ./settings.yaml
#   --dry-run            stop after Phase 1 (scaffold only)
#   …plus any other flag `research-framework generate --help` documents.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "ERROR: virtualenv not found. Run ./install.sh first." >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# Crash-safe log file (v0.2.23) — sibling of install.log.
# Mirrors every line written by `research-framework generate` (including agent
# CLI output and cycle-runner orchestration banners) to ./generate.log so
# post-mortem analysis works even when the pipeline crashes mid-cycle and
# the terminal session is gone.
# ---------------------------------------------------------------------------
GENERATE_LOG="${ROOT_DIR}/generate.log"
if [[ -z "${RV_GENERATE_LOG_FORWARDED:-}" ]]; then
    if [[ "${RV_GENERATE_LOG:-1}" != "0" ]]; then
        : > "${GENERATE_LOG}"
        export RV_GENERATE_LOG_FORWARDED=1
        exec > >(tee -a "${GENERATE_LOG}") 2>&1
        echo "[generate] log: ${GENERATE_LOG}"
    fi
fi

# Force unbuffered I/O on the Python child so pip-style progress lines and
# orchestration banners flush in real time when tee'd to disk.
export PYTHONUNBUFFERED=1

# ---------------------------------------------------------------------------
# Argument shape detection.
#
# 1. If the first arg is a flag (starts with `-`) OR there are no args at all,
#    treat everything as flags — read spec/settings/output from the bundle
#    directory unless the user supplied --spec/--settings/--output.
# 2. Otherwise honour the classic `./generate.sh <spec> <output> [extra...]`
#    layout. This keeps the old docs working while the new zero-arg form
#    becomes the recommended path.
# ---------------------------------------------------------------------------

DEFAULT_SPEC="${ROOT_DIR}/research.spec.md"
DEFAULT_SETTINGS="${ROOT_DIR}/settings.yaml"

spec_arg=""
output_arg=""
extra_args=()

if [[ $# -ge 2 && "${1:-}" != -* && "${2:-}" != -* ]]; then
    # Classic positional form: <spec> <output> [extras...]
    spec_arg="$1"
    output_arg="$2"
    shift 2
fi
# Everything remaining — whether we consumed two positionals above or not —
# is forwarded as-is to the Python CLI. Empty $@ is fine.
while [[ $# -gt 0 ]]; do
    extra_args+=("$1")
    shift
done

# Scan extra_args to see whether --spec / --settings have been supplied; the
# zero-arg defaults only apply when they're not already set by the user.
has_flag() {
    local needle="$1"
    if [[ ${#extra_args[@]} -eq 0 ]]; then
        return 1
    fi
    local a
    for a in "${extra_args[@]}"; do
        if [[ "${a}" == "${needle}" || "${a}" == "${needle}="* ]]; then
            return 0
        fi
    done
    return 1
}

if [[ -z "${spec_arg}" ]] && ! has_flag --spec; then
    if [[ ! -f "${DEFAULT_SPEC}" ]]; then
        cat >&2 <<USAGE
ERROR: no --spec supplied and ${DEFAULT_SPEC} does not exist.

Either:
  1. Author a spec at ${DEFAULT_SPEC} (re-run ./install.sh for the wizard), or
  2. Pass one explicitly: ./generate.sh --spec path/to/research.spec.md
USAGE
        exit 2
    fi
    spec_arg="${DEFAULT_SPEC}"
fi

if ! has_flag --settings && [[ -f "${DEFAULT_SETTINGS}" ]]; then
    extra_args+=("--settings" "${DEFAULT_SETTINGS}")
fi

cmd=("${VENV_PYTHON}" -m research_framework.cli generate)
if [[ -n "${spec_arg}" ]]; then
    cmd+=("--spec" "${spec_arg}")
fi
if [[ -n "${output_arg}" ]]; then
    cmd+=("--output" "${output_arg}")
fi
if [[ ${#extra_args[@]} -gt 0 ]]; then
    cmd+=("${extra_args[@]}")
fi

exec "${cmd[@]}"
