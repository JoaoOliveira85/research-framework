# Implementation Plan: Cross-Cycle Digest (Spec 035)

**Branch**: `035-cross-cycle-digest` · **Date**: 2026-06-03
**Spec**: [spec.md](./spec.md) · **Contract**: [contracts/digest-format.contract.md](./contracts/digest-format.contract.md) · **Research**: [research.md](./research.md)
**Status**: planned (post-clarify Q1-Q5). Wave 3 / rc1.

## Summary

Add a `./vault digest [--since|--last-*] [--output]` verb that renders a
deterministic, LLM-call-free weekly markdown roll-up: a Header + 7 content
sections (Strongest Signals, Gaps, New Notes by Category, Source Quality Drift,
Coverage Delta, Cost Summary, Cycle Index). All inputs are local artifacts
(filesystem cycle dirs + reports, `sources.db`, `coverage-targets.json`, 028 cost
sidecars, the 051 inbound-link index); git is used only for the run-level commit
range/dates (spec 050 squashes per-cycle commits). Integer composite ranker with
total-order tiebreakers guarantees byte-identical repeat runs.

## Technical Context

- **Language**: Python 3.11+. **Deps**: `jinja2` (already a dep — one template),
  stdlib `sqlite3`/`json`/`pathlib`/`argparse`/`subprocess` (git range). **No new
  runtime dependency** (Principle V).
- **New code**:
  - `src/research_framework/pipeline/digest/` package:
    - `__init__.py` — `build_digest(vault_dir, since, until) -> str`
    - `scope.py` — enumerate in-range cycles from the **filesystem** + resolve the
      git run range/dates (Q5).
    - `sections.py` — the 7 section builders (pure functions over loaded data).
    - `ranker.py` — the integer composite score (FR-007) + gap detector (FR-008)
      + drift signal (FR-006). Reuses `vault/indexer.inbound_link_counts`.
    - `render.py` — Jinja2 render of the loaded section models.
  - `src/research_framework/templates/digest.md.j2` — the single template.
  - `cli` `digest` verb (argparse wiring; `--since`/`--last-*`/`--output`).
- **Reused (read-only)**: `vault/indexer.inbound_link_counts` (051);
  `pipeline/source_manager` `source_cycles` + incidents (drift); the 028 sidecar
  shape; `cycle-NNN-quality-report.json` (coverage progress); `vault_commit`
  knowledge of the squash topology (Q5) — but the digest only *reads* git, it
  never writes (it is a pure consumer; spec 050 owns commits).
- **Storage**: output `_pipeline/cycles/`-adjacent at `_pipeline/digests/`.
- **Testing**: deterministic unit tests (ranker/gap/drift table-driven); a
  multi-cycle fixture vault for end-to-end; `tmp_path`-isolated (spec 026). Tier 2
  (deterministic) + a tier-5 e2e for the verb per ADR-0008.

## Constitution Check

| Principle | Status | Note |
|-----------|--------|------|
| IV — deterministic / no LLM self-assessment | ✅ PASS | FR-012/SC-004: zero agent dispatch; pure render. |
| V — no new runtime dependency | ✅ PASS | jinja2 + stdlib + sqlite3 (all present). |
| X — vault history append-only git | ✅ PASS | Digest only READS git; writes a file under `_pipeline/` (gitignored workspace) — no vault-history mutation. (If the user commits the digest, that rides the normal `vault_commit` path.) |
| VIII — fixtures are test data | ✅ PASS | New digest fixture is test data. |
| TDD | ✅ PLANNED | ranker/gap/drift + section tests first. |

No violations; no Complexity-Tracking entries.

## Project Structure (artifacts this spec produces)

```
specs/035-cross-cycle-digest/
├── spec.md                              # IMPLEMENT-READY
├── plan.md                              # this file
├── research.md                          # D1–D6 + audit table
├── contracts/digest-format.contract.md  # layout + formulas + determinism rules
├── checklists/requirements.md
└── tasks.md
```

## Phase 0 — Research ✅
[research.md](./research.md): Q1-Q5 locked; the spec↔code audit table reconciled
every data-plumbing claim against shipped artifacts (050/028/051/022) and
in-flight ones (030/055 = optional, not gates).

## Phase 1 — Design ✅
[contracts/digest-format.contract.md](./contracts/digest-format.contract.md): the
input table, CLI surface, the Header+7-section layout, the integer composite
ranker (with path tiebreaker), the gap/drift definitions, the filesystem cycle
index + run-squash ship SHA, and the determinism + robustness rules.

## Phase 2 — Task strategy (for `/speckit.tasks`)
- **TDD order**: ranker/gap/drift unit tests (table-driven from the contract) →
  `ranker.py` → `scope.py` (filesystem enumeration + git range) → `sections.py`
  builders → `render.py` + template → `cli` verb → end-to-end fixture test →
  determinism/offline tests → README cron note + doc-sync.
- **Fixture**: a vault with 3 cycles across a 1-week window (cycle dirs +
  quality-reports + a couple `cycle-N-report.md` + a small `sources.db` +
  `coverage-targets.json` + 028 sidecars). One note engineered to top "Strongest
  Signals"; one coverage category engineered to regress; one source engineered to
  drift. `tmp_path`-isolated (spec 026).
- **Performance** (SC-001 <5s): pure local reads + one render; trivially met;
  add a guard test that the fixture digest renders well under budget.

## Complexity & Risks
- **`cycle-NNN-quality-report.json` coverage shape** — Gaps needs per-cycle
  coverage *progress*; the exact field is validated at implement (research D-note).
  *Mitigation*: the gap detector takes a small adapter `coverage_progress(report)`;
  if the field is absent, Gaps degrades to "progress signal unavailable" rather
  than failing.
- **051 `inbound_link_counts` key shape** — keyed by note path/title; the ranker
  must match the digest's note identity. *Mitigation*: a single
  `note_key(path)` helper shared by ranker + section builders.
- **Squash-topology date mapping** — mapping a cycle to the run squash commit
  date requires associating cycles→run. *Mitigation*: filesystem is authoritative
  for cycle identity; git supplies the run window only — no per-cycle git lookup.
- **Scope creep** — charts beyond ASCII sparklines, cross-vault digests, PDF
  delivery are all explicit Out-of-scope (→ 040/043).
