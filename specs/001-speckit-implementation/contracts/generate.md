# Contract: `speckit generate`

**Sub-command**: `speckit generate`
**Version**: v0.2+ (infrastructure); v0.3+ (--resume)

---

## Synopsis

```
speckit generate --spec <path> [--output <dir>] [--dry-run] [--resume] [--cycle <N>]
```

---

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `--spec` | path | Yes | — | Path to `vault-spec.md` |
| `--output` | path | No | `location` from spec | Override vault output directory |
| `--dry-run` | flag | No | off | Run Phase 0 + Phase 1 only; skip Phase 2 |
| `--resume` | flag | No | off | Skip Phase 0/1; check preconditions; enter Phase 2 |
| `--cycle` | int | No | auto | With `--resume`: start at a specific cycle number |

`--dry-run` and `--resume` are mutually exclusive.

---

## Behavior

### Without flags (full generation)

1. **Phase 0**: Parse and validate `--spec`. Exit code 2 on any validation error.
2. **Phase 1**: Create vault directory structure, render templates, copy scripts bundle.
   Run `pytest scripts/tests/` — **hard exit if tests fail** (not a warning).
3. **Phase 2**: Research cycles until termination + all coverage targets met.
4. **Phase 3**: Rebuild Layer 1, `git init`, generate `phase1-report.md`.

### With `--dry-run`

Runs Phase 0 + Phase 1 only. Stops after infrastructure generation and the pytest gate.
Produces a complete vault skeleton with no research content.

### With `--resume`

Skips Phase 0 and Phase 1. Reads the existing `_pipeline/spec-parse.json` from the vault.
Checks 5 preconditions before entering Phase 2:
1. `pytest scripts/tests/` passes in vault directory
2. `validate_vault.py` exits 0
3. `coverage-targets.json` exists and is valid
4. `budget-log.md` exists and is initialized
5. Naming convention declared in `CLAUDE.md`

If any precondition fails: prints a report of which preconditions are unmet. Exits with
code 1. Does not proceed.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Vault generated successfully; all phases complete |
| 1 | Phase 2 terminated with unmet coverage targets (targeted re-entry needed) |
| 2 | Fatal error: spec validation failed, pytest failed, or Phase 3 gate failed |

---

## Output Files (Phase 1)

```
{vault}/
├── CLAUDE.md                    # Rendered from CLAUDE.md.j2 with SpecConfig values
├── AGENTS.md                    # Rendered skeleton (topic index empty until Phase 2)
├── README.md                    # Rendered from README.md.j2
├── _templates/                  # One .md file per NoteTypeConfig
├── scripts/                     # Verbatim copy of speckit's scripts/ bundle
│   ├── validate_vault.py
│   ├── validate_cycle.py
│   └── ...
└── _pipeline/
    ├── spec-parse.json          # Machine-readable SpecConfig
    ├── coverage-targets.json    # Written from spec coverage targets
    ├── budget-log.md            # Initialized empty
    └── research-backlog.md      # Initialized empty
```

---

## Error Cases

| Condition | Exit | Output |
|-----------|------|--------|
| `--spec` path does not exist | 2 | "spec file not found: {path}" |
| Spec YAML parse failure | 2 | Line number + YAML error message |
| Required spec field missing | 2 | One line per missing field: "missing required field: {name}" |
| search_dimensions missing "domain" or "market" | 2 | "search_dimensions must include 'domain' and 'market'" |
| `pytest scripts/tests/` fails | 2 | Full pytest output + "Phase 1 gate failed" |
| `--dry-run` + `--resume` together | 2 | "error: --dry-run and --resume are mutually exclusive" |
| Phase 3 coverage check fails | 1 | List of unmet categories + targeted re-entry instructions |
