# Feature Specification: Assistant-Framework Integration

**Feature Branch**: `036-assistant-framework-integration`
**Created**: 2026-05-27 (promoted from `docs/TODO.md` during the post-Wave-1 doc restructure).
**Status**: planned — clarified 2026-09-08: Q1–Q3 resolved by owner decision (see § Clarifications), the envelope-evolution policy recorded in ADR-0013, and `tests/contracts/vault-ask-1.0.schema.json` committed ahead of any producer. Three-phase plan agreed 2026-05-27 with the assistant-framework agent; v1 is now queued in v1.4.0 ("contracts a consumer can build against"), v2 against assistant-framework Phase 5.

**Input**: Sibling project [`assistant-framework`](https://github.com/JoaoOliveira85/assistant-framework) is a separate codebase. Its Phase 5 (AI & Learning) needs structured access to research vaults — both inbound (assistant asks the vault a question via `./vault ask`) and outbound (research-framework pushes cycle results to the assistant's inbox). Today there's no contract: `./vault ask` returns human markdown, and `research-framework` has no notion of a downstream consumer. Without a defined contract, every integration session re-invents the wire format. The "research-as-a-service" arc described in ROADMAP Horizon 3 needs to ship in flat-file slices rather than as a big rewrite, preserving the deploy-time-separability invariant.

## Clarifications

### Resolved 2026-09-08 (owner decision D5; ADR-0013)

- **Q1 (FR-005 / v1 schema evolution)** → **Additive.** Evolution within `1.x` is append-only: new fields are optional, nothing is removed, renamed, retyped or made required; a consumer ignores fields it does not know and refuses a major it does not know. Every envelope carries `schema_version` **as a safeguard that is recorded but not acted on yet** — no negotiation, handshake or migration code is built until a consumer exists; the field is there so a consumer *can* refuse. The rule is cross-spec (the inbox envelope, the #189 claims export and eventually the note format face the same question), so it lives in ADR-0013 and this spec cites it rather than restating it. The ADR was written before the schema, as the owner asked; `tests/contracts/vault-ask-1.0.schema.json` now exists and pins the policy (`schema_version` pattern `^1\.[0-9]+$`, `additionalProperties: true`).
- **Q2 (FR-009 / v2 inbox path)** → **Configurable, with the proposed default.** `settings.yaml::integrations.assistant.inbox_path`, default `~/.assistant/inbox/`; when `${ASSISTANT_HOME}` is set the default becomes `${ASSISTANT_HOME}/inbox/`. A run-control key, so it lives in settings per ADR-0011.
- **Q3 (FR-002 / 023 Phase 2 overlap)** → **036 v1 ships first; 023 Phase 2 references this spec's contract as the source of truth.** The headless requirement 023 FR-003 already states is the precondition (see § Preconditions found while clarifying); the *shape* of the JSON answer is this spec's and 023 does not redefine it.

### Preconditions found while clarifying

- **`./vault ask` is an interactive `claude` session today.** `templates/vault-script.sh.j2`'s `ask` arm checks for the `claude` binary, `cd`s into the vault and runs `claude "$@"` (spec 077 § `./vault` table: "interactive `claude` in the vault, then auto-commit"). There is no framework-side answer producer to emit JSON. FR-001's `--format json` therefore needs a headless `ask` path that dispatches the rendered `ask` command template through `agent_call` (`078` FR-001, FR-008) and parses the answer into the envelope — 023 FR-003's headless rule, applied to this verb. That path is T001's first deliverable and is why v1 is no longer "a 2–4 hour quick-win".
- **The v2 inbox schema is not written yet, on purpose.** `tests/contracts/research-result-1.0.schema.json` is written under ADR-0013's rule when v2 is planned against assistant-framework Phase 5, not speculatively now; the constitution's obligations row for it stays **Not met** until then and says so.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Assistant queries vault via subprocess + JSON (Priority: P2, v1)

The assistant-framework runtime needs to ask the research vault a question. It invokes `./vault ask "What's the best way to deploy a Cassandra cluster?" --format json` as a subprocess. The vault returns a structured JSON response matching `tests/contracts/vault-ask-1.0.schema.json`. The assistant parses + integrates the answer.

**Why this priority**: v1 is the MINIMUM viable contract. The CLI subprocess model preserves deploy-time-separability (per Principle V + ROADMAP Horizon 3) — no in-process imports, no Python ABI coupling. P2 (not P1) because the existing markdown output works for human consumers today; v1 is purely additive for the assistant integration.

**Independent Test**: Invoke `./vault ask "test question" --format json` against a fixture vault. Verify: stdout is valid JSON; it conforms to `tests/contracts/vault-ask-1.0.schema.json`; the assistant-framework's existing parser consumes it without reshape (cross-validated via fixture).

**Acceptance Scenarios**:

1. **Given** a vault with content, **When** the operator runs `./vault ask "<q>" --format json`, **Then** stdout is valid JSON matching the v1.0 schema (`schema_version`, `answer`, `citations[]`, `confidence`).
2. **Given** the default invocation `./vault ask "<q>"` (no `--format`), **When** it runs, **Then** stdout is markdown (existing CLI behavior preserved — no regression).
3. **Given** the v1.0 schema is the contract, **When** assistant-framework consumes the output, **Then** it does so without ad-hoc parsing or shape coercion.
4. **Given** the `confidence` field is required by the schema, **When** a vault can't compute confidence (e.g. no citations), **Then** the field is populated with `0.0` + a `low_confidence_reason` optional field.

---

### User Story 2 — Research-framework pushes cycle results to assistant inbox (Priority: P3, v2)

After a cycle completes, the framework writes a JSON envelope file to `~/.assistant/inbox/<uuid>.json` describing the cycle's outcome (status, summary, result note paths, request-id if it was assistant-initiated). The assistant-framework watches the inbox via FSEvents (macOS) / inotify (Linux) and consumes the result asynchronously.

**Why this priority**: v2 is the OUTBOUND direction — research pushes to assistant. P3 because v1 (US1) gates this — without the JSON contract surface, v2 has no clean payload to push. Also: the assistant-framework Phase 5 timeline puts this in Q3/Q4 2026 (post-revival).

**Independent Test**: Configure `settings.yaml::integrations.assistant.enabled: true`. Run a cycle. Verify: a JSON file appears in the configured inbox path; the envelope schema matches `tests/contracts/research-result-1.0.schema.json`; the payload includes the cycle's result note paths.

**Acceptance Scenarios**:

1. **Given** `integrations.assistant.enabled: true` in settings, **When** a cycle completes, **Then** a JSON envelope file is written to the configured inbox path.
2. **Given** integrations are disabled (default), **When** a cycle completes, **Then** no inbox file is written (silent noop).
3. **Given** the inbox path is unreachable (disk full, permissions), **When** the cycle completes, **Then** the cycle exits successfully + a warning is logged (non-blocking — same pattern as spec 044 mirror).
4. **Given** the envelope includes `request_id` (for assistant-initiated cycles), **When** the assistant reads it, **Then** it can correlate the result to the original request.

---

### User Story 3 — Deploy-time separability is preserved (Priority: P1, invariant)

Throughout v1 + v2, the two frameworks NEVER share in-process Python imports. The assistant never does `import research_framework`; research-framework never does `import assistant`. Communication is flat-file + CLI subprocess only.

**Why this priority**: This is the architectural invariant. Without it, the two projects can't be deployed independently (e.g. assistant on a Mac, research-framework in a server). P1 because every other story depends on this constraint holding.

**Independent Test**: Search both codebases for cross-imports. Verify: zero `from research_framework` imports in assistant-framework; zero `from assistant` imports in research-framework. Every integration touchpoint is a CLI subprocess OR a file in `~/.assistant/inbox/`.

**Acceptance Scenarios**:

1. **Given** the integration is live, **When** searching either codebase, **Then** no cross-import statements exist.
2. **Given** v2's inbox push, **When** auditing the implementation, **Then** the push uses `pathlib.Path.write_text(...)` (or equivalent) — never an in-process call.
3. **Given** v1's CLI surface, **When** the assistant invokes it, **Then** it uses `subprocess.run(["./vault", "ask", ...])` semantics — never a Python-level call.

---

### Edge Cases

- What if the vault's `./vault ask` is invoked with `--format json` but the question can't be answered? → Return JSON with `answer: ""`, `confidence: 0.0`, `low_confidence_reason: "no relevant notes found"`. Never omit the JSON output entirely.
- What if v2's inbox push happens while the assistant is reading the inbox directory? → JSON files are atomic-write (write to `.tmp`, rename to final) so partial reads never see corrupt JSON.
- What if both v1 (request) AND v2 (push) fire for the same request? → Idempotent: v2 push includes the `request_id` from v1 so the assistant correlates and doesn't double-process.
- What if the schema version evolves mid-flight (cycle in progress when assistant upgrades)? → Per Q1's default, schema is append-only within `1.x`. Old consumer + new producer → consumer ignores unknown fields. New consumer + old producer → consumer treats missing fields as None.
- What if assistant-framework is not installed but `integrations.assistant.enabled: true`? → The push writes to the configured inbox path regardless (the file is the contract; assistant existence is the assistant's problem).

## Requirements *(mandatory)*

### Functional Requirements

#### v1 — Inbound (assistant → research)

- **FR-001**: `./vault ask` MUST accept a `--format json|markdown` flag. Default `markdown` (preserves existing CLI behavior — no regression).
- **FR-002**: When `--format json` is set, stdout MUST be valid JSON matching the v1.0 schema at `tests/contracts/vault-ask-1.0.schema.json`.
- **FR-003**: The v1.0 schema MUST include: `schema_version` (string, required, value `"1.0"`), `answer` (string, required), `citations` (array of `{note_path, snippet}`, required), `confidence` (float in [0.0, 1.0], required), `source_urls` (array of strings, optional), `cost_usd` (float, optional), `low_confidence_reason` (string, optional).
- **FR-004**: A contract fixture MUST exist at `tests/contracts/vault-ask-1.0.schema.json` (the JSON Schema). Same pattern as agent-call sidecar v1.1. **Met 2026-09-08**: the file exists and `tests/contracts/test_vault_ask_envelope_schema.py` pins it against hand-written fixtures; the producer-output test lands with T001, the way #326 wired the state schema.
- **FR-005**: Per Q1 (resolved — ADR-0013), v1 schema evolution is APPEND-ONLY within `1.x`. New fields are optional + ignored by older consumers. Breaking changes require a `2.0` major-version bump, a new schema file beside the old one, and a transition period. `schema_version` is carried in every envelope as a safeguard; nothing acts on it until a consumer exists.
- **FR-006**: When the JSON-format answer can't be computed (no relevant content), the framework MUST emit `answer: ""`, `confidence: 0.0`, `low_confidence_reason: "<reason>"` — NEVER omit the JSON output.

#### v2 — Outbound (research → assistant)

- **FR-007**: A new `integrations.assistant.enabled: bool` setting in `settings.yaml` (default `false`) opt-in enables v2 push.
- **FR-008**: When enabled, after every successful cycle completion the framework MUST write a JSON envelope file to the configured inbox path with name `<uuid>.json`.
- **FR-009**: Per Q2's default, the inbox path is configurable via `integrations.assistant.inbox_path` with default `~/.assistant/inbox/`. The framework MUST honor `${ASSISTANT_HOME}` env var if set (`${ASSISTANT_HOME}/inbox/`).
- **FR-010**: The envelope schema MUST live at `tests/contracts/research-result-1.0.schema.json` and contain: `type` (string, value `"research.result"`), `source` (string, value `"research-framework"`), `timestamp` (ISO8601), `payload` (object: `request_id` UUID optional, `status` enum {COMPLETE, FAILED, PARTIAL}, `result_notes` array of strings, `summary` string).
- **FR-011**: Envelope files MUST be written atomically (write to `<uuid>.json.tmp`, fsync, rename) so partial reads never see corrupt JSON.
- **FR-012**: When the inbox path is unreachable (perms, disk full), the framework MUST log a warning but MUST NOT fail the cycle. Cycle exit code reflects only cycle success.

#### v3 — Reserved (DEFERRED)

- **FR-013**: v3 (MCP / HTTP protocol) is DEFERRED. Reserved for if/when v1+v2 prove insufficient. This spec does NOT obligate v3 implementation.

#### Invariant — Deploy-time separability

- **FR-014**: No source file in `research-framework` MAY `import` from `assistant-framework`. CI gate (per spec 041) MUST enforce this with a grep against `from assistant` / `import assistant`.
- **FR-015**: The integration touchpoint is the CLI subprocess (v1) OR the inbox JSON file (v2). NEVER an in-process Python call.

### Key Entities

- **`./vault ask --format json|markdown` flag**: New CLI flag on existing verb. Default `markdown` preserves existing UX.
- **`tests/contracts/vault-ask-1.0.schema.json`**: The v1 JSON Schema. Source of truth for the inbound contract.
- **`tests/contracts/research-result-1.0.schema.json`**: The v2 envelope JSON Schema. Source of truth for the outbound contract.
- **`integrations.assistant.*` settings block**: New `settings.yaml` section. `enabled: bool` + `inbox_path: str`.
- **Inbox push worker**: A non-blocking post-cycle worker that writes the envelope JSON. Atomic-write semantics.
- **Cross-project import guard**: A CI check (per spec 041) ensuring zero cross-imports between the two projects.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After v1 lands, `./vault ask "<q>" --format json` works on the feeds-vault fixture with output matching the v1.0 schema (validated by JSON Schema validation in CI).
- **SC-002**: assistant-framework's existing parser consumes v1 output without reshape — measured by a cross-project fixture test (run from assistant-framework's CI).
- **SC-003**: After v2 lands, 100% of completed cycles on a vault with integrations enabled produce a JSON envelope in the configured inbox.
- **SC-004**: 0 cycles fail because of v2 push errors (mirror failure pattern: log + non-blocking).
- **SC-005**: Across both projects' codebases, zero cross-imports detected by the CI gate (deploy-time separability invariant).

## Assumptions

- assistant-framework Phase 5 (AI & Learning) is real and lands in Q3/Q4 2026 — v2 is timed against it.
- The "research-as-a-service" arc in ROADMAP Horizon 3 stays flat-file-first throughout v1 + v2 + (potentially) v3.
- Schema-version evolution within v1 is append-only (Q1, resolved — ADR-0013) — major bumps are rare events.
- FSEvents (macOS) and inotify (Linux) are sufficient for assistant's inbox watching. No daemon mode needed in research-framework.

## Dependencies

- **Hard for v1**: a headless `ask` path through `agent_call` (spec 078 FR-001/FR-008; 023 FR-003) — today the verb is an interactive `claude` session (see § Preconditions found while clarifying), so `--format json` is a producer, not a flag.
- **Hard for v2**: Spec 028 (telemetry sidecar) — `cost_usd` field in the envelope's payload depends on honest cost data.
- **Soft**: Spec 023 Phase 2 — per Q3 (resolved) this spec ships first and 023 Phase 2 cites its contract.
- **Soft**: Spec 041 (release infrastructure v2) — the cross-project-import CI gate (FR-014) lives in the CI workflow 041 establishes.

## Acceptance coverage

Evidence cells are populated by `/speckit.tasks` when v1 is scheduled (v1.2.0). FR-004's schema is already pinned by `tests/contracts/test_vault_ask_envelope_schema.py`; the producer-side evidence lands with T001.

| User Story | Evidence |
|---|---|
| US1 — Assistant queries vault via subprocess + JSON (v1) | _(deferred to tasks.md — Q1–Q3 resolved 2026-09-08; schema pinned, producer not built)_ |
| US2 — Research-framework pushes cycle results to inbox (v2) | _(deferred to tasks.md — v2 is timed against assistant-framework Phase 5)_ |
| US3 — Deploy-time separability is preserved (invariant) | _(deferred to tasks.md — the FR-014 import grep ships with v1's T001)_ |

## Out of Scope

- In-process Python imports of `research_framework` from `assistant-framework`. Violates the deploy-time-separable invariant.
- Daemon mode for the research engine (stays a CLI-invokable thing).
- Cross-vault source sharing (Horizon 4 follow-on; not v1/v2 scope).
- v3 (MCP / HTTP protocol). Deferred to FR-013; ship only if v1+v2 prove insufficient.
- Bi-directional sync of assistant + research state. Out — push-only OR pull-only directions in v1/v2; sync is a future spec if needed.
- Authentication / authorization between the two frameworks. Both deploy on the same operator's machine; trust boundary is the filesystem.

---

*Clarified 2026-09-08 (Q1–Q3 above). Next step is `/speckit.tasks` when v1 is scheduled in v1.2.0; the v2 inbox schema is written under ADR-0013's rule when v2 is planned, not before.*
