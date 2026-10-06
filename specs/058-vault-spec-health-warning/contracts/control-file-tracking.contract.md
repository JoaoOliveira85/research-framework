# Contract: Control-File Git Tracking (058)

Normative behaviour for `scripts/vault_health.py::scan_control_file_git_tracking()` and
its integration into `HealthReport` / `render_report()`.

## 0. Scope

- **In**: tracking status (untracked / ignored) for **present** control files in git-backed vaults.
- **Out**: file absence (skip), dirty/uncommitted state (spec 050), auto-`git add` (`--fix` deferred).

## 1. Critical control-file set (FR-002)

Fixed vault-relative paths (v1 — not configurable):

| # | Vault-relative path |
|---|---------------------|
| 1 | `research.spec.md` |
| 2 | `settings.yaml` |
| 3 | `_pipeline/research-backlog.md` |
| 4 | `_pipeline/coverage-targets.json` |

Constant name in implementation: `CONTROL_FILE_PATHS` (ordered as above for iteration;
warnings sorted by path for output).

**Absent file rule (FR-002a)**: if `(vault / rel_path).exists()` is false → **no warning,
no error** for that path.

## 2. Warning record shape

```python
@dataclass
class ControlFileTrackingWarning:
    rel_path: str       # vault-relative, forward slashes
    reason: str         # exactly "untracked" | "ignored"
```

**Reason priority**: if `git check-ignore -q` succeeds → `ignored` (even if also untracked).
Otherwise if `git ls-files --error-unmatch` fails → `untracked`. Otherwise → no record.

**MUST NOT** warn for tracked files with uncommitted modifications (index entry exists).

## 3. Git-backed detection

```
git -C <vault> rev-parse --is-inside-work-tree
```

- stdout stripped == `"true"` → proceed.
- any failure / other value / `git` missing on PATH → return `[]` (silent skip, FR-003).

All subsequent git invocations use `git -C <vault> …` with paths from §1 relative to vault root.

Per present file:

```
git -C <vault> check-ignore -q -- <rel_path>     # exit 0 → ignored
git -C <vault> ls-files --error-unmatch -- <rel_path>  # exit 0 → tracked; else untracked
```

**MUST NOT**: mutate git state (`add`, `commit`, `clean`).

## 4. HealthReport integration (FR-004)

- Field: `control_file_tracking: list[ControlFileTrackingWarning]`
- `HealthReport.unresolved_count` **MUST NOT** include `control_file_tracking` entries.
- `main()` exit code **MUST** depend only on `unresolved_count` (unchanged contract).

## 5. Report / stdout line format (FR-005)

Markdown section header:

```markdown
## Control-file git tracking
```

When zero warnings:

```markdown
all four present control files are tracked in git
```

(If zero warnings because vault is non-git or all files absent, section still renders the
all-clear line when git-backed and every **present** file is tracked; if non-git, section
reads `skipped (not a git work tree)`.)

Per warning (one bullet, sorted by `rel_path`):

```markdown
- WARN IGNORED settings.yaml
- WARN UNTRACKED research.spec.md
```

Tokens: `WARN`, reason uppercased, then vault-relative path. No trailing punctuation required.

## 6. Determinism (FR-007 / SC-005)

- Iterate §1 in fixed order; emit warnings sorted by `rel_path`.
- No timestamps inside warning records.
- Same filesystem + git index state → identical `control_file_tracking` list and report section.

## 7. Test obligations (informative)

Hermetic tests MUST use `git init` under `tmp_path` and MUST NOT require network or global git config.

| Scenario | Expected |
|---|---|
| Git vault, `research.spec.md` untracked (present) | 1 warning, reason `untracked` |
| Git vault, `settings.yaml` in `.gitignore` | 1 warning, reason `ignored` |
| All four present + `git add` | 0 warnings |
| No `.git` directory | 0 warnings, silent |
| `run()` with wikilinks clean + tracking warnings | `main()` exit 0 |
| Two runs, same tree | byte-identical warning list |
