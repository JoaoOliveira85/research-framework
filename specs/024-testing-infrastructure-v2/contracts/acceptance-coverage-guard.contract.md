# Contract: Spec Acceptance Coverage Lint Guard

**Status**: v2 (issue #283 — fixed the numbered-G/W/T discovery gap and
added the evidence-existence check the guard never had; see Changes below)
**Tier**: 2 (markdown lint, fast local loop)
**Test file**: `tests/spec/test_acceptance_coverage_guard.py`
**Authority**: ADR-0008 § Spec acceptance coverage convention.
**Spec ratification**: 024 clarify Q4 — **strict at launch, no allowlist**.

### Changes since v1 (issue #283)

- **Discovery.** The numbered-G/W/T regex is now `re.DOTALL`-bounded to
  the current numbered item (was single-line, so any scenario wrapping
  `**When**`/`**Then**` onto a following line was silently invisible to
  the guard — specs 001, 002, 019, 020, 021 and 024 all use that shape).
- **Rollout grandfather, codified.** `docs/testing-strategy.md`'s
  non-retroactive rollout note ("Existing specs 001-19, 021 are annotated
  only when next touched") is now an explicit, named set in the guard
  (`_ROLLOUT_GRANDFATHERED_SPEC_DIRS`) rather than an accident of the
  discovery bug. It is not a general-purpose allowlist — Q4's "no
  allowlist" ratification still holds for anything discovered going
  forward; this only encodes a rollout decision the project already made
  in writing. It shrinks the way the LLM dispatch allowlist does: backfill
  one of the four in a dedicated PR and delete its entry.
- **Evidence existence.** A `path.py[::Symbol[::Symbol...]]` evidence
  citation is now resolved against the filesystem and parsed with `ast`:
  the file must exist, and if a symbol is named, a `def`/`class` of that
  name must exist somewhere in the file (nested-path match preferred;
  falls back to "exists anywhere in the module" so the corpus's existing
  `path.py::test_method` shorthand for a method nested in a test class
  keeps working). This is the check issue #283 flagged as entirely
  missing ("the guard never checks that the test it names exists").
- **Fail-closed discovery canary.** `test_discovery_is_not_vacuous` pins
  a floor on the discovered-spec count so a future regex regression that
  makes discovery under-count (or return nothing) fails loudly instead of
  silently passing the main test with zero failures (#278).
- **Known, documented non-goal.** The newer flat `## Acceptance` bullet
  format (no `### User Story` headings, no G/W/T) used by specs 073, 074
  and the 015b-h/016 family is still out of discovery scope — see
  `docs/adr/0012-acceptance-bullet-format-not-guarded.md` for why
  extending discovery to it was rejected for this issue and what closing
  it later would need.

---

## Purpose

A spec's `## Acceptance coverage` table is what makes each user
story's evidence (test paths, regression markers, or historical
references) traceable from the spec to the codebase. This guard
ensures that every spec which **declares** Given/When/Then
acceptance scenarios also **provides** the matching coverage table,
and that the rows in that table are non-empty and well-formed.

---

## Scope

### Scanned paths

```
specs/**/spec.md
```

### Excluded paths

- `specs/013-vault-migrator/spec.md` — tombstoned (retired in 0.2.33; preserved for git history). The exclusion is a one-line `# tombstoned` marker check, not an allowlist row.
- Any `specs/*/spec.md` that does NOT declare a Given/When/Then
  scenario in the body is **not in scope** — the guard skips them.
  The flat `## Acceptance` bullet format (073, 074, 015b-h, 016) is one
  such shape — see `docs/adr/0012-acceptance-bullet-format-not-guarded.md`.
- `specs/001-speckit-implementation`,
  `019-pipeline-architecture`, `021-spec-driven-coverage` — grandfathered
  by directory name (`_ROLLOUT_GRANDFATHERED_SPEC_DIRS`), per
  `docs/testing-strategy.md`'s non-retroactive rollout note. Not a general
  allowlist (see Changes since v1 above).
- The spec file's own line numbers and content otherwise are
  treated identically.

### Spec discovery (must-have G/W/T scenarios)

A spec (not excluded above) is **in scope** if its `spec.md` body
contains at least one line matching:

```regex
^\d+\.\s+\*\*Given\*\*(?:(?!^\d+\.\s).)*?\*\*When\*\*(?:(?!^\d+\.\s).)*?\*\*Then\*\*
```
(`re.MULTILINE | re.DOTALL`; the negative lookahead bounds the match to
the current numbered item so it can't run on into the next one)

OR

```regex
^\*\*Given\*\*.*?\*\*When\*\*.*?\*\*Then\*\*
```
(`re.MULTILINE`; single-line bare form)

OR standalone `**Given**` / `**When**` / `**Then**` lines all present
anywhere in the body (the multi-line bare fallback for specs like
015a's user scenarios).

(All three shapes appear in the existing spec corpus.)

If none appear, the spec is out of scope and the guard skips it.

---

## Required structure (in-scope specs)

An in-scope spec MUST contain a `## Acceptance coverage` section
matching:

```regex
^## Acceptance coverage\s*$
```

The section MUST contain a markdown table whose first column begins
with a user-story identifier (e.g. `US1 — `, `US2 — `, etc.). The
table MAY be preceded by free-form prose explaining the section's
purpose.

Each table row's second column (the "Evidence" column) MUST match
exactly one of these four forms:

| Form | Regex |
|---|---|
| Test path | `` `\S+\.py(::\S+)?` `` (one or more backtick-wrapped pytest paths in the cell) |
| Multiple test paths | Two or more test paths separated by `+` or "and" or commas |
| Historical reference | `_(historical — .+?)_` (italicized "historical" wrapper, free-form rationale) |
| Tasks.md deferral | `_(deferred to tasks.md.*?)_` (italicized "deferred" wrapper, optional detail) |

Rows that match none of these forms — including empty cells, plain
TODO strings, or non-italicized free-form notes — fail the guard.

**Test path / multiple test path rows are further checked for
existence** (issue #283 — the guard previously accepted any string
shaped like a test path without checking it resolved to anything). For
each `path.py[::Symbol[::Symbol...]]` reference in the cell:

1. `path.py` MUST exist under the repo root.
2. If a `::Symbol` chain follows, a `def`/`class` matching the exact
   nested chain is preferred; failing that, a `def`/`class` matching the
   *last* segment anywhere in the module also satisfies it (accepts the
   corpus's common `path.py::test_method` shorthand for a method that
   actually lives inside a test class).

Historical, deferred, and sibling-draft-prose cells are NOT existence
-checked — they are prose by design and may legitimately mention a file
that isn't a test.

---

## Coverage requirement

For every user story declared in the spec body (matched by `### User
Story <N> — ` or `### User Story <N> [^\n]+` heading), the spec
MUST have at least one row in the `## Acceptance coverage` table
whose first column starts with `US<N>`.

A user story declared in the spec but missing from the table is a
guard failure.

---

## Test behaviour

```python
def test_every_spec_with_gwt_has_acceptance_coverage():
    in_scope = discover_specs_with_gwt(SPECS_DIR)
    failures = []
    for spec_path in in_scope:
        problems = validate_acceptance_coverage(spec_path)
        if problems:
            failures.append((spec_path, problems))
    assert failures == [], format_failures(failures)
```

### Failure report format

```text
acceptance-coverage guard failed:

specs/_archive/015a-corpus-folder-name/spec.md
  - Missing `## Acceptance coverage` section.
    Add one per ADR-0008 § Spec acceptance coverage convention.

specs/029-foo/spec.md
  - User story US3 is declared in the body but absent from
    the `## Acceptance coverage` table.

specs/030-bar/spec.md
  - Row for US2 has empty evidence cell.
    Use a test path, multiple test paths, _(historical — ...)_,
    or _(deferred to tasks.md...)_.
```

---

## Allowlist

**There is no allowlist for violations.** Per Q4 ratification, the guard
ships strict: a spec that is discovered and lacks valid coverage is a
failure, full stop, with no per-spec opt-out. Pre-existing specs that
lacked the section were backfilled in the same PR that first discovered
them (FR-013 — 015a, 017, 018 at v1 launch; 020 at v2 / issue #283, once
the discovery bug that had been hiding it was fixed).

The one exception is `_ROLLOUT_GRANDFATHERED_SPEC_DIRS` (001, 002, 019,
021 — see Changes since v1 above), which is not a violation allowlist: it
codifies `docs/testing-strategy.md`'s own written, pre-existing
non-retroactive rollout decision for specs that predate the convention,
not a way to silence a spec the convention already applies to. It shrinks
the same way: backfill one in a dedicated PR, delete its entry.

If a future spec needs to ship without acceptance-coverage rows
(e.g. a doc-only spec with no G/W/T scenarios), the right answer is
to NOT declare G/W/T scenarios in the spec body — the guard then
correctly skips it.

---

## Runtime budget

< 5 seconds total over the full `specs/` tree (Assumptions). The
guard is a pure regex / state-machine pass over ~30 spec files at
clarify time; performance is bounded by `read_text()` and not by
parsing.

---

## Dogfood requirement (SC-009)

`specs/024-testing-infrastructure-v2/spec.md` MUST pass this guard
against itself. The dogfood section (Entity 3 row, form 4 —
`_(deferred to tasks.md…)_`) is a valid evidence form per the
contract; no allowlist needed.

---

## Amendment process

1. **Tightening** — if a new evidence form is added (e.g. a "code
   review only" form for spec-style decisions), the contract is
   amended via ADR. Backwards compatible — old rows keep passing.
2. **Loosening** — adding an allowlist would require explicit
   constitution-level discussion. The Q4 ratification position is
   "no allowlist is the convention".
3. **Schema change** — anything that changes Entity 3's row schema
   requires updating this contract AND the backfilled sections in
   FR-013 in the same PR.
