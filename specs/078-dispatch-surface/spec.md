# Feature Specification: The `agent_call` dispatch surface

**Status**: shipped(2026-09-07, commit 6935644) — a *record* of the single
LLM dispatch seam as it is, written from the code at that commit. It adds no
scope. Divergences are filed under § Known divergences.

**Spec**: `078-dispatch-surface` · **Supersedes as the owning document**:
`specs/_archive/034-runtime-consolidation/` (SUBSUMED by ADR-0009) ·
**Epic**: #217 · **Issue**: #275, #259, #262

---

## Why this spec exists

Constitution Principle V says every LLM call goes through one dispatch
surface. That surface has never been specified — only guarded. So the guard
is what the repo actually has, and the guard can only say "this is not a
second dispatcher"; it cannot say what the first one promises. Issues #259
and #262 are the consequence: a test double described as a drop-in
replacement, with nothing to check it against, that turned out not to be one.

A reader with no code access must be able to build both this dispatcher and a
faithful test double for it.

## Scope

**In scope**: the module's location and public API, the runtime adapters and
how each is invoked, tier resolution, cost capture and its on-disk record,
timeout and logging behaviour, the guard that enforces the seam, and the
contract the test double must satisfy.

**Out of scope**: budget *enforcement* (`033-cost-enforcement`,
`061-cycle-budget-config`), which consumes what this surface records; the
weekly runner's own outer timeout (`075` FR-022).

---

## User Scenarios & Testing

### User Story 1 — One seam, and the tree proves it (Priority: P1)

1. **Given** the framework source tree, **When** the dispatch guard scans it,
   **Then** no module spawns an LLM binary or calls an inference endpoint
   directly.
2. **Given** the guard, **When** it runs, **Then** its subject set is derived
   from the dispatcher's own runtime registry, not from a hand-maintained
   second list that could drift.
3. **Given** the allowlist of sanctioned exceptions, **When** it is read,
   **Then** it is empty — and a test asserts that emptiness, so a new entry
   is a visible decision.

### User Story 2 — Every call is recorded, whatever the runtime charged (Priority: P1)

1. **Given** a dispatch on a runtime that reports real cost, **When** it
   completes, **Then** a sidecar records the dollar figure with its source
   marked as coming from the runtime.
2. **Given** a runtime that reports tokens but no dollars, **When** it
   completes, **Then** the dollars are estimated and the source says so —
   never silently zero.
3. **Given** a runtime that reports nothing, **When** it completes, **Then**
   the estimator supplies a figure marked estimated, and a genuine inability
   to determine any of it emits a warning rather than recording a confident
   zero.
4. **Given** a call that failed, **When** it completes, **Then** a sidecar is
   still written, carrying the failure status, the exit code and an excerpt
   of stderr.

### User Story 3 — A hung or missing runtime cannot wedge a run (Priority: P1)

1. **Given** a dispatch whose subprocess never exits, **When** the timeout
   elapses, **Then** the whole process group is terminated (SIGTERM, grace,
   SIGKILL) and the call returns within a bounded wall clock.
2. **Given** that subprocess spawned grandchildren, **When** the timeout
   fires, **Then** they die too.
3. **Given** a runtime binary that is not installed, **When** a dispatch is
   attempted, **Then** it returns exit 2 with a message naming the binary,
   rather than raising.

### User Story 4 — The test double is a drop-in, and that is checked (Priority: P1)

1. **Given** the fake agent's CLI, **When** it is compared with the real
   one, **Then** it accepts every flag the real one accepts and requires
   nothing the real one makes optional.
2. **Given** the fake's sidecar, **When** it is compared with the real
   sidecar, **Then** it carries every key, declares the same schema version
   and uses a real cost-source value.
3. **Given** a stage name the fake does not handle, **When** it is invoked,
   **Then** it fails closed with exit 2 rather than silently succeeding.

### Edge Cases

- A vault whose `scripts/agent_call.py` has been replaced by the fake shim is
  detected by a marker in the file, and every sidecar it writes is stamped
  `fake` with deterministic timestamps so fixture vaults stay byte-stable.
- One runtime dispatches over HTTP and never through the CLI adapter
  registry; the "unknown runtime" error therefore does not list it.
- Repeated dispatches for the same stage in one cycle get suffixed sidecar
  filenames rather than overwriting each other.

---

## Requirements

### Functional Requirements

**Location and API**

- **FR-001**: There MUST be exactly one dispatch module. It lives at
  `scripts/agent_call.py`; framework code under `src/` reaches it by loading
  that file, preferring a vault-local copy over the framework's own so a test
  shim installed in a vault intercepts in-process dispatch too.
- **FR-002**: The in-process API MUST be
  `dispatch(stage, prompt, *, tier="standard", agent=None, model=None,
  vault_dir=None, cycle_dir=None, timeout_s=None)`, returning an immutable
  result carrying `stdout`, `stderr`, `exit_code`, `cost_usd`, `tokens_in`,
  `tokens_out`, `latency_ms`.
- **FR-003**: `dispatch` MUST raise when neither `vault_dir` nor `cycle_dir`
  is given, and MUST derive the vault from the cycle directory otherwise.
- **FR-004**: The CLI API MUST accept `--vault` and `--stage` (both
  required), and `--prompt-file`, `--cost-sidecar`, `--output-file`,
  `--batch-index`, `--topic-count` (all optional), reading the prompt from
  stdin when no prompt file is given, and returning a process exit code.
- **FR-005**: A dispatch failure MUST be returned as a non-zero-exit result,
  not raised: a missing binary and a timeout both produce a result object.

**Runtimes**

- **FR-006**: The CLI runtimes MUST be `claude`, `codex`, `cursor-agent`,
  `opencode` and `python` (for `type: script` executors), resolved through a
  registry; an unrecognised runtime MUST raise an error listing the supported
  set.
- **FR-007**: `ollama` MUST dispatch over HTTP, never through the CLI
  registry, selected by `type: api` or by the runtime name.
- **FR-008**: Every CLI runtime MUST receive the prompt on **stdin**. No
  adapter may place prompt text on the command line.
- **FR-009**: The three sandboxed runtimes (`codex`, `cursor-agent`,
  `opencode`) MUST be given the vault directory as their working root, and an
  operator-supplied working-directory flag MUST win over the injected one
  rather than being duplicated.
- **FR-010**: `opencode` MUST derive its provider from the `provider/model`
  string and MUST pre-flight, fail-closed: binary resolvable, local provider
  reachable, or hosted-provider credentials present.
- **FR-011**: Binary locations MUST be overridable per runtime by an
  environment variable, for testing and for non-standard installs.

**Tiers**

- **FR-012**: `stages.<name>.tier` is a **complexity label**
  (`basic|standard|expert`) carried through to the cost record for every
  stage; it does not select a model.
- **FR-013**: For the two stages that use D7 resolution, the same key names a
  **model tier** (`basic|normal|flagship`) looked up in the top-level
  `tiers:` map, mutually exclusive with an explicit `model`.
- **FR-014**: The two vocabularies sharing one key name MUST be treated as a
  documented hazard, not a design (§ Known divergences D3).

**Cost**

- **FR-015**: Cost resolution precedence MUST be: a runtime's own reported
  cost; else a runtime-reported token count with an estimated dollar figure;
  else a full pre-dispatch estimate; else zero **with a warning**, never a
  silent zero.
- **FR-016**: Each resolved cost MUST carry its provenance as one of
  `runtime`, `runtime_tokens`, `estimated`, `none`.
- **FR-017**: A local/free provider's true zero MUST be recorded as
  `runtime`, distinguishable from an unknown zero.
- **FR-018**: A sidecar MUST be written under
  `<cycle>/agent-calls/<stage>.json`, with a numeric suffix on collision, and
  MUST be written atomically. It MUST carry the schema version, stage, agent,
  whether the agent was real or fake, tier, status, exit code, cost, cost
  source, token counts, latency, start/completion timestamps and cycle
  number, plus a stderr excerpt on failure.
- **FR-019**: A sidecar written by a fake agent MUST use fixed sentinel
  timestamps so committed fixture vaults stay byte-stable.

**Bounds and logging**

- **FR-020**: Every dispatch MUST be bounded by a timeout resolved from the
  call, then the stage's executor, then the default executor, then a built-in
  default.
- **FR-021**: On timeout the entire process group MUST be terminated —
  SIGTERM to the group, a grace wait, SIGKILL, and a final forced close of
  the pipes.
- **FR-022**: The dispatcher itself MUST NOT retry. Retry and backoff are the
  caller's concern, so that one policy is not silently applied twice.
- **FR-023**: A debug environment variable MUST make the resolved
  stage/runtime/model/command visible on stderr before dispatch.

**The seam guard and the test double**

- **FR-024**: A static guard MUST scan the framework source tree for direct
  LLM subprocess spawns and direct inference HTTP calls, taking its subject
  set from the dispatcher's own registry rather than a copied list.
- **FR-025**: The guard's allowlist MUST be empty, and that emptiness MUST
  itself be asserted.
- **FR-026**: The test double MUST be argument-compatible and
  sidecar-compatible with the real dispatcher, and that compatibility MUST be
  derived from the real module at test time, not restated.
- **FR-027**: The test double MUST fail closed on an unhandled stage, and
  MUST be able to produce failures — a fake that can only succeed cannot test
  a failure path.

### Key entities

| Entity | Shape |
| --- | --- |
| Dispatch result | `stdout: str`, `stderr: str`, `exit_code: int`, `cost_usd: float`, `tokens_in: int`, `tokens_out: int`, `latency_ms: int` |
| Cost sidecar | `schema_version`, `stage`, `agent`, `agent_kind` (`real`\|`fake`), `tier`, `status` (`ok`\|`failed`), `exit_code`, `cost_usd`, `cost_source` (`runtime`\|`runtime_tokens`\|`estimated`\|`none`), `tokens_in`, `tokens_out`, `latency_ms`, `started_at`, `completed_at`, `cycle`, optional `stderr_excerpt`, `batch_index`, `topic_count`, `duration_ms`, `timed_out` |
| Executor | `type`, `runtime`, `model`, `args`, `timeout_s`, and for HTTP `base_url`/`api_path` — resolved per `076` FR-008 |

## Success Criteria

- **SC-001**: The guard's subject set and the dispatcher's registry can never
  disagree, because one is derived from the other.
- **SC-002**: No dispatch records a confident zero cost it did not verify.
- **SC-003**: A hung runtime is bounded and leaves no orphaned process.
- **SC-004**: The test double's drop-in claim is a checked invariant, not a
  docstring.

---

## Acceptance coverage

| User story | Evidence |
| --- | --- |
| US1 — One seam, and the tree proves it | `tests/_helpers/test_llm_dispatch_guard.py::test_no_direct_llm_subprocess_in_pipeline_package`, `tests/_helpers/test_llm_dispatch_parity.py::test_both_guards_read_the_same_source_of_truth` |
| US2 — Every call is recorded, whatever the runtime charged | `tests/scripts/test_agent_call_sidecar_v1.py::test_valid_sidecar_payloads`, `tests/scripts/test_agent_call.py::test_opencode_cost_class_no_usage_never_silent_zero_runtime` |
| US3 — A hung or missing runtime cannot wedge a run | `tests/scripts/test_agent_call_process_tree.py::test_grandchild_dies_when_tree_is_terminated`, `tests/scripts/test_agent_call.py::test_missing_binary_returns_exit_2_with_clear_error` |
| US4 — The test double is a drop-in, and that is checked | `tests/_helpers/test_fake_agent_parity.py::test_fake_cli_accepts_every_flag_the_real_cli_accepts`, `tests/_helpers/test_fake_agent_parity.py::test_fake_sidecar_carries_every_key_the_real_sidecar_carries` |

### Testing Requirements

| FR group | Pinned by |
| --- | --- |
| FR-002…FR-005 (API) | `tests/scripts/test_agent_call.py::TestRunDispatch` |
| FR-006…FR-011 (runtimes) | `tests/scripts/test_agent_call.py::TestBuildCommand`, `::TestCodexWorkingRoot`, `tests/scripts/test_agent_call_cursor.py`, `tests/scripts/test_agent_call_ollama.py` |
| FR-012…FR-014 (tiers) | `tests/pipeline/test_tier_resolution.py`, `tests/pipeline/test_default_tier_resolution.py` |
| FR-015…FR-019 (cost, sidecar) | `tests/scripts/test_agent_call_sidecar_v1.py`, `tests/scripts/test_agent_call_codex_cost.py`, `tests/scripts/test_agent_call_detect_agent_kind.py` |
| FR-020…FR-021 (bounds) | `tests/scripts/test_agent_call_process_tree.py` |
| FR-023 (audit record) | `tests/pipeline/test_agent_call_logging.py` |
| FR-024…FR-025 (guard) | `tests/_helpers/test_llm_dispatch_guard.py`, `tests/scripts/test_agent_call.py::test_llm_dispatch_allowlist_is_empty` |
| FR-026…FR-027 (test double) | `tests/_helpers/test_fake_agent_parity.py`, `tests/_helpers/test_fake_agent_contract.py::test_unknown_stage_fails_closed` |

---

## Known divergences

- **D1 — Every document points at the wrong path.** ARCHITECTURE.md and
  CONTRIBUTING.md both name
  `src/research_framework/pipeline/agent_call.py` as the canonical dispatch
  surface. No such file exists; the module is `scripts/agent_call.py`, loaded
  dynamically. A clean-room reader following the docs would build the seam in
  a package that has never contained it.
- **D2 — The audit-log filename in ARCHITECTURE does not match reality.** It
  describes `<timestamp>-<stage>-<call-id>.json`; the sidecars are
  `<stage>.json`, `<stage>-N.json` and `<stage>-batch-N.json`.
- **D3 — Two tier vocabularies share one key.** `stages.<name>.tier` means
  `basic|standard|expert` for most stages and `basic|normal|flagship` for the
  two D7 stages, disambiguated only by the stage name. ARCHITECTURE credits
  the dispatcher with resolving the second, which it does not — that
  resolution lives in the settings loader.
- **D4 — The complexity tier reaches the estimator and is ignored.** The cost
  estimator accepts a `tier` parameter and never references it; the value's
  only real consumer is a soft warning threshold.
- **D5 — A documented cursor model-tier map is not a resolver.** A
  tier→model dictionary exists in the dispatcher and is consulted by no code
  path; it is a recommendation for a human editing a vault's `tiers:` block.
- **D6 — The weekly runner never asks for a cost sidecar.** The runner's
  dispatches omit `--cost-sidecar` entirely, which is the mechanical reason
  `075` FR-006 refuses `--budget-cap`: there is nothing to enforce a cap
  against on that surface.

## Assumptions

- One dispatch per stage per process at a time; sidecar suffixing handles
  repeats within a cycle, not concurrent writers.
- The runtime binaries, where used, are on `PATH` or named by their
  environment override.
