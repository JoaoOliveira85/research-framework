# Contract — `install_summary.json` + machine-readable log lines

Covers **FR-013** (the install audit JSON) and **FR-012** (the grep-able status
line grammar that spec 009's `ubuntu-latest` CI consumes).

## 1. `install_summary.json` (FR-013)

**Path**: `<TARGET>/_pipeline/install_summary.json`
**Write**: atomic (temp file + `mv` rename); created on **every** run, real or
dry. Re-run **overwrites** (idempotent — reflects the most recent attempt, never
appends history).

### Fields

| Field | Type | Notes |
|---|---|---|
| `framework_version` | string | The wheel version installed (or that *would* be, in dry-run). From the `research_framework-<v>-…whl` basename. |
| `installed_at` | string | ISO-8601 UTC, e.g. `2026-06-03T13:40:11Z`. |
| `os` | string | `darwin` \| `linux`. |
| `os_version` | string | Best-effort (`sw_vers -productVersion` / `uname -r`); `""` if undetectable. |
| `python_version` | string | e.g. `3.11.9` (the `PYTHON_BIN` actually used). |
| `package_manager` | string | `brew` \| `apt` \| `dnf` \| `pacman` \| `apk` \| `none`. |
| `target_dir` | string | Absolute resolved `TARGET`. |
| `root_dir` | string | Absolute `ROOT_DIR` (bundle/tmpdir; wheel source). |
| `dry_run` | bool | `true` when `--dry-run`/`INSTALL_DRY_RUN=1`. |
| `warnings` | array<string> | Human-readable WARN messages emitted this run. |
| `degraded_modes` | array<string> | Dep names that hit their WARN/INFO tier and were skipped (e.g. `["claude","weasyprint"]`). |
| `exit_status` | string | `ok` \| `degraded` \| `failed`. |

### Example
```json
{
  "framework_version": "0.8.0",
  "installed_at": "2026-06-03T13:40:11Z",
  "os": "linux",
  "os_version": "6.8.0-31-generic",
  "python_version": "3.11.9",
  "package_manager": "apt",
  "target_dir": "/home/me/my-vault",
  "root_dir": "/tmp/rf-update-9k2x",
  "dry_run": false,
  "warnings": ["claude CLI not found — onboarding chat disabled (degraded)"],
  "degraded_modes": ["claude", "weasyprint", "gh"],
  "exit_status": "degraded"
}
```

### Rules
- `exit_status: ok` ⟺ all MANDATORY deps present and no WARN fired.
- `exit_status: degraded` ⟺ all MANDATORY present but ≥1 WARN/INFO dep missing.
- `exit_status: failed` ⟺ a MANDATORY dep missing or a fatal step failed. The
  file is still written (records the failure) **and** the script exits non-zero.
- In `dry_run: true`, `exit_status` reflects what the **real** install *would*
  produce (so CI can gate on it), and zero files other than this summary are
  written under `TARGET` (SC-002 measures the real-mode invariant; dry-run's own
  summary is exempt and lives under `_pipeline/`).

> **Dry-run note (resolves a self-consistency trap):** SC-002 ("`--dry-run` writes
> zero files") is asserted in tests by pointing the summary elsewhere
> (`INSTALL_SUMMARY_PATH=/dev/stdout` or a tmp path) OR by excluding
> `_pipeline/install_summary.json` from the `find` count. The contract is: dry-run
> performs **no install mutation**; emitting its own audit record is not a mutation
> of the vault's content.

## 2. Status line grammar (FR-012)

Every status-bearing line install.sh prints MUST start with one of these tokens
as the **first** whitespace-delimited field, so CI can `grep '^\[FAIL\]'`:

| Prefix | Meaning | Exit impact |
|---|---|---|
| `[FAIL]` | A MANDATORY dep/step failed. | Script exits non-zero. |
| `[WARN]` | A WARN-tier dep missing / recoverable issue. | Continue; `degraded`. |
| `[INFO]` | INFORMATIONAL-tier note. | Continue; `ok`. |
| `[dry-run]` | A mutating op suppressed in dry-run mode. | n/a. |

- Each `[FAIL]`/`[WARN]` line naming a missing dependency MUST include the exact
  install command for the detected `package_manager`, e.g.
  `[FAIL] python3.11 missing — install via: apt install python3.11`.
- These lines go to **stderr** for `[FAIL]`/`[WARN]`, **stdout** for `[INFO]`/`[dry-run]`.
- The existing `[install] …` progress prefix is unchanged and is NOT a status token.

## 3. Backward compatibility
- Vaults from before this spec have no `install_summary.json`; `./vault update`
  (027) MUST treat its absence as "legacy install, proceed" — never an error.
- The `[install] …` prefix and existing log lines are preserved verbatim so the
  v0.2.24 TTY tests and any log-scraping stay green.
