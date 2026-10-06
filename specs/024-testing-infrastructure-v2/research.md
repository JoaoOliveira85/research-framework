# Phase 0 Research — Spec 024 Testing Infrastructure v2

**Branch**: `024-testing-infrastructure-v2`
**Status**: Phase 0 (Outline & Research) — produced by `/speckit.plan`
**Reads from**: [spec.md](./spec.md), `.specify/memory/constitution.md`,
`specs/018-testing-strategy/contracts/{llm-dispatch-guard.contract.md, fake-agent.contract.md, vault-factory.contract.md}`,
`docs/testing-strategy.md` § Phase 2 checklist.

This document resolves the six open implementation choices that the
spec deliberately deferred to plan time. Most heavy design is already
locked in the 018 contracts; what's left here is local mechanics.

---

## Decision 1 — LLM dispatch guard: allowlist file format

**Decision**: YAML list of mappings at
`tests/_helpers/llm_dispatch_allowlist.yaml`, with the shape laid out
in [data-model.md § LLM dispatch allowlist entry](./data-model.md).

**Rationale**:

- YAML is already a runtime dependency (`pyyaml ≥ 6.0`) and is the
  format the project already uses for `settings.yaml`,
  `settings.codex.yaml`, and every spec-kit frontmatter — adding a
  YAML file fits the house style without new tooling.
- The allowlist's primary failure mode is **drift between the row
  and reality** (the production code moves, the row keeps a stale
  line range). YAML's required-key validation by the guard at
  load time catches "you renamed the file but forgot the allowlist"
  cheaply. JSON would lose the inline comments that name each row's
  retirement spec (spec 025 Tier A1 vs A2). A Python list-of-dicts
  would couple the data to the test module, making `spec 025` Tier
  A's "delete the row in the same PR" workflow noisier (`diff`s a
  `.py` edit, not a data edit).
- YAML's comment support lets the row carry "remove me when spec
  025 Tier A1 ships" inline alongside the row, so the cleanup PR
  has no ambiguity.

**Alternatives considered**:

| Alternative | Why rejected |
|---|---|
| JSON | No inline comments; loses retirement-spec pointer. |
| Python list-of-dicts in `test_llm_dispatch_guard.py` | Couples data to module; spec 025 Tier A PRs would diff `.py`. |
| TOML | Not used anywhere else in the repo; adds cognitive load. |
| Inline as a `pytest.fixture` returning a list | Same coupling as the Python list approach + harder for non-Python readers (release engineers reading the PR). |

**Contract reference**:
`specs/018-testing-strategy/contracts/llm-dispatch-guard.contract.md`
§ Allowlist; the contract specifies "file: line region: stage:
cleared when" as the row shape — YAML preserves all four cleanly.

---

## Decision 2 — Lint-guard parser strategy

**Decision**: All three lint guards (US1 LLM dispatch, US4
acceptance-coverage, US5 CHANGELOG regression-link) use **regex +
state-machine parsing**, NOT a full markdown parser dependency.

**Rationale**:

- Principle V forbids new runtime deps; `markdown-it`, `mistune`, or
  `markdown2` would all violate it for no real return — the patterns
  we need to recognise are well-defined headings (`## Acceptance
  coverage`, `### Fixed`, `**Given** … **When** … **Then**`) plus
  bullet lists. Regex covers all three.
- Lint-guard runtime budget is < 5 s each (Assumptions). A regex
  + state-machine pass over the 670-line spec.md and the 1543-line
  CHANGELOG.md completes in tens of milliseconds; a real markdown
  parser would not be faster and would add a dep.
- For US1 (LLM dispatch), Python's stdlib `ast` module is the right
  tool, not regex — we need to recognise `subprocess.run(["claude",
  ...])` AND `subprocess.Popen(claude_args)` where `claude_args =
  ["claude", ...]` two lines earlier. `ast.walk` over each module
  in `src/research_framework/` resolves the second case; a pure
  regex over source text would miss it (false negative — the
  failure mode the guard exists to prevent).

**Parser layout per guard**:

- **US1 LLM dispatch**: `ast.parse(source)` per `.py` file under
  `src/research_framework/`. Walk for `Call` nodes whose `.func`
  resolves to `subprocess.run` or `subprocess.Popen`. Inspect the
  first positional arg — if it's a `List` literal starting with
  `Str("claude")` or `Str("codex")`, flag. If it's a `Name`,
  follow the simple single-assignment case (`name = ["claude", ...]`
  in the same function scope) — anything more complex is reported
  with file+line so the human can decide.
- **US4 acceptance-coverage**: regex `^### .+?(?=^##|\Z)` against
  `**Given** ... **When** ... **Then**` to detect "this spec has
  G/W/T scenarios". Then regex `^## Acceptance coverage\s*$` to
  detect "this spec also has a coverage section". If A and not B,
  fail with the spec path.
- **US5 CHANGELOG regression-link**: state machine over
  `CHANGELOG.md`. Top-level `## [Unreleased]` block → skip. Other
  `## [X.Y.Z] - YYYY-MM-DD` blocks → enter "released" mode. Inside
  released, each `### Fixed` opens a sub-mode where every bullet
  line (`^- `) must match one of the three annotation regexes:
  `\(test: [^)]+\)`, `\(regression test: [^)]+\)`, `\(no test: [^)]+\)`.

**Alternatives considered**:

| Alternative | Why rejected |
|---|---|
| Add `markdown-it-py` as test-only dep | Violates Principle V; adds zero value over regex for these patterns. |
| Use `mistletoe` | Same. |
| String `find()` for headings + regex for everything else | OK for headings but loses inline-annotation matching. Not materially simpler than regex; one tool is better than two. |
| For US1: regex over source text | False negatives on multi-line subprocess calls and on `args = [...]; subprocess.run(args)`. AST is the right tool. |

---

## Decision 3 — Backfill mechanics for FR-013 (acceptance-coverage on 015a / 017 / 018)

**Decision**: Backfill is done by **hand-editing each spec** to add a
`## Acceptance coverage` section near the end of the file, using the
table shape already in 022/024/025. Where a user story's evidence is
already shipped (017's tests, 018's tests), the row points at the
actual test path. Where the user story shipped without a dedicated
test, the row uses `_(historical — see CHANGELOG.md [<version>] entry
"<text>")_` and explains the gap.

**Rationale**:

- Auto-generation would require an LLM call to summarise each user
  story → test mapping, which Principle V + IV forbid in test
  infrastructure code. A human-curated backfill is more accurate
  and ships once.
- Three specs is a small enough number that the cost of a
  semi-mechanical pass is acceptable (estimated 30–60 minutes total
  across the three).
- The dogfood property still holds: the guard from FR-006 runs
  against the backfilled specs and passes, proving the convention
  scales to existing material.

**Per-spec scope sketch** (full content lands during impl in
`/speckit.tasks`):

- **`015a-corpus-folder-name`** — 4 G/W/T acceptance scenarios
  shipped 0.2.16; rows point at `tests/scripts/test_validate_vault.py`
  + `tests/spec/test_validator.py` where the corpus-folder-name
  contract is exercised.
- **`017-vault-quality-fix`** — multiple user stories; rows
  map US1 (preflight) → `tests/scripts/test_preflight_sources.py`,
  US2 (quality report) → `tests/scripts/test_quality_report.py`,
  US3 (research plan) → `tests/pipeline/test_research_plan_*.py`,
  etc. Two-three rows may use `_(historical — see CHANGELOG.md
  [0.2.27] / [0.2.28])_` where coverage is end-to-end and lives in
  multiple files.
- **`018-testing-strategy`** — meta-spec; rows reference each of
  its own contracts (`fake-agent.contract.md`, `llm-dispatch-guard.contract.md`,
  `vault-factory.contract.md`) AND the contract-test files
  (`tests/_helpers/test_fake_agent_contract.py`,
  `tests/_helpers/test_vault_factory_contract.py`). The
  llm-dispatch row points at `tests/_helpers/test_llm_dispatch_guard.py`
  (which 024 itself creates) — a forward reference that becomes
  valid in the same ship PR.

**Alternatives considered**:

| Alternative | Why rejected |
|---|---|
| Skip the backfill, grandfather via allowlist | Q4 ratification explicitly rejected this. |
| Stub the backfill with `_(deferred to a follow-up)_` rows | Violates Principle VIII spirit; the lint guard would still pass but the section would be noise. |
| Auto-generate via an LLM call from this spec | Violates Principle IV (agents don't validate). And a guard backfilled by an agent is a guard backfilled by an unreliable narrator. |

---

## Decision 4 — Backfill mechanics for FR-014 (CHANGELOG annotations)

**Decision**: Each `### Fixed` bullet is annotated by hand. The
annotation tag picker follows this priority:

1. **`(test: <path>::<name>)`** — if a single regression test
   exists. Found by `git log --follow` against the bullet's commit
   and looking for sibling test changes.
2. **`(regression test: <path>::<name>)`** — when the test is more
   recent than the fix (i.e. someone wrote a guard for the bug
   later); also used when the test name doesn't follow the
   `test_<bug_summary>` pattern.
3. **`(no test: <one-line rationale>)`** — last resort. Used when
   the bullet is documentation-only, environmental, or impossible
   to test post-hoc (e.g. "Fixed a typo in a deprecated CLI flag's
   help string").

**Rationale**:

- The spec is explicit (FR-014): three valid annotations, with
  `(no test: …)` requiring a one-line rationale. This is the
  mechanical interpretation.
- For 15 sections × ~2–4 bullets each = ~30–50 annotations, the
  manual cost is dominated by the look-up step (find the test that
  covers this fix), not by typing. `git log --follow` per bullet
  is the right tool.
- The lint guard from FR-007 enforces the three forms with no
  allowlist — Q5 ratification. Anything left as `(no test: …)`
  becomes a visible coverage gap that future contributors can
  promote to `(test: …)` by writing the missing test.

**Cross-check with FR-015**: any bullet whose `(test: …)` annotation
points at `tests/pipeline/test_e2e_synthetic_vault.py` (the file
deleted in US7) MUST be re-pointed at the equivalent
`tests/integration/test_cycle_e2e.py` scenario from US6. The
US7-affected bullets are identified during the FR-014 pass by
greping for old paths in the about-to-be-deleted file.

**Alternatives considered**:

| Alternative | Why rejected |
|---|---|
| Permissive allowlist for pre-0.2.34 entries | Q5 explicitly rejected. |
| Auto-fill all bullets with `(no test: legacy)` | Hollows the discipline — the whole point is honest coverage. |
| Sample-only audit (10 of 50 bullets) | Doesn't satisfy the strict-at-launch posture; guard fails on the unaudited 40. |

---

## Decision 5 — Fake-agent scenario file layout

**Decision**: Each scenario's response is stored as a JSON file at
`tests/_helpers/fake_agent_scenarios/<stage>/<scenario>.json`. The
JSON is the EXACT bytes the new stage will write to stdout (or
`--output-file`), with one wrinkle: scenarios that need cycle-number
or vault-path interpolation use `{cycle:03d}` / `{vault_root}` style
templates that `fake_agent.py`'s new stage handlers fill in.

**Rationale**:

- Keeps the fake-agent module small — the response payload data
  lives in version-controlled JSON, not Python string literals.
- A future "fake agent v3" that adds a new scenario for an existing
  stage drops a new file under the directory; the contract test
  picks it up automatically via the discovery walk.
- Determinism: the bytes are committed. The fake-agent walks the
  file, optionally interpolates the two whitelisted placeholders,
  and prints. No randomness, no time.
- The directory layout matches the contract's table-of-stages,
  making "is this stage × scenario implemented?" a single `ls`
  away.

**Files at ship (5 total)**:

```
tests/_helpers/fake_agent_scenarios/
├── verifier/
│   ├── accept.json              {"verdict": "accept", "violations": [], "suggested_fix": null}
│   ├── reject.json              {"verdict": "reject", "violations": [...], "suggested_fix": "Add tier-2 sources"}
│   └── malformed_json.json      Literally not JSON — wrapped in prose to exercise ADR-0004
├── narrator/
│   └── happy.json               {"narrative": "Synthetic focus rationale for cycle {cycle}."}
└── probe_retrieval/
    └── happy.json               [{"query": "...", "answer": "...", "sources": [...]}, ...]
```

**Alternatives considered**:

| Alternative | Why rejected |
|---|---|
| Inline string constants in `fake_agent.py` | Couples data to code; future scenario additions diff `.py`. |
| One scenario file per stage with all variants in one JSON object | Two-level dict; harder to add new scenarios without merge conflicts. |
| YAML | JSON matches the on-disk output shape (verifier and probe both emit JSON in production); zero conversion. |

---

## Decision 6 — US6 tier-5 e2e scenario wiring

**Decision**: All three new scenarios (`oos_topic`, `partial_yield`,
`verifier_reject`) live in **one** test file at
`tests/integration/test_cycle_e2e.py`, parametrized by scenario
name. Each scenario uses `vault_factory.build_minimal_vault` for
fixture construction and `fake_agent.install_shim` + env-var-driven
scenario selection (per the existing v2 contract § Scenario
selection) for stage routing.

**Rationale**:

- One file = one entry point for tier-5 discovery + one place to
  add a new scenario row. Matches the existing `test_full_cycle_e2e.py`
  pattern.
- `vault_factory.build_minimal_vault` is the contract-blessed
  fixture builder (`specs/018-testing-strategy/contracts/vault-factory.contract.md`)
  and is already used by the contract tests. Using it for US6
  scenarios means no new fixture machinery.
- Scenario selection via `FAKE_AGENT_VERIFIER_SCENARIO=reject`
  (and equivalents) is exactly what the v2 contract specifies. No
  new env var, no new param plumbing.
- Each scenario asserts on the cycle's output JSON shape (e.g.
  `cycle-NNN-research.json`'s `skipped_topics` for `partial_yield`,
  `cycle-NNN-quality-report.json` for `verifier_reject`).

**Test cases at ship (3)**:

- `test_cycle_oos_topic_rejected_by_verifier` — uses
  `FAKE_AGENT_SCOUT_SCENARIO=oos_topic` + `FAKE_AGENT_VERIFIER_SCENARIO=reject`;
  asserts the OOS topic appears in the verifier-reject log.
- `test_cycle_partial_yield_trips_diversity_gate` — uses
  `FAKE_AGENT_NOTE_WRITER_SCENARIO=partial_yield`; asserts
  `cycle-NNN-quality-report.json` shows SG-002 warning.
- `test_cycle_verifier_reject_moves_note_to_rejected` — uses
  `FAKE_AGENT_VERIFIER_SCENARIO=reject` against a happy-path note;
  asserts the note ends up under `_pipeline/rejected/`.

**Alternatives considered**:

| Alternative | Why rejected |
|---|---|
| Three separate test files | Inflates the tier-5 file count without giving any isolation benefit. |
| Use bespoke vault fixtures per scenario | Violates the vault_factory contract; risks the bespoke-mock pattern US7 is deleting. |
| Run scenarios as parametrized cases of an existing test in `test_full_cycle_e2e.py` | Mixes 024 scenarios with 018 scenarios; reviewer cognitive load. |

---

## Cross-cutting risks resolved

- **Risk**: The dogfood acceptance-coverage table in
  `spec.md` itself uses `_(deferred to tasks.md)_` placeholders. Does
  that pass the FR-006 guard?
  **Resolution**: The guard checks "the section exists AND has rows
  that map to user stories" — not "every row points at a shipped
  test". The dogfood section satisfies the guard at clarify time
  and is fully populated by `/speckit.tasks` time anyway. SC-009
  is preserved.
- **Risk**: US3's smoke meta-tests might fail when uncommented
  (the comment says they "vanished from the working tree without
  anyone noticing" — what if they're stale?).
  **Resolution**: Glob confirmed both files exist at
  `tests/build/test_install_wizard_skip_redundant_questions.py`
  and `tests/build/test_smoke_gate_enforces_contract_tier.py` as
  of clarify time. Plan validates this with a local
  `pytest tests/build/` run before flipping the comment lines.
- **Risk**: FR-015 says CHANGELOG `(test: …)` annotations
  pointing at the deleted file must be re-pointed. What if none
  of them do?
  **Resolution**: That's fine — FR-015 is conditional. The FR-014
  pass discovers whether any historical bullets reference the
  deleted file; if zero do, FR-015 is satisfied vacuously and SC-012
  passes by inspection.
- **Risk**: spec 025 ships immediately after 024 and shrinks the
  LLM dispatch allowlist to zero. What if 024's allowlist format
  is incompatible with 025's editing workflow?
  **Resolution**: Decision 1 (YAML list-of-mappings) is precisely
  what spec 025 Tier A1/A2 specify they will edit. The contract
  in `llm-dispatch-guard.contract.md` § Amendment process locks
  the schema both specs agree on.

---

## Open questions for `/speckit.tasks`

None. The six decisions above + the three re-used 018 contracts
fully specify the implementation work. Tasks can be enumerated
mechanically from FR-001 → FR-015 + the three backfill workstreams.
