# Feature Specification: Obsidian Canvas Auto-Generation

**Feature Branch**: `043-obsidian-canvas-autogen`
**Created**: 2026-05-27 (promoted from `docs/ROADMAP.md` Horizon 2 "Obsidian Canvas frontend" + queue item #11 during post-Wave-1 doc restructure).
**Status**: planned — DRAFT (full spec; awaiting `/speckit.clarify` on 3 open questions). Post-revival, post-spec-022 (quality first), post-spec-020-Tier-1-ports (need source-cache signal for value gauges). Low priority — UX polish, not pipeline foundation.

**Input**: Two Obsidian Canvas files generated and maintained automatically per vault: `_pipeline/research-pipeline.canvas` (static, install-time) showing the configured pipeline, and `_pipeline/vault-state.canvas` (cycle-end refresh) showing newly added content, source-health gauges, and the open backlog. Every generated vault uses Obsidian as the frontend, but the framework's output today is just markdown files + JSON sidecars. Users who installed the framework but don't read the docs have no visual way to understand "what does my vault do?" or "what changed this cycle?". Surfacing both through Obsidian's native Canvas feature meets users where they already look.

## Clarifications

### Pending — `/speckit.clarify` session TBD

- **Q1 (FR-010 / user_owned detection)**: How do we detect "user_owned" nodes — a reserved metadata field on the canvas JSON (explicit marker), or "anything we didn't write" by hash-comparison against the previous auto-write (implicit)? Default proposed: explicit metadata field `_research_framework_owned: bool`. Nodes WITHOUT this field are user-owned. Nodes WITH `_research_framework_owned: true` are auto-managed.
- **Q2 (FR-014 / Canvas 2 layout)**: Canvas 2 layout — deterministic grid (every cycle re-shuffles positions of nodes whose order changed) OR stable layout (existing nodes keep positions; new nodes append)? Default proposed: STABLE layout — existing nodes keep positions; new nodes append below the last node in their group. User position-customizations survive cycles.
- **Q3 (FR-016 / cost gauge)**: Should Canvas 2 also have a "Cost gauge" node showing remaining budget per spec 033 (useful for autonomous-mode users)? Default proposed: yes — small gauge node in the "Vault-state header" group showing cumulative cycle spend / cap percentage.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — "What does my vault do?" answered visually (Priority: P2)

A new user installs the framework, opens their vault in Obsidian, and opens `_pipeline/research-pipeline.canvas`. They see a visual diagram of the configured pipeline: stages (scout → research → write → verify), executors backing each (Claude / Codex / Ollama), source modules installed (youtube, oreilly, reddit, etc.), budget caps (per spec 033). In <2 minutes they understand what their vault is configured to do without reading any docs.

**Why this priority**: Discoverability for non-doc-readers. The framework's primary failure mode in 2026-05-15 trial run was "user didn't understand what was configured". P2 because the pipeline IS documented in markdown; this just surfaces it visually.

**Independent Test**: Install a fresh vault with 5 stages + 3 source modules. Verify: `_pipeline/research-pipeline.canvas` exists; opening it in Obsidian renders the expected layout (stages as nodes, executors as edges, source modules grouped together).

**Acceptance Scenarios**:

1. **Given** a fresh `install.sh` run, **When** the install completes, **Then** `_pipeline/research-pipeline.canvas` exists with the configured stages + executors + source modules as nodes.
2. **Given** the canvas, **When** opened in Obsidian, **Then** the layout renders without errors AND the visual structure matches the configured `settings.yaml`.
3. **Given** the operator modifies `settings.yaml` (adds a stage, changes an executor), **When** they re-run `./vault update`, **Then** `research-pipeline.canvas` is updated to reflect the changes.

---

### User Story 2 — "What changed this cycle?" answered visually (Priority: P2)

After every `./vault research` cycle, the operator opens `_pipeline/vault-state.canvas` in Obsidian. They see:
1. **Newly added content (this cycle)**: fresh notes grouped by `coverage_targets` category, with wikilinks.
2. **Source list with value gauges**: every source rendered as a node, sized by citation count, coloured by source-quality (green / yellow / red).
3. **Open backlog**: orphan wikilinks + stub notes the next cycle will try to resolve.

In <3 minutes they understand what changed, what's healthy, and what's pending.

**Why this priority**: The visual roll-up complement to the markdown digest (spec 035) — different surface, same goal. P2 because the digest is the primary roll-up channel; canvas is for visual learners.

**Independent Test**: Run a cycle on a fixture vault. Verify: `_pipeline/vault-state.canvas` exists; the 3 logical groups are present; the source gauges colour correctly based on quality scores; opening in Obsidian renders cleanly.

**Acceptance Scenarios**:

1. **Given** a cycle just completed, **When** the operator opens `vault-state.canvas`, **Then** the 3 logical groups (Newly Added, Source List, Open Backlog) are present + populated.
2. **Given** a source with high quality score (>0.8) and 10+ citations, **When** the canvas renders, **Then** that source's node is green + large.
3. **Given** a source approaching auto-archive threshold (quality <0.3), **When** the canvas renders, **Then** that source's node is red.
4. **Given** orphan wikilinks exist in vault notes, **When** the canvas renders, **Then** the Open Backlog group lists them as nodes.

---

### User Story 3 — User-added nodes survive auto-regeneration (Priority: P1)

The operator opens `vault-state.canvas`, manually adds a node + group ("My priorities"), positions it where they want. The next cycle runs. The operator's added nodes + groups are STILL THERE, in the same positions, with the same content. Only the auto-managed groups (Newly Added, Source List, Open Backlog) were re-rendered.

**Why this priority**: This is the INVARIANT. Without it, the canvas is unusable — users would never customize a canvas the framework re-writes from scratch every cycle. P1 because losing user data is the worst failure mode.

**Independent Test**: Run a cycle. Manually add a node to `vault-state.canvas` (no `_research_framework_owned` field). Run another cycle. Verify: the manually-added node is STILL present at the same position; the auto-managed groups were updated.

**Acceptance Scenarios**:

1. **Given** the operator adds a node WITHOUT the `_research_framework_owned` metadata field, **When** the next cycle runs, **Then** the operator's node is preserved (position + content unchanged).
2. **Given** the operator moves an auto-managed node, **When** the next cycle runs, **Then** the auto-write either: respects the new position (per Q2 stable-layout default) OR re-renders to the canonical position (per Q2 grid alternative).
3. **Given** the operator deletes an auto-managed node, **When** the next cycle runs, **Then** the auto-write re-creates it (it's the framework's responsibility).
4. **Given** the operator manipulates the canvas JSON directly, **When** the next cycle runs, **Then** the framework parses the existing canvas BEFORE writing, carrying through user_owned nodes.

---

### User Story 4 — Canvases work without an Obsidian dep (Priority: P2)

The framework writes `.canvas` files as JSON conforming to Obsidian's documented schema. The framework has NO Obsidian dependency, NO Obsidian binary invocation. Users who don't use Obsidian (e.g. headless servers, alternative editors) simply don't open the canvas files — the framework still operates.

**Why this priority**: Principle V (offline-first / no new runtime deps). Obsidian is a frontend; the framework should write its files but not depend on it.

**Acceptance Scenarios**:

1. **Given** the framework code, **When** auditing imports, **Then** no Obsidian-specific library / binary is imported.
2. **Given** a server without Obsidian installed, **When** the framework runs, **Then** all cycles complete + canvas files are produced (just unviewed).
3. **Given** the canvas file format evolves in Obsidian, **When** the framework's schema-version doesn't match, **Then** the framework writes the BEST version it knows + logs the schema version expected vs written.

---

### Edge Cases

- What if Obsidian's `.canvas` JSON schema evolves and breaks compat? → Pin to the schema version the framework supports at impl time (e.g. Obsidian 1.5 canvas v1.0). Document the supported version in the canvas file's metadata. Update on a separate spec when needed.
- What if the operator opens the canvas while a cycle is mid-write? → Atomic-write semantics (write to `.tmp`, fsync, rename). Obsidian's reader sees either the old version or the new — never a partial.
- What if the canvas file is corrupted (manual edit gone wrong)? → Framework attempts to repair (drop unknown nodes, regenerate auto-managed ones); on irreparable corruption, logs an error + writes a fresh canvas (operator-owned content is lost — document this risk).
- What if a vault has 1000+ sources? → Source list group renders only the top N (configurable; default 50) by activity; remaining sources are reachable via the markdown digest.
- What if user_owned nodes reference notes that were deleted? → Preserve the user_owned node verbatim — don't auto-resolve broken refs. User's responsibility.
- What if the cost gauge (per Q3) shows a budget that was changed mid-cycle (operator edited `settings.yaml`)? → Show the gauge at last-cycle-end; document that mid-cycle config changes don't reflect until next cycle.

## Requirements *(mandatory)*

### Functional Requirements

#### Canvas 1 — Pipeline visualization

- **FR-001**: A new `_pipeline/research-pipeline.canvas` file MUST be generated at the END of `install.sh` (and re-generated on `./vault update`).
- **FR-002**: The canvas MUST contain nodes for: each configured stage in `settings.yaml`, each configured source module, each budget cap (per spec 033). Edges connect stages to their executors + source modules.
- **FR-003**: The canvas MUST be deterministic — same `settings.yaml` produces byte-identical canvas (modulo a rendered-at timestamp in the metadata).
- **FR-004**: Re-running `install.sh` or `./vault update` with no `settings.yaml` change MUST produce a byte-identical canvas (idempotent).

#### Canvas 2 — Vault state + freshness

- **FR-005**: A new `_pipeline/vault-state.canvas` file MUST be generated at the END of every `./vault research` cycle.
- **FR-006**: The canvas MUST contain three logical groups (Obsidian Canvas supports groups natively):
  - "Newly added content (this cycle)" — fresh notes from this cycle grouped by `coverage_targets` category.
  - "Source list with value gauges" — every source in `_pipeline/sources.db` as a node.
  - "Open backlog" — orphan wikilinks + stub notes pending resolution.
- **FR-007**: Source nodes MUST be sized by citation count (proportional, with reasonable min/max bounds).
- **FR-008**: Source nodes MUST be coloured by source-quality score: GREEN (>0.7), YELLOW (0.3-0.7), RED (<0.3, approaching auto-archive). Colours configurable in `settings.yaml::canvas.colors`.
- **FR-009**: Per Q3 default, the canvas MUST include a "Cost gauge" node in the header group showing cumulative cycle spend / budget cap as a percentage gauge.

#### User-owned node preservation (CRITICAL INVARIANT)

- **FR-010**: Per Q1 default, auto-managed nodes MUST carry a `_research_framework_owned: true` metadata field. Nodes WITHOUT this field are user-owned. The framework MUST NEVER modify or remove user-owned nodes.
- **FR-011**: Before writing a canvas, the framework MUST parse the existing canvas (if present), extract user-owned nodes + groups, and write them BACK to the new canvas unchanged.
- **FR-012**: User-owned groups (i.e. groups WITHOUT `_research_framework_owned: true`) MUST be preserved verbatim — the framework does not modify, position, or remove them.
- **FR-013**: Auto-managed group names MUST follow a deterministic pattern (e.g. `_auto:newly-added`, `_auto:source-list`, `_auto:open-backlog`) so the writer can identify them across cycles.

#### Layout

- **FR-014**: Per Q2 default, canvas layout is STABLE — existing auto-managed nodes keep their positions across cycles; new nodes append below the last existing node in their group.
- **FR-015**: First-time canvas generation (no prior file) uses a default grid layout grouped by category for predictability.

#### Cross-cutting

- **FR-016**: Canvas files MUST conform to the Obsidian `.canvas` v1 JSON schema (or the latest version supported at impl time, documented in the file's metadata).
- **FR-017**: Canvas writes MUST be atomic (write to `.tmp`, fsync, rename) so concurrent reads by Obsidian never see partial JSON.
- **FR-018**: The framework MUST NOT import any Obsidian-specific library or invoke any Obsidian binary. Canvas files are plain JSON.
- **FR-019**: Corrupted canvas files MUST be repaired (drop unknown nodes, regenerate auto-managed) OR replaced with a fresh canvas + a logged warning. NEVER fail the cycle on canvas error.

### Key Entities

- **`_pipeline/research-pipeline.canvas`**: Static-ish canvas regenerated on install / vault update. Pipeline visualization.
- **`_pipeline/vault-state.canvas`**: Cycle-end canvas regenerated every cycle. Vault state + freshness.
- **`_research_framework_owned` metadata field**: Per-node JSON field marking auto-managed nodes. Per Q1 — explicit opt-in for framework ownership.
- **Auto-managed group naming**: `_auto:<group-name>` pattern per FR-013.
- **Canvas writer**: A new module (`src/research_framework/canvas/writer.py` or similar) responsible for parsing existing canvas, preserving user-owned nodes, writing new auto-managed nodes.
- **`canvas.colors` settings block**: Optional `settings.yaml` block to override default source-quality colours.
- **Cost gauge node** (per Q3 default): A specially-formatted node in `vault-state.canvas` header group showing cumulative spend / cap percentage.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of fresh `install.sh` runs produce a valid `research-pipeline.canvas` that renders cleanly in Obsidian.
- **SC-002**: 100% of `./vault research` cycles produce/update `vault-state.canvas`.
- **SC-003**: Across 100 manufactured cycles on the feeds-vault fixture with user-added nodes, ZERO user-owned nodes are lost (FR-010 invariant).
- **SC-004**: Canvas generation completes in <2 seconds for a vault with 100 sources + 500 notes (no perceptible slowdown).
- **SC-005**: After this spec ships, the 2026-05-15 trial-run operator's "what's my vault doing" friction is resolved (verified via post-revival operator interview).

## Assumptions

- Obsidian's `.canvas` JSON schema stays stable through 2026. (Spec amends if schema rev'd materially.)
- Operators who use Obsidian want visual surfaces; operators who don't use Obsidian don't care (per FR-018, the framework writes the files but doesn't depend on the renderer).
- Source-quality scores from spec 030's harness are sufficient signal for the source-gauge colors.
- The 3-group layout (Newly Added / Source List / Open Backlog) is the right structure; if real operators want a different shape post-revival, this spec may rev to v2.

## Dependencies

- **Hard**: Spec 020 (source modules) — source-cache signal is required for source-gauge data.
- **Hard**: Spec 022 (E2E quality harness v1) — source-quality scores feed the gauge colours.
- **Hard**: Spec 030 (quality harness v3) — `source_quality` metric family powers the gauges.
- **Soft**: Spec 035 (cross-cycle digest) — canvas roll-up + markdown digest are complementary surfaces.
- **Soft**: Spec 033 (cost enforcement) — cost gauge (per Q3) reads from 033's telemetry.

## Acceptance coverage

Draft — evidence cells populated by `/speckit.tasks` after `/speckit.clarify`.

| User Story | Evidence |
|---|---|
| US1 — "What does my vault do?" answered visually | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US2 — "What changed this cycle?" answered visually | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US3 — User-added nodes survive auto-regeneration | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US4 — Canvases work without an Obsidian dep | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |

## Out of Scope

- A `.canvas` editor inside the framework. Obsidian owns the editor.
- Replacing per-cycle markdown reports. Canvases supplement; markdown stays canonical.
- Interactive canvas behaviour (live updates while user is viewing). Framework writes static files; Obsidian renders them.
- Cross-vault canvases (one canvas spanning multiple vaults). Out until multi-vault aggregation ships per spec 023 Phase 2 / spec 036 v2.
- LLM-generated canvas layouts. Deterministic algo only; no LLM in the loop.
- Real-time canvas refresh during a running cycle. Cycle-end refresh only.

---

*Promote to active queue by running `/speckit.clarify` against this draft; the three pending clarifications (Q1-Q3) gate the promotion to `IMPLEMENTABLE`. Low priority — wait until quality harness (022) is sustainably green and Tier-1 module ports (Wave 2) are landing.*
