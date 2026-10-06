---
spec_number: 069
title: Source-relevance tuning + declared-but-unimplemented validation
status: SHIPPED 1.0.0rc9 (2026-06-15, PR #173, squash d038302) — FR1/FR2 (declared-source backing validation + fail-closed preflight) + FR3/FR5 (stagnant-source WARN signal) shipped; FR4 (relevance-classifier tuning) split to a follow-up sub-spec — rc8-wave umbrella #152 (CLOSED). Default-Web-source regression fixed in PR #174. Re-validated on reference-vault-rc7 (generate --dry-run fails closed on the 4 unbacked sources).
target_version: 1.0.0rc9 / 1.0.0
created: 2026-06-14
source_input: |
  2026-06-13 rc7 reference-vault validation run (`~/Documents/reference-vault-rc7/`,
  GitHub issue #160, umbrella #152). The vault declared 4 primary sources
  in `research.spec.md` (codebase_vault_seed, Official Documentation, Web,
  gh). Across 4 cycles, only `code` + `github` (Tier-2 modules from rc5)
  yielded; the other three contributed ZERO facts/signals despite the
  cycles drafting notes on Fastify (would have benefited from official
  docs), CAP Theorem (would have benefited from Web), etc. The framework
  silently dropped 3 of 4 declared sources — a vault that lies about its
  coverage.
---

**Status:** **SHIPPED 1.0.0rc9** (2026-06-15, PR #173, squash `d038302`; rc8-wave umbrella #152 CLOSED) —
rc8-wave umbrella #152. FR1/FR2 (declared-source backing validation + fail-closed
preflight) + FR3/FR5 (stagnant-source WARN signal) shipped. FR4
(relevance-classifier tuning) split out to a follow-up sub-spec (Q3). A
default-`Web`-source regression in this validation was fixed in PR #174 (the
injected default is now `kind: strategy_hint`).

# Feature Specification: Source-relevance tuning + declared-source validation

**Feature Branch**: `069-source-relevance-tuning`
**Created**: 2026-06-14

## Clarifications

### Round 1 (resolved 2026-06-15)

**Live audit of the rc7 vault** (`~/Documents/reference-vault-rc7/`): the vault has
**no `modules/` directory at all**; all 4 declared `data_sources` ("Codebase
Vault Seed", "GitHub", "Official Documentation", "Web") use free-text
`access_method` strings (`local filesystem` / `GitHub MCP` / `web fetch`) with
no backing module — so 3 of 4 silently produced zero facts/signals across 4
cycles. (`code`+`github` yielded only because those were framework-side rc5
Tier-2 modules, not vault-declared sources.)

| Q | Decision | Notes |
| --- | --- | --- |
| **Q1 — source-vs-strategy policy + binding mechanism** | **(a)+(b) with manifest-declared triggers.** Modules are **drop-ins**: dropping a module folder into `<vault>/modules/<name>/` makes it available, and **the module's `manifest` declares its triggers** (e.g. URL/domain patterns, source kinds it handles). A declared `data_source` is "backed" iff some installed module's manifest triggers match it. If no module's triggers match **and** the source carries no explicit `kind: strategy_hint` annotation, scaffolding errors with a clear "source X declared but has no implementation" message. Strategy hints are honestly named so they never masquerade as first-class module-backed sources. | Operator decision (overrode the plain (a)/(b)/(c) options): binding is by **manifest-declared triggers**, not name-equality. This makes module drop-in composition the mechanism — adding a source = dropping a module whose manifest claims the relevant triggers, OR annotating the declared source as a strategy hint. Plan-stage defines the manifest `triggers` schema + the matching algorithm (URL/domain/kind). |
| **Q2 — migration of existing vaults** | **Operator-driven.** The framework WARNs on `./vault update` and **fails closed at preflight** (FR2) when a declared source has neither a trigger-matching module nor a `strategy_hint`; the operator then annotates `kind: strategy_hint` or drops in a module. The framework **never rewrites `research.spec.md`** automatically. | Trust-the-operator (same stance as 066 Q11). The vault's source declaration is the operator's; the framework surfaces the gap loudly but doesn't silently mutate the spec. |
| **Q3 — relevance-classifier tuning scope (FR4)** | **Split.** 069 ships the honest-coverage fix for rc8 — **FR1/FR2** (manifest-trigger scaffold + preflight validation) + **FR3** (stagnant-source signal). **FR4** (the `gh`-went-cold relevance-classifier tuning) becomes a **separate follow-up sub-spec** because it needs live data + investigation and shouldn't gate the rc8 honesty fix. | Keeps 069 shippable + scoped. FR5 (spec-053 authority alignment) rides with the FR3 signal (an authoritative source going cold is a worse smell). |
| **Q4 — stagnant-source signal severity (FR3)** | **WARN (advisory).** A source yielding zero facts/signals for ≥2 consecutive cycles is surfaced in the cycle report + `./vault status`; it never blocks the cycle. The hard gate is the scaffold-time/preflight validation (FR1/FR2). | Runtime stagnation is informational (a source can legitimately be quiet a cycle); the *structural* "declared-but-unimplemented" case is what fails closed. Consistent with the framework's "ops surfaces warn, gates block structure" split. |

All four resolved. Locked shape for **069 (rc8 scope)**: manifest-declared
`triggers` make modules drop-in-composable; scaffold + preflight validation
fails closed on declared-but-unbacked sources lacking a `strategy_hint`
(FR1/FR2); a WARN-level stagnant-source signal in the cycle report +
`./vault status` (FR3) with spec-053 authority weighting (FR5); operator-driven
migration (no auto-rewrite of `research.spec.md`). **FR4** (relevance-classifier
tuning) is deferred to a follow-up sub-spec. Ready for `/speckit.plan`.

## Why this spec exists

A vault that declares 4 sources but only uses 2 is **lying to the operator**.
The operator wrote `research.spec.md` expecting all 4 to contribute; the
framework silently dropped 3. That's exactly the kind of dishonesty the
framework was designed to prevent.

The rc7 evidence:

- `codebase_vault_seed` — declared, empty across all 4 cycles.
- `Official Documentation` — declared, empty across all 4 cycles.
- `Web` — declared, empty across all 4 cycles.
- `gh` — yielded in cycles 2-3, then stopped.
- `code` — only consistently-yielding source.
- `github` — second consistently-yielding source.

The three "cold" sources almost certainly have NO source module in
`vault/modules/` — they're strategy hints (LLM-fetch directives) that the
framework treats as declared sources but has no implementation for. Result:
they appear "declared but unimplemented" and silently produce nothing.

This spec is really TWO related problems:

1. **Spec-time validation** — declare-but-no-module should be a
   scaffold-time error, not a runtime silent-empty.
2. **Source-relevance classifier tuning** — even for sources that ARE
   implemented (like `gh`), the source-relevance classifier may be too
   aggressive, marking most topic⊗source pairs as `unrelated` and
   filtering them out before the bridge runs.

## Suggested approach (for the clarify stage)

1. **Audit the vault** — for each declared source, is there a module in
   `vault/modules/`? (Verifiable: `~/Documents/reference-vault-rc7/vault/modules/`).
2. **Decide source-vs-strategy policy** (clarify Q1):
   - (a) Every declared source MUST have a backing module — scaffold-time
     error if it doesn't.
   - (b) Spec supports two kinds of sources: module-backed (concrete) and
     strategy hints (LLM-fetch directives without modules). Strategy hints
     are honest-named so they don't look like first-class sources.
   - (c) The framework auto-generates a stub module for any declared source
     without one, and the operator fills it in.
3. **Spec-time validation** (FR1): scaffold-time error if a declared source
   has no implementation OR if the source-relevance classifier defaults to
   `unrelated` for that source.
4. **Stagnant-source signal** (FR3): cycle report calls out "source X
   yielded zero facts/signals for ≥2 cycles" as a WARN surfaced in the
   cycle report, not just a buried digest line.
5. **Source-relevance tuning** (FR4): investigate whether the classifier
   is too aggressive (the `gh` source went cold after cycles 2-3 despite
   the cycles continuing to draft GitHub-relevant content). Possibly the
   classifier is over-fitting on early cycle output.

## Functional requirements (sketch)

- **FR1** — Scaffold-time validation: every declared source has either
  (a) a backing module in `vault/modules/<name>/` or (b) an explicit
  `kind: strategy_hint` annotation acknowledging it's LLM-fetched.
  Otherwise scaffolding errors out with a clear "source X declared but
  has no implementation" message.
- **FR2** — Runtime: when a declared source has no module AND no
  strategy-hint annotation, the framework errors at preflight, not
  silently produces empty signals.
- **FR3** — Stagnant-source signal: cycle report includes a "Sources"
  section that flags any source yielding zero facts/signals for ≥2
  consecutive cycles. `./vault status` echoes the same signal.
- **FR4** — **DEFERRED to a follow-up sub-spec (clarify Q3 — NOT implemented in
  069).** Source-relevance classifier audit: investigate the rc7 `gh`-going-cold
  case; document whether tuning, threshold, or algorithm change is the right fix.
  This needs live data and is out of 069's locked scope; 069 ships only the
  structural honesty fix (FR1/FR2/FR3/FR5). Tracked by tasks.md T023 (file the
  sub-spec via `/speckit.specify`).
- **FR5** — Spec 053 (Source Authority) alignment: the authority signal
  and the relevance signal should be consistent — an authoritative source
  going cold is a worse smell than a low-authority source going cold.

## Cross-references

- Issue #160 (this spec's tracking issue)
- Issue umbrella #152 (rc7 validation findings → rc8 wave)
- Spec 020 (source modules architecture — owns module enumeration)
- Spec 053 (declarable source authority — must stay consistent)
- Spec 055 (source credibility — sibling concept, different axis)
- `source-relevance` skill (`.agents/skills/source-relevance/SKILL.md`)

## Open questions (for /speckit.clarify)

- Q1: Which source-vs-strategy policy? (Option (a) — scaffold-time error
  unless `kind: strategy_hint` — is the most honest.)
- Q2: Migration: existing vaults with declare-but-no-module sources need
  to be upgraded. Is that automatic on `./vault update` or operator-driven?
- Q3: Source-relevance tuning — is the existing classifier the right tool,
  or should the framework move to a per-source threshold (e.g. relevance
  classifier output × source authority × source recency)? This may itself
  be a follow-up sub-spec.
- Q4: Stagnant-source signal severity — WARN (default) or FAIL when
  multiple primary sources go cold simultaneously?

## Deferred to plan/tasks

Full plan + tasks + foreman test-design enrichment happens after clarify.
This stub exists so the rc8-wave umbrella has a concrete spec dir to point
at; full spec-kit work lives in a dedicated session.
