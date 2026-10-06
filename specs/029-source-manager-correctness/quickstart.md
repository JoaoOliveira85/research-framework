# Quickstart: 029 Source Manager Correctness

## Reproduce Bug 1 (source-incidents.md never written) — before the fix

```python
# tmp_path vault with a required source; drive a mid-run degradation:
from research_framework.pipeline._cycle_helpers import notify_required_source_degraded
notify_required_source_degraded(vault_dir, "BrokenFeed", role="domain", reason="HTTP 503")

# BEFORE fix: _pipeline/source-incidents.md does NOT exist (the 2-arg call raised TypeError,
#             swallowed by the broad except → only a "[sources] mark_degraded failed" warning).
#             But _pipeline/cycles/cycle-NNN-source-incidents.json DOES exist (the working sidecar).
assert not (vault_dir / "_pipeline" / "source-incidents.md").exists()   # the bug

# AFTER fix (FR-001): the markdown log exists with the degraded line, AND the sidecar still exists.
```

## Reproduce Bug 2 (path-substring attribution) — before the fix

```python
# 3 sources A/B/C; 5 notes whose FRONTMATTER source_urls cite: A; B; C; A+B; (none).
# notes_created carries the file names/paths.
from research_framework.pipeline.source_manager import record_cycle
record_cycle(vault_dir, cycle_num=1, research_report={"notes_created": [...]} , notes_dir=...)

# BEFORE fix: notes_generated is whatever "url-in-filepath" coincidence yields (≈0 for most),
#             so consecutive_empty_cycles inflates and good sources get archived.
# AFTER fix (FR-002): sources.db notes_generated == A:2, B:2, C:1 (frontmatter truth).
```

## Run the regression suite

```bash
pytest tests/pipeline/test_source_manager_correctness.py -v
# SC-004 proof: revert the FR-001 one-liner locally → the incidents-file test MUST fail.
```

## Reconcile an already-corrupted production vault (FR-008)

Undoes the bug's durable harm — sources **wrongly archived** because their `consecutive_empty_cycles`
inflated under path-substring attribution.

```bash
# Read-only diff: which archived sources are actually still cited (no mutations):
python scripts/reconcile_source_metrics.py --vault ~/Documents/feeds-vault --dry-run
#   per-source table: name | status | consecutive_empty_cycles | cited_now | action
#   e.g.  HackerNews | archived | 4 | 12 | UN-ARCHIVE + reset streak

# Apply (writes ONLY sources.db; never the note tree):
python scripts/reconcile_source_metrics.py --vault ~/Documents/feeds-vault --apply
#   un-archives still-cited sources (status→active), resets their consecutive_empty_cycles→0;
#   genuinely-uncited sources are left untouched.

# Idempotency / zero-false-positive: on a vault that never ran the buggy code,
# --dry-run reports "no changes"; a second --apply is a no-op.
python scripts/reconcile_source_metrics.py --vault <clean-vault> --dry-run   # → no changes
```

## Sequencing note (049)
`notify_required_source_degraded` moves to `pipeline/_helpers/` under spec **049** (Wave 1).
Implement 029 **after 049 merges**; import the function (and patch targets) from its post-049
module path. The fix itself is unchanged — only the import location.
