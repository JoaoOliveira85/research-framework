#!/usr/bin/env bash
# research-framework — end-user installer (bundled with every release tarball).
# Creates a self-contained Python virtual environment inside this directory,
# installs the bundled wheel, and then — optionally, interactively — walks
# the user from "fresh download" to "first vault generated" in one flow:
#
#   1. Set up the venv + install the wheel.
#   2. Look for ./research.spec.md.
#      - Missing → offer to draft one inline via the `vault-spec` skill on
#                  whichever agent CLI (claude / codex) the user prefers.
#      - Missing + user declines → exit cleanly with next-step instructions.
#      - Present → skip the draft step.
#   3. Offer to run ./generate.sh — prompts for destination folder (Enter =
#      spec/settings default) and uses the same agent CLI profile as the
#      vault-spec chat when applicable.
#
# The interactive steps are skipped automatically when:
#   - stdin is not a terminal (CI, pipes),
#   - --non-interactive is passed, or
#   - $RV_NONINTERACTIVE is set to any non-empty value.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# TTY-state capture (MUST happen BEFORE the log redirect).
#
# The log redirect below rewires stdout/stderr to a tee process substitution,
# so ``-t 1`` / ``-t 2`` become false even when the user is sitting at a
# real terminal. The interactive wizard later in this script tests both, so
# we record the *pre-redirect* state here and use the cached values in
# ``is_interactive``. Without this, v0.2.23 silently degraded every install
# to non-interactive mode and the wizard never offered to run generate.sh.
# ---------------------------------------------------------------------------
RV_STDIN_IS_TTY=0
RV_STDOUT_IS_TTY=0
RV_STDERR_IS_TTY=0
[[ -t 0 ]] && RV_STDIN_IS_TTY=1
[[ -t 1 ]] && RV_STDOUT_IS_TTY=1
[[ -t 2 ]] && RV_STDERR_IS_TTY=1
export RV_STDIN_IS_TTY RV_STDOUT_IS_TTY RV_STDERR_IS_TTY

# ---------------------------------------------------------------------------
# Argument parsing (before TARGET resolution / log redirect).
# ---------------------------------------------------------------------------
NON_INTERACTIVE="${RV_NONINTERACTIVE:-}"
ACCEPT_PATH=""
INSTALL_DRY_RUN="${INSTALL_DRY_RUN:-}"
POSITIONAL_TARGET=""
_prev_arg=""
for arg in "$@"; do
    if [[ "${_prev_arg}" == "--accept-path" ]]; then
        ACCEPT_PATH="${arg}"
        _prev_arg=""
        continue
    fi
    case "${arg}" in
        --non-interactive|-y|--auto-confirm)
            NON_INTERACTIVE=1
            ;;
        --accept-path)
            _prev_arg="${arg}"
            ;;
        --dry-run)
            INSTALL_DRY_RUN=1
            ;;
        -*)
            ;;
        *)
            if [[ -z "${POSITIONAL_TARGET}" ]]; then
                POSITIONAL_TARGET="${arg}"
            fi
            ;;
    esac
done
export INSTALL_DRY_RUN

# ---------------------------------------------------------------------------
# TARGET resolution (FR-001/002): $1 > ${VAULT_DIR} > ROOT_DIR.
# Wheel + skills are SOURCED from ROOT_DIR; install state lands under TARGET.
# ---------------------------------------------------------------------------
TARGET="${POSITIONAL_TARGET:-${VAULT_DIR:-${ROOT_DIR}}}"
mkdir -p "${TARGET}"
if [[ "${INSTALL_DRY_RUN:-}" == "1" ]]; then
    echo "[dry-run] would mkdir -p ${TARGET}"
fi
# shellcheck disable=SC2312
TARGET="$(cd "${TARGET}" 2>/dev/null && pwd || echo "${TARGET}")"
ROOT_DIR_ABS="$(cd "${ROOT_DIR}" && pwd)"
if [[ "${TARGET}" == "${ROOT_DIR_ABS}" ]]; then
    echo "[install] installing in place at ${TARGET}"
fi
cd "${TARGET}"

# ---------------------------------------------------------------------------
# Crash-safe log file (v0.2.23, TTY-fix v0.2.24).
# Every line printed to stdout/stderr by install.sh — including subprocess
# output from pip, python, claude/codex, generate.sh — is mirrored to
# ./install.log via a process-substitution tee. The tee survives this
# script's exit so the file is always closed cleanly even on Ctrl+C or a
# mid-script crash. Re-running install.sh truncates the previous log so the
# file always reflects the most recent attempt.
#
# Note: ``bash`` `exec` for I/O redirection rewires this shell's file
# descriptors in place (no re-execution), so any variables set before this
# block — notably the TTY-state cache above — remain visible afterward.
# ---------------------------------------------------------------------------
INSTALL_LOG="${TARGET}/install.log"
if [[ -z "${RV_INSTALL_LOG_FORWARDED:-}" ]]; then
    # Skip the redirect when the user explicitly opts out (e.g. piping to
    # their own tee or redirecting elsewhere via RV_INSTALL_LOG=0).
    if [[ "${RV_INSTALL_LOG:-1}" != "0" ]]; then
        : > "${INSTALL_LOG}"  # truncate any previous log
        export RV_INSTALL_LOG_FORWARDED=1
        exec > >(tee -a "${INSTALL_LOG}") 2>&1
        echo "[install] log: ${INSTALL_LOG}"
    fi
fi

VENV_DIR="${TARGET}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
INSTALL_SUMMARY_PATH="${INSTALL_SUMMARY_PATH:-${TARGET}/_pipeline/install_summary.json}"
INSTALL_FAILED=0
DEGRADED_MODES=()
INSTALL_WARNINGS=()
OS=""
OS_VERSION=""
PACKAGE_MANAGER=""
PY_VERSION=""
FRAMEWORK_VERSION="unknown"

# Force Python child processes (pip, the installed CLI, scripts/*) to write
# unbuffered stdout/stderr so the tee above captures evidence in real time
# even when the consumer is a file rather than a TTY. Without this, pip's
# progress lines and any long-running step would block-buffer to 4KB chunks
# and a mid-step crash would leave the log evidence-free for the latest
# step. Cheap, scoped to install.sh; the generated `./rv` shim inherits the
# variable so generate.sh and rv pipeline runs benefit too.
export PYTHONUNBUFFERED=1

# ---------------------------------------------------------------------------
# Spec 039 helpers — dry-run wrapper, status lines, OS/dep probe (FR-004..013).
# ---------------------------------------------------------------------------
is_dry_run() {
    [[ "${INSTALL_DRY_RUN:-}" == "1" ]]
}

run() {
    if is_dry_run; then
        echo "[dry-run] would $*"
    else
        "$@"
    fi
}

fail() {
    echo "[FAIL] $*" >&2
    INSTALL_FAILED=1
}

warn() {
    echo "[WARN] $*" >&2
    INSTALL_WARNINGS+=("$*")
}

info() {
    echo "[INFO] $*"
}

_detect_os() {
    case "$(uname -s)" in
        Darwin) echo "darwin" ;;
        Linux) echo "linux" ;;
        *) echo "unsupported" ;;
    esac
}

_detect_package_manager() {
    local os="$1"
    if [[ "${os}" == "darwin" ]]; then
        if command -v brew >/dev/null 2>&1; then
            echo "brew"
            return 0
        fi
        echo "none"
        return 0
    fi
    if [[ "${os}" == "linux" ]]; then
        if command -v apt >/dev/null 2>&1; then echo "apt"; return 0; fi
        if command -v dnf >/dev/null 2>&1; then echo "dnf"; return 0; fi
        if command -v pacman >/dev/null 2>&1; then echo "pacman"; return 0; fi
        if command -v apk >/dev/null 2>&1; then echo "apk"; return 0; fi
        if command -v brew >/dev/null 2>&1; then echo "brew"; return 0; fi
        echo "none"
        return 0
    fi
    echo "none"
}

_install_cmd_for() {
    local dep="$1"
    local pm="${2:-none}"
    case "${pm}" in
        brew) echo "brew install ${dep}" ;;
        apt) echo "apt install ${dep}" ;;
        dnf) echo "dnf install ${dep}" ;;
        pacman) echo "pacman -S ${dep}" ;;
        apk) echo "apk add ${dep}" ;;
        *)
            echo "# install ${dep} using your system package manager"
            ;;
    esac
}

_probe_dependencies() {
    local pm="${PACKAGE_MANAGER}"
    local py_bin=""

    if command -v python3.11 >/dev/null 2>&1; then
        py_bin="python3.11"
    elif command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
        py_bin="${PYTHON_BIN}"
    else
        fail "python3.11 missing — install via: $(_install_cmd_for python3.11 "${pm}")"
        return 1
    fi

    PY_VERSION="$("${py_bin}" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
    local py_major="${PY_VERSION%.*}"
    local py_minor="${PY_VERSION#*.}"
    if [[ -z "${PY_VERSION}" || "${py_major}" -lt 3 || ( "${py_major}" -eq 3 && "${py_minor}" -lt 11 ) ]]; then
        fail "python3.11 missing — install via: $(_install_cmd_for python3.11 "${pm}")"
        return 1
    fi
    PYTHON_BIN="${py_bin}"

    if ! command -v git >/dev/null 2>&1; then
        fail "git missing — install via: $(_install_cmd_for git "${pm}")"
        return 1
    fi
    if ! command -v curl >/dev/null 2>&1; then
        fail "curl missing — install via: $(_install_cmd_for curl "${pm}")"
        return 1
    fi

    if ! command -v rsync >/dev/null 2>&1; then
        warn "rsync missing — install via: $(_install_cmd_for rsync "${pm}") (degraded sync)"
        DEGRADED_MODES+=("rsync")
    fi
    if ! command -v claude >/dev/null 2>&1; then
        warn "claude CLI not found — onboarding chat disabled (degraded)"
        DEGRADED_MODES+=("claude")
    fi
    if ! command -v codex >/dev/null 2>&1; then
        info "codex CLI not found — optional runtime unavailable"
        DEGRADED_MODES+=("codex")
    fi
    if ! command -v weasyprint >/dev/null 2>&1; then
        info "weasyprint not found — PDF export unavailable"
        DEGRADED_MODES+=("weasyprint")
    fi
    if ! command -v gh >/dev/null 2>&1; then
        info "gh CLI not found — GitHub integration unavailable"
        DEGRADED_MODES+=("gh")
    fi
    return 0
}

_write_install_summary() {
    local framework_version="${1:-${FRAMEWORK_VERSION}}"
    local exit_status="ok"
    if [[ "${INSTALL_FAILED}" == "1" ]]; then
        exit_status="failed"
    elif [[ ${#DEGRADED_MODES[@]} -gt 0 || ${#INSTALL_WARNINGS[@]} -gt 0 ]]; then
        exit_status="degraded"
    fi

    local installed_at
    installed_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")"

    if [[ -z "${OS_VERSION}" ]]; then
        if [[ "${OS}" == "darwin" ]]; then
            OS_VERSION="$(sw_vers -productVersion 2>/dev/null || true)"
        else
            OS_VERSION="$(uname -r 2>/dev/null || true)"
        fi
    fi

    local dry_flag="false"
    is_dry_run && dry_flag="true"

    # The summary is the install AUDIT RECORD, not an install mutation, so it is
    # written even in dry-run (contract §1 dry-run note). Its parent dir is
    # therefore created for real regardless of dry-run — using `run` here would
    # skip the mkdir in dry-run and leave the unconditional write below with
    # nowhere to land.
    if [[ "${INSTALL_SUMMARY_PATH}" != "/dev/stdout" ]]; then
        mkdir -p "$(dirname "${INSTALL_SUMMARY_PATH}")"
    fi

    # Both arrays are empty on a clean run. bash < 4.4 (macOS ships 3.2 as
    # /bin/bash) treats "${ARR[@]}" on an empty array as an unbound variable
    # under `set -u`; the `${ARR[@]+…}` form below expands to nothing instead.
    local summary_tmp
    if [[ "${INSTALL_SUMMARY_PATH}" == "/dev/stdout" ]]; then
        summary_tmp="$(mktemp "${TMPDIR:-/tmp}/rf-install-summary.XXXXXX")"
    else
        summary_tmp="${INSTALL_SUMMARY_PATH}.tmp.$$"
    fi
    OS="${OS}" \
    OS_VERSION="${OS_VERSION}" \
    PY_VERSION="${PY_VERSION}" \
    PACKAGE_MANAGER="${PACKAGE_MANAGER}" \
    TARGET="${TARGET}" \
    ROOT_DIR_ABS="${ROOT_DIR_ABS}" \
    FRAMEWORK_VERSION="${framework_version}" \
    INSTALLED_AT="${installed_at}" \
    SUMMARY_EXIT_STATUS="${exit_status}" \
    SUMMARY_DRY_RUN="${dry_flag}" \
    DEGRADED_LIST="$(printf '%s\n' ${DEGRADED_MODES[@]+"${DEGRADED_MODES[@]}"})" \
    WARN_LIST="$(printf '%s\n' ${INSTALL_WARNINGS[@]+"${INSTALL_WARNINGS[@]}"})" \
    "${PYTHON_BIN}" - <<'PY' > "${summary_tmp}"
import json, os

def _list(name):
    raw = os.environ.get(name, "")
    return [x for x in raw.split("\n") if x]

print(json.dumps({
    "framework_version": os.environ.get("FRAMEWORK_VERSION", "unknown"),
    "installed_at": os.environ.get("INSTALLED_AT", ""),
    "os": os.environ.get("OS", ""),
    "os_version": os.environ.get("OS_VERSION", ""),
    "python_version": os.environ.get("PY_VERSION", ""),
    "package_manager": os.environ.get("PACKAGE_MANAGER", ""),
    "target_dir": os.environ.get("TARGET", ""),
    "root_dir": os.environ.get("ROOT_DIR_ABS", ""),
    "dry_run": os.environ.get("SUMMARY_DRY_RUN", "false") == "true",
    "warnings": _list("WARN_LIST"),
    "degraded_modes": _list("DEGRADED_LIST"),
    "exit_status": os.environ.get("SUMMARY_EXIT_STATUS", "ok"),
}, indent=2))
PY

    if [[ "${INSTALL_SUMMARY_PATH}" == "/dev/stdout" ]]; then
        cat "${summary_tmp}"
        rm -f "${summary_tmp}"
        return 0
    fi

    mv "${summary_tmp}" "${INSTALL_SUMMARY_PATH}"
}

_finalize_install() {
    local rc=0
    _write_install_summary "${FRAMEWORK_VERSION}"
    if [[ "${INSTALL_FAILED}" == "1" ]]; then
        rc=1
    fi
    return "${rc}"
}

confirm_install_path() {
    local target_abs
    target_abs="$(cd "${TARGET}" && pwd)"
    if is_interactive; then
        echo "Installing into: ${target_abs}"
        if ! ask_yn "Proceed?" y; then
            echo "Aborted." >&2
            exit 2
        fi
        return 0
    fi
    if [[ -z "${ACCEPT_PATH}" ]]; then
        echo "ERROR: non-interactive install requires --accept-path <PATH>" >&2
        exit 2
    fi
    local accept_abs
    if ! accept_abs="$(cd "${ACCEPT_PATH}" 2>/dev/null && pwd)"; then
        accept_abs="${ACCEPT_PATH}"
    fi
    if [[ "${accept_abs}" != "${target_abs}" ]]; then
        echo "ERROR: --accept-path (${accept_abs}) must match install directory (${target_abs})" >&2
        exit 2
    fi
}

# ---------------------------------------------------------------------------
# Interactive helpers — defined here (before §2) so the venv stale-rebuild
# prompt below can use them. (They are also used by the onboarding wizard in
# §5.) is_interactive() consults the TTY-state cache captured at the top of
# this script, because the log-capture ``exec > >(tee …)`` redirect makes a
# live ``-t 1`` check unreliable.
# ---------------------------------------------------------------------------
is_interactive() {
    [[ -z "${NON_INTERACTIVE}" \
        && "${RV_STDIN_IS_TTY:-0}" == "1" \
        && "${RV_STDOUT_IS_TTY:-0}" == "1" ]]
}

ask_yn() {
    # ask_yn "Prompt" <default: y|n>
    local prompt="$1"
    local default="${2:-n}"
    local hint
    if [[ "${default}" == "y" ]]; then
        hint="[Y/n]"
    else
        hint="[y/N]"
    fi
    local reply
    read -r -p "${prompt} ${hint} " reply
    reply="${reply:-${default}}"
    [[ "${reply}" =~ ^[Yy]$ ]]
}

# A venv whose recorded interpreter (``pyvenv.cfg::home``) no longer exists on
# disk is stale: reusing it yields confusing import errors (seen during the
# feeds-vault revival, spec 051 FR2). Exit 0 ⇒ stale (rebuild), non-zero ⇒ fine or
# absent. The "wrong version" case is caught separately by the post-install
# sanity check (§3), which is a more reliable signal than comparing home paths.
_detect_stale_venv() {
    local cfg="${VENV_DIR}/pyvenv.cfg"
    [[ -f "${cfg}" ]] || return 1          # no venv (or no cfg) → not stale
    local home
    home="$(sed -n 's/^home[[:space:]]*=[[:space:]]*//p' "${cfg}" | head -n1)"
    [[ -n "${home}" ]] || return 1         # unparseable → leave alone
    [[ -d "${home}" ]] && return 1         # interpreter dir still present → fine
    return 0                               # recorded interpreter is gone → stale
}

# ---------------------------------------------------------------------------
# 1. OS branch + dependency probe (FR-004/005)
# ---------------------------------------------------------------------------
OS="$(_detect_os)"
if [[ "${OS}" == "unsupported" ]]; then
    echo "ERROR: unsupported OS: $(uname -s)" >&2
    INSTALL_FAILED=1
    _write_install_summary "unknown"
    exit 3
fi
PACKAGE_MANAGER="$(_detect_package_manager "${OS}")"

if ! _probe_dependencies; then
    _write_install_summary "unknown"
    exit 1
fi

echo "[install] Python ${PY_VERSION} OK"

confirm_install_path

# shellcheck disable=SC2012 # wheel names are controlled (research_framework-<ver>-…); ls|head is safe and find would reorder
WHEEL="$(ls "${ROOT_DIR}"/research_framework-*.whl 2>/dev/null | head -n 1 || true)"
if [[ -n "${WHEEL}" ]]; then
    FRAMEWORK_VERSION="$(basename "${WHEEL}" | sed -E 's/^research_framework-([^-]+)-.*/\1/')"
fi

# Idempotent re-run fast path (FR-010/011). A summary that records a failed
# install is not "already installed": the failure exits below write one too.
if [[ -d "${VENV_DIR}" && -f "${INSTALL_SUMMARY_PATH}" ]] \
    && ! grep -q '"exit_status": "failed"' "${INSTALL_SUMMARY_PATH}" \
    && ! _detect_stale_venv; then
    echo "[install] vault already installed at ${TARGET}; updating only changed scaffolds"
    # TODO(spec-027): gate scaffold overwrite on user_authored flag before copying files.
    _write_install_summary "${FRAMEWORK_VERSION}"
    exit 0
fi

# ---------------------------------------------------------------------------
# 2. Virtual environment
# ---------------------------------------------------------------------------
# Tear down a stale venv (recorded interpreter gone) before reuse — otherwise
# `source .venv/bin/activate` resurrects a broken environment (spec 051 FR2).
if _detect_stale_venv; then
    echo "[install] WARNING: the existing venv at ${VENV_DIR} references a" >&2
    echo "[install]          Python interpreter that no longer exists" >&2
    echo "[install]          (pyvenv.cfg 'home' is gone). It must be rebuilt." >&2
    if [[ -n "${NON_INTERACTIVE}" ]] || ask_yn "  Rebuild the virtualenv from scratch?" y; then
        echo "[install] rebuilding virtualenv (removing ${VENV_DIR})"
        run rm -rf "${VENV_DIR}"
    else
        echo "[install] keeping the existing venv — expect import errors." >&2
    fi
fi

if [[ ! -d "${VENV_DIR}" ]]; then
    echo "[install] creating virtualenv at ${VENV_DIR}"
    run "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

if is_dry_run; then
    echo "[install] installing $(basename "${WHEEL:-research_framework-*.whl}")"
    run python -m pip install --quiet --force-reinstall "${WHEEL:-${ROOT_DIR}/research_framework-0.0.0-py3-none-any.whl}"
    run bash -c "cat > \"${TARGET}/rv\" <<'SHIM'
#!/usr/bin/env bash
HERE=\"\$(cd \"\$(dirname \"\${BASH_SOURCE[0]}\")\" && pwd)\"
exec \"\${HERE}/.venv/bin/research-framework\" \"\$@\"
SHIM"
    run chmod +x "${TARGET}/rv"
    _write_install_summary "${FRAMEWORK_VERSION}"
    exit 0
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade --quiet pip

# ---------------------------------------------------------------------------
# 3. Install the bundled wheel
# ---------------------------------------------------------------------------
if [[ -z "${WHEEL}" ]]; then
    echo "ERROR: no research_framework-*.whl found next to install.sh." >&2
    echo "The distribution bundle appears incomplete." >&2
    # The venv exists by now, so a summary that does not say "failed" would
    # send the next plain run down the "already installed" fast path.
    INSTALL_FAILED=1
    _write_install_summary "${FRAMEWORK_VERSION}"
    exit 2
fi

echo "[install] installing $(basename "${WHEEL}")"
python -m pip install --quiet --force-reinstall "${WHEEL}"

# Post-install sanity check (spec 051 FR2): the importable version MUST match
# the bundled wheel. A mismatch means the venv is stale or a shadowing install
# is on the path — exactly the silent failure mode the feeds-vault revival hit.
BUNDLE_VERSION="$(basename "${WHEEL}" | sed -E 's/^research_framework-([^-]+)-.*/\1/')"
INSTALLED_VERSION="$(python -c 'import research_framework; print(research_framework.__version__)' 2>/dev/null || true)"
if [[ -n "${BUNDLE_VERSION}" && "${INSTALLED_VERSION}" != "${BUNDLE_VERSION}" ]]; then
    echo "ERROR: installed research_framework '${INSTALLED_VERSION:-<none>}' does not" >&2
    echo "       match the bundled wheel '${BUNDLE_VERSION}'. The venv is likely stale" >&2
    echo "       or a shadowing install is on PATH. Inspect ${VENV_DIR}/pyvenv.cfg, then:" >&2
    echo "           rm -rf .venv && ./install.sh" >&2
    INSTALL_FAILED=1
    _write_install_summary "${BUNDLE_VERSION}"
    exit 2
fi
echo "[install] research_framework ${INSTALLED_VERSION} OK"

# ---------------------------------------------------------------------------
# 4. Convenience shim — ./rv runs the CLI without needing to activate the venv.
# (Dry-run exits earlier in §2 after reporting the would-be venv/pip/rv ops, so
# this section only runs in real-install mode.)
# ---------------------------------------------------------------------------
cat > "${TARGET}/rv" <<'SHIM'
#!/usr/bin/env bash
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${HERE}/.venv/bin/research-framework" "$@"
SHIM
chmod +x "${TARGET}/rv"

echo ""
echo "[install] runtime ready."

# ---------------------------------------------------------------------------
# 4b. Skill-file preflight.
# External agent CLIs (Cursor, Codex, the Superpowers plugin) auto-discover
# .agents/skills/*/SKILL.md files when they open the bundle and have, in
# earlier releases, rewritten them in-place — flattening multi-line strings
# and breaking the YAML frontmatter so the cycle's own skill loader silently
# drops them. We run the same preflight the cycle runner uses, with
# auto-restore enabled, so the bundle leaves install.sh in a known-good state.
# ---------------------------------------------------------------------------
if [[ -d "${ROOT_DIR}/.agents/skills" ]]; then
    if python -m research_framework.cli check-skills --vault "${TARGET}"; then
        :
    else
        echo "" >&2
        echo "ERROR: one or more .agents/skills/*/SKILL.md files are broken and" >&2
        echo "could not be auto-restored. The bundle is incomplete — re-download" >&2
        echo "the release tarball or run \`./rv check-skills --vault .\` after fixing" >&2
        echo "the listed files by hand." >&2
        INSTALL_FAILED=1
        _write_install_summary "${FRAMEWORK_VERSION}"
        exit 2
    fi
fi

# ---------------------------------------------------------------------------
# 5. Interactive onboarding — skip cleanly in non-TTY / CI / --non-interactive.
# ---------------------------------------------------------------------------
# NOTE: is_interactive() and ask_yn() are defined earlier (just after arg
# parsing, before §2) so the venv stale-rebuild prompt can use them. See there.

SPEC_FILE="${TARGET}/research.spec.md"
SETTINGS_FILE="${TARGET}/settings.yaml"
SETTINGS_CODEX="${TARGET}/settings.codex.yaml"

# Set when the user drafts the spec via inline chat (claude vs codex). Used so
# ./generate.sh receives matching --settings instead of always defaulting to
# the Claude profile bundled as ./settings.yaml.
RUNTIME=""

# ---------------------------------------------------------------------------
# Settings sniffers (spec-019 / 0.2.29).
#
# v0.2.28 still asked "Which agent runtime for generation? [claude/codex]"
# even when settings.yaml *declared* the runtime — and asked for a
# destination folder even when settings.output_dir / spec.location made it
# unambiguous. Wizard golden rule: only ask the user for things we cannot
# infer. These helpers parse the bundled settings.yaml (and, when present,
# research.spec.md frontmatter) so the wizard can quietly satisfy itself.
#
# Both helpers are best-effort and echo only the inferred value (or empty
# string when nothing is declared) to stdout — never errors. The wizard
# falls back to its old prompt when the helper prints nothing.
# ---------------------------------------------------------------------------
declared_runtime_from_settings() {
    local settings_path="$1"
    [[ -f "${settings_path}" ]] || return 0
    "${VENV_DIR}/bin/python" - <<'PY' "${settings_path}" 2>/dev/null || true
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    sys.exit(0)

path = Path(sys.argv[1])
try:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
except Exception:
    sys.exit(0)
executor = data.get("default_executor") or {}
runtime = str(executor.get("runtime") or "").strip().lower()
# Only echo runtimes we know how to launch from install.sh; ignore api/
# script profiles so the wizard's interactive ask still triggers when
# the user *should* be asked.
if runtime in ("claude", "codex"):
    print(runtime)
PY
}

declared_output_dir() {
    local settings_path="$1"
    local spec_path="$2"
    "${VENV_DIR}/bin/python" - <<'PY' "${settings_path}" "${spec_path}" 2>/dev/null || true
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    sys.exit(0)


def _from_yaml(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or None
    except Exception:
        return None


def _extract_spec_frontmatter(path: Path) -> dict | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    try:
        return yaml.safe_load(text[3:end]) or None
    except Exception:
        return None


settings = _from_yaml(Path(sys.argv[1])) or {}
spec = _extract_spec_frontmatter(Path(sys.argv[2])) or {}

candidate = settings.get("output_dir") or spec.get("location") or ""
candidate = str(candidate).strip()
if candidate:
    print(candidate)
PY
}

echo ""
echo "=============================================================="
echo "  Next step: author research.spec.md and generate your vault"
echo "=============================================================="

if ! is_interactive; then
    echo ""
    echo "Running non-interactively — skipping the wizard."
    echo "Run ./generate.sh once you have a research.spec.md next to it."
    _write_install_summary "${FRAMEWORK_VERSION}"
    exit 0
fi

# --- 5a. Ensure research.spec.md exists ------------------------------------
if [[ -f "${SPEC_FILE}" ]]; then
    echo ""
    echo "  Found existing spec: ${SPEC_FILE}"
else
    echo ""
    echo "  No research.spec.md found in this directory."
    echo ""
    echo "  The 'vault-spec' agent skill can walk you through drafting one in"
    echo "  a short chat (≤ 4 turns). It uses your local 'claude' or 'codex'"
    echo "  CLI — whichever you have installed."
    echo ""

    if ask_yn "  Draft research.spec.md now via an inline chat?" y; then
        if command -v claude >/dev/null 2>&1 && command -v codex >/dev/null 2>&1; then
            echo ""
            echo "  Both 'claude' and 'codex' are available."
            read -r -p "  Which runtime should host the chat? [claude/codex] " RUNTIME
            RUNTIME="${RUNTIME:-claude}"
        elif command -v claude >/dev/null 2>&1; then
            RUNTIME="claude"
        elif command -v codex >/dev/null 2>&1; then
            RUNTIME="codex"
        fi

        if [[ -z "${RUNTIME}" ]]; then
            cat <<EOF

  Neither 'claude' nor 'codex' was found on PATH. The inline chat needs one
  of them. You can install the Anthropic CLI from:
      https://docs.anthropic.com/claude/docs/claude-code
  Or the OpenAI Codex CLI from:
      https://github.com/openai/codex

  Once installed, either:
      (a) re-run ./install.sh, or
      (b) copy examples/research.spec.md to research.spec.md and edit it.
EOF
            exit 0
        fi

        SKILL_FILE="${ROOT_DIR}/.agents/skills/vault-spec/SKILL.md"
        if [[ ! -f "${SKILL_FILE}" ]]; then
            echo "ERROR: cannot find vault-spec skill at ${SKILL_FILE}" >&2
            echo "The bundle appears incomplete." >&2
            exit 2
        fi

        # Both Claude Code and Codex accept a seed prompt as a positional
        # argument and then drop into interactive mode. Embedding the skill
        # text inline (rather than relying on runtime-specific flags like
        # `--append-system-prompt` or `@<file>`) keeps the invocation
        # portable across CLI versions.
        SEED_PROMPT=$(cat <<EOF
You are running the 'vault-spec' agent skill. Follow every instruction
in the skill file below. Author the final file at this exact path:

  ${SPEC_FILE}

Start by inviting the user to describe what they want to learn about,
then drive the conversation per the skill. When the spec is written,
exit so the installer can pick up.

--- BEGIN SKILL: vault-spec ---
$(cat "${SKILL_FILE}")
--- END SKILL: vault-spec ---
EOF
        )

        echo ""
        echo "  Launching '${RUNTIME}' with the vault-spec skill seeded."
        echo "  The chat will write ${SPEC_FILE} when you confirm the draft."
        echo "  Exit the chat (Ctrl-D, /exit, or 'quit') when finished."
        echo ""

        # Run the chat in the bundle dir so file writes from the skill land
        # here. Failures don't abort the installer — the user can retry or
        # fall back to manual editing of examples/research.spec.md.
        set +e
        (cd "${TARGET}" && "${RUNTIME}" "${SEED_PROMPT}")
        CHAT_RC=$?
        set -e

        if [[ ${CHAT_RC} -ne 0 ]]; then
            echo ""
            echo "  '${RUNTIME}' exited with code ${CHAT_RC}."
        fi

        if [[ ! -f "${SPEC_FILE}" ]]; then
            echo ""
            echo "  ${SPEC_FILE} still doesn't exist. Nothing to run."
            echo "  You can re-run ./install.sh to try again, or copy"
            echo "  examples/research.spec.md and edit it by hand."
            exit 0
        fi
        echo ""
        echo "  research.spec.md authored. Validating…"
    else
        echo ""
        echo "  Skipped spec drafting."
        echo "  Copy examples/research.spec.md to research.spec.md, edit it,"
        echo "  then run ./generate.sh when you're ready."
        exit 0
    fi
fi

# --- 5b. Offer to run generate.sh right now --------------------------------
echo ""
if [[ -f "${SETTINGS_FILE}" ]]; then
    echo "  settings.yaml is in place (${SETTINGS_FILE})."
else
    echo "  No settings.yaml found — generate.sh will use the bundled default."
fi
echo ""

if ask_yn "  Generate the vault now?" y; then
    # Infer or confirm CLI profile for generate when vault-spec chat didn't set RUNTIME.
    # Wizard golden rule (spec-019 / 0.2.29): never ask for what we already
    # have. Order: vault-spec chat preference > settings.yaml declaration >
    # solo-binary-on-PATH heuristic > interactive ask (only when truly
    # ambiguous).
    if [[ -z "${RUNTIME}" ]]; then
        DECLARED_RT="$(declared_runtime_from_settings "${SETTINGS_FILE}")"
        if [[ -n "${DECLARED_RT}" ]]; then
            if command -v "${DECLARED_RT}" >/dev/null 2>&1; then
                RUNTIME="${DECLARED_RT}"
                echo ""
                echo "  Using runtime '${RUNTIME}' (declared in settings.yaml — not asking)."
            else
                echo ""
                echo "  WARNING: settings.yaml declares runtime '${DECLARED_RT}' but"
                echo "  that binary is not on PATH. Falling back to interactive pick."
            fi
        fi
    fi
    if [[ -z "${RUNTIME}" ]]; then
        if command -v claude >/dev/null 2>&1 && command -v codex >/dev/null 2>&1; then
            echo ""
            read -r -p "  Which agent runtime for generation? [claude/codex] (Enter=claude) " PICK_RT
            PICK_RT="${PICK_RT:-claude}"
            if [[ "${PICK_RT}" == "codex" ]]; then
                RUNTIME="codex"
            else
                RUNTIME="claude"
            fi
        elif command -v codex >/dev/null 2>&1 && ! command -v claude >/dev/null 2>&1; then
            RUNTIME="codex"
        elif command -v claude >/dev/null 2>&1 && ! command -v codex >/dev/null 2>&1; then
            RUNTIME="claude"
        fi
    fi

    # Destination folder — only ask if neither settings.output_dir nor the
    # spec's location field declared one. Otherwise generate.sh will
    # resolve it itself and we'd just be re-asking for what's on disk.
    VAULT_DEST=""
    INFERRED_DEST="$(declared_output_dir "${SETTINGS_FILE}" "${SPEC_FILE}")"
    if [[ -n "${INFERRED_DEST}" ]]; then
        echo ""
        echo "  Vault destination: ${INFERRED_DEST}"
        echo "  (declared in settings.yaml/research.spec.md — not asking)."
    else
        echo ""
        echo "  Where should the vault be created?"
        echo "  (Press Enter to use the default from your spec and settings —"
        echo "   usually the \`location\` field in research.spec.md.)"
        read -r -p "  Destination folder: " VAULT_DEST
        VAULT_DEST="${VAULT_DEST#"${VAULT_DEST%%[![:space:]]*}"}"
        VAULT_DEST="${VAULT_DEST%"${VAULT_DEST##*[![:space:]]}"}"
        if [[ -n "${VAULT_DEST}" && "${VAULT_DEST}" == "~"* ]]; then
            VAULT_DEST="${VAULT_DEST/#\~/${HOME}}"
        fi
    fi

    echo ""
    echo "  Running ./generate.sh …"
    echo ""

    gen_cmd=("${ROOT_DIR}/generate.sh")
    if [[ -n "${VAULT_DEST}" ]]; then
        gen_cmd+=(--output "${VAULT_DEST}")
    fi
    # Bake in the matching profile (Codex vs Claude) when RUNTIME is known.
    # If RUNTIME is empty, generate.sh falls back to ./settings.yaml when present.
    if [[ -n "${RUNTIME}" ]]; then
        if [[ "${RUNTIME}" == "codex" && -f "${SETTINGS_CODEX}" ]]; then
            gen_cmd+=(--settings "${SETTINGS_CODEX}")
        elif [[ "${RUNTIME}" == "claude" && -f "${SETTINGS_FILE}" ]]; then
            gen_cmd+=(--settings "${SETTINGS_FILE}")
        fi
    fi
    exec "${gen_cmd[@]}"
fi

echo ""
echo "  Done. When you're ready: ./generate.sh"
echo ""
