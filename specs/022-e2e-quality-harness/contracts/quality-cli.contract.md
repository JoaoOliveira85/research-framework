# Contract: `./build.sh --quality` and `./vault quality-baseline-update`

**Spec**: [`../spec.md`](../spec.md) FR-005, FR-007, FR-016
**Research**: [`../research.md`](../research.md) D8

Two surfaces touch the harness from the user side. This contract
pins both.

## 1. `./build.sh --quality`

### Surface

```bash
./build.sh --quality [--fixture <name>] [--no-color]
```

### Behaviour

| Step | Action |
|---|---|
| 1 | If `--quality` not supplied, current `build.sh` behaviour unchanged (smoke gate + wheel build). |
| 2 | If supplied, run the normal smoke gate FIRST. If smoke fails, exit before harness (preserving the existing failure mode). |
| 3 | After smoke green, invoke `python -m research_framework.quality.runner` with optional fixture filter. |
| 4 | Stream the runner's stdout (regression-report.contract § 3). |
| 5 | Exit with the runner's exit code (regression-report.contract § 2). |

### Flags

| Flag | Default | Effect |
|---|---|---|
| `--quality` | _absent_ | Toggle that adds the harness step. Idempotent — no-op when re-supplied. |
| `--fixture <name>` | `all` | Limit harness to one fixture. Valid: `tech-lite`, `source-poor`, `source-rich`, `all`. |
| `--no-color` | _auto_ | Disable ANSI colour in harness stdout. Auto-disabled when stdout is not a TTY. |

### Exit codes

Inherits the harness exit codes (regression-report.contract § 2):
`0` pass/warn, `1` regression fail, `2` harness crash. The smoke
gate's existing exit codes (which are also `0` pass / non-zero fail)
chain naturally: a failed smoke gate exits before the harness runs.

### Side effects

- Files: as listed in regression-report.contract § 4.
- Git state: unchanged. The harness MUST NOT `git add`, `git commit`,
  or modify any tracked files.

### Performance

Total `./build.sh --quality` wall-clock < 12 min on a recent Mac
(SC-006). Decomposed: smoke ~2 min + harness < 10 min.

---

## 2. `./vault quality-baseline-update`

### Surface

```bash
./vault quality-baseline-update <fixture> --reason "<text>" [--actor "<name>"] [--dry-run] [--yes]
```

### Behaviour

| Step | Action |
|---|---|
| 1 | Validate `<fixture>` against the registered fixture list. Reject unknown names with a clear error. |
| 2 | Run the harness for the named fixture only (single-fixture invocation, no diff). Produces `<fixture>.current.json`. |
| 3 | Compute the diff between `<fixture>.current.json` and the existing `<fixture>.baseline.json` (if any). |
| 4 | Print the diff to stdout in human-readable form. |
| 5 | If `--dry-run`, exit 0 without writing. |
| 6 | If interactive (TTY) and `--yes` not supplied, prompt: "Apply baseline update for <fixture>? [y/N]". |
| 7 | If confirmed, write the new baseline atomically: `<fixture>.baseline.json.tmp` → atomic rename → `<fixture>.baseline.json`. |
| 8 | Print the path of the written file and exit 0. |

### Flags

| Flag | Required | Default | Effect |
|---|---|---|---|
| `<fixture>` (positional) | yes | — | Fixture name. |
| `--reason "<text>"` | yes (unless `--dry-run`) | — | Persisted as `last_updated_reason`. Empty string rejected. |
| `--actor "<name>"` | no | `$GIT_AUTHOR_NAME` then `$USER` | Persisted as `last_updated_by`. |
| `--dry-run` | no | _absent_ | Show the diff that would be written; exit 0 without writing. Required by Constitution "Always Do" #2. |
| `--yes` | no | _absent_ | Skip interactive confirmation. For CI only; rejected if `$CI` is unset (loose protection). |

### Exit codes

- `0` — baseline updated (or dry-run succeeded).
- `1` — user declined the confirmation prompt.
- `2` — error (unknown fixture, harness crash during single-fixture
  run, missing `--reason` without `--dry-run`, etc.).

### Side effects

- Writes `tests/fixtures/quality/baselines/<fixture>.baseline.json`
  (the only codepath authorised by FR-007 and guarded by FR-012's
  guard test).
- Writes harness-run artifacts under `_pipeline/quality/` per § 1.

### Atomicity

- Baseline write uses tempfile-then-atomic-rename (`os.replace`).
- A `SIGINT`/`SIGTERM` mid-write MUST NOT leave a partial baseline
  file on disk (the existing file remains intact).

### Forbidden behaviours

- MUST NOT modify baselines for fixtures other than the one
  specified.
- MUST NOT modify fixture vault contents under
  `tests/fixtures/quality/<fixture>/`.
- MUST NOT auto-bump `schema_version` — version migrations are a
  separate manual step (baseline-schema.contract § 4).

---

## 3. `./vault quality-fixture-init` (helper, v1 stub)

Reserved subcommand name for v2 (when adding the missing 3
fixtures). In v1, the three fixtures are committed directly; this
subcommand exists as a stub that prints "fixture init is a v2
feature; for v1 fixtures use `./vault quality-baseline-update`
after editing the fixture by hand".

Documented here so v2 doesn't have to negotiate the name later.

---

## 4. Help text guarantee

`./build.sh --help` MUST mention `--quality` and link the spec.
`./vault quality-baseline-update --help` MUST be self-documenting
with examples. Both contribute to the
`docs/testing-strategy.md` § How to run each tier table.
