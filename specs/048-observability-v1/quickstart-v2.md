# Quickstart: Source-Consideration Ledger (v2 MVP)

**For**: operators running the three live evaluation runs (clean-room codebase-vault rebuild, new reference-vault, feeds-vault update) — and anyone who needs to answer "did the framework actually consider and use every required source?"
**Spec**: `/specs/048-observability-v1/spec.md` § v2 scope · **Plan**: `plan-v2.md` · **Contract**: `contracts/source-ledger-v2.contract.md`

The ledger is a **read-only post-run diagnostic**. It changes nothing in the pipeline; you run it *after* a run (or any time during one) over the artifacts the run already wrote.

---

## 1. Run it on a finished (or partial) run

```bash
# whole run: per-cycle ledgers + a run roll-up to stdout
python scripts/source_ledger.py --vault ~/Personal/codebase-vault-test

# also persist the roll-up next to run-report.md
python scripts/source_ledger.py --vault ~/Personal/codebase-vault-test --write-rollup

# a single cycle only
python scripts/source_ledger.py --vault ~/Personal/reference-vault-test --cycle 3

# machine-readable (for the acceptance probe / CI)
python scripts/source_ledger.py --vault ~/Documents/feeds-vault --json
```

It writes `_pipeline/cycles/cycle-NNN-source-ledger.json` per reached cycle and (with `--write-rollup`) `_pipeline/source-ledger-run.md`. It reads `research.spec.md`, `sources.db`, and the per-cycle scout/research/incidents/quality artifacts — none of which it modifies.

## 2. Read the verdict table

```
| Source                | Role      | Req | Verdict           | notes(gen/cited) | Reason                  |
|-----------------------|-----------|-----|-------------------|------------------|-------------------------|
| GitHub PRs            | behaviour | yes | USED              | 3/2              |                         |
| Confluence ADRs       | intent    | yes | ACCESS_FAIL       | 0/0              |                         |
| Hacker News           | domain    | no  | SKIPPED_RELEVANCE | 0/0              | not on-topic this cycle |
```

Read each verdict as:

| Verdict | What it means | What to do |
|---|---|---|
| `USED` | considered, fetched, produced notes, ≥1 cited | nothing — the source is working |
| `SKIPPED_RELEVANCE` | the agent looked and recorded *why* it skipped (see Reason) | sanity-check the reason is legitimate; benign by default |
| `ACCESS_FAIL` | a fetch was attempted and failed (auth / 403 / 404 / timeout / broken feed / JS-shell) | **investigate** — check creds / URL / feed; for required sources this drives a non-zero exit |
| `QUALITY_REJECT` | content was fetched and produced notes, but the verifier rejected them all | **investigate** — content reached the vault but failed the quality bar |
| `PIPELINE_DROP` | 0 contribution **and** no recorded reason, but the stage ran | **investigate hard** — this is the (c)-masquerading-as-(a) class the ledger exists to catch (cf. the 0.6.0 scout bare-string drift) |
| `NOT_REACHED` | the stage never got to this source (run ended early) | usually a constrained/aborted run; resume to cover it |

## 3. Use the exit code as a CI / acceptance gate (FR-019)

```bash
python scripts/source_ledger.py --vault ~/Personal/codebase-vault-test
echo "exit=$?"
#   0  all required sources OK (USED or explained SKIPPED_RELEVANCE)
#   1  >=1 required source has a failure verdict (ACCESS_FAIL / PIPELINE_DROP / QUALITY_REJECT)
#   2  usage / structural error (bad --vault, missing spec, reconciliation broke)
```

Failure is **uniform** (Clarifications SL-Q2): an unexplained silence, a dead service, and a wrong API key all surface the same way — a WARN line naming the source + a non-zero exit. There is no special "unexplained silence" category to learn. Optional (`required: false`) sources never trip the exit.

## 4. Per-role reading

The roll-up histograms verdicts by `role` (`behaviour` / `intent` / `domain`). A required `intent` or `behaviour` source failing matters more than an optional `domain` one — scan the `## By role` block first to triage.

## 5. How spec 053 consumes it

`cycle-NNN-source-ledger.json` is the gate-consumable artifact: spec 053's **trunk-inversion gate** reads it to verify the derived trunk source (highest-priority) actually resolved to `USED` (not silently dropped). The per-cycle JSON's stable schema (`contracts/source-ledger-v2.contract.md`) is the contract that wire-in depends on — keep it stable.

## 6. The MCP caveat (read before trusting MCP rows)

MCP-backed sources (Jira/Confluence via Atlassian MCP, GitHub PRs/ADRs via GitHub MCP) are a known v1 blind spot — an empty MCP source may read as `PIPELINE_DROP` or `SKIPPED_RELEVANCE` rather than `ACCESS_FAIL`, because routing-derived MCP instrumentation (FR-018) is blocked on spec 054 (`managed`) and not in this MVP. For the codebase-vault run (which leans hardest on MCP), treat a `PIPELINE_DROP`/`SKIPPED_RELEVANCE` on a known-MCP source as "possible silent MCP miss — verify by hand" until FR-018 ships.

## 7. What it does NOT do (MVP boundaries)

- It does not run during the cycle or block any phase (zero pipeline change).
- It does not hard-fail the run in-loop — the non-zero exit is an out-of-band signal (opt-in hard-fail is a later promotion).
- It does not surface in the cycle-summary health header or `vault status` (FR-021 deferred).
- It does not call any agent — the verdict is deterministic, computed from the fused evidence (Principle IV).
