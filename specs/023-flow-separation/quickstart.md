# Quickstart: Feeds-Vault Revival — After Spec 023 Phase 1 Ships

**Audience**: Vault operator on the revival sprint critical path  
**Vault**: `$VAULT_DIR` (e.g. `/path/to/feeds-vault`). The reference vault for the revival sprint is the operator's personal `feeds-vault` (dormant since 2026-05-13; archaeology 2026-05-26 \u2014 see `docs/Feeds-VAULT-ARCHAEOLOGY.md`). Throughout this quickstart, replace `$VAULT_DIR` with the absolute path to your vault.  
**Prerequisite**: Manual pre-flight (venv + `pip install research-framework` + framework version \u2265 Phase 1 ship)

## What Phase 1 gives you

| Verb / guarantee | Problem solved |
|------------------|----------------|
| `./vault regenerate-shim` | Broken `./vault` with dead temp `VAULT_DIR` + `research_vault.cli` (F2) |
| `./vault refresh-sources` | Re-run legacy collectors before spec 020 youtube module ships |
| `./vault update` (hardened) | No longer wipes `scripts/collect_*.py` (F6) |
| Atomic research writes | Safe to run `./vault ask` while `./vault research` is running |

## Step 0 — Verify framework version

```bash
export VAULT_DIR=/path/to/your/vault    # e.g. ~/Documents/feeds-vault
cd "$VAULT_DIR"
.venv/bin/python -c "import research_framework; print(research_framework.__version__)"
```

Expect version \u2265 the release that ships spec 023 Phase 1.

## Step 1 — Fix the entry point (FR-014)

```bash
cd "$VAULT_DIR"

# Inspect without writing
./vault regenerate-shim --dry-run

# Repair shim (use --force if you previously hand-edited vault)
./vault regenerate-shim --force

# Confirm idempotency (optional)
./vault regenerate-shim --force
shasum -a 256 vault   # same hash on second run
```

**Verify**:

```bash
head -5 vault                    # VAULT_DIR must match $VAULT_DIR
grep research_framework vault    # NOT research_vault
./vault help                     # lists refresh-sources, regenerate-shim
```

## Step 2 — Refresh legacy sources (FR-013)

```bash
# Full collector sweep
./vault refresh-sources --verbose

# Or JSON for automation
./vault refresh-sources --json | jq .

# YouTube only (example)
./vault refresh-sources --only collect_youtube.py
```

**Verify**: new artefacts under `raw_data/` (per collector), exit code 0 or 1 (partial).

## Step 3 — Framework update without losing collectors (FR-015)

```bash
./vault update
# After update, collectors must still exist:
ls scripts/collect_*.py
shasum -a 256 scripts/collect_youtube.py   # compare to pre-update hash if paranoid
```

If `./vault update` still mis-targets vault root (spec 027), upgrade framework via pip in `.venv` and re-run Step 1 — **regenerate-shim remains the shim repair path**.

## Step 4 — First framework research cycle

```bash
./vault research
# In another terminal while cycle runs:
./vault ask "What changed in the last cycle?"    # may warn later (FR-016 Phase 2)
```

Phase 1 guarantees readers never see torn note files (FR-018); answers may reflect mid-cycle state.

## Step 5 — Hand off to spec 020

Once spec 020 Phase 1 lands the youtube module:

- Continue `./vault refresh-sources` for reddit/O'Reilly until those modules port.
- Migrate youtube to `modules/youtube/` per 020 plan; collectors become optional legacy.

## Troubleshooting

| Symptom | Action |
|---------|--------|
| `./vault: command not found` | `chmod +x vault` after regenerate-shim |
| `regenerate-shim` exit 2 "customized" | `--force` or restore from git |
| `refresh-sources` exit 2, no collectors | Ensure `scripts/collect_*.py` exist |
| Collectors fail individually | exit 1 + JSON `partial_failure`; fix per `stderr_tail` |
| `update` wiped scripts | File bug — FR-015 regression; restore from git snapshot branch |

## Related docs

- Archaeology evidence: `$VAULT_DIR/_pipeline/archaeology-2026-05-26.md` (for the operator's reference feeds-vault: `~/Documents/feeds-vault/_pipeline/archaeology-2026-05-26.md`)
- Contracts: `specs/023-flow-separation/contracts/`
- Full spec (Phase 2 deferred): `specs/023-flow-separation/spec.md`
