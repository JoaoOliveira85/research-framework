# Contract: Source-Consideration Ledger (v2 MVP)

**Authority**: Spec 048 v2 scope — FR-017 (ledger artifact), FR-019 (fail-loud, uniform), FR-020 (verdict state machine). Resolved by Clarifications — Session 2026-06-03.
**Producer**: `scripts/source_ledger.py` (read-only post-run diagnostic).
**Testable via**: `tests/scripts/test_source_ledger.py` (Tier 2).
**This MVP does NOT cover**: FR-018 (routing-derived MCP — blocked on spec 054 `managed`), FR-020-as-pipeline-gate, FR-021 (health-header surfacing). See `plan-v2.md § Out of scope`.
**Versioning (#297)**: the `v2` in this file's name is spec 048's second scope phase (see
`plan-v2.md`) — it is unrelated to the artifact's own wire version. The artifact has exactly
one version a consumer may branch on: the `schema_version` field in the JSON payload below,
currently `"1.1"`. Additive fields shipped after `"1.1"` are called out by FR number and date
below, never by a second version number.

---

## 1. CLI surface

```
python scripts/source_ledger.py --vault <path> [--cycle N] [--write-rollup] [--json]
```

| Flag | Required | Meaning |
|---|---|---|
| `--vault <path>` | yes | vault root (must contain `research.spec.md` + `_pipeline/`) |
| `--cycle N` | no | build the ledger for a single cycle only (writes just `cycle-NNN-source-ledger.json`); default = all reached cycles + run roll-up |
| `--write-rollup` | no | also write `_pipeline/source-ledger-run.md` (default: roll-up printed to stdout only) |
| `--json` | no | emit the run roll-up as JSON to stdout instead of the human table |

The script is **read-only over input artifacts** — it never modifies `research.spec.md`, `sources.db`, or any `cycle-NNN-*.json` it reads. It writes only its own derived `cycle-NNN-source-ledger.json` and (with `--write-rollup`) `source-ledger-run.md`. `--dry-run` is therefore N/A and intentionally absent.

## 2. Exit codes (FR-019 diagnostic signal)

| Code | Meaning |
|---|---|
| `0` | All **required** sources resolved to a non-failure verdict (`USED` or explained `SKIPPED_RELEVANCE`). |
| `1` | At least one **required** source resolved to a failure verdict (`ACCESS_FAIL`, `PIPELINE_DROP`, or `QUALITY_REJECT`). This is the FR-019 fail-loud signal — uniform across all failure causes (Clarifications SL-Q2). The roll-up names each failing source. |
| `2` | Usage / structural error — `--vault` missing, `research.spec.md` absent, unreadable `_pipeline/`, or the reconciliation invariant broke (declared-set ≠ ledger-set). |

Optional sources (`required: false`) NEVER drive the exit code. The non-zero exit is an **out-of-band** diagnostic for an operator/CI to run after a finished run; it does NOT alter the orchestrator's own 0/1/2 cycle exit semantics (zero pipeline change).

## 3. Per-cycle ledger JSON — `_pipeline/cycles/cycle-NNN-source-ledger.json`

```jsonc
{
  "schema_version": "1.1",             // bumped from "1.0" 2026-06-03 (FR-022/FR-023/FR-024); additive fields only
  "kind": "source-ledger",
  "cycle": 2,
  "vault": "/Users/.../feeds-vault",
  "generated_at": "2026-06-03T14:22:09.114",
  "reconciled": true,
  "entries": [
    {
      "name": "GitHub Pull Requests and Review Conversations",
      "role": "behaviour",
      "required": true,
      "priority": 1,
      "declared": true,
      "considered": true,
      "fetch_attempted": true,
      "fetch_outcome": "ok",            // "ok" | "failed" | "not_attempted"
      "notes_generated": 3,
      "notes_referencing": 2,
      "reason": null,                    // non-null ONLY when verdict == SKIPPED_RELEVANCE
      "verdict": "USED",                 // see §4 enum
      "read_via": "direct",              // added 2026-06-03, FR-024: "direct" | "mcp" | "unknown" (§4.2)
      "disagreement_was": null,          // added 2026-06-03, FR-022/FR-023: the join verdict when verdict == LEDGER_DISAGREEMENT (§4.1)
      "evidence": {
        "notes_generated": "sources.db",
        "notes_referencing": "sources.db",
        "considered": "cycle-002-scout.json"
      }
    }
    // ... exactly one entry per spec.data_sources source
  ]
}
```

**Invariants**:
- `entries` set of `name` ≡ `spec.data_sources` set of `name` (reconciliation; §5).
- `verdict` ∈ the §4 enum, exactly one value.
- `reason` is non-null **iff** `verdict == "SKIPPED_RELEVANCE"`.
- `read_via` ∈ `{"direct","mcp","unknown"}` (added 2026-06-03, FR-024; §4.2). `disagreement_was` is non-null **iff** `verdict == "LEDGER_DISAGREEMENT"` (added 2026-06-03, FR-022/FR-023; §4.1).
- `read_via`/`disagreement_was` are **additive** — a v1.0 reader ignores them; a v1.0 ledger lacking them still validates.
- The file is deterministic: same inputs ⇒ byte-identical output (stable key order, sorted entries by `(priority, name)`).

## 4. Verdict enum (FR-020, normative)

```
USED | LEDGER_DISAGREEMENT | QUALITY_REJECT | ACCESS_FAIL | SKIPPED_RELEVANCE | PIPELINE_DROP | NOT_REACHED
```

Per-cycle assignment (the state machine in `data-model-v2.md` Entity 2):

| Verdict | Per-cycle discriminator |
|---|---|
| `USED` | `notes_generated > 0 and notes_referencing > 0` |
| `QUALITY_REJECT` | `notes_generated > 0 and notes_referencing == 0` and a `cycle-NNN-quality-report.json` rejection touches this source (per-source attribution join heuristic — implementer choice; see `data-model-v2.md` Entity 2 row 2) |
| `ACCESS_FAIL` | a `cycle-NNN-source-incidents.json` entry or a capture-failure `(host, reason)` matches this source (`fetch_outcome == "failed"`) |
| `SKIPPED_RELEVANCE` | the scout `sources_consulted` row carries a non-empty `reason` — applies to **any** declared source, including `required: true`; a non-failure under FR-019 (exit `0`). The ledger **trusts the agent's stated reason**; detecting bad-faith trunk-skips is **not** this ledger's job — spec 053's trunk-inversion gate owns that. |
| `PIPELINE_DROP` | `notes_generated == 0` **and** no recorded reason **and** the stage demonstrably ran (a scout/research artifact exists for the cycle) — **fires FR-019** |
| `NOT_REACHED` | no scout/research signal for this source in any reached cycle (stage never got to it). A `required` source with collapsed verdict `NOT_REACHED` is a WARN in the roll-up but exit `0` for this read-only MVP |

**Run roll-up precedence** (single verdict per source when per-cycle verdicts differ):

```
USED  >  LEDGER_DISAGREEMENT  >  QUALITY_REJECT  >  ACCESS_FAIL  >  SKIPPED_RELEVANCE  >  PIPELINE_DROP  >  NOT_REACHED
```

The per-cycle files retain the full history; the roll-up collapse is lossless and auditable. The collapse runs over the **raw join verdicts** (`disagreement_was` when set), then re-derives `LEDGER_DISAGREEMENT` once on the collapsed set so the roll-up carries a clean `disagreement_was`.

## 4.1 `LEDGER_DISAGREEMENT` (added 2026-06-03, FR-022/FR-023) — terminal verdict

**Mechanism.** At ledger-build time the ledger builds a **note-citation corpus** —
the set of hosts every `data_vault/**` note actually cites in its `source_urls`
frontmatter (Principle IX Tier-2), which the v2 join never read. A
`reconcile_against_citations` post-pass then enforces the invariant:

> A source whose declared host appears in the citation corpus can **never** read
> as a 0-contribution failure.

When a source's reported verdict is non-`USED` (`ACCESS_FAIL`, `PIPELINE_DROP`,
`NOT_REACHED`, `QUALITY_REJECT`, or `SKIPPED_RELEVANCE`) yet its host ∈ corpus,
the reported `verdict` becomes `LEDGER_DISAGREEMENT` and the **original join
verdict is preserved in `disagreement_was`** (keep the join verdict, flag the
mismatch). `LEDGER_DISAGREEMENT` is a true positive about the *ledger's* blind
spot, **not** a source failure — so it is **excluded from the FR-019 failure set**
(exit code unaffected; a cited source is never a required-source failure).

Consumers (spec 053 trunk-inversion gate, spec 063 §4.2 reconciliation gate)
MUST treat `LEDGER_DISAGREEMENT` as **citation-evidenced** — acceptable like
`USED`, never a silent drop.

## 4.2 `read_via` attribution (added 2026-06-03, FR-024) — MCP blind spot

Each entry carries a best-effort `read_via ∈ {"direct","mcp","unknown"}`:

| `read_via` | Discriminator |
|---|---|
| `mcp` | the source declares `access_method: mcp` (or every repo is MCP) — read through a managed MCP server, NOT raw_capture; never silently dropped to `NOT_REACHED` for lack of a direct fetch signal |
| `direct` | a direct fetch signal exists (`fetch_attempted`, or a `sources.db` note) |
| `unknown` | unattributable (no direct signal, no MCP declaration) — never a false drop |

This partially closes the FR-018 MCP blind spot: a managed source that reads as
`PIPELINE_DROP`/`NOT_REACHED` but is `read_via: mcp` is attributable rather than
invisible.

## 5. Reconciliation invariant (acceptance criterion)

```python
{e["name"] for e in ledger["entries"]} == {ds.name for ds in spec.data_sources}
```

- No declared source missing. No source invented. Exactly one entry per declared source.
- On violation: `reconciled: false`, the symmetric difference is reported, and the script exits `2`.

## 6. Run roll-up — `_pipeline/source-ledger-run.md` (with `--write-rollup`) / stdout

Human-readable table + per-`role` verdict histogram + the FR-019 block:

```
# Source-Consideration Ledger — run roll-up
Vault: /Users/.../feeds-vault   Cycles: 1-4   Reconciled: yes

| Source | Role | Req | Verdict | notes(gen/cited) | Reason |
|--------|------|-----|---------|------------------|--------|
| GitHub PRs ... | behaviour | yes | USED | 3/2 | |
| Confluence ... | intent    | yes | ACCESS_FAIL | 0/0 | |
| Hacker News    | domain    | no  | SKIPPED_RELEVANCE | 0/0 | not on-topic this cycle |

## By role
behaviour: USED 1
intent:    ACCESS_FAIL 1
domain:    SKIPPED_RELEVANCE 1

## ⚠ Required-source failures (FR-019)
- Confluence ... — ACCESS_FAIL   (required, role=intent)
=> exit 1
```

With `--json`, the same `RunRollup` (data-model-v2.md Entity 3) is emitted as a JSON object instead of the table.

## 7. Degradation / robustness

- A missing or malformed input artifact for a cycle contributes **no** signal for that cycle (logged at WARN); it never crashes the build.
- A source with no signal across all reached cycles ⇒ `NOT_REACHED`.
- Runs that aborted mid-flight (partial `_pipeline/` tree) are the expected common case during the live runs — the script must produce a complete, reconciled ledger over whatever cycles exist.

## 8. Known MVP limitation — MCP blind spot (FR-018 deferred)

MCP-backed sources (Atlassian/GitHub MCP) do not pass through `raw_capture.py` or `bridge.log`, and MCP-backed-ness is routing-derived from a module's `managed: true` flag (spec 054) which **has not shipped**. In this MVP an MCP-backed source that returns nothing resolves to `PIPELINE_DROP` (if the agent recorded no reason — loud and roughly correct) or `SKIPPED_RELEVANCE` (if it did — the v1 false-negative the spec names). Operators reading the MCP rows of a codebase-vault run should apply that caveat. FR-018 promotion (a managed-handler access signal so empty MCP ⇒ `ACCESS_FAIL`) lands with spec 054. This limitation is stated here, not raised as an unresolved clarification, because the spec already routes FR-018 to spec 054.
