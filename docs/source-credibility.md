# Source Credibility Guidelines

**Status**: active (spec 055, Wave 2 / 0.10.0).
**Contract**: `specs/055-source-credibility-model/contracts/credibility-model.contract.md`
**Extends**: spec 053 source authority (`role` / `priority` axis).

---

## What this is

Source **authority** (spec 053) answers *who may anchor a claim* for a note
type. Source **credibility** (this doc) answers *how much to trust this
particular citation instance* — same platform, different author, different
level.

Credibility is **declared at note-writing time** and **validated for shape only**
at verifier time. Gates and metrics never re-judge the value with an LLM.

---

## The four levels (ordinal)

| Level | Rank | Use when |
|-------|:----:|----------|
| `primary` | 3 | Authoritative origin for the claim: the artifact itself (code for behaviour, ADR/spec for intent), first-party official docs, or a disinterested primary study. No COI. |
| `corroborated` | 2 | Reputable secondary, peer- or editorially vetted, **in-field**, no disqualifying COI: survey paper, standards body, named domain expert writing in their field. |
| `commentary` | 1 | Identified opinion or discussion: practitioner blog, named HN/Reddit comment from a plausible expert, conference hot-take. Useful signal, not authoritative. |
| `unvetted` | 0 | Anonymous / unknown author, unverifiable provenance, or promotional material. |

Higher rank = more credible. Tier-1 for metrics = `{primary, corroborated}`.
Tier-2 / lower-authority = `{commentary, unvetted}`.

---

## Where to record it

Per-citation on Tier-2 `source_urls` object entries:

```yaml
source_urls:
  - url: "https://news.ycombinator.com/item?id=12345"
    title: "HN: practitioner on retry semantics"
    credibility: commentary
    coi: false
    credibility_rationale: "Named commenter, plausible expert, no COI."
```

Optional per-source default when most citations from a source share a level:

```yaml
# research.spec.md data_sources[] or module sources.yaml
default_credibility: corroborated
```

**A default only applies to citations the framework can attribute to that
source.** For a module-backed source that is its `repos[]` / module source ids.
For a `kind: strategy_hint` source — which has no module by definition — it is
the domains the source declares:

```yaml
data_sources:
  - name: "Regional company engineering blogs"
    kind: strategy_hint
    default_credibility: primary
    url: "https://eng.alpha.example/"        # one representative domain
    urls:                               # the rest of the set
      - "https://engineering.bravo.example/"
      - "https://engineering.charlie.example/"
```

Matching is **host-exact**: `https://eng.alpha.example/` grounds
`https://eng.alpha.example/any/deep/path`, but `engineering.bravo.example` does NOT
ground `bravo.example`, and `person-a.example` does not ground `www.person-a.example`. List every
host you actually cite.

> Before spec 070 a strategy hint's `default_credibility` was silently inert:
> `url:` was discarded at parse time and only `repos[]` fed the index, so a
> declared source could not ground a citation to its own domain. If you are
> reading this because notes are being quarantined for "no source default
> applies", that is the bug — and `./vault re-grade` reinstates the casualties
> once the declaration is fixed.

For a **multi-tenant platform** (`medium.com`, `dev.to`, `linkedin.com`), do not
declare it under `urls:` — that would grade the whole platform at your source's
level. Use the path-scoped vault override instead:

```yaml
# settings.yaml
credibility:
  trusted_domains:
    - { domain: "medium.com", tier: tier_3, match_type: host_path, min_segments: 1 }
```

Resolution order: **explicit citation → source default (exact id, then declared
host) → source role → domain catalog (vault override, then shipped default) →
FAIL** (no silent fallback).

---

## Conflict of interest (COI)

Set `coi: true` when the author has a stake in the conclusion (e.g. vendor paper
on their own product). COI **caps effective level at `commentary`** — never
`primary` or `corroborated` after the cap.

---

## Topic scope (off-field downgrade)

Reuse spec 053's `note_type → authoritative_role`. When the citation's source
`role` ≠ the note type's authoritative role, apply a **one-step downgrade**
(floor at `unvetted`). COI cap applies **before** the topic downgrade.

Example: `primary` + COI + off-field → `commentary` (COI) → `unvetted` (off-field).

If the citation's role cannot be resolved, **do not** apply off-field downgrade
(the 053 grounding gate handles missing roles).

---

## Worked examples

| Case | Declared | COI | Off-field | Effective |
|------|----------|-----|-----------|-----------|
| HN expert, on-topic | `commentary` | false | false | `commentary` |
| HN random opinion | `unvetted` | false | false | `unvetted` |
| OpenAI paper on GPT | `corroborated` | true | false | `commentary` |
| Leader off their field | `corroborated` | false | true | `commentary` |
| Leader off-field + COI | `primary` | true | true | `unvetted` |
| First-party docs, in-field | `primary` | false | false | `primary` |

---

## Verifier rules (shape only)

The verifier emits `IX-credibility-unresolved` or `IX-credibility-malformed` when:

- a citation has neither explicit `credibility` nor a resolvable source default;
- `credibility` is not one of the four enum values;
- `coi` is present but not a boolean.

It never asserts that a chosen level is "correct" — that is the authoring agent's
recorded judgement.

---

## Consumers

- **Spec 030 `tier2_source_ratio`**: fraction of resolved citations at
  `{commentary, unvetted}` — detects lower-authority sources displacing tier-1.
- **Spec 048 v2 ledger** (optional): may annotate `USED` rows with recorded levels.

Implementation: `src/research_framework/vault/credibility.py`.
