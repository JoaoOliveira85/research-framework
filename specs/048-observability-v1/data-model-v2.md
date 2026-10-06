# Data Model: Source-Consideration Ledger (v2 MVP)

**Spec**: `/specs/048-observability-v1/spec.md` § v2 scope (FR-017, FR-019, FR-020)
**Plan**: `plan-v2.md` · **Contract**: `contracts/source-ledger-v2.contract.md`
**Date**: 2026-06-03

All entities below are **derived** — built by joining existing read-only artifacts. None is persisted to a new store; the only new on-disk artifact is the per-cycle ledger JSON the script writes (and the optional run roll-up markdown). No `sources.db` schema change.

---

## Entity 1 — `SourceLedgerEntry`

One per declared source, computed **per cycle** (in the per-cycle JSON) and again **collapsed** (in the run roll-up, one entry per source). In-memory it's a `@dataclass`; on disk it serialises to the JSON object specified in the contract.

| Field | Type | Source artifact (read-only) | Notes |
|---|---|---|---|
| `name` | `str` | `spec.data_sources[].name` | declared identity; the join key |
| `role` | `str` | `spec.data_sources[].role` | `behaviour` \| `intent` \| `domain` (default `behaviour`, `schema.py:171`) |
| `required` | `bool` | `spec.data_sources[].required` | drives FR-019; default `True` (`schema.py:168`) |
| `priority` | `int` | `spec.data_sources[].priority` | `1` = primary; informational in roll-up ordering |
| `declared` | `bool` | always `True` for a `spec.data_sources` entry | reconciliation anchor (see invariant below) |
| `considered` | `bool` | scout `sources_consulted[].searched` | agent self-report — an *input*, not the verdict (D1) |
| `fetch_attempted` | `bool` | derived: any of {source-incident for this source, capture-failure host match, ≥1 `notes_generated` in any cycle} | "did the pipeline try to pull content?" |
| `fetch_outcome` | `str` | derived enum: `ok` \| `failed` \| `not_attempted` | `failed` when an incident/capture-failure is recorded; `ok` when notes were generated |
| `notes_generated` | `int` | `source_cycles.notes_generated` | `0` is the silence trigger combined with reason absence |
| `notes_referencing` | `int` | `source_cycles.notes_referencing` | = Tier-1 citations; `≥1` is the USED discriminator |
| `reason` | `str \| None` | scout `sources_consulted[].reason` | carried through ONLY when verdict is `SKIPPED_RELEVANCE` |
| `verdict` | `Verdict` (enum, str) | computed by `resolve_verdict` | exactly one of the six; the headline field |
| `evidence` | `dict[str, str]` | provenance map: which artifact supplied each non-trivial field | makes the join auditable (e.g. `{"notes_referencing": "sources.db", "reason": "cycle-002-scout.json"}`) |

`mcp_backed` is **NOT** a field in the MVP (FR-018 deferred; spec 054 `managed` unshipped — see `research-v2.md` §3). It is reserved for the promotion.

---

## Entity 2 — `Verdict` enum + `VerdictStateMachine` (FR-020, normative)

A `str`-valued enum. The state machine is a **pure function** `resolve_verdict(signals) -> Verdict` with no filesystem coupling, so the deferred FR-020-in-pipeline promotion lifts it unchanged.

### Terminal states (the spec's FR-020 table, normative)

Walk: `declared -> considered? -> fetch_attempted? -> yielded notes? -> cited?`

| # | Terminal state | Verdict | Discriminator (per cycle) |
|---|---|---|---|
| 1 | considered + notes generated + ≥1 cited | `USED` | `notes_generated > 0 and notes_referencing > 0` |
| 2 | considered, fetched, yielded notes, all verifier-rejected | `QUALITY_REJECT` | `notes_generated > 0 and notes_referencing == 0` and a quality-report rejection touches this source (per-source attribution join heuristic — implementer choice) |
| 3 | considered, fetch attempted, fetch failed | `ACCESS_FAIL` | `fetch_attempted and fetch_outcome == "failed"` (source-incident or capture-failure recorded) |
| 4 | considered, no fetch, agent recorded a relevance reason | `SKIPPED_RELEVANCE` | `reason is a non-empty string` — applies to **any** declared source, including `required: true`; non-failure under FR-019. The ledger trusts the agent's stated reason; bad-faith trunk-skips are **not** this ledger's job (spec 053 trunk-inversion gate) |
| 5 | 0 contribution **and** no recorded reason | `PIPELINE_DROP` | `notes_generated == 0 and not reason and stage demonstrably ran` — *fires FR-019* |
| 6 | stage never reached this source | `NOT_REACHED` | no scout/research signal for this source in any reached cycle |

### Precedence (run roll-up collapse — D2)

When per-cycle verdicts for one source differ, the roll-up's single verdict is the **highest-precedence** observed:

```
USED  >  QUALITY_REJECT  >  ACCESS_FAIL  >  SKIPPED_RELEVANCE  >  PIPELINE_DROP  >  NOT_REACHED
```

The per-cycle JSON retains every per-cycle verdict, so the collapse is auditable and lossless.

### Failure verdicts (FR-019)

```
FAILURE_VERDICTS = {ACCESS_FAIL, PIPELINE_DROP, QUALITY_REJECT}
```

A *required* source whose collapsed verdict ∈ `FAILURE_VERDICTS` ⇒ a WARN in the roll-up + contributes to the script's non-zero exit. `SKIPPED_RELEVANCE` (non-empty agent `reason`, including on required sources) and `USED` are not failures. `NOT_REACHED` on a required source is a WARN in the roll-up but exit `0` for this read-only MVP (benign "run ended early" or stage never reached the source).

---

## Entity 3 — `RunRollup`

The per-run aggregation, printed to stdout and optionally written to `_pipeline/source-ledger-run.md`.

| Field | Type | Notes |
|---|---|---|
| `vault` | `str` | vault root path |
| `cycles_covered` | `list[int]` | cycle numbers that contributed a ledger |
| `entries` | `list[SourceLedgerEntry]` | one collapsed entry per declared source (precedence-collapsed) |
| `by_role` | `dict[str, dict[Verdict, int]]` | per-`role` verdict histogram (`behaviour`/`intent`/`domain`) — FR-020 "reportable per role" |
| `required_failures` | `list[str]` | names of required sources with a failure verdict — drives FR-019 + exit code |
| `reconciled` | `bool` | the invariant below |

### Reconciliation invariant (acceptance criterion)

```
{e.name for e in entries}  ==  {ds.name for ds in spec.data_sources}
```

Every declared source appears exactly once; no source is invented; none is dropped. The script asserts this and reports `reconciled: false` (with the symmetric difference) if it ever breaks — itself a loud signal that the join logic or the spec changed.

---

## On-disk artifacts (written by the script — the only new writes)

| Path | Producer | Content |
|---|---|---|
| `<vault>/_pipeline/cycles/cycle-NNN-source-ledger.json` | `source_ledger.py` (per cycle) | per-source ledger for that cycle; **spec 053's trunk-inversion gate reads this** |
| `<vault>/_pipeline/source-ledger-run.md` | `source_ledger.py` (per run, optional `--write-rollup`) | the `RunRollup` rendered as a table + per-role histogram + FR-019 WARN block |

Both are derived, idempotent (re-running overwrites deterministically), and atomic-write-friendly. Neither is consumed by the cycle loop (zero pipeline change).

---

## Relationships (read-only join graph)

```
research.spec.md (data_sources)         ──┐  declared set + role/required/priority
sources.db (source_cycles)              ──┤  notes_generated / notes_referencing  -> USED / QUALITY_REJECT split
cycle-NNN-scout.json (sources_consulted)──┤  considered + reason                  -> SKIPPED_RELEVANCE
cycle-NNN-source-incidents.json         ──┼─►  resolve_verdict  ─►  SourceLedgerEntry  ─►  cycle-NNN-source-ledger.json
source-incidents.md                     ──┤  required access failure               -> ACCESS_FAIL                      │
capture-failures (via _aggregate_*)     ──┤  host/reason (JS_SHELL/THIN/404)        -> ACCESS_FAIL                      ▼
cycle-NNN-quality-report.json (gates)   ──┘  verifier rejection                     -> QUALITY_REJECT       precedence-collapse -> RunRollup -> source-ledger-run.md + exit code
```
