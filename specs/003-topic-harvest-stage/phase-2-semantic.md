# Topic propose — Phase 2 (semantic, agent-driven)

> Sibling of Phase 1 (`topic_harvest`). See
> [`spec.md`](./spec.md) for the overall architecture. This document
> specifies the **independent** second sub-stage.

## Problem

Phase 1 answers "what did the writer point at that doesn't exist yet?"
That only catches **explicit** gaps — `[[Foo]]` with no `Foo.md`.

It misses the larger class of **implicit, in-scope tangents**: topics
nobody wikilinked, but that a reasonable user of the vault would expect
to find. A recipe vault benefits from notes on **gas vs electric ovens**
long before any recipe happens to wikilink them; a pizza note might
imply **dough hydration** without ever writing `[[Dough hydration]]`.

The risk is obvious: left unfenced, an agent will propose
thermodynamics, metallurgy, and a Wikipedia tour. The whole game is the
**fence**.

## Design principles

1. **Fully independent from Phase 1.** Phase 2 reads the vault and the
   spec directly; it does not require Phase 1 to have run, and it does
   not share output files or backlog markers. Either sub-stage can be
   enabled, disabled, or replaced without the other noticing.
2. **Spec-scope is the non-negotiable fence.** Every proposal is
   evaluated against `scope.domain` and `scope.out_of_scope` from the
   vault's spec; anything outside is dropped before it reaches disk.
3. **Structure beats prose.** Each proposal must carry a
   **parent note**, a **relation type** drawn from a closed enum, and a
   one-sentence **justification**. Free-form "interesting topic" is
   rejected at validation time.
4. **Capped fan-out.** Hard per-cycle cap on proposals (default 10).
   Degrees of separation from covered topics are also capped (default
   ≤ 2) so Cycle 3's tangents can't seed a tangent explosion in Cycle 4.
5. **Best-effort, never fails the cycle.** Same contract as Phase 1:
   any error (timeout, invalid JSON, verifier rejection) logs a WARN
   and exits 0.
6. **Opt-in by default.** Disabled in the shipped `settings.yaml`
   profiles; users flip one boolean to turn it on, and tune caps
   without touching Python or shell code.
7. **Auto-promote by default.** When Phase 2 is enabled, accepted
   proposals flow into the **next** cycle's scout `target_topics` list
   automatically. Users keep the valve: `auto_promote: false` reverts
   to backlog-only mode (scout reads them as soft hints). Rationale:
   the whole point of Phase 2 is to expand coverage; making users
   hand-promote every proposal defeats the purpose.

## Pipeline placement

```
scout → validate_scout → DFS → quality suite → post-metrics
    → validate_research
    → Step 7a: topic_harvest (Phase 1, deterministic)
    → Step 7b: topic_propose (Phase 2, agent — this spec)
    → exit
```

Phase 2 runs **after** Phase 1 strictly so it can read Phase 1's manifest
to dedup titles (soft coupling — advisory, not required). If Phase 1
didn't run or failed, Phase 2 proceeds with an empty dedup set.

## Inputs

| Input | Purpose | Source |
|-------|---------|--------|
| Touched notes (new / updated this cycle) | Content to reason over | `cycle-NNN-research.json` → `notes_created` + `notes_updated` |
| Spec scope | Fence | `_pipeline/spec-parse.json` → `scope.domain`, `scope.out_of_scope` |
| Coverage gaps | Priority signal | `_pipeline/coverage-targets.json` |
| Backlog | Dedup against already-queued | `_pipeline/research-backlog.md` |
| Phase 1 manifest | Dedup against wikilink gaps | `cycle-NNN-harvest.json` (optional) |

## Outputs

### 1. `_pipeline/cycles/cycle-NNN-propose.json`

Separate file from Phase 1's manifest so neither stage can corrupt the
other's output.

```json
{
  "schema_version": "1.0",
  "cycle": 3,
  "phase": "propose",
  "timestamp": "2026-04-29T09:15:00Z",
  "model": "haiku",
  "proposals": [
    {
      "title": "Gas Oven",
      "relation_type": "variant",
      "parent_note": "data_vault/01 - Concepts/Oven.md",
      "justification": "Pasta recipes reference oven temperatures but don't distinguish combustion vs. resistive heating, which affects browning and moisture.",
      "degree": 1,
      "scope_check": "in_scope",
      "suggested_note_type": "concept"
    }
  ],
  "rejected": [
    {
      "title": "Heat transfer through metal",
      "relation_type": "prerequisite",
      "parent_note": "data_vault/01 - Concepts/Oven.md",
      "justification": "Heat transfer theory underpins all cooking.",
      "rejected_by": "scope_check",
      "reason": "title contains out_of_scope term 'heat transfer'"
    }
  ],
  "stats": {
    "proposed": 4,
    "accepted": 3,
    "rejected": 1,
    "dropped_dedupe": 2
  }
}
```

### 2. `_pipeline/research-backlog.md` — independent managed block

Different marker from Phase 1 so both can coexist in the same file:

```markdown
<!-- topic-propose:cycle=003 -->
## Proposed tangents — cycle 003 (agent)

Scope-bounded tangents the agent identified. Review before promoting to a
cycle target; mark `<!-- rejected -->` on a line to suppress from future cycles.

- **Gas Oven** (variant of [[Oven]]) — Pasta recipes reference oven temperatures but don't distinguish combustion vs. resistive heating, which affects browning and moisture.
- **Convection setting** (variant of [[Oven]]) — …
<!-- /topic-propose:cycle=003 -->
```

## Relation-type enum (closed set, configurable)

| Relation | Meaning | Example |
|----------|---------|---------|
| `variant` | A subtype or specialization of a covered topic | Oven → Gas Oven |
| `prerequisite` | Something the covered topic depends on | Pizza → Dough hydration |
| `contrast` | A peer that matters for comparison | Wok → Saucepan |
| `sibling` | Same generation, shared parent | Oven → Stovetop |
| `downstream_effect` | What the covered topic causes / enables | Resting time → Texture |
| `user_question` | Question a vault user would reasonably ask | Pizza → "Which flour?" |

Unknown relation types are **rejected** at validation (fail-closed).
Operators can narrow the set further in `settings.yaml`; they cannot
silently add new values without also extending the validator.

## Degrees of separation

- **Degree 1**: parent note was created or updated **this cycle**.
- **Degree 2**: parent note exists in vault and is wikilinked from a
  note touched this cycle.
- **Degree ≥ 3**: rejected (default; `max_degree` setting).

Rationale: tangents-of-tangents compound per cycle. Forcing proposals
back onto fresh or directly-connected work keeps total topic count
linear with cycles, not super-linear.

## Validation / verifier gate

Rule-based gate in `scripts/topic_propose.py` (not the verifier skill —
these rules are structural, not editorial). Each proposal must pass all
of:

1. **Schema well-formed** — required fields present, types correct.
2. **`relation_type`** — in the configured enum.
3. **`parent_note`** — resolves to a real file under `data_vault/`.
4. **`degree`** ≤ `max_degree`.
5. **Scope check** — title and justification must not contain any term
   from `scope.out_of_scope`; title should intersect with `scope.domain`
   vocabulary (soft match — warnings, not rejections).
6. **Dedup** — normalized title not already an existing note, not in the
   current backlog, not in the Phase 1 manifest.

Proposals that fail 1–4 or 6 land in `rejected[]` with a
**structured diagnostic** — full original proposal fields plus
`rejected_by` (which rule fired) and `reason` (human-readable
explanation). Rejected entries are NOT rendered into the backlog; they
live only in the JSON manifest as a signal for spec tuning. Proposals
that only trigger the soft-match scope warning still ship but are
tagged `scope_check: "warn"` for human review.

Rejection-rule enum for `rejected_by`:
`schema_invalid`, `bad_relation`, `parent_missing`, `degree_exceeded`,
`scope_check`, `dedupe_existing_note`, `dedupe_backlog`,
`dedupe_phase1`, `cap_exceeded`.

## Settings contract

Each sub-stage has its own `settings.yaml` block. Add to `settings.yaml`
and `settings.codex.yaml` alongside the existing `stages:` entries:

```yaml
stages:
  # --- Topic harvest (Phase 1): deterministic; zero LLM cost -----------
  # Does not use `type`, `model`, `skill` — it's a Python script.
  topic_harvest:
    enabled: true
    max_followups: 100
    output_filename: "cycle-{cycle:03d}-harvest.json"
    backlog_marker: "topic-harvest"

  # --- Topic propose (Phase 2): agent-driven tangent finder ------------
  # Opt-in: disabled by default so zero-cost profiles stay zero-cost.
  topic_propose:
    enabled: false
    model: haiku                 # cheap by default; NOT router-eligible in v1
    skill: topic-propose
    timeout_s: 900
    max_proposals: 10
    max_degree: 2
    output_filename: "cycle-{cycle:03d}-propose.json"
    backlog_marker: "topic-propose"
    relation_types:
      - variant
      - prerequisite
      - contrast
      - sibling
      - downstream_effect
      - user_question
    # Accepted proposals flow into the NEXT cycle's scout target_topics
    # when true. Set false to keep them as backlog-only hints.
    auto_promote: true
    # Phase 2 requires an `out_of_scope` list in the spec (see
    # "Spec prerequisite" below). The setting only controls what
    # happens if the list is missing: skip (default), warn, or error.
    on_missing_out_of_scope: skip   # skip | warn | error
```

The model router's `eligible_stages` list is intentionally NOT extended
to include `topic_propose`. The stage's closed-schema output means
structure carries the quality, not reasoning depth — haiku is
sufficient. Power users who disagree can set `model: opus` directly
in their profile. This decision can be revisited with real-world data
(see "Open questions" below).

The Codex profile mirrors this with `model: gpt-5.4` and the low-reasoning
`args` override, same as other cheap stages in that file.

## Skill contract (`.agents/skills/topic-propose/SKILL.md`)

The skill must:

- Accept the five inputs listed in [Inputs](#inputs) as a structured prompt.
- Emit **only** the JSON specified in [Outputs](#outputs) — no prose.
- Include every proposal's `parent_note`, `relation_type`,
  `justification`, `degree`, `suggested_note_type`. Missing fields →
  structural rejection.
- Respect the cap: **never** emit more than `max_proposals` entries in
  `proposals[]`. Over-budget proposals go to `rejected[]` with
  reason `cap_exceeded`.
- Include a `rejected[]` list for anything it self-rejected (e.g. it
  knew the topic was out of scope). This is diagnostic, not
  authoritative.

The skill file will:

1. State the scope fence in the **first paragraph** of the prompt.
2. Include a few-shot block with 2 in-scope and 2 out-of-scope examples
   drawn from the spec's domain.
3. Forbid the agent from writing anything other than the JSON object.

## Runtime wiring

`scripts/topic_propose.py` (new):

- Read settings → if `enabled == false`, log and exit 0.
- Load inputs, build the prompt, call `scripts/agent_call.py` with
  `--stage topic_propose`.
- Parse JSON, run the validation gate, write the manifest, render the
  backlog block via the same managed-block helpers used by Phase 1.
- Exit 0 regardless of agent success (best-effort).

`scripts/run_cycle.sh` gets Step 7b:

```bash
# Step 7b: topic propose (agent, opt-in; best-effort)
if [[ ${RESEARCH_EXIT} -ne 2 ]]; then
    "${PYTHON_BIN}" "${SCRIPTS_DIR}/topic_propose.py" "${VAULT_DIR}" "${CYCLE}"
fi
```

(Settings drive the enabled flag; the shell never reads it.)

## Scout integration

Two paths, depending on `auto_promote`:

1. **Auto-promote (default `true`):** Between cycles, the orchestrator
   reads the **latest** `cycle-NNN-propose.json`, extracts
   `proposals[].title` for entries with `scope_check in {"in_scope",
   "warn"}`, and appends them to the next cycle's `target_topics`
   (merged with existing code-scan / coverage-gap targets, deduped).
   This is a **one-way read** — the orchestrator consumes Phase 2
   output; Phase 2 doesn't know the orchestrator exists.
2. **Backlog-only (`auto_promote: false`):** Scout reads the
   `<!-- topic-propose:cycle=N -->` block in `research-backlog.md` as
   soft hints, same as Phase 1's Harvest block.

`templates/prompts/scout-prompt.md.j2` is updated in both cases to note:

- The **Proposed tangents** backlog block is agent-suggested, lower
  priority than the Phase 1 Harvest block.
- Proposals flagged `scope_check: "warn"` should be spot-checked for
  scope fit before being promoted to `topics_found.new`.

## Spec prerequisite — `scope.out_of_scope`

Phase 2 **requires** a non-empty `scope.out_of_scope` list in the
vault's spec. The fence is meaningfully weaker without one, so this is
enforced at the spec-validation layer:

- `scripts/validate_spec.py` emits a **WARNING** (not an error) when
  `scope.out_of_scope` is missing or empty. Phase 1 is unaffected.
- `scripts/topic_propose.py` reads `on_missing_out_of_scope` at runtime:
  `skip` (default) exits 0 with a logged reason; `warn` proceeds with
  an empty fence and tags every proposal `scope_check: "warn"`;
  `error` exits 0 after logging but writes an empty manifest with
  `stats.rejected_reason: "no_out_of_scope"` so downstream tools can
  surface the configuration problem.

Recipe-vault example:

```yaml
scope:
  domain: "Home cooking techniques and recipes"
  out_of_scope:
    - "molecular thermodynamics"
    - "food chemistry beyond Maillard / emulsification"
    - "commercial kitchen operations"
    - "nutrition science"
```

## Failure modes (every one exits 0 and logs WARN)

| Failure | Behaviour |
|---------|-----------|
| `enabled: false` | Exit 0 immediately, no output. |
| `require_out_of_scope: true` and spec has no `out_of_scope` | Honor `on_missing_out_of_scope` (`skip` default). |
| Agent timeout | Log timeout, write empty manifest with `stats.proposed = 0`. |
| Agent emits non-JSON / malformed JSON | Log the parse error, empty manifest. |
| Individual proposal fails validation | Drop to `rejected[]`, keep the rest. |
| `max_proposals` exceeded | First `max_proposals` by agent order go to `proposals[]`, rest to `rejected[]` with `cap_exceeded`. |
| Target vault dir unreadable | Exit 0 with WARN; never block the cycle. |

## Files to add

| Path | Purpose |
|------|---------|
| `scripts/topic_propose.py` | Phase 2 stage driver + validation gate |
| `.agents/skills/topic-propose/SKILL.md` | Agent contract (prompt + rules) |
| `templates/prompts/topic-propose-prompt.md.j2` | Runtime prompt template |
| `tests/scripts/test_topic_propose.py` | Unit coverage (see test matrix below) |
| `settings.yaml` | New `stages.topic_propose` block |
| `settings.codex.yaml` | Codex mirror of the block |
| `scripts/run_cycle.sh` | Step 7b wiring |
| `templates/prompts/scout-prompt.md.j2` | Lower-priority guidance for tangents block |

## Test matrix

Unit (script-level, with an agent stub that returns canned JSON):

1. **Disabled by default** — `enabled: false` → no manifest written,
   exit 0.
2. **Happy path** — stub returns 3 valid proposals → manifest has 3
   entries, backlog block rendered with 3 bullets.
3. **Parent note missing** → proposal moved to `rejected[]`.
4. **Unknown relation type** → proposal moved to `rejected[]`.
5. **Out-of-scope term in title** → proposal moved to `rejected[]` with
   reason `out_of_scope`.
6. **Degree > max_degree** → rejected.
7. **Cap exceeded** — stub returns 15 with `max_proposals: 10` → first
   10 accepted, last 5 rejected with `cap_exceeded`.
8. **Dedup against Phase 1 manifest** — title already in
   `cycle-NNN-harvest.json` followups → dropped with reason
   `dedupe_phase1`.
9. **Dedup against existing note** — title stem matches an existing
   file → dropped.
10. **Missing out_of_scope in spec** with `on_missing_out_of_scope: skip`
    → stage exits 0, writes empty manifest, logs the skip reason.
11. **Malformed JSON from agent** → empty manifest, WARN logged,
    exit 0.
12. **Coexistence with Phase 1** — running Phase 1 then Phase 2 produces
    two separate files and two separate backlog blocks in the same
    `research-backlog.md`, neither disturbing the other.
13. **Auto-promote ON (default)** — a vault with a valid
    `cycle-001-propose.json` containing 3 accepted proposals builds a
    cycle-002 scout prompt whose `target_topics` includes all 3 titles.
14. **Auto-promote OFF** — same fixture but `auto_promote: false` → the
    titles do NOT appear in `target_topics`; the scout still sees the
    backlog block.
15. **Missing `scope.out_of_scope`** + `on_missing_out_of_scope: skip` →
    manifest written with `stats.rejected_reason: "no_out_of_scope"`,
    zero proposals, exit 0.

Integration (`tests/generator/test_integration.py`):

- Generated vault includes `scripts/topic_propose.py`,
  `.agents/skills/topic-propose/SKILL.md`, and the Codex / Claude
  profiles both carry the new `stages.topic_propose` block with the same
  keys (values may differ).
- `validate_spec.py` emits a warning on a sample spec missing
  `scope.out_of_scope` and does NOT error.

## Decisions log

Resolved during spec review (2026-04-29):

1. **`scope.out_of_scope` required when Phase 2 is enabled.**
   `validate_spec.py` emits a warning when missing; Phase 2's runtime
   behaviour is governed by `on_missing_out_of_scope` (default `skip`).
   Phase 1 is unaffected.
2. **Auto-promote ON by default.** Accepted proposals flow into the
   next scout's `target_topics`. User can set `auto_promote: false` to
   keep backlog-only hints.
3. **Model-router eligibility for `topic_propose`: NO in v1.** Default
   model is `haiku` (or `gpt-5.4` on Codex). Power users can pin a
   stronger model via `stages.topic_propose.model`. Revisit when we
   have real-world quality data from dense vaults.
4. **Rejections live in the JSON manifest only**, with full diagnostic
   shape: `{title, relation_type, parent_note, justification,
   rejected_by, reason}`. Backlog shows only accepted actionable items.

Resolved during implementation (2026-04-29):

5. **`validate_spec.py` warning wording.** Appended to the existing
   `_warnings_from_raw` list (no new channel). Exact text:
   > `scope.out_of_scope is missing or empty. Phase 1 is unaffected,
   > but Phase 2 (stages.topic_propose) will follow
   > \`on_missing_out_of_scope\` (default 'skip') instead of proposing
   > tangents against an empty fence.`
6. **Persistent rejects are scope-only.** `_pipeline/propose-rejects.md`
   records titles rejected with `rejected_by: scope_check` and nothing
   else. Transient reasons (`cap_exceeded`, `dedupe_*`, `parent_missing`,
   `schema_invalid`, `bad_relation`, `degree_exceeded`) stay in the
   manifest but are not persisted — they may become valid next cycle.
7. **Per-cycle scout-prompt re-render extended beyond resume mode.**
   The orchestrator now re-renders the scout prompt for every
   `cycle_num >= 2`, unifying the resume and normal paths. Without
   this, auto-promote would only fire on resume runs. Cycle 1 still
   uses the generate-time prompt.

## Non-goals

- Any change to Phase 1's deterministic harvester.
- Any change to the scout, DFS, or verifier skill contracts beyond the
  backlog wording tweak.
- Automatic note-writing from proposals. Proposals are **topics**, not
  notes; writing happens in a later cycle's DFS if the scout selects
  them.
- Network lookups to validate topic existence on external sources.
  The spec's `data_sources` already carry that responsibility; this
  stage is offline.
