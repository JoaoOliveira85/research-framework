# ADR-0006: Code access is cached infrastructure, not a per-cycle agent task

**Status**: Accepted
**Date**: 2026-05-18
**Tags**: architecture, scout, code-bridge, spec-020, planned-0.3.0

## Context

The user's reference-vault-0.2.30 audit found the scout was severely
under-delivering: 7\u201312 new topics per cycle against a quota of 49,
and the same two repositories were being walked on every cycle.
Approximately 80% of the scout's ~120k tokens per cycle went into
re-extracting code information the framework had already extracted
on previous cycles.

Coverage also skewed badly: every code-derived category filled
(services, flows, decisions, kafka), but every external-only
category (concepts, learning-modules, java-jvm, spring-features)
stayed empty. The scout never went looking for spec-coverage gaps
because it had no surplus attention left.

The user's framing during brainstorming captured the principle:

> "I see repositories as a way for research to branch out but I
> don't see a reason for the agents to return to the repository
> multiple times unless they find something like 'ok, it seems
> that often testcontainers are used to test this type of
> microservice architectures but I don't know what they're using,
> let me check it out real quickly'."

The framework was treating code-reading as something the scout
agent must do every cycle from scratch. But code is STATIC between
commits; reading it every cycle is pure waste. The right pattern
is: extract code signals ONCE per commit-SHA-drift, cache the
signals, and let the scout consume the cache.

## Decision

Adopt the code-bridge architecture as the canonical pattern for
code access. Detail lives in `specs/020-code-bridge/spec.md`;
this ADR captures the principle so other parts of the codebase
can reference it without re-arguing the design.

Core principles:

1. **Code access is infrastructure, not an agent task.** Agents
   never invoke `git`, `gh`, or read repo files directly. They
   read cached signal payloads.
2. **Cache is keyed by `(repo_path, commit_sha)`.** A repo whose
   HEAD matches its watermark serves from cache and burns zero
   tokens. Commit drift triggers re-extraction.
3. **The bridge is a subprocess.** Same invocation pattern as
   every other pipeline stage. Cheapest to ship; can graduate to
   an HTTP/MCP server later without changing the contract.
4. **Signal payload is mixed-shape.** Structured `facts` (the
   guardrail buckets) + freeform `notable` observations. Vault
   authors can extend the shape via per-vault validators.
5. **Per-vault validators are YAML with a Python escape hatch.**
   Most rules are simple ("this category is required, non-empty
   list of strings"); the escape hatch covers the cross-field
   cases without forking the framework.
6. **Consensus before "exhausted" verdict.** When the bridge wants
   to mark a repo "nothing useful remains", it requires M-of-N
   extractors to agree (default N=2, M=2). Single-agent give-ups
   are a hint, not a decision.

## Consequences

**Good**:

- Scout token spend on code drops by an estimated 60%+ (per
  spec SC-002). The freed attention budget redirects to topic
  proposal from spec gaps.
- Code access is no longer entangled with the scout's other
  concerns. Bugs in code-walking can be fixed without touching
  scout logic.
- Per-vault validators let vault authors shape the signal without
  framework changes. Vault-specific concerns stay in the vault.
- The architecture is generally applicable: any future agent
  stage that needs code information reads the cache the same way.

**Trade-offs**:

- A new pipeline stage to maintain. The cycle gets longer (by
  one stage), but only by the duration of cache-key lookups when
  nothing has changed.
- Vault authors have to learn the validator format if they want
  shaped signals. Default minimal validator handles vaults that
  don't care.
- Cache-coherence concerns: stale signal entries, schema-version
  drift, watermark corruption. Spec 020 explicitly addresses each.

## Alternatives considered

- **Keep code-walking inside scout but cache more aggressively
  inside the scout's prompt.** Rejected: prompt-level caching is
  brittle and gives the scout no way to know whether its cache
  is stale.
- **Run code-walk less frequently (every Nth cycle).** Rejected:
  arbitrary N. Commit-drift is the correct cadence \u2014 anything
  finer is waste, anything coarser is stale data.
- **Make the bridge an in-process Python module.** Rejected:
  doesn't match the framework's per-stage subprocess pattern;
  harder to swap implementations later.
- **Make the bridge an HTTP server or MCP server.** Considered.
  Graduation path stays open; we start with subprocess because
  it's cheaper and matches existing patterns.

## Tests / Status

Spec only at the time of this ADR. Implementation targets 0.3.0
under `specs/020-code-bridge/plan.md` (not yet written). The 0.2.31
release ships the verifier and wikilink fixes; the code-bridge
work is the next major architectural change.
