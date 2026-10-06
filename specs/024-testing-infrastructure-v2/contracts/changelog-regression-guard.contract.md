# Contract: CHANGELOG Regression-Link Lint Guard

**Status**: v1 (spec 024 — Phase 2 implementation)
**Tier**: 2 (markdown lint, fast local loop)
**Test file**: `tests/spec/test_changelog_regression_links.py` *(to be created in Phase 2)*
**Authority**: ADR-0008 § Regression discipline.
**Spec ratification**: 024 clarify Q5 — **strict at launch, no allowlist**.

---

## Purpose

A `### Fixed` bullet in `CHANGELOG.md` that doesn't say which test
prevents the same bug from coming back is a bug-future-self. The
discipline rule (ADR-0008) is that every fix lands with either a
test reference or an explicit `(no test: …)` rationale. This guard
enforces the discipline.

---

## Scope

### Scanned paths

```
CHANGELOG.md
```

(Only the project's root CHANGELOG. Per-spec changelogs are not in
scope — they're free-form notes.)

### Scanned blocks

The guard parses `CHANGELOG.md` as a state machine over level-2
release headings:

| Heading shape | Treatment |
|---|---|
| `## [Unreleased]` | **Skipped** — annotations not required for in-flight work. |
| `## [X.Y.Z] - YYYY-MM-DD` | **Released** — all `### Fixed` bullets in scope. |
| `## [X.Y.Z]` (no date) | **Released** — same treatment. |
| Any other `## ` heading | Skipped (e.g. `## Versions`, `## Migration notes`). |

Inside a released block, only sub-blocks whose heading matches
`### Fixed` (possibly followed by a parenthetical or em-dash
descriptor) are in scope. `### Added`, `### Changed`, `### Removed`,
`### Security` are not.

`### Fixed` heading shapes that are in scope:

```regex
^### Fixed\s*$
^### Fixed\s*\(.+?\)\s*$              # e.g. "### Fixed (build infrastructure)"
^### Fixed\s+—\s+.+$                  # e.g. "### Fixed — validator (`scripts/...`)"
```

---

## Required annotation shape

Each leading bullet line under a `### Fixed` sub-block MUST carry
exactly one annotation from:

```regex
\(test: ([^)]+)\)
\(regression test: ([^)]+)\)
\(no test: ([^)]+)\)
```

| Annotation | Semantic | Path-existence check |
|---|---|---|
| `(test: <path>::<name>)` | A test exists that covers this fix. | YES — `<path>` MUST exist in the working tree at lint time. |
| `(regression test: <path>::<name>)` | A test was added *later* than the fix; covers regressions. | YES — same. |
| `(no test: <rationale>)` | No test exists; rationale is mandatory. | NO — rationale is free-form text. |

The annotation MAY appear anywhere on the leading bullet line —
beginning, middle, or end. Multi-line bullets (those with nested
`  - ` detail lines) are parsed on the leading line ONLY; the
annotation MUST be on that leading line.

---

## Bullet identification

A "bullet" is a line matching `^- ` directly under a `### Fixed`
sub-block. Nested continuation lines (`^  - ` or indented prose) are
considered detail of the previous bullet, not new bullets.

Empty lines and prose paragraphs inside a `### Fixed` sub-block are
ignored.

---

## Test behaviour

```python
def test_every_changelog_fixed_bullet_has_test_annotation():
    bullets = parse_changelog_fixed_bullets(CHANGELOG_PATH)
    failures = []
    for bullet in bullets:
        if bullet.block_is_unreleased:
            continue
        problems = validate_annotation(bullet)
        if problems:
            failures.append((bullet, problems))
    assert failures == [], format_failures(failures)
```

### Failure report format

```text
changelog-regression-link guard failed:

CHANGELOG.md:599  ## [0.2.10] - 2026-04-22
                  ### Fixed
                  line 612: "Fixed scout-validation race condition on slow disks."
                  - missing annotation. Add `(test: ...)`, `(regression test: ...)`,
                    or `(no test: <rationale>)`.

CHANGELOG.md:752  ## [0.2.15] - 2026-05-01
                  ### Fixed
                  line 758: "Fixed CLI exit code on partial-yield. (test: tests/path/that/does/not/exist.py::test_x)"
                  - test reference does not exist in the tree.
```

---

## Allowlist

**There is no allowlist.** Per Q5 ratification, the guard ships
strict. The 15 released-version `### Fixed` sections in
`CHANGELOG.md` at clarify time (~30-50 bullets total) are
backfilled in the SAME PR that adds the guard (FR-014).

If a historical bullet truly never had a test and writing one
retroactively is infeasible, `(no test: <rationale>)` is the
explicit escape hatch. It's an admission of coverage gap, not a
hidden one.

---

## Runtime budget

< 5 seconds total (Assumptions). `CHANGELOG.md` is ~1500 lines at
clarify time; a single-pass state machine completes in
milliseconds. The path-existence check for `(test: …)` and
`(regression test: …)` is a stat per referenced file — bounded by
the number of bullets, typically < 100.

---

## Interaction with FR-015 (synthetic-vault deletion)

After FR-014's backfill pass, any `(test: …)` or `(regression test:
…)` annotation that points at `tests/pipeline/test_e2e_synthetic_vault.py`
(deleted in US7) MUST be re-pointed at the equivalent tier-5
scenario in `tests/integration/test_cycle_e2e.py` from US6. The
guard's path-existence check enforces this naturally — if a
re-pointer is missed, the path-existence check fails and surfaces
the orphan annotation by line number.

---

## Amendment process

1. **New annotation form** — adding a fourth form (e.g. `(manual
   test: <runbook>)` for ops-only fixes) requires an ADR. Until
   that ADR ships, only the three forms above are valid.
2. **Schema change** — anything that changes Entity 4's regex
   shape requires updating this contract AND the backfilled
   annotations in FR-014 in the same PR.
3. **Loosening** — adding an allowlist would require explicit
   constitution-level discussion. The Q5 ratification position is
   "no allowlist is the convention".
