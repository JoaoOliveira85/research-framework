# Data Model: Spec 023 — Phase 1

**Scope**: FR-013, FR-014, FR-015, FR-018 entities only.  
**Deferred (Phase 2)**: `VaultHandle`, `active-sources.json`, `spec-fingerprint.json`, `in-loco-modules.json` — do not implement from this document.

---

## 1. Scaffold manifest entry (FR-015)

Source of truth: `dist-templates/scaffold-manifest.json` (framework) and optional vault snapshot `_pipeline/scaffold-manifest-snapshot.json`.

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `path` | string | yes | Vault-relative POSIX path (e.g. `scripts/agent_call.py`, `vault`) |
| `kind` | string | yes | `shell`, `python`, `yaml`, `markdown`, … |
| `template_version` | int | yes | Monotonic template version for overwrite decisions |
| `rendered_sha256` | string | yes | Hash of last known framework render at manifest build time |
| `is_user_owned_after_first_write` | bool | yes | If true + file exists → `LEAVE_ALONE` on update |

**Phase 1 manifest changes**:

| Path | Phase 1 flag | Notes |
|------|--------------|-------|
| `vault` | `false` (change from `true`) | Shim is framework scaffolding; regeneration via FR-014, not leave-alone trap |
| `scripts/agent_call.py`, `scripts/vault_health.py`, … | `false` | Framework may update shipped helpers |
| `scripts/collect_*.py` | **not listed** | Vault-local; protected by absence + merge copy |
| User-added `scripts/custom_collector.py` | **not listed** | Protected by absence + merge copy |

**Vault snapshot extension** (`_pipeline/scaffold-manifest-snapshot.json`):

```json
{
  "framework_version": "0.3.2",
  "captured_at": "ISO-8601",
  "entries": [ "... copy of dist entries at update time ..." ],
  "scripts_user_owned": [
    "scripts/collect_youtube.py",
    "scripts/collect_oreilly.py"
  ]
}
```

`scripts_user_owned` is append-only discovery: any `scripts/*.py` not matching a framework-shipped basename at update time.

---

## 2. Shim fingerprint (FR-014)

Path: `_pipeline/shim-fingerprint.json`

| Field | Type | Description |
|-------|------|-------------|
| `path` | string | Always `vault` (relative) |
| `sha256` | string | SHA-256 of last successful `regenerate-shim` output |
| `framework_version` | string | `pyproject` version at render time |
| `rendered_at` | string | ISO-8601 UTC |

Used for customization detection — **not** for stale-spec warnings (that's Phase 2 `spec-fingerprint.json`).

---

## 3. Refresh-sources summary (FR-013)

Emitted on stdout when `--json`; also logged to stderr in human mode.

| Field | Type | Description |
|-------|------|-------------|
| `vault` | string | Absolute vault root |
| `collectors` | array | Per-collector results |
| `collectors[].script` | string | Basename e.g. `collect_youtube.py` |
| `collectors[].status` | string | `ok` \| `failed` \| `skipped` |
| `collectors[].exit_code` | int | Subprocess return code |
| `collectors[].duration_s` | float | Wall time |
| `collectors[].raw_dirs` | string[] | Relative paths under `raw_data/` touched |
| `collectors[].stderr_tail` | string | Last 2 KiB stderr on failure |
| `partial_failure` | bool | true if any failed but ≥1 ok |

**Exit code mapping**: all ok → 0; any failed with ≥1 ok → 1; framework/orchestration error or all failed → 2.

---

## 4. Settings overlay (FR-013 optional)

Path: `settings.yaml`

```yaml
refresh_sources:
  collectors:   # optional ordered list of basenames
    - collect_youtube.py
    - reddit_rss.py
  timeout_s: 600  # per collector, optional
```

Loaded via `pipeline/settings.py::VaultSettings.extras` or typed extension in implementation — no schema change to `research.spec.md`.

---

## 5. Atomic-write file state machine (FR-018)

States for destination file `D`:

```text
[ABSENT] --write_start--> [TEMP_WRITING]
[TEMP_WRITING] --write+fsync--> [TEMP_COMPLETE]
[TEMP_COMPLETE] --os.replace--> [STABLE_NEW]
[STABLE_OLD] --os.replace--> [STABLE_NEW]   # readers see OLD or NEW, never torn
[TEMP_COMPLETE] --crash before replace--> [STABLE_OLD] + orphan temp
```

**Invariants**:
- Readers opening `D` never observe partial content.
- Temp files created with `dir=D.parent`, prefix `.atomic-`, suffix `.tmp`.
- JSON writes use UTF-8 + trailing newline for vault JSON conventions.

**Call sites (Phase 1 MUST migrate)**:

| Area | Files | Pattern today |
|------|-------|---------------|
| Cycle JSON | `pipeline/steps/research.py`, `postprocess.py`, `scout.py` | direct `write_text` |
| Pipeline state | `pipeline/runner.py` | local `_atomic_write_json` → delegate |
| Plans / narrator | `research_plan.py`, `plan_narrator.py` | local `_atomic_write_text` → delegate |
| Quality / coverage | `quality_report.py`, `coverage.py`, `correction.py` | local helpers → delegate |
| Verifier stamp | `verifier._stamp_frontmatter` | `.tmp` sibling rename → delegate |
| Wikilink fix | `wikilinks.py` note rewrite | direct `write_text` → delegate |
| Shim | `regenerate_shim.py` | `atomic_write.write_text` |

**Out of Phase 1 migration** (already atomic or read-only): `quality/report.py`, `quality/baseline_update.py` — may delegate later for DRY, not blocking.

---

## 6. Migration operation (existing — FR-015 interaction)

`scaffold_diff.compute_plan` operations unchanged structurally:

| `OpKind` | Meaning |
|----------|---------|
| `CREATE` | Manifest path missing on disk |
| `OVERWRITE` | Framework-owned, exists |
| `LEAVE_ALONE` | User-owned per manifest, exists |

Phase 1 adds **no new `OpKind`** — protection for unlisted `scripts/*.py` is enforced in `copy_scripts` + snapshot, not in diff matrix.

---

## Relationships

```text
dist-templates/scaffold-manifest.json
        │
        ├─► scaffold_diff.compute_plan ──► ./vault update apply
        │
        └─► copy_scripts merge (FR-015)

settings.yaml + research.spec.md
        │
        └─► regenerate_shim ──► vault (shim) + shim-fingerprint.json

scripts/collect_*.py
        │
        └─► refresh-sources ──► raw_data/<source>/
```
