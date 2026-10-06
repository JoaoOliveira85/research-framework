# Architecture Decision Records (ADRs)

Lightweight record of architectural decisions made in the
`research-framework` codebase. Each ADR captures a single decision,
why we made it, and what we accepted in trade.

## Why these exist

Between releases 0.2.20 and 0.2.31 we lost the same context multiple
times \u2014 a bug got fixed, a year later someone (often us) "fixed" it
again the original way and broke the original fix. ADRs are the
defense against that loop: they're the long-term memory the in-code
comments don't have room for.

Each ADR is small (50\u2013150 lines), dated, and either `Accepted`,
`Superseded`, or `Deprecated`. We do NOT edit accepted ADRs after the
fact \u2014 if a decision changes, we write a new ADR that supersedes
the old one and explicitly says so in both directions.

## Format

We use a lightweight [MADR-ish](https://adr.github.io/madr/) shape:

```
# ADR-NNNN: Title

**Status**: Accepted | Superseded by ADR-NNNN | Deprecated
**Date**: YYYY-MM-DD
**Tags**: ...

## Context
What forced the decision? What constraints applied?

## Decision
What did we decide? Stated in the active voice.

## Consequences
What follows from this? Both the good and the trade-offs.

## Alternatives considered
What else did we look at and why didn't we pick it?
```

## Index

| ID | Date | Title | Status |
|----|------|-------|--------|
| [0001](./0001-adopt-adrs.md) | 2026-05-18 | Adopt ADRs for architectural decisions | Accepted |
| [0002](./0002-phase-scoped-source-validation.md) | 2026-05-18 | Phase-scoped `sources_consulted` validation | Accepted |
| [0003](./0003-correction-directive-injection.md) | 2026-05-18 | Correction directives must be injected into prompts | Accepted |
| [0004](./0004-tolerant-verifier-json-extraction.md) | 2026-05-18 | Verifier output parsing must tolerate non-strict JSON | Accepted |
| [0005](./0005-cycle-time-wikilink-normalization.md) | 2026-05-18 | Wikilink case is normalized at cycle time | Accepted |
| [0006](./0006-code-bridge-as-cached-infrastructure.md) | 2026-05-18 | Code access is cached infrastructure, not a per-cycle agent task | Accepted |
| [0007](./0007-smoke-gate-is-mandatory.md) | 2026-05-18 | Smoke gate is mandatory and cannot be skipped | Accepted |
| [0008](./0008-testing-pyramid-restructure.md) | 2026-05-21 | Testing pyramid restructure — integration vocabulary, tier-4 split, regression discipline | Accepted (supersedes Feature 018 pyramid naming in part) |
| [0009](./0009-collectors-vs-modules-reconciliation.md) | 2026-05-22 / -26 | Reconciling 014/015 collectors vs 020 source modules (chose option A) | Accepted (2026-06-01 — transition criterion met, no amendment needed) |
| [0010](./0010-foreman-verification-pattern.md) | 2026-05-27 | Foreman verification pattern + test-design role separation | Accepted |
| [0011](./0011-operational-config-in-settings.md) | 2026-06-05 | Operational run-control config lives in settings, not the spec | Accepted (spec 061 shipped 1.0.0rc3, PR #126) |
| [0012](./0012-acceptance-bullet-format-not-guarded.md) | 2026-09-07 | The flat `## Acceptance` bullet format is not guard-enforced | Accepted |
| [0013](./0013-cross-repo-envelopes-additive-and-versioned.md) | 2026-09-08 | Cross-repo envelopes are additive within a major, carry `schema_version`, and get their schema before their producer | Accepted |

## How to add an ADR

1. Pick the next sequential number.
2. Write to `docs/adr/NNNN-kebab-title.md` using the format above.
3. Add a row to the index table.
4. Commit. Don't edit accepted ADRs later \u2014 supersede them instead.
