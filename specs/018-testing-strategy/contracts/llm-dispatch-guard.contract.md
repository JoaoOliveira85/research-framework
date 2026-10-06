# Contract: LLM Dispatch Guard

**Status**: **v2 (amended 2026-09-06, issue #292)** — supersedes v1
(testing-strategy refresh, phase 2). v1 named `claude`/`codex` as the
forbidden binaries and gated the subprocess mode only. Two executors shipped
after it (`cursor-agent`, spec 052; `opencode`, spec 064) and one whole
dispatch *mode* (HTTP, specs 047/064) were outside its subject. v2 stops
declaring the subject list and derives it, and adds the HTTP mode. See
"Amendment v2" at the foot of this file for the full delta.  
**Tier**: 2 (static analysis test)  
**Test file**: `tests/_helpers/test_llm_dispatch_guard.py`  
**Shared subject module**: `tests/_helpers/llm_dispatch.py`  
**Parity test**: `tests/_helpers/test_llm_dispatch_parity.py`  
**Runtime sibling**: `tests/quality/test_fake_agent_interception.py`  
**Authority**: Constitution Principle IV (Agent-Script Separation of
Concerns) + project rule — `scripts/agent_call.py` is the **sole LLM
dispatch surface** for the research cycle pipeline. Principle IV mandates
that agent work (LLM calls) and script work (validation, gating,
enforcement) stay separated; a single dispatch point is how that
separation is operationalised for LLM I/O. Project rule (see
`docs/ROADMAP.md` "agent_call.py as sole LLM dispatch"): cost capture,
runtime selection (`settings.yaml`), audit sidecars, and fake-agent
substitution in tests all depend on this single point.

---

## Purpose

Catch regressions where production code invokes `claude` or `codex` directly
via `subprocess`, bypassing cost capture, runtime selection (`settings.yaml`),
audit sidecars, and fake-agent substitution in e2e tests.

This guard complements code review — it fails CI when a new bypass lands.

---

## Scope

### Scanned paths

```
src/research_framework/**/*.py
```

### Excluded paths (never scanned)

| Path | Reason |
|------|--------|
| `scripts/agent_call.py` | Canonical dispatch |
| `tests/**` | Tests use fake agent, not production dispatch |
| `processors/extract.py` | Legacy raw-data pipeline; separate debt (see below) |

### Forbidden patterns

A call is a **violation** if it matches either dispatch mode:

**Mode `subprocess`** — `subprocess.run(...)` / `subprocess.Popen(...)` whose
command's `argv[0]` (a list literal, or a simple local name bound to one)
basenames to a shipped LLM binary. The binary set is **not declared in this
contract**; it is `agent_call._LLM_AGENT_NAMES`, read through
`tests/_helpers/llm_dispatch.py`. At v2 that is `claude`, `codex`,
`cursor-agent`, `ollama`, `opencode` — but the guard tracks the constant, not
this list, so a sixth executor is gated the moment it ships.

**Mode `http`** — `urlopen` / `Request` / `requests.<verb>` / `httpx.<verb>`
whose URL (literal, simple local binding, `+` concatenation, or f-string
fragments) addresses a model-inference endpoint, per
`llm_dispatch.INFERENCE_PATH_MARKERS` / `INFERENCE_HOST_MARKERS`. `ollama` and
every `type: api` executor reach their model this way and touch `subprocess`
at no point, so a subprocess-only scan is blind to them by construction.

Outbound HTTP that is *not* an inference endpoint is explicitly NOT a
violation: the pipeline package legitimately fetches feeds and repo APIs
(`collectors/`, `pipeline/preflight.py`, `cli/refresh_sources.py`). A blanket
outbound-HTTP ban would be noise, not a guard.

### Allowlist (known violations — must shrink to empty)

Until simplify phase 3 (A1/A2), these files are **explicitly permitted**:

| File | Line region | Stage | Cleared when |
|------|-------------|-------|--------------|
| `src/research_framework/pipeline/plan_narrator.py` | `prepend_narrative` | `research_plan_narrator` | Routed through `agent_call.py` (QW-1) |
| `src/research_framework/pipeline/cycle_runner.py` | `_run_probe_retrieval_and_cache` | `probe_retrieval` | Routed through `agent_call.py` (A2) |

**Rule**: adding a row requires a linked TODO or ROADMAP item with a clear
removal milestone. Removing a row requires the guard test to pass without it.

---

## Test behaviour

```python
def test_no_direct_llm_subprocess_in_pipeline_package():
    violations = scan_for_violations(SCAN_ROOT, ALLOWLIST)
    assert violations == [], format_report(violations)
```

Report format (on failure) — each row carries its dispatch mode:

```text
LLM dispatch guard failed — direct LLM dispatch in production code:
  [subprocess] pipeline/plan_narrator.py:153  ["claude", "--print"]
  [http] pipeline/some_module.py:88  urlopen(req)
Fix: route through scripts/agent_call.py, or add to ALLOWLIST with ROADMAP ref.
```

---

## Related production surfaces (documented, not gated)

| File | Pattern | Notes |
|------|---------|-------|
| `processors/extract.py` | `_default_call_claude` | Pre-research raw-data pipeline; uses injectable `_call_claude` for unit tests. Future: route through `agent_call.py` or mark `@guard-exempt` with ADR. |
| `pipeline/verifier.py` | subprocess → `agent_call.py` | ✅ Correct pattern |
| `pipeline/gates_step.py` | subprocess → validator scripts | ✅ Not LLM |

---

## When the allowlist is empty

Phase 3 simplify (A1 + A2) complete. Guard becomes a hard gate with no
exceptions under `src/research_framework/`.

---

## Amendment process

1. **New exemption** — ROADMAP/TODO entry + allowlist row + comment in test.
2. **Remove exemption** — production fix + allowlist row deleted in same PR.
3. **Expand scan to `scripts/`** — deferred; most scripts are validators.
   Revisit if a script other than `agent_call.py` gains LLM dispatch.
4. **New executor** — nothing to amend here. Add it to
   `agent_call._LLM_AGENT_NAMES` (and `_HTTP_RUNTIMES` if it dispatches over
   HTTP) and both guards pick it up; `test_llm_dispatch_parity.py` fails until
   the shipped set, `settings.DefaultAgent` and the guards agree.

---

## Amendment v2 (2026-09-06, issue #292)

**What was wrong.** The static guard and the runtime interception guard each
carried a hand-maintained binary list. The two disagreed with each other and
both lagged the shipped executor set:

| | binaries | declared at |
|---|---|---|
| static guard | `{claude, codex, cursor-agent}` | `test_llm_dispatch_guard.py:30` |
| runtime guard | `("claude", "codex")` | `test_fake_agent_interception.py:15` |
| shipped executors | `{claude, codex, cursor-agent, ollama, opencode}` | `agent_call.py:932` |

So `opencode` was invisible to both, `cursor-agent` to the runtime guard, and
the HTTP dispatch mode to both — the last one by construction, not omission.

**What changed.**

- `tests/_helpers/llm_dispatch.py` is the single source of truth. It derives
  `llm_binaries()` / `http_runtimes()` from `scripts/agent_call.py` and owns
  the two predicates both guards use: `is_llm_command` and `is_inference_url`.
  Neither guard declares a list any more.
- The static guard gained the `http` mode (see Forbidden patterns above) and
  basenames `argv[0]`, so an absolute `CLAUDE_BIN`-style path is still caught.
- The runtime guard patches `urllib.request.urlopen` alongside
  `subprocess.Popen`, and asserts it OBSERVED dispatch traffic
  (`agent_call.py` spawns) before asserting that traffic was clean — it can no
  longer pass green over zero observations.
- `tests/_helpers/test_llm_dispatch_parity.py` builds each shipped executor's
  real dispatch shape via `agent_call._build_command` / `_http_endpoint` and
  asserts both guards classify all of them identically, plus that
  `llm_binaries() == get_args(settings.DefaultAgent)`.

**Deliberately out of scope.** The guard's fail-open scan root (a vacuous pass
on a tree with no code) is issue #278, not this amendment.
