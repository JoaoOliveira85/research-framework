# Data Model — Spec 024 Testing Infrastructure v2

**Branch**: `024-testing-infrastructure-v2`
**Status**: Phase 1 (Design & Contracts) — produced by `/speckit.plan`
**Reads from**: [research.md](./research.md), [spec.md](./spec.md) § Key Entities.

This spec's "data" is entirely test infrastructure: structured files
the guards parse, scenario payloads the fake-agent emits, and
markdown shapes the lint guards enforce. There is no runtime
business object, no production schema change. Every entity below is
either a new committed file or a new convention applied to an
existing file.

---

## Entity 1 — LLM dispatch allowlist entry (`tests/_helpers/llm_dispatch_allowlist.yaml`)

A YAML list of mappings. Each entry permits one production-code
location to invoke `claude` or `codex` via `subprocess` until the
named retirement spec ships.

### Schema (one entry)

```yaml
- file: src/research_framework/pipeline/plan_narrator.py   # str, repo-relative
  function: prepend_narrative                              # str, the function containing the bypass
  line_range: [148, 165]                                   # [int, int], inclusive; updated by hand if the function moves
  stage: research_plan_narrator                            # str, must match a fake_agent v2 stage name
  reason: |                                                # str, multi-line; the why
    Production code path predates agent_call.py.
    Routed through agent_call.py by spec 025 Tier A1.
  cleared_by: 025-simplify-pass/A1                         # str, "<spec-dir>/<task-or-tier>"; deletion gate
```

### Field-level rules

| Field | Type | Required | Validation |
|---|---|---|---|
| `file` | str | yes | Must be a relative path under `src/research_framework/`. Guard refuses entries outside the scan root. |
| `function` | str | yes | The function name in the file that contains the bypass. Future move-detection. |
| `line_range` | [int, int] | yes | Both ≥ 1; second ≥ first. Guard reports a soft warning if the function has drifted outside this range. |
| `stage` | str | yes | Must be in `fake_agent.VALID_STAGES`. Prevents stale rows pointing at deleted stages. |
| `reason` | str | yes | Free-form, multi-line; informative — not parsed by the guard. |
| `cleared_by` | str | yes | Format `<spec-dir>/<task-or-tier>`. Documentation only at 024 ship; spec 025 uses it as the deletion key. |

### At-ship contents (2 entries)

```yaml
- file: src/research_framework/pipeline/plan_narrator.py
  function: prepend_narrative
  line_range: [148, 165]   # exact bounds confirmed at impl time
  stage: research_plan_narrator
  reason: |
    Production code predates agent_call.py routing.
    Spec 025 Tier A1 will route through agent_call.py.
  cleared_by: 025-simplify-pass/A1

- file: src/research_framework/pipeline/cycle_runner.py
  function: _run_probe_retrieval_and_cache
  line_range: [TBD, TBD]   # impl-time
  stage: probe_retrieval
  reason: |
    Probe-cache retrieval invokes claude directly.
    Spec 025 Tier A2 will route through agent_call.py.
  cleared_by: 025-simplify-pass/A2
```

### State / lifecycle

- **Added** by spec 024 (this spec) at ship.
- **Modified** only via PRs that simultaneously fix the production
  code (spec 025 Tier A1 / A2).
- **Deleted entries**: removing a row REQUIRES the production fix to
  land in the same PR (enforced by the contract test in
  `specs/018-testing-strategy/contracts/llm-dispatch-guard.contract.md`).

---

## Entity 2 — fake-agent scenario response JSON files

Five new files under `tests/_helpers/fake_agent_scenarios/`. Each
file is the literal stdout the fake-agent's new stage handler
prints when that stage × scenario is selected (with two whitelisted
template placeholders the handler interpolates).

### Schema (one file per stage × scenario combination)

```
tests/_helpers/fake_agent_scenarios/
├── verifier/
│   ├── accept.json           — VerifierVerdict shape (see below)
│   ├── reject.json           — VerifierVerdict shape (see below)
│   └── malformed_json.json   — Deliberately non-JSON text wrapped in prose
├── narrator/
│   └── happy.json            — NarratorOutput shape (see below)
└── probe_retrieval/
    └── happy.json            — array of ProbeResult shapes (see below)
```

### Sub-schema 2a — `VerifierVerdict`

```json
{
  "verdict": "accept" | "reject",
  "violations": [
    {"code": "<STRING>", "message": "<STRING>"}
  ],
  "suggested_fix": "<STRING or null>"
}
```

Matches the production verifier output contract exercised by
`pipeline/verifier._extract_json_blob` (ADR-0004).

### Sub-schema 2b — `NarratorOutput`

```json
{
  "narrative": "Synthetic focus rationale for cycle {cycle}."
}
```

The `{cycle}` placeholder is interpolated by the handler from the
prompt's cycle number; no other interpolation is permitted.

### Sub-schema 2c — `ProbeResult` (array element)

```json
{
  "query": "<STRING>",
  "answer": "<STRING>",
  "sources": ["<URL>", "<URL>", ...]
}
```

### Sub-schema 2d — `malformed_json.json` (deliberate violation)

```text
Here is the verifier verdict:
```json
{verdict: "reject", missing_quotes: true}
```
That's the verdict — should be parseable by the relaxed regex.
```

Used by the `verifier`/`malformed_json` scenario to exercise the
non-strict JSON extraction added in 0.2.31 (ADR-0004).

### Whitelisted template placeholders

Only two are honored by the handler:

| Placeholder | Source | Used in |
|---|---|---|
| `{cycle}` | `_parse_cycle_from_prompt(prompt_text)` in `fake_agent.py` | narrator/happy.json |
| `{cycle:03d}` | Same, zero-padded | (none at ship; available for future scenarios) |

Anything else in a scenario file is treated as literal bytes. No
generic Jinja, no env-var interpolation, no system clock.

---

## Entity 3 — Acceptance-coverage row (markdown table cell)

The convention introduced by ADR-0008 § Spec acceptance coverage,
enforced by the FR-006 guard, and dog-fooded by every post-2026-05-21
spec.

### Schema (one row in a spec's `## Acceptance coverage` table)

```markdown
| US<N> — <user-story-title> | <evidence> |
```

`<evidence>` MUST be one of:

| Form | When | Example |
|---|---|---|
| Test path | A dedicated test exists | `` `tests/spec/test_acceptance_coverage_guard.py::test_finds_all_three_specs` `` |
| Multiple test paths | Coverage spans multiple files | `` `tests/_helpers/test_fake_agent_contract.py` (contract) + `tests/integration/test_cycle_e2e.py::test_cycle_verifier_reject_moves_note_to_rejected` (consumer) `` |
| Historical reference | Coverage shipped without a dedicated test | `_(historical — see CHANGELOG.md [0.2.27] "Probe-cache fix")_` |
| Tasks.md deferral | Pre-implementation; `/speckit.tasks` has not run yet | `_(deferred to tasks.md; test will be tests/_helpers/test_llm_dispatch_guard.py)_` |

### Guard pass / fail

- **Pass**: section exists; ≥ 1 row per user story declared in the
  spec; every row matches one of the four evidence forms.
- **Fail**: section missing OR a row is empty OR a row matches none
  of the four evidence forms.

---

## Entity 4 — CHANGELOG `### Fixed` annotation (regex shape)

The convention introduced by ADR-0008 § Regression discipline,
enforced by the FR-007 guard.

### Schema (one bullet under a `### Fixed` heading inside a released-version block)

```markdown
- <Fix description>. <Annotation>
```

`<Annotation>` MUST match exactly one of:

```regex
\(test: ([^)]+)\)
\(regression test: ([^)]+)\)
\(no test: ([^)]+)\)
```

| Annotation | Semantic |
|---|---|
| `(test: <path>::<name>)` | A pre-existing test covers this fix or was added simultaneously. The path MUST exist in the tree at lint time. |
| `(regression test: <path>::<name>)` | Test was added later (after the fix shipped). Path MUST exist at lint time. |
| `(no test: <one-line rationale>)` | No test exists; rationale explains why. Free-form text. |

### Guard pass / fail

- **Pass**: every bullet under every `### Fixed` heading in every
  released-version block (`## [X.Y.Z] - YYYY-MM-DD`) carries exactly
  one annotation; for `(test: …)` and `(regression test: …)`, the
  referenced path exists.
- **Fail**: a bullet has zero annotations, two annotations, a
  `(test: …)` or `(regression test: …)` whose path does not exist,
  or a `(no test: …)` without a rationale string.
- **Skipped**: bullets under `## [Unreleased]` blocks — annotation
  required only by release time, not in-flight.

### Multi-line bullet shape

Where a bullet spans multiple lines (e.g. nested `  - …` detail),
the annotation MUST appear on the **leading** line. Detail lines
are not parsed.

---

## Entity 5 — Backfilled spec acceptance-coverage sections (3 files)

Three existing spec files gain a new `## Acceptance coverage`
section per FR-013. The section follows the schema in Entity 3.

### Files affected

| Spec | G/W/T scenarios | Expected row count |
|---|---|---|
| `specs/_archive/015a-corpus-folder-name/spec.md` | ~4 | 1 row per US |
| `specs/017-vault-quality-fix/spec.md` | ~8 (US1–US8) | 1 row per US |
| `specs/018-testing-strategy/spec.md` | ~5 user stories | 1 row per US |

### Placement convention

The section is added **after the spec's primary content** and
**before** any `## Out of scope` or `## Assumptions` blocks that
exist at the bottom. For 015a/017/018 which lack those, the section
goes at the very end of the file.

---

## Entity 6 — CHANGELOG annotations applied to existing entries (15 sections)

Per FR-014, every `### Fixed` bullet under every released-version
block gains an annotation in place. Schema is Entity 4 above. No
new file; this is a content edit to `CHANGELOG.md`.

### Sections affected (line numbers at clarify time, commit `1b34c2b`)

```
CHANGELOG.md:191  ### Fixed (build infrastructure)
CHANGELOG.md:212  ### Fixed (lint baseline)
CHANGELOG.md:599  ### Fixed
CHANGELOG.md:752  ### Fixed
CHANGELOG.md:871  ### Fixed — validator (`scripts/validate_cycle.py`)
CHANGELOG.md:890  ### Fixed — scout prompt (`templates/prompts/scout-prompt.md.j2`)
CHANGELOG.md:960  ### Fixed
CHANGELOG.md:1069 ### Fixed — research-phase budget-field seam bug
CHANGELOG.md:1107 ### Fixed
CHANGELOG.md:1194 ### Fixed
CHANGELOG.md:1237 ### Fixed — mid-pipeline crash logs are now actually useful
CHANGELOG.md:1361 ### Fixed
CHANGELOG.md:1414 ### Fixed
CHANGELOG.md:1462 ### Fixed
CHANGELOG.md:1543 ### Fixed
```

Estimated 30–50 individual bullets across these 15 sections.

---

## Entity 7 — Smoke gate manifest re-inclusions

Two lines in `build.sh` go from commented to uncommented. No new
schema; this is a one-character change per line.

### Before (lines 73-75 at clarify time)

```bash
    # "tests/build/test_install_wizard_skip_redundant_questions.py"
    # "tests/build/test_smoke_gate_enforces_contract_tier.py"
)
```

### After

```bash
    "tests/build/test_install_wizard_skip_redundant_questions.py"
    "tests/build/test_smoke_gate_enforces_contract_tier.py"
)
```

The `SMOKE_TESTS` shell array's existing existence-check pre-flight
(per ADR-0007 + 2026-05-20 triage item #9 — see
`docs/TODO.md#restoration-notes`) will catch any silent removal of
these files after re-enablement.

---

## Entity 8 — Tier-5 e2e scenarios (new test cases in `tests/integration/test_cycle_e2e.py`)

Three new pytest test functions, each parametrized via the
fake_agent scenario env-vars per
`specs/018-testing-strategy/contracts/fake-agent.contract.md` §
Scenario selection.

### Test functions

```python
@pytest.mark.e2e
def test_cycle_oos_topic_rejected_by_verifier(tmp_path, monkeypatch):
    """Scout pollutes the topic list with an out-of-scope topic;
    verifier rejects; rejection is recorded in cycle-NNN-quality-report.json."""

@pytest.mark.e2e
def test_cycle_partial_yield_trips_diversity_gate(tmp_path, monkeypatch):
    """note_writer yields K of N topics; SG-002 diversity-gate fires
    in cycle-NNN-quality-report.json."""

@pytest.mark.e2e
def test_cycle_verifier_reject_moves_note_to_rejected(tmp_path, monkeypatch):
    """Verifier rejects a happy-path note; note moves to
    _pipeline/rejected/<note-name>.md."""
```

Each uses `vault_factory.build_minimal_vault(tmp_path, ...)` for
fixture construction; each `monkeypatch.setenv()`s the relevant
`FAKE_AGENT_<STAGE>_SCENARIO` per the v2 contract.

---

## Cross-entity invariants

- The `cleared_by` field of Entity 1 rows MUST point at spec 025's
  task IDs once spec 025's `tasks.md` lands. At 024 ship time, the
  pointer is `025-simplify-pass/A1` and `025-simplify-pass/A2`
  (named tiers from `docs/SIMPLIFY-PASS.md`); 025's `/speckit.tasks`
  will replace these with concrete task IDs in a single update PR.
- Entity 3 (acceptance-coverage rows) and Entity 5 (backfilled
  sections) share one schema. Backfills MUST pass the same lint
  guard that future specs pass.
- Entity 4 (CHANGELOG annotations) and Entity 6 (backfilled
  annotations) share one schema. Same lint guard.
- Entity 8 scenarios MUST consume Entity 2 scenario files via the
  v2 fake-agent CLI — no inline scenario data inside the test
  module.
