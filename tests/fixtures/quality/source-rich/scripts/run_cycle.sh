#!/usr/bin/env bash
# Run one research cycle: pre-metrics → scout (BFS) → validate → research (DFS)
#                        → validate vault → validate research → post-metrics.
#
# Args:
#   $1 = cycle number (1-indexed; formatted as 3-digit in output paths)
#   $2 = vault directory (absolute path; defaults to $(pwd))
#   $3 = max cycles (default: 5)
#   $4 = budget cap USD (default: 250)
#
# Exit codes (propagated from validate_cycle.py):
#   0 — CONTINUE (proceed to next cycle)
#   1 — TERMINATE (Condition A, B, or C satisfied)
#   2 — ABORT (structural error; do not proceed)
#
# Environment:
# Agent runtime is picked from `<vault>/settings.yaml` via `scripts/agent_call.py`
# — NOT hardcoded in this script. That's how the `--settings codex|claude`
# generator flag actually reaches the orchestrator.
#
# Environment:
#   CLAUDE_BIN / CODEX_BIN  — override the binary path for the respective CLI.
#   AGENT_CALL_DEBUG=1      — print the resolved runtime/model for each stage.
#
# Prompts are read from `_pipeline/prompts/{scout,dfs}-prompt.md` (rendered at
# generation time from the spec). Runtime placeholders `{CYCLE_NUM}`, `{SCOUT_REPORT}`,
# and `{RESEARCH_REPORT}` are substituted here, then piped into agent_call.py on
# stdin (avoids argv length limits and shell-escape hell for large prompts).

set -euo pipefail

CYCLE="${1:-1}"
VAULT_DIR="${2:-$(pwd)}"
MAX_CYCLES="${3:-5}"
BUDGET_CAP="${4:-250}"

# Python interpreter used for every helper script in this cycle. The
# orchestrator exports RV_PYTHON pointing at the bundle venv's python
# (which has PyYAML + research_framework installed). Without this we'd fall
# back to system python3, which may lack PyYAML and make agent_call.py
# blow up. Falling back to `python3` still works for dev-mode runs
# against a checkout where the system Python happens to have PyYAML.
PYTHON_BIN="${RV_PYTHON:-python3}"

PIPELINE_DIR="${VAULT_DIR}/_pipeline"
CYCLES_DIR="${PIPELINE_DIR}/cycles"
PROMPTS_DIR="${PIPELINE_DIR}/prompts"
SCRIPTS_DIR="${VAULT_DIR}/scripts"
CYCLE_3="$(printf '%03d' "${CYCLE}")"

SCOUT_REPORT="${CYCLES_DIR}/cycle-${CYCLE_3}-scout.json"
RESEARCH_REPORT="${CYCLES_DIR}/cycle-${CYCLE_3}-research.json"
PRE_METRICS="${CYCLES_DIR}/cycle-${CYCLE_3}-pre-metrics.json"
POST_METRICS="${CYCLES_DIR}/cycle-${CYCLE_3}-post-metrics.json"

mkdir -p "${CYCLES_DIR}"

bar='============================================================'
echo "$bar"
echo "RESEARCH CYCLE ${CYCLE}/${MAX_CYCLES}"
echo "Budget cap: \$${BUDGET_CAP}"
echo "Vault: ${VAULT_DIR}"
echo "$bar"

# --- Step 0: pre-cycle metrics ---
echo ""
echo "[Step 0] Capturing pre-cycle vault metrics..."
"${PYTHON_BIN}" "${SCRIPTS_DIR}/vault_metrics.py" "${VAULT_DIR}" --output "${PIPELINE_DIR}/vault-metrics.json"
cp "${PIPELINE_DIR}/vault-metrics.json" "${PRE_METRICS}"

# --- Step 1: scout (BFS) ---
echo ""
echo "[Step 1] Running scout (BFS)..."

if [[ ! -f "${PROMPTS_DIR}/scout-prompt.md" ]]; then
    echo "ERROR: scout prompt missing at ${PROMPTS_DIR}/scout-prompt.md"
    echo "Re-run 'research-framework generate' to re-render prompts from the spec."
    exit 2
fi

SCOUT_PROMPT_FILE="${CYCLES_DIR}/cycle-${CYCLE_3}-scout-prompt.rendered.md"
sed \
    -e "s|{CYCLE_NUM}|${CYCLE}|g" \
    -e "s|{SCOUT_REPORT}|${SCOUT_REPORT}|g" \
    "${PROMPTS_DIR}/scout-prompt.md" > "${SCOUT_PROMPT_FILE}"

cd "${VAULT_DIR}"
"${PYTHON_BIN}" "${SCRIPTS_DIR}/agent_call.py" \
    --vault "${VAULT_DIR}" \
    --stage scout \
    --prompt-file "${SCOUT_PROMPT_FILE}" \
    --cost-sidecar "${CYCLES_DIR}/cycle-${CYCLE_3}-scout.cost.json" \
    2>&1 | tee "${CYCLES_DIR}/cycle-${CYCLE_3}-scout.log"

# --- Step 2: validate scout ---
echo ""
echo "[Step 2] Validating scout report..."

if [[ ! -f "${SCOUT_REPORT}" ]]; then
    echo "ERROR: scout report not written at ${SCOUT_REPORT}"
    echo "The agent may have ignored the output-path instruction."
    exit 2
fi

SCOUT_EXIT=0
"${PYTHON_BIN}" "${SCRIPTS_DIR}/validate_cycle.py" "${SCOUT_REPORT}" \
    --vault "${VAULT_DIR}" \
    --max-cycles "${MAX_CYCLES}" \
    --budget-cap "${BUDGET_CAP}" || SCOUT_EXIT=$?

if [[ ${SCOUT_EXIT} -eq 2 ]]; then
    echo "ABORT: scout report has structural errors. Fix and retry."
    exit 2
fi
if [[ ${SCOUT_EXIT} -eq 1 ]]; then
    echo "TERMINATE after scout — no DFS this cycle."
    # Still capture post-metrics so the cycle directory is complete
    "${PYTHON_BIN}" "${SCRIPTS_DIR}/vault_metrics.py" "${VAULT_DIR}" \
        --output "${POST_METRICS}"
    exit 1
fi

# --- Step 3: research (DFS) ---
echo ""
echo "[Step 3] Running research (DFS)..."

if [[ ! -f "${PROMPTS_DIR}/dfs-prompt.md" ]]; then
    echo "ERROR: dfs prompt missing at ${PROMPTS_DIR}/dfs-prompt.md"
    exit 2
fi

RESEARCH_PROMPT_FILE="${CYCLES_DIR}/cycle-${CYCLE_3}-dfs-prompt.rendered.md"
sed \
    -e "s|{CYCLE_NUM}|${CYCLE}|g" \
    -e "s|{SCOUT_REPORT}|${SCOUT_REPORT}|g" \
    -e "s|{RESEARCH_REPORT}|${RESEARCH_REPORT}|g" \
    "${PROMPTS_DIR}/dfs-prompt.md" > "${RESEARCH_PROMPT_FILE}"

"${PYTHON_BIN}" "${SCRIPTS_DIR}/agent_call.py" \
    --vault "${VAULT_DIR}" \
    --stage note_writer \
    --prompt-file "${RESEARCH_PROMPT_FILE}" \
    --cost-sidecar "${CYCLES_DIR}/cycle-${CYCLE_3}-research.cost.json" \
    2>&1 | tee "${CYCLES_DIR}/cycle-${CYCLE_3}-research.log"

# --- Step 4: post-DFS validation suite (report-only; does not halt the cycle) ---
# Per constitution: validate_cycle.py drives CONTINUE/TERMINATE/ABORT.
# validate_vault.py / check_template_compliance.py / check_acronym_links.py
# report quality issues for later correction — they MUST NOT halt the cycle.
echo ""
echo "[Step 4] Post-DFS validation suite (report-only)..."
VV_RC=0
"${PYTHON_BIN}" "${SCRIPTS_DIR}/validate_vault.py" "${VAULT_DIR}" || VV_RC=$?
TC_RC=0
"${PYTHON_BIN}" "${SCRIPTS_DIR}/check_template_compliance.py" "${VAULT_DIR}" || TC_RC=$?
AC_RC=0
"${PYTHON_BIN}" "${SCRIPTS_DIR}/check_acronym_links.py" "${VAULT_DIR}" || AC_RC=$?
# Feature 002 — code-first validators. Skip silently if the scripts aren't
# present (back-compat with v0.1 vaults that predate this feature).
ID_RC=0
if [[ -f "${SCRIPTS_DIR}/check_intent_drift.py" ]]; then
    "${PYTHON_BIN}" "${SCRIPTS_DIR}/check_intent_drift.py" "${VAULT_DIR}" || ID_RC=$?
fi
CS_RC=0
if [[ -f "${SCRIPTS_DIR}/check_code_source_coverage.py" ]]; then
    "${PYTHON_BIN}" "${SCRIPTS_DIR}/check_code_source_coverage.py" "${VAULT_DIR}" || CS_RC=$?
fi
if [[ ${VV_RC} -ne 0 || ${TC_RC} -ne 0 || ${AC_RC} -ne 0 || ${ID_RC} -ne 0 || ${CS_RC} -ne 0 ]]; then
    echo "[Step 4] Quality violations reported (vault=${VV_RC} template=${TC_RC} acronym=${AC_RC} drift=${ID_RC} code_source=${CS_RC}) — cycle continues."
fi

# --- Step 5: post-metrics + validate research ---
echo ""
echo "[Step 5] Capturing post-cycle vault metrics..."
"${PYTHON_BIN}" "${SCRIPTS_DIR}/vault_metrics.py" "${VAULT_DIR}" \
    --output "${PIPELINE_DIR}/vault-metrics.json"
cp "${PIPELINE_DIR}/vault-metrics.json" "${POST_METRICS}"

if [[ ! -f "${RESEARCH_REPORT}" ]]; then
    echo "ERROR: research report not written at ${RESEARCH_REPORT}"
    exit 2
fi

echo ""
echo "[Step 6] Validating research report..."
RESEARCH_EXIT=0
"${PYTHON_BIN}" "${SCRIPTS_DIR}/validate_cycle.py" "${RESEARCH_REPORT}" \
    --vault "${VAULT_DIR}" \
    --max-cycles "${MAX_CYCLES}" \
    --budget-cap "${BUDGET_CAP}" || RESEARCH_EXIT=$?

# --- Step 7: topic harvest (Phase 1; deterministic, always runs, best-effort) ---
if [[ ${RESEARCH_EXIT} -ne 2 ]]; then
    echo ""
    echo "[Step 7] Topic harvest — Phase 1 (wikilinks + coverage gaps)..."
    "${PYTHON_BIN}" "${SCRIPTS_DIR}/topic_harvest.py" "${VAULT_DIR}" "${CYCLE}"
fi

# --- Step 7b: topic propose (Phase 2; agent, opt-in, best-effort) ---
# Independent from Phase 1 — runs only when stages.topic_propose.enabled=true
# in settings.yaml. Writes its own manifest (cycle-NNN-propose.json) and
# its own managed block in research-backlog.md. Never fails the cycle:
# the script itself catches errors and exits 0.
if [[ ${RESEARCH_EXIT} -ne 2 ]]; then
    if [[ -f "${SCRIPTS_DIR}/topic_propose.py" ]]; then
        echo ""
        echo "[Step 7b] Topic propose — Phase 2 (agent, scope-bounded tangents)..."
        "${PYTHON_BIN}" "${SCRIPTS_DIR}/topic_propose.py" "${VAULT_DIR}" "${CYCLE}"
    fi
fi

echo ""
echo "$bar"
echo "CYCLE ${CYCLE} COMPLETE"
echo "$bar"
exit ${RESEARCH_EXIT}
