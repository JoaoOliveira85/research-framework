# Contract: Fake-Agent v2 Stage Extensions — Implementation Tracker

**Status**: Implementation tracker, not a new schema
**Authoritative shape**: `specs/018-testing-strategy/contracts/fake-agent.contract.md`
**Spec ratification**: 024 clarify Q1 (one spec) + Q3 (two-entry LLM dispatch allowlist).

---

## Purpose

The fake-agent v2 contract in spec 018 defines five stages
(`scout`, `note_writer`, `verifier`, `narrator`, `probe_retrieval`)
but marks the last three as `pending` for Phase 2 implementation.
Spec 024 IS that Phase 2 implementation.

This document is **not a new schema**. It tracks which clauses of
018's v2 contract are honored by 024's implementation, plus where
the new scenario response payloads live on disk.

If a future change drifts from 018's v2 contract, the source of
truth is 018, not this document. Update 018's contract; this
tracker updates as a side effect.

---

## Stages implemented by spec 024

| Stage | Scenario | 018 contract clause | 024 implementation site |
|---|---|---|---|
| `verifier` | `accept` | § Scenarios by stage > verifier | `fake_agent_scenarios/verifier/accept.json` + handler in `fake_agent.py` |
| `verifier` | `reject` | Same | `fake_agent_scenarios/verifier/reject.json` + handler |
| `verifier` | `malformed_json` | Same | `fake_agent_scenarios/verifier/malformed_json.json` + handler |
| `narrator` (aka `research_plan_narrator`) | `happy` | § Scenarios by stage > research_plan_narrator | `fake_agent_scenarios/narrator/happy.json` + handler |
| `probe_retrieval` | `happy` | § Scenarios by stage > probe_retrieval | `fake_agent_scenarios/probe_retrieval/happy.json` + handler |

**Stages NOT implemented by 024** (intentionally out of scope):

- `narrator/empty` and `narrator/timeout_sim` — documented in
  018's contract but not required by any 024 user story. Future
  specs MAY add them; the v2 contract permits it without itself
  changing.
- `probe_retrieval/empty` — same.

These omissions are not contract violations because 018's contract
flags them as "Phase 2 implementation" entries, not "Phase 2
required minimum".

---

## CLI argv changes

Per 018 v2 § Command-line interface, no argv changes are needed.
The fake-agent already accepts `--vault`, `--stage`, `--prompt-file`,
`--cost-sidecar`, `--output-file` — the new stages use the existing
flags without introducing new ones.

`--output-file` is honored for `verifier` (the production code
writes the verdict JSON there); the new handler writes its
scenario payload to that path.

---

## Scenario selection (env vars)

Per 018 v2 § Scenario selection. Three new env vars become
operational at 024 ship:

| Env var | Stage |
|---|---|
| `FAKE_AGENT_VERIFIER_SCENARIO` | `verifier` |
| `FAKE_AGENT_RESEARCH_PLAN_NARRATOR_SCENARIO` | `research_plan_narrator` (aka `narrator`) |
| `FAKE_AGENT_PROBE_RETRIEVAL_SCENARIO` | `probe_retrieval` |

These are read by the existing `_resolve_scenario(stage)` helper
in `fake_agent.py` with no functional change to the helper — the
existing stage→env-var mapping is extended by three rows.

---

## Determinism guarantees

Per 018 v2 § Determinism guarantee, all new handlers:

- Do NOT use `datetime.now()`, `uuid.*`, or `random.*`.
- Read static bytes from `fake_agent_scenarios/<stage>/<scenario>.json`
  and emit them verbatim, with the single exception of the two
  whitelisted placeholders (`{cycle}`, `{cycle:03d}`).
- Use `tempfile` + `os.replace` for atomic writes when
  `--output-file` is provided.

---

## Contract-test enforcement

Per 018 v2 § Phase 2 acceptance tests, every (stage, scenario) pair
implemented by 024 MUST have a corresponding test in
`tests/_helpers/test_fake_agent_contract.py`. At 024 ship, the new
tests are:

| Test | Asserts |
|---|---|
| `test_verifier_accept_emits_canonical_verdict` | Stage=verifier × scenario=accept produces a parseable JSON verdict with `verdict == "accept"`. |
| `test_verifier_reject_emits_violations` | Stage=verifier × scenario=reject produces verdict with `verdict == "reject"` and ≥ 1 violation. |
| `test_verifier_malformed_json_exercises_parser_tolerance` | Stage=verifier × scenario=malformed_json produces non-strict JSON that `pipeline/verifier._extract_json_blob` (ADR-0004) recovers. |
| `test_narrator_happy_emits_short_markdown` | Stage=narrator × scenario=happy produces a ≤200-word markdown paragraph with `{cycle}` interpolated. |
| `test_probe_retrieval_happy_emits_array` | Stage=probe_retrieval × scenario=happy produces a JSON array of `{query, answer, sources}` shapes. |

---

## Discovery convention

The contract test walks `tests/_helpers/fake_agent_scenarios/` and
asserts that every `<stage>/<scenario>.json` file has a matching
test function above. Adding a new scenario JSON without a matching
test is a guard failure — protects against silent test-coverage
gaps.

---

## Open work after 024 ship

These items remain on the v2 contract's roadmap but are NOT 024's
responsibility:

- Production `verifier` consumers in tier-5 e2e tests beyond the
  one US6 wires (`verifier_reject`). 022's quality harness picks
  up `verifier_accept` and `verifier_malformed_json` consumers
  during its fixture-vault e2e runs.
- Routing the production `plan_narrator` and `probe_retrieval`
  through `scripts/agent_call.py` so they invoke the fake-agent
  via the canonical dispatch surface — spec 025 Tier A1 / A2.
  Until 025 ships, those production paths bypass the fake-agent
  entirely (the LLM dispatch guard's two-entry allowlist exists
  precisely because of this).
