#!/usr/bin/env bash
# build.sh — produce a distributable research-framework bundle in ./build/.
#
# Outputs:
#   build/wheel/research_framework-<version>-py3-none-any.whl
#   build/bundle/research-framework-<version>/        (staging directory)
#   build/research-framework-<version>.tar.gz         (the distributable)
#
# Run locally before releasing, or let .github/workflows/release.yml run it
# on a pushed `v*` tag.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

BUILD_DIR="${ROOT_DIR}/build"
WHEEL_DIR="${BUILD_DIR}/wheel"
BUNDLE_ROOT="${BUILD_DIR}/bundle"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# ---------------------------------------------------------------------------
# CLI flags (spec 022 US5 — additive; default behaviour unchanged)
# ---------------------------------------------------------------------------
RUN_QUALITY=0
QUALITY_FIXTURE=""
QUALITY_NO_COLOR=0
SHOW_HELP=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --quality)
            RUN_QUALITY=1
            shift
            ;;
        --fixture)
            # Without this check a trailing `--fixture` made `shift 2` fail
            # and `set -e` end the script with exit 1 and no message, and
            # `--fixture --quality` took `--quality` as the fixture name.
            if [[ $# -lt 2 || "$2" == -* ]]; then
                echo "[build] ERROR: --fixture needs a fixture name (tech-lite, source-poor, source-rich, or all)." >&2
                echo "[build] Run ./build.sh --help for usage." >&2
                exit 2
            fi
            QUALITY_FIXTURE="$2"
            shift 2
            ;;
        --no-color)
            QUALITY_NO_COLOR=1
            shift
            ;;
        --help|-h)
            SHOW_HELP=1
            shift
            ;;
        *)
            echo "[build] ERROR: unknown option: $1" >&2
            echo "[build] Run ./build.sh --help for usage." >&2
            exit 2
            ;;
    esac
done

if [[ "${SHOW_HELP}" -eq 1 ]]; then
    cat <<'EOF'
Usage: ./build.sh [OPTIONS]

Produce a distributable research-framework bundle in ./build/.

Options:
  --quality              After the smoke gate, run the spec-022 quality harness
                         (see specs/022-e2e-quality-harness/).
  --fixture <name>       With --quality: limit to one fixture (tech-lite,
                         source-poor, source-rich, or all). Default: all.
  --no-color             With --quality: disable ANSI colour in harness stdout.
  -h, --help             Show this help and exit.

Without --quality, behaviour is unchanged: mandatory smoke gate, then wheel
bundle build (ADR-0007). With --quality, the smoke gate runs first; on failure
the harness does not run. The harness exit code is propagated on failure.
EOF
    exit 0
fi

# ---------------------------------------------------------------------------
# 0. Smoke gate (feature 018 + spec-019) — refuse to build if red.
#
# Contract: the SMOKE_TESTS bash array below is the manifest. Every entry
# MUST exist on disk before pytest runs (existence pre-flight loop); pytest
# silently skips missing paths, so the pre-flight is mandatory (ADR-0007).
# There is intentionally no --skip-smoke flag: shipping a broken bundle
# requires editing this section in build.sh.
#
# Manifest tiers (in array order):
#   - tier-4/5 e2e: full/multi-cycle against run_cycle_steps + fake agents
#   - tests/_helpers/: fake_agent contract surface the e2e suite depends on
#   - tier-2 contracts: prompt↔validator, validate_cycle variants, probes, etc.
# Two build-meta tests are commented out pending spec 024 US3 restoration.
# See specs/019-pipeline-architecture/spec.md US1 and ADR-0007.
# ---------------------------------------------------------------------------
# Lint baseline guard (MONDAY §1.5 — locks in the ruff-format pass landed in
# chore/post-foundation-housekeeping). Runs BEFORE the smoke test suite so a
# format drift fails fast and cheap — no point spending ~5 minutes on the
# full smoke gate if the diff itself is unformatted. `ruff check` is already
# at zero errors (per the 0.2.33 baseline reset), so we add it here too for
# symmetry. Both are non-skippable per ADR-0007.
# ---------------------------------------------------------------------------
echo "[build] running lint baseline (ruff check + ruff format --check) — non-skippable."
# Invoked through PYTHON_BIN like every other tool in this script, not as a
# bare `ruff`. ruff lives in the project venv, so a bare call only resolves
# when that venv happens to be ACTIVE on PATH — build.sh is run directly (and
# by tests/quality/test_build_script_quality_flag.py) without activation,
# where it died at line 101 with "ruff: command not found" and exit 127,
# before the gate it guards ever ran.
"${PYTHON_BIN}" -m ruff check .
"${PYTHON_BIN}" -m ruff format --check .

echo "[build] running smoke gate (feature 018 + spec-019 extension) — this is mandatory."
SMOKE_TESTS=(
    # Original tier-4/5 e2e suite (feature 018):
    "tests/pipeline/test_full_cycle_e2e.py"
    "tests/pipeline/test_multi_cycle_e2e.py"
    "tests/_helpers/"
    # Spec-019 extension — tier-2 contract tests:
    "tests/scripts/test_prompt_validator_contract.py"
    "tests/scripts/test_validate_cycle_research_schema.py"
    "tests/scripts/test_validate_cycle_source_file_shapes.py"
    "tests/scripts/test_validate_cycle_budget_aliases.py"
    "tests/scripts/test_validate_cycle_sources_consulted.py"
    "tests/scripts/test_validate_cycle_termination_fields.py"
    "tests/scripts/test_validate_spec.py"
    "tests/scripts/test_check_abstraction.py"
    "tests/scripts/test_quality_report.py"
    "tests/scripts/test_probe_runner.py"
    "tests/pipeline/test_preconditions_resume.py"
    "tests/pipeline/test_resume_phase3_completion.py"
    # Spec-019 / 0.2.29 — scout-validation correction loop:
    "tests/scripts/test_validate_cycle_sidecar.py"
    "tests/pipeline/test_cycle_runner_scout_correction.py"
    "tests/build/test_install_wizard_skip_redundant_questions.py"
    "tests/build/test_smoke_gate_enforces_contract_tier.py"
    # 0.3.2 post-mortem (spec 022 + 025) — tier-6 fake-agent interception gate.
    # This is the canonical "no live claude/codex during fixture cycles"
    # assertion (Principle IV runtime guarantee). It catches in-process
    # dispatch bugs that the static LLM-dispatch-guard (tier 2) cannot —
    # specifically the kind of bug the 0.3.2 hotfix in plan_narrator /
    # _cycle_helpers fixed. Marked @pytest.mark.e2e + @pytest.mark.slow,
    # so it does NOT run in `pytest -m "not e2e"`; the smoke gate selects
    # by file path so the markers do not apply here. ~7s wall-clock.
    "tests/quality/test_fake_agent_interception.py"
    # Spec 026 (US1 / SC-005): the quality harness must run against an isolated
    # copy and leave the tracked fixture tree pristine. This guards both the
    # run_fixture_cycles (pytest) and the `python -m …quality.runner` (the path
    # THIS script's --quality flag invokes) seams so a future in-place-mutation
    # regression hard-fails the build instead of silently dirtying git.
    "tests/quality/test_fixture_isolation.py"
    # Spec 068 (FR5): coverage is a disk recompute, not a stale per-cycle
    # increment. A multi-category vault carrying the rc7 stale-count shape must
    # report non-zero coverage after recompute (digest snapshot + harness metric)
    # — guards against the ``0% → 0%`` regression returning. Fast tier-2 (<1s).
    "tests/quality/test_coverage_recompute_regression.py"
    # Spec 067 (T029): the rc7 acronym corruption ([[cache-aside pattern]] renaming
    # a CAP Theorem note's own title) must be flagged by the deterministic verifier
    # gate; a clean note stays silent. Guards against the title-corruption regression
    # returning. Fast tier-2 (<1s).
    "tests/quality/test_wikilink_corruption_regression.py"
    # Spec 027 (FR-010 / SC-005): ./vault update pre-flight existence loop +
    # topology / health / dirty-tree / short-circuit guard. Fast CLI test
    # (<15s); a release must never ship an update path that silently breaks
    # vault upgrades.
    "tests/cli/test_vault_update.py"
    # Spec 048 v1.1 (FR-013/014/016): health header, print allowlist, vault status.
    "tests/observability/test_log_surfaces.py"
    "tests/observability/test_health_header.py"
    "tests/observability/test_vault_status.py"
)

# Existence pre-flight (hardening — feature 018 + 2026-05-20 triage #9;
# see docs/TODO.md#restoration-notes for the triage's other surviving items).
#
# pytest silently skips paths that don't exist. That is exactly how the
# two `tests/build/*` entries above stopped being enforced at some point
# between 0.2.28 and 0.2.32: their files vanished from the working tree
# without anyone noticing, and the smoke gate kept reporting green. To
# guarantee that category of regression can never happen silently again,
# every entry in SMOKE_TESTS MUST exist on disk before pytest is invoked.
# A missing entry is a build-stopping error — restore the file, or remove
# the entry from SMOKE_TESTS with a comment explaining why.
for smoke_path in "${SMOKE_TESTS[@]}"; do
    if [[ ! -e "${ROOT_DIR}/${smoke_path}" ]]; then
        echo "[build] ERROR: smoke-gate entry missing from disk: ${smoke_path}" >&2
        echo "[build] pytest would silently skip this. Either restore the" >&2
        echo "[build] file or remove the entry from SMOKE_TESTS with a" >&2
        echo "[build] comment explaining the deletion." >&2
        exit 1
    fi
done

if ! "${PYTHON_BIN}" -m pytest "${SMOKE_TESTS[@]}" -q --tb=short; then
    echo ""
    echo "[build] ERROR: smoke gate failed — refusing to build bundle." >&2
    echo "[build] Failing test files are listed above; re-run with -v for" >&2
    echo "[build] full diagnostics:" >&2
    echo "[build]   ${PYTHON_BIN} -m pytest ${SMOKE_TESTS[*]} -v" >&2
    echo "[build] See specs/019-pipeline-architecture/spec.md US1 for which" >&2
    echo "[build] tier-2 contracts the gate enforces and why." >&2
    exit 1
fi
echo "[build] smoke gate passed."
echo ""

# ---------------------------------------------------------------------------
# 0b. Quality harness (spec 022) — optional, runs only after smoke is green.
# ---------------------------------------------------------------------------
if [[ "${RUN_QUALITY}" -eq 1 ]]; then
    echo "[build] running quality harness (spec 022) — smoke gate already passed."
    QUALITY_ARGS=()
    if [[ -n "${QUALITY_FIXTURE}" && "${QUALITY_FIXTURE}" != "all" ]]; then
        QUALITY_ARGS+=(--fixture "${QUALITY_FIXTURE}")
    fi
    if [[ "${QUALITY_NO_COLOR}" -eq 1 ]]; then
        QUALITY_ARGS+=(--no-color)
    fi
    QUALITY_RUNNER_CMD="${QUALITY_RUNNER_CMD:-${PYTHON_BIN} -m research_framework.quality.runner}"
    # QUALITY_ARGS is empty for a plain `--quality`. bash < 4.4 (macOS ships
    # 3.2 as /bin/bash) treats "${ARR[@]}" on an empty array as an unbound
    # variable under `set -u`; the `+` form expands to nothing instead.
    # shellcheck disable=SC2086
    if ! ${QUALITY_RUNNER_CMD} ${QUALITY_ARGS[@]+"${QUALITY_ARGS[@]}"}; then
        echo ""
        echo "[build] ERROR: quality harness failed — refusing to build bundle." >&2
        exit 1
    fi
    echo "[build] quality harness passed."
    echo ""
fi

# Test-only: skip wheel packaging after smoke (+ optional quality) for tier-6 tests.
if [[ "${RESEARCH_FRAMEWORK_BUILD_TEST:-}" == "1" ]]; then
    echo "[build] RESEARCH_FRAMEWORK_BUILD_TEST=1 — skipping wheel bundle."
    exit 0
fi

# ---------------------------------------------------------------------------
# 1. Read version from pyproject.toml — single source of truth.
# ---------------------------------------------------------------------------
VERSION="$(
    "${PYTHON_BIN}" - <<'PY'
import re, pathlib
text = pathlib.Path("pyproject.toml").read_text(encoding="utf-8")
m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
if not m:
    raise SystemExit("ERROR: could not read version from pyproject.toml")
print(m.group(1))
PY
)"

BUNDLE_NAME="research-framework-${VERSION}"
BUNDLE_DIR="${BUNDLE_ROOT}/${BUNDLE_NAME}"
TARBALL="${BUILD_DIR}/${BUNDLE_NAME}.tar.gz"

echo "[build] research-framework ${VERSION}"
echo "[build] bundle root → ${BUNDLE_DIR}"

# ---------------------------------------------------------------------------
# 2. Clean previous build outputs. Preserve ./build/ itself (gitignored).
# ---------------------------------------------------------------------------
rm -rf "${WHEEL_DIR}" "${BUNDLE_ROOT}" "${TARBALL}"
mkdir -p "${WHEEL_DIR}" "${BUNDLE_DIR}"

# ---------------------------------------------------------------------------
# 3. Build the Python wheel in an isolated environment.
#    Uses `python -m build` when available (PEP 517 isolated build), falling
#    back to `pip wheel` so the script runs on vanilla Python installs too.
#
#    NOTE: we run the build command from a scratch directory, because this
#    repo has a local `./build/` folder that would otherwise shadow the
#    PyPA `build` module via namespace-package discovery. Running from an
#    empty cwd and passing srcdir/outdir as absolute paths avoids that.
# ---------------------------------------------------------------------------
echo "[build] building wheel"
BUILD_CWD="$(mktemp -d)"
trap 'rm -rf "${BUILD_CWD}"' EXIT

if "${PYTHON_BIN}" -c 'import build.__main__' 2>/dev/null; then
    (cd "${BUILD_CWD}" && "${PYTHON_BIN}" -m build --wheel \
        --outdir "${WHEEL_DIR}" "${ROOT_DIR}")
else
    echo "[build] 'build' module not installed; falling back to 'pip wheel'"
    (cd "${BUILD_CWD}" && "${PYTHON_BIN}" -m pip wheel --no-deps \
        --wheel-dir "${WHEEL_DIR}" "${ROOT_DIR}")
fi

# shellcheck disable=SC2012 # build emits one controlled-name wheel; ls|head is intentional and find would reorder
WHEEL_FILE="$(ls "${WHEEL_DIR}"/research_framework-*.whl | head -n 1)"
if [[ -z "${WHEEL_FILE}" ]]; then
    echo "ERROR: wheel build produced no output in ${WHEEL_DIR}" >&2
    exit 2
fi
echo "[build] wheel: $(basename "${WHEEL_FILE}")"

# ---------------------------------------------------------------------------
# 4. Stage the bundle.
#    Everything an end-user needs at runtime gets copied here; nothing else.
#    Specifically excluded: src/, tests/, .git/, .venv/, specs/, dist-templates/
#    (dist-templates is the *source* of the shell scripts we re-copy below).
# ---------------------------------------------------------------------------
echo "[build] staging bundle"

# 4a. The wheel (top level, so install.sh finds it by glob).
cp "${WHEEL_FILE}" "${BUNDLE_DIR}/"

# 4b. Runtime support folders. Each is part of the runtime contract:
#     - scripts/   — copied into every generated vault
#     - templates/ — Jinja2 vault scaffolds
#     - .agents/   — skills consumed by the orchestrator
#     - examples/  — sample research.spec.md the user edits
_copy_tree() {
    local src="$1"
    local dst="$2"
    if [[ -d "${src}" ]]; then
        rm -rf "${dst}"
        # -a preserves modes, -L dereferences symlinks (none expected but safe).
        cp -aL "${src}" "${dst}"
    else
        echo "WARN: ${src} missing; skipping" >&2
    fi
}

_copy_tree "${ROOT_DIR}/scripts"    "${BUNDLE_DIR}/scripts"
_copy_tree "${ROOT_DIR}/templates"  "${BUNDLE_DIR}/templates"
_copy_tree "${ROOT_DIR}/.agents"    "${BUNDLE_DIR}/.agents"
_copy_tree "${ROOT_DIR}/examples"   "${BUNDLE_DIR}/examples"

# 4c. Single-file config + docs.
cp "${ROOT_DIR}/settings.yaml"                 "${BUNDLE_DIR}/settings.yaml"
cp "${ROOT_DIR}/settings.codex.yaml"           "${BUNDLE_DIR}/settings.codex.yaml"
cp "${ROOT_DIR}/settings.cursor.yaml"          "${BUNDLE_DIR}/settings.cursor.yaml"
cp "${ROOT_DIR}/settings.cursor-claude.yaml"   "${BUNDLE_DIR}/settings.cursor-claude.yaml"
cp "${ROOT_DIR}/settings.opencode.yaml"        "${BUNDLE_DIR}/settings.opencode.yaml"
cp "${ROOT_DIR}/settings.ollama.yaml"          "${BUNDLE_DIR}/settings.ollama.yaml"
cp "${ROOT_DIR}/dist-templates/install.sh"     "${BUNDLE_DIR}/install.sh"
cp "${ROOT_DIR}/dist-templates/generate.sh"    "${BUNDLE_DIR}/generate.sh"
cp "${ROOT_DIR}/dist-templates/update.sh"      "${BUNDLE_DIR}/update.sh"
cp "${ROOT_DIR}/dist-templates/README.md"      "${BUNDLE_DIR}/README.md"

# 4d. Version stamp — easy to `cat VERSION` inside the bundle for debugging.
echo "${VERSION}" > "${BUNDLE_DIR}/VERSION"

# 4e. Executable bits on shell scripts (cp on some filesystems drops them).
chmod +x \
    "${BUNDLE_DIR}/install.sh" \
    "${BUNDLE_DIR}/generate.sh" \
    "${BUNDLE_DIR}/update.sh"
# The glob can match nothing (since #298 the framework ships no vault shell
# scripts); an unmatched glob leaves the literal, and under `set -e` a false
# `[[ -f ]]` as the loop body's last command would abort the build.
for sh in "${BUNDLE_DIR}/scripts"/*.sh; do
    [[ -f "${sh}" ]] || continue
    chmod +x "${sh}"
done

# ---------------------------------------------------------------------------
# 5. Strip caches that snuck in via copy (they balloon the tarball).
# ---------------------------------------------------------------------------
find "${BUNDLE_DIR}" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "${BUNDLE_DIR}" -name "*.pyc"        -type f -delete 2>/dev/null || true
find "${BUNDLE_DIR}" -name ".DS_Store"    -type f -delete 2>/dev/null || true

# ---------------------------------------------------------------------------
# 6. Pack the tarball. `gtar` on macOS preserves UIDs; plain `tar` is fine too.
# ---------------------------------------------------------------------------
echo "[build] packing ${TARBALL}"
tar -C "${BUNDLE_ROOT}" -czf "${TARBALL}" "${BUNDLE_NAME}"

TARBALL_SIZE="$(du -h "${TARBALL}" | awk '{print $1}')"

# ---------------------------------------------------------------------------
# 7. Summary.
# ---------------------------------------------------------------------------
echo ""
echo "[build] done."
echo ""
echo "  wheel    : ${WHEEL_FILE}"
echo "  bundle   : ${BUNDLE_DIR}"
echo "  tarball  : ${TARBALL}  (${TARBALL_SIZE})"
echo ""
echo "Smoke-test locally:"
echo "  tar -xzf ${TARBALL} -C /tmp"
echo "  cd /tmp/${BUNDLE_NAME} && ./install.sh"
