# Contract: Cross-Cycle Digest Format & Deterministic Rules

**Spec**: 035 — Cross-Cycle Digest · **Status**: authored 2026-06-03 (post-clarify Q1-Q5).
Authoritative for the layout, the ranking/gap/drift formulas, the cycle-index
resolution, and the determinism rules. Every rule is LLM-call-free (FR-012).

---

## 1. Inputs (all local; no network, no agent)

| input | path | used by |
|-------|------|---------|
| cycle dirs | `_pipeline/cycles/cycle-NNN/` | Cycle Index, scope enumeration (Q5) |
| cycle report | `_pipeline/cycles/cycle-<N>-report.md` | Cycle Index summaries (soft; FR-015 skip-if-absent) |
| quality report | `_pipeline/cycles/cycle-NNN-quality-report.json` | Gaps (coverage progress), New Notes |
| sources db | `_pipeline/sources.db` (`sources`, `source_cycles`) | Source Quality Drift |
| source incidents | the `source-incidents` log (degraded transitions) | Source Quality Drift |
| coverage targets | `<vault>/coverage-targets.json` (**vault root**) | Gaps (goals) |
| cost sidecars | `_pipeline/cycles/cycle-NNN/agent-calls/*.json` (spec 028) | Cost Summary |
| vault graph | `vault/indexer.inbound_link_counts(vault_dir)` (spec 051) | Strongest Signals |
| git | run-level commit range + commit dates **only** (spec 050 squashes per-cycle) | Header range, ship dates |

## 2. CLI surface (FR-001..003)

```
./vault digest [--since <ISO8601>] [--last-week|--last-month|--last-quarter] [--output <path>]
```
- `--since` is the primitive; the `--last-*` flags desugar to a `--since` date
  (computed from "now" in the vault's local date). Exactly one range source.
- Default output: `_pipeline/digests/digest-<start>--<end>.md`.
- No cycles in scope ⇒ exit 0, message "No cycles in scope", **no file written**.
- `--since <future>` ⇒ exit non-zero "no cycles in scope". `--since <before vault
  existed>` ⇒ clamp to vault creation silently.

## 3. Layout: Header + 7 content sections (FR-004), fixed order

```
# Digest: <vault-identity>  <start> → <end>
_rendered-at: <ISO8601>  ·  commit range: <base>..<head>_     ← header (excluded from idempotency)

## Strongest Signals          (§4)
## Gaps                       (§5)
## New Notes by Category      (§6)
## Source Quality Drift       (§7)
## Coverage Delta             (§8)
## Cost Summary               (§9)
## Cycle Index                (§10)
```
Empty section ⇒ a single explicit line (e.g. "No regressions or stagnations in
scope."), never an absent heading.

## 4. Strongest Signals — deterministic composite (FR-007, Q2)

Integer score (no float weighting — avoids drift + bikeshedding):

```
score(note) = inbound_links(note)                                  # int, vault/indexer.inbound_link_counts
            + source_drift_bonus(note)                             # +1 per cited source with a POSITIVE notes_referencing delta in range
            + freshness_points(note)                               # 2 if first-written in the last 25% of the range, 1 if last 50%, else 0
```

- **Top 5** by `score` descending; **tiebreaker = note path ascending**
  (lexicographic) for total determinism. Fewer than 5 notes in scope ⇒ list all.
- Each entry renders: the note wikilink, the score breakdown rationale
  (e.g. `score 6 = 3 inbound + 1 source-drift + 2 fresh`), and a 1-line summary
  (note frontmatter `summary`, else first non-heading paragraph).
- "New in scope" = note file first appears in a cycle within the range.
- *(Spec 055 credibility is a future optional addend — NOT in v1 per Q2.)*

## 5. Gaps (FR-008) — coverage regression/stagnation

For each category in `<vault>/coverage-targets.json`:
- `progress_start` = coverage at the first in-range `cycle-NNN-quality-report.json`;
  `progress_end` = at the last.
- **regressed** ⇔ `progress_end < progress_start`.
- **stagnant** ⇔ `progress_end == progress_start` AND `progress_end < target`.
- Report regressed first, then stagnant; each shows category id, the delta
  (e.g. `47% → 39%`), and the last cycle that touched it. Healthy-everywhere ⇒
  "No regressions or stagnations in scope."

## 6. New Notes by Category (FR-005)

Group notes first-written in range by their note `type` (the vault's
`note_types`); render `<type>: N` + up to 3 sample wikilinks per type, types in
declared order.

## 7. Source Quality Drift (FR-006, Q4) — from REAL sources.db data

No quality-score column exists. For each source, over the cycles in range:
- **yield delta**: Σ`notes_generated` and Σ`notes_referencing` change (from
  `source_cycles`).
- **degraded transition**: the source appears in the `source-incidents` log
  within range.
- **went cold**: `consecutive_empty_cycles` crossed the degrade threshold in range.

Report any source with a non-flat signal: name + signal(s) + most-recent in-range
cycle touched. All-flat sources omitted (not "no data" noise).

## 8. Coverage Delta (FR-004 section)

Aggregate coverage movement across all categories (sum of per-category
`progress_end − progress_start`), rendered as a per-category table. Distinct from
Gaps (which is the *negative* subset); Coverage Delta is the full picture.

## 9. Cost Summary (FR-009) — spec 028 sidecars

Sum `cost_usd` across `cycle-NNN/agent-calls/*.json` in range; per-stage
breakdown (by `agent_kind`); per-cycle totals as an ASCII sparkline. Missing
sidecars for a cycle ⇒ that cycle contributes 0 + a footer note.

## 10. Cycle Index (FR-010, Q5) — filesystem-authoritative

Enumerate cycles from `_pipeline/cycles/cycle-NNN/` dirs that carry the
completion marker (`cycle-NNN-quality-report.json`, per 0.6.3) AND fall in range.
For each: cycle number, ship date (git commit date of the run squash, else the
report mtime), 1-line summary (`cycle-<N>-report.md` H1 if present, else
"(no report)"), and **ship SHA = the run-level squash commit** that merged the
cycle to `main` (spec 050) — or the retained `research/<ts>` branch SHA on a
constrained exit. **Never assume a distinct per-cycle commit in `main`'s log.**

## 11. Determinism rules (FR-011, SC-002)

- All ranking/aggregation uses integers or fixed-precision; every sort has an
  explicit total-order tiebreaker (note path / source name / cycle number asc).
- Dates rendered ISO8601; the **only** non-deterministic field is the header
  `_rendered-at:` line, which is excluded from byte-identity comparison.
- No network, no agent dispatch (SC-004). Pure read of local artifacts + one
  Jinja2 render pass.

## 12. Robustness (FR-015, edge cases)

- Missing/malformed `cycle-<N>-report.md` ⇒ skip its summary (use "(no report)"),
  footer warning; never fail the run.
- `sources.db` locked ⇒ wait ≤5s; if still locked, render WITHOUT §7 + footer warn.
- Schema-migrated older entries ⇒ best-effort parse + `[schema-migrated]` annotation.
