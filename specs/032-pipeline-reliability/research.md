# Phase 0 Research — Pipeline Reliability Hardening (spec 032)

Two planning unknowns the spec flagged, resolved here:

1. The **usage audit** (Clarifications Q5 — gating): does any target vault
   still exercise `extract.py`'s legacy raw_data path?
2. The **sandbox-failure stderr signature** that FR-001's detection keys on.

---

## 1. Usage audit — does `extract.py` still run on any target vault?

**Question (Q5):** if no target vault hits `extract.py`, US1-3 drop to P3 and
only the FR-007 migration is rc1-blocking. `/speckit.plan` MUST confirm
target-vault usage before sizing US1-3.

**Method:** traced every call site of `processors.extract.extract` from the
CLI down, and mapped which `./vault` verb reaches it.

**Findings — `extract.py` is reached by exactly ONE path:**

```
./vault pipeline {full,extract}
  → cli/research_cycles.py::_cmd_pipeline
      → pipeline/runner.py::run_full / run_extract
          → runner.py::_drive_extract
              → processors.extract.extract(vault)   ← THE legacy raw_data path
```

`runner.py` defines the legacy linear PHASES chain:

```python
# src/research_framework/pipeline/runner.py:33
PHASES = ["collect", "extract", "scout", "triage", "research", "verify", "report"]
```

This is the **same `/pipeline full` flow that produced the 2026-05-13
feeds-vault incident** described in the spec input.

**The three live vault runs use a DIFFERENT path that never touches
`extract.py`:**

```
./vault research
  → cli/research.py → pipeline/cycle_runner.run_cycle_steps
      → pipeline/steps/Step01…Step15  +  source_bridge subprocess modules
        (youtube / reddit / rss / oreilly / code — spec-020 architecture)
```

The spec-020 subprocess-module architecture (`<vault>/modules/<name>/`,
shipped 0.6.0) **superseded** the `collect_*.py` + `extract.py` raw_data
pipeline for source ingestion (ADR-0009 Option A: "020 supersedes 014/015
collectors"). The Step01…Step15 BFS/DFS cycle runner consumes spec-020
module facts directly; it has no `extract` phase and never imports
`processors.extract`.

Cross-check — the only `src/` references to the extract processor:

| Reference | Path | On a live run path? |
|-----------|------|---------------------|
| `_drive_extract` | `pipeline/runner.py:211` | only `./vault pipeline` (legacy) |
| re-export | `processors/__init__.py:15` | API surface, not a run path |
| superseded-path map | `migration/superseded_paths.py:16` | maps the *old* `scripts/extract.py` → this module (confirms legacy status) |

`cycle_runner.py`, `orchestrator.py`, and `steps/*` carry **no** import of
`processors.extract`.

**Conclusion (gating answer):** **NO target vault exercises `extract.py`'s
raw_data path.** All three upcoming live runs (codebase-vault rebuild, new
reference-vault, feeds-vault update) go through `./vault research` →
`cycle_runner` → spec-020 modules.

**⇒ Decision confirmed:** US1, US2, US3 are **P3 transitional legacy
hardening**. The **only rc1-blocking item is the FR-007 migration** — and
that is rc1-blocking purely on the *Principle IV / EMPTY-allowlist invariant*
grounds, independent of whether `extract.py` ever runs again. (The guard
exclusion is live debt the moment the spec ships, regardless of usage.)

**Why migrate at all if the path is dead?** Because the guard *exclusion*
(`_SCAN_SKIP_REL = {"processors/extract.py"}`) is itself the standing
Principle-IV violation. Leaving a direct `subprocess.run(["claude", ...])` in
`src/` — even on a cold path — keeps the only crack in the EMPTY-allowlist
invariant open. Migrating removes the file's direct call AND the guard
exclusion, so the guard fires on any *future* bypass anywhere in `extract.py`.
This is cheap (the dispatch seam already exists) and closes the spec's US4.

---

## 2. Sandbox-failure stderr signature (FR-001)

**Question:** what does a sandboxed `claude -p` auth failure look like, so the
detector can key on it (primary signature), and what is the fallback when the
string is unstable?

### Current behaviour (the bug)

`extract.py::_default_call_claude` shells `claude -p … --output-format json`
and parses `r.stdout` as JSON. Today it handles auth failure via the
`is_error` JSON field and the magic substring check:

```python
# extract.py:160-163
if data.get("is_error"):
    msg = data.get("result", "unknown error")
    if attempt >= 3 or "logged in" in msg.lower():
        raise RuntimeError(f"claude CLI error: {msg}")
```

So the only signature `extract.py` currently recognizes is the substring
**`"logged in"`** inside the JSON `result` field of an `is_error` response
(i.e. the "Invalid API key · Please run /login" / "not logged in" family of
messages claude emits when it can't reach the OAuth keychain). When this
fires inside the sandbox, the per-source `_extract_one` catches the
`RuntimeError` and writes an `extraction-failed` stub (`extract.py:419-428`)
— **the exact silent-corruption path US1 must replace with a hard exit.**

### Signature surface after migration

After Phase 1, the call goes through `agent_call.dispatch()`, which **does not
raise** on CLI failure — it returns:

```python
AgentCallResult(stdout, stderr, exit_code, cost_usd, tokens_in, tokens_out, latency_ms)
```

For a sandboxed-auth failure the detectable signals on that result are:

- **`exit_code != 0`** (claude exits non-zero when it can't authenticate), and
- **`stderr`** carrying the auth-failure text. `dispatch()` captures stderr
  (agent_call.py:911, 994, `stderr_excerpt` propagated to the sidecar).

### Detection design (layered — robust to string drift)

The spec's own Assumption #2 warns the exact string "may be unstable across
claude CLI versions" and pre-authorizes a TIME-based fallback. The plan
adopts the three-layer scheme from Clarifications Q2:

1. **Primary — stderr auth-failure signature.** Match the known family
   (case-insensitive), e.g. any of:
   `"invalid api key"`, `"please run /login"`, `"not logged in"`,
   `"logged in"`, `"authentication"`/`"auth"` + `"fail"`, `"oauth"`,
   `"credential"`/`"keychain"`. The exact canonical string is a **NEEDS
   CLARIFICATION live-probe** (see below) — the matcher is written as a
   tolerant set so a single string change does not silently disable
   detection.
2. **Fallback — time-based.** If the signature doesn't match but the **first
   ≥3 extractions each exited <1s wall-clock AND failed**, declare sandbox.
   Rationale: a real Haiku extraction takes seconds-to-minutes; three
   instant failures in a row is the unmistakable shape of a tool that can't
   start (auth refused before any model work). `dispatch()` exposes
   `latency_ms` per call, so the <1s test reads directly off the result —
   no extra timing instrumentation needed.
3. **Override — `RV_`-prefixed env var** (e.g. `RV_DISABLE_SANDBOX_DETECT`)
   suppresses both layers for documented mis-fire suppression (SC-005). Exact
   name is a `/speckit.tasks` decision; the `RV_` prefix is fixed by Q2.

### Why fail-closed (Q3), not WARN

A sandbox-broken environment is **not** a source-silence event (which 048-v2
treats as a WARN in its consideration ledger). It is a *broken tool*: the
dispatch surface itself cannot authenticate, so every extraction in the run
will fail identically. Writing N `extraction-failed` stubs (one per source)
silently corrupts the raw_data tree and the user only learns after a
"complete" cycle yields no data — the precise 2026-05-13 failure. Therefore
FR-001 mandates **hard-exit non-zero, ZERO stubs written**: detect on the
first failure cluster, abort the `ThreadPoolExecutor` fan-out before any
`_write_extraction` call, and exit with the FR-002 actionable message.

### Codex note (spec Assumption #3)

`extract.py` only ever calls the `claude` runtime (Haiku + Sonnet). After
migration the runtime is whatever the vault's `settings.yaml` resolves for the
extract stage; in practice that is still `claude`. Cross-CLI sandbox detection
(codex/ollama) is **explicitly Out of Scope** per the spec — this research
does not extend the signature set to codex.

---

## Open items carried to the plan's NEEDS CLARIFICATION

- **Exact primary stderr signature string + cross-version stability.** Needs a
  one-off live probe in a real sandboxed `claude -p` (or confirmation that
  `dispatch()` yields a stable `exit_code` we can match on). The layered
  design degrades gracefully to the time-based fallback if the string drifts,
  so this does not block planning — flagged for a `/speckit.tasks` probe task.
- **`RV_` override env var name** — `/speckit.tasks`-level naming.
