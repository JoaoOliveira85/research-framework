---
spec_number: 066
title: Credibility model calibration — canonical project domains must not 100%-reject
status: SHIPPED 1.0.0rc9 (2026-06-15) — PR #175, squash 0b031ef — credibility domain catalog + vault override + WARN/FAIL split + re-grade verb; rc8-wave umbrella #152 (CLOSED). Re-validated on reference-vault-rc7 (re-grade reinstates 12/12 quarantined notes).
target_version: 1.0.0rc9 / 1.0.0
created: 2026-06-14
source_input: |
  2026-06-13 rc7 reference-vault validation run (`~/Documents/reference-vault-rc7/`,
  GitHub issue #153, umbrella #152). 12/12 cycle notes rejected with
  `IX-credibility-unresolved` — Fastify (fastify.dev + github.com),
  Express.js, CAP Theorem (wikipedia.org), Boto3 (boto3.amazonaws.com),
  every other reference-vault note cited canonical project domains and the
  spec-055 credibility model returned "no source default applies". The
  verifier became a 100%-reject quality blocker instead of a graded gate.
---

**Status:** shipped(2026-06-15, PR #175) — **SHIPPED 1.0.0rc9** (2026-06-15, PR #175, squash `0b031ef`; rc8-wave
umbrella #152 CLOSED) — twelve clarifications recorded (round 1 2026-06-14 + rounds
2 & 3 2026-06-15); re-validated on the reference-vault-rc7 testbed (re-grade reinstates
12/12 quarantined notes).
**Shipped:** a default credibility domain catalog
(`src/research_framework/data/credibility_catalog.yaml`, ~60 entries, tier_1/2/3
→ spec-055 `Level`) + a fail-closed `ResolvedCatalog` loader
(`vault/credibility_catalog.py`); the catalog wired into `effective_level`
(consulted after the source-default lookup misses, override-before-default,
COI/off-field unchanged on top); a vault override + `unknown_domain_policy`
(`settings.yaml::credibility`, FR3); the FR2 WARN/FAIL severity split
(`IX-credibility-unresolved` is WARN under `warn`, FAIL under `reject`;
malformed URLs → `IX-citation-malformed` FAIL) so the verifier stops
100%-rejecting canonical project domains (the rc7 #153 trap); and the
`./vault re-grade` verb (`cli/regrade.py`) that reinstates quarantined
credibility-only notes now clean under the post-066 model (auto-commit,
idempotent, zero LLM). ~50 new tests (catalog, settings, resolver, verifier
severity, re-grade, `resolve_category_folder`); `ruff` clean; `build.sh
--quality` 3/3 fixtures green; catalog ships in the wheel. rc8-wave umbrella #152.

> **Plan-stage notes (see `research.md` for full detail):** Phase-0 resolved all
> seven deferred unknowns and surfaced two corrections to this spec's deferred
> wording — (1) the FR4 re-grade verdict source is the quarantined note's **own
> frontmatter** (`verifier_status`/`verifier_notes`), **not** a
> `_pipeline/quarantine/<note>.failure.json` (that artifact does not exist in the
> spec-062 quarantine layout); (2) quarantine **flattens** the category path, so
> re-grade re-derives `data_vault/<NN - Category>/` from `coverage_category`. One
> decision is **flagged Ask-First** for `/speckit.tasks`: the `tier_1/2/3`
> vocabulary is an operator-facing alias mapping onto spec-055's existing
> `primary/corroborated/commentary` enum (`unvetted` is never catalog-assigned),
> because spec 055 has no native `tier_N` scale.

# Feature Specification: Credibility-model calibration for canonical project domains

**Feature Branch**: `066-credibility-model-calibration`
**Created**: 2026-06-14

## Clarifications

### Round 1 (resolved 2026-06-14)

| Q | Decision | Notes |
| --- | --- | --- |
| **Q1 — credibility policy** | **(a)+(d)** — grow the spec-055 default catalog with ~50 canonical patterns AND emit `credibility ungraded` for unknown well-formed URLs instead of rejecting them. | Catches the common case via a grown catalog; fails-open on the long tail so the verifier stops being a quality blocker. The "ungraded" counter already exists in the acceptance scorecard's `credibility ungraded` total, so the signal is preserved. |
| **Q2 — vault-local override** | **Yes** — ship a vault-local override (`<vault>/credibility.yaml` OR a `credibility:` section in `settings.yaml` — plan-stage decides the surface). Operators add trusted domains + tiers (`tier_1` / `tier_2` / `tier_3`). | Operators have local knowledge the framework doesn't (internal wikis, company URLs, niche-domain authors). The override augments the default catalog; it does NOT downgrade defaults. |
| **Q3 — catalog growth** | **Conservative** — default catalog covers ~50 well-known canonical domains (project `*.dev`/`*.io`, `wikipedia.org`, MDN, archive.org, well-known tech authors, OSS project hosts). Everything else is `ungraded` (per Q1). Catalog grows via PR to the framework. | Prevents catalog-as-policy creep; signals quality without dictating it. Operators with non-default trusted domains use the Q2 override. |
| **Q4 — migration path** | **`./vault re-grade` verb** — idempotent pass that re-evaluates every rejected/quarantined note against the current credibility model, reinstates any that now pass (move from `_pipeline/quarantine/` back into `data_vault/<category>/`). | Operator-friendly + reusable for future credibility-model changes. The verb is small surface (one new CLI entry), independent of cycle scheduling. |
| **Q5 — scope** *(in-spec default, no operator pushback)* | **Standalone spec, not an amendment to 055.** | 055 owns the model + tiering; 066 calibrates the catalog + adds the override + adds the re-grade verb — these are large enough to warrant their own spec dir + plan. |

### Round 2 (resolved 2026-06-15)

| Q | Decision | Notes |
| --- | --- | --- |
| **Q6 — catalog shape (wildcards vs exact-match)** | **Hybrid** — wildcards (`*.dev`, `*.io`) at **tier_3 only** ("likely-credible-but-not-authoritative"); exact-match entries (`fastify.dev`, `wikipedia.org`, `developer.mozilla.org`) for **tier_1 / tier_2**. | Anyone can register a `.dev` domain; default-trusting all of them at tier_2 risks `shady-blog.dev` getting the same grade as `fastify.dev`. Wildcard-at-tier_3 gives the catalog a sensible floor for new project sites without elevating unknowns to "authoritative". Operators promote specific wildcards-matched domains via the Q2 override when warranted. |
| **Q7 — interaction with spec 053 source authority** | **Independent** — spec 053 grades the SOURCE (declared in `research.spec.md`), spec 066 grades the URL CITATION; both ship to the verifier separately with no cross-influence. | Least coupling, easiest to reason about, lets each spec own its axis. The verifier can later combine the two signals if needed, but they don't reshape each other. An operator who wants tier-2-by-default for their declared 053 sources adds those domains explicitly to the Q2 vault-local override. |
| **Q8 — `./vault re-grade` scope** | **Quarantined notes only** — re-grade only notes in `_pipeline/quarantine/`; reinstate any that now pass under the current credibility model. Currently-accepted notes are untouched. | Conservative, fast, no risk of demoting passing notes on innocent catalog tweaks. Future "full corpus re-grade" is a separable concern that doesn't gate the rc8-wave bug fix. |
| **Q9 — `./vault re-grade` commit policy** | **Auto-commit** — single `regrade(<YYYY-MM-DD>): N notes reinstated` commit per run; if N=0 the verb is a no-op (no empty commit). | Matches the spec-050 per-cycle commit pattern; auditable; idempotent; no dangling-deletes failure mode (the exact rc7 GA-003 class of problem). |

### Round 3 (resolved 2026-06-15)

| Q | Decision | Notes |
| --- | --- | --- |
| **Q10 — strict mode** | **Ship strict mode as opt-in** via `unknown_domain_policy: reject` in the vault override (the FR3 schema already shows it). Default is `warn` (Q1's permissive behaviour); operators flip to `reject` per-vault for academic-rigor / compliance / regulated-domain vaults. | Gives those vaults the lever they may legitimately want. Cost is one config key + a few lines of branching logic in the verifier credibility check. The `reject` setting restores the rc7-pre-066 FAIL semantics for unknown URLs but does NOT affect catalog-hit URLs (those still grade by tier). |
| **Q11 — override semantics** | **Full override** — the vault-local `trusted_domains` list **silently replaces** matching default-catalog entries at any tier. Operator's `trusted_domains` is the vault's opinion and wins; the default catalog is the framework's opinion (used only when the vault has nothing to say). | Trust-the-operator stance: an operator who explicitly lists `wikipedia.org` at `tier_3` in their override gets exactly that, no warning. This makes per-vault credibility tuning explicit (everything in the vault override IS the policy for that vault) and avoids the maintenance burden of a "downgrade reason" field. Trade-off: per-vault credibility drift IS possible; operators take responsibility for their own override. |
| **Q12 — `./vault re-grade` invocation** | **Manual only** — the verb is never auto-invoked. The framework does not re-grade on `./vault update`, on framework upgrade, or on any other lifecycle event. Operator runs it when they want it. | Simplest; predictable; matches the spec-050 "cycle commits are auto, ops verbs are manual" separation. Auto-invocation would surprise operators with file moves they didn't ask for. The verb's job is documented in release notes (e.g. "after upgrading to 1.0.0rc8+, run `./vault re-grade` to reinstate any quarantined notes that pass the new credibility model"). |

All twelve resolved; spec genuinely clarified (not "defaulted-clarified"). The locked-in shape:

1. **Catalog**: grows with a hybrid wildcard+exact-match policy (wildcards at tier_3 only, exact-match at tier_1/tier_2).
2. **Unknown URLs**: emit `credibility ungraded` instead of rejecting; the existing acceptance-scorecard counter is the live signal.
3. **Vault-local override**: a `trusted_domains` list **fully replaces** matching default-catalog entries (operator trust); `unknown_domain_policy` controls strict-vs-permissive per-vault.
4. **Spec-053 orthogonality**: 066 stays independent of source authority; operators add 053-source domains to the override explicitly if they want default trust.
5. **`./vault re-grade`**: quarantine-only scope, auto-commits the move as `regrade(<YYYY-MM-DD>): N notes reinstated`, manually invoked only.

Ready for `/speckit.plan`.

## Why this spec exists

Spec 055 (Source Credibility Model, SHIPPED 0.10.0) graded citations by
mapping URLs to credibility tiers. The rc7 reference-vault validation run
(GitHub #153) revealed the catalog has **no entries for project-canonical
domains** — `*.dev`, `github.com/<org>/<project>`, `mozilla.org/docs`,
`wikipedia.org`, `martinfowler.com`, `kleppmann.com`, etc. — so every
honest citation reaches the verifier as "no source default applies" and
gets rejected under `IX-credibility-unresolved`. Result: 12/12 fresh notes
rejected on a 4-cycle run that *should* have been the framework's "first
clean reference-vault" milestone.

The credibility gate is acting as a quality **blocker**, not a quality
**gate**. "I haven't seen this domain before" ≠ "this is non-credible".

## Functional requirements

### FR1 — Default catalog with hybrid wildcard+exact-match shape (Q3 + Q6)

The spec-055 default catalog grows to cover the canonical-domain shapes
that bit the rc7 run, using a **hybrid** policy per Q6:

- **Wildcards at tier_3 only** (`*.dev`, `*.io`, others as finalised at
  plan-stage). "Likely-credible-but-not-authoritative" floor for new
  project sites; prevents `shady-blog.dev` from getting the same default
  trust as `fastify.dev`.
- **Exact-match entries at tier_1 / tier_2** — the operator-curated
  authoritative list. Seed list (finalised in `/speckit.plan` Phase-0):
  - **Encyclopedic / reference (tier_1)**: `wikipedia.org` (+ language
    subdomains), `developer.mozilla.org`, `archive.org`.
  - **OSS project hosting (tier_2)**: `github.com/<org>/<project>`
    (org-scoped, NOT blanket `github.com/*`), `gitlab.com/<org>/<project>`,
    `sourceforge.net`.
  - **Standards bodies (tier_1)**: IETF / W3C / ECMA / ISO standards sites.
  - **Vendor documentation (tier_1)**: `aws.amazon.com/documentation/`,
    `cloud.google.com/docs`, `learn.microsoft.com`, `docs.oracle.com/javase`,
    `docs.python.org`, `docs.rs`, `pkg.go.dev`.
  - **Well-known project sites (tier_2)**: `fastify.dev`, `vitejs.dev`,
    `nextjs.org`, etc. (the exact list is plan-stage research).
  - **Well-known tech authors (tier_2)**: `martinfowler.com`, `kleppmann.com`,
    + others surfaced by the rc7 citation log.
- **Total catalog target**: ~50–80 entries (~10 wildcards + ~40–70
  exact-match). Goal: covers the rc7 + rc8 + likely-next-reference-vault
  citations cleanly, not "everything".

Each entry carries a tier (`tier_1` / `tier_2` / `tier_3`) per spec 055's
existing tiering; the wildcard entries are pinned at tier_3 per Q6.

### FR2 — Unknown well-formed URLs classify as "ungraded", not "rejected"

When the verifier evaluates a citation:

- **Catalog hit** ⇒ assign the catalog's tier; existing 055 behaviour.
- **Catalog miss + URL is well-formed** (parseable, scheme is http/https,
  host has at least one dot) ⇒ emit `credibility: ungraded`. The verifier
  rule `IX-credibility-unresolved` is downgraded from FAIL → WARN by default.
  The note is NOT rejected on this signal alone.
- **Catalog miss + URL is malformed** ⇒ existing `IX-citation-malformed` rule
  applies (unchanged); FAIL.

The acceptance scorecard's existing `credibility ungraded` counter (already
emitted by spec 063 GA-005 / citation-grading section) now becomes the live
operator signal for "domains I should review and add to my catalog or
override".

A strict opt-in mode (`credibility.unknown_domain_policy: "reject"` under
the vault override of FR3) restores the FAIL semantics for operators who
want it.

### FR3 — Vault-local credibility override (Q2 + Q7)

Operators can augment the default catalog without forking the framework.
The exact surface is finalised in `/speckit.plan` Phase-0 (two candidates:
a standalone `<vault>/credibility.yaml` file vs a `credibility:` section
in the existing `settings.yaml`). Either way the schema:

```yaml
trusted_domains:
  - domain: "internal.companyhost.com"
    tier: tier_1
  - domain: "<acquaintance>.substack.com"
    tier: tier_3
    notes: "Senior architect; reliable for opinion / lessons-learned, not specs"
unknown_domain_policy: warn   # warn (default) | reject (strict)
```

**Override semantics (Q11)**: the `trusted_domains` list **fully replaces**
matching default-catalog entries at any tier — no warnings, no special flags.
The default catalog is the framework's opinion (used only when the vault has
nothing to say about a domain); an operator's override is **the vault's
opinion** and wins. Concretely: if the default catalog has
`wikipedia.org` at tier_1 and the override has `wikipedia.org` at tier_3,
the vault evaluates wikipedia citations at tier_3 with no audit-log warning.

This is a deliberate trust-the-operator stance: per-vault credibility
tuning is a legitimate operator capability (academic-rigor vaults that
distrust Wikipedia, internal-tooling vaults that elevate niche company
sources, etc.). The cost is per-vault credibility drift; the operator
takes responsibility for their own override file — which is exactly the
appropriate place for that responsibility to live.

**Strict mode (Q10)**: the `unknown_domain_policy` key (`warn` default |
`reject` strict) controls the FR2 behavior for unknown-but-well-formed
URLs. Strict mode is the rc7-pre-066 behavior (FAIL on unknown), useful
for academic-rigor / compliance / regulated-domain vaults that want
to-the-letter source policy. Strict mode does NOT change behavior for
catalog-hit URLs (those still grade by tier). Default `warn` matches the
permissive default established by Q1.

The override does **NOT** know about spec 053 (per Q7 — credibility and
source-authority stay orthogonal axes). If an operator wants their declared
053 sources treated as tier_2 by default, they add those source-URL domains
explicitly to the `trusted_domains` list. The framework does NOT auto-grant
credibility based on 053 declarations — declaring a source as "primary" in
`research.spec.md` says nothing about how credible its content should be
treated.

### FR4 — `./vault re-grade` verb (Q4 + Q8 + Q9)

A new CLI verb that re-evaluates **quarantined notes only** (Q8 —
conservative scope; currently-accepted notes are untouched) against the
current credibility model. For each note in `_pipeline/quarantine/`:

- Re-run the verifier's credibility check on its citations.
- If the note now passes ⇒ move it back to `data_vault/<category>/` and
  record the re-grade in the cycle log.
- If the note still fails ⇒ leave it in quarantine and update its
  `_pipeline/quarantine/<note>.failure.json` with the new verdict.

The verb is **idempotent**: running it on a clean vault (no quarantined
notes) is a no-op. It does NOT trigger any LLM calls (deterministic,
zero-cost). The verb is reusable for any future credibility-model change,
not just this one.

**Commit policy** (Q9): the verb **auto-commits** the move as a single
`regrade(<YYYY-MM-DD>): N notes reinstated` commit on the current branch.
If N = 0 the verb is a no-op and produces no commit (no empty commits).
This matches the spec-050 per-cycle commit pattern + the spec-062 quarantine
atomicity invariant — at no point should the working tree contain
uncommitted reinstatements (exactly the rc7 GA-003 failure mode pattern).

**Invocation (Q12)**: the verb is **manually invoked only** —
`./vault re-grade` from the operator's shell. The framework never
auto-invokes it: not on `./vault update`, not on framework upgrade, not
on any other lifecycle event. This matches the spec-050 "cycle commits
are auto, ops verbs are manual" separation; auto-invocation would
surprise operators with file moves they didn't ask for. Release notes
for credibility-model changes document when operators should run it
(e.g. "after upgrading to 1.0.0rc8+, run `./vault re-grade` to reinstate
any quarantined notes that pass the new credibility model").

**Out of scope for this spec** (future work, NOT required for rc8/v1.0.0):
re-grading currently-accepted notes (Q8 deliberately excluded this; a
"full corpus re-grade" verb is separable); auto-invocation lifecycles
(Q12 deliberately excluded this; could be revisited per-operator-feedback
post-v1.0.0). Plan-stage decides: `--dry-run` flag, `--note <path>` to
re-grade a single note, output format (table / JSON).

### FR5 — Regression coverage

The spec 022 quality fixtures (`tests/fixtures/quality/`) include at least
one "tech-stack" shaped fixture with notes citing the rc7-failure-class
sources (`fastify.dev`, `wikipedia.org`, `github.com/<org>`,
`martinfowler.com`). The fixture's verifier-rejection rate stays ≤ 10% on
rc8+; a regression would re-introduce the rc7 symptom and is caught at
`./build.sh --quality` time, not at live-validation time.

## Cross-references

- Issue #153 (this spec's tracking issue)
- Issue umbrella #152 (rc7 validation findings → rc8 wave)
- Spec 055 (Source Credibility Model — what this calibrates; FR1+FR3 grow it)
- Spec 063 GA-005 / citation-grading section (consumes the FR2 "ungraded"
  counter — no scorecard change needed)
- Spec 062 (vault-output integrity / quarantine — FR4 reuses the quarantine
  layout that 062 established)

## Deferred to /speckit.plan

- **Exact catalog (FR1)** — the seed list above is the floor; plan-stage
  research finalises the concrete tier_1 / tier_2 exact-match entries +
  the precise wildcard set at tier_3. The hybrid shape (Q6) is locked.
- **Override surface (FR3)** — `credibility.yaml` file vs `settings.yaml`
  section. Both are viable; plan picks one based on operator-discovery cost
  vs config-file proliferation cost.
- **`./vault re-grade` flags + output** (FR4) — `--dry-run` flag,
  `--note <path>` to re-grade a single note, output format (table / JSON),
  interactions with `./vault acceptance` re-grading. The verb's core
  contract (quarantine-only Q8, auto-commit Q9) is locked.
- **Catalog data format** — does the framework's default catalog live in
  Python code (current spec 055 home) or move to a YAML data file
  (`src/research_framework/data/credibility-catalog.yaml`)? Plan-stage
  decides based on operator-inspection ergonomics vs typing-safety.
- **Test-design enrichment** (foreman ADR-0010) — `Testing Requirements`
  blocks per task, dispatched after `/speckit.tasks` and before
  `/speckit.implement`.
