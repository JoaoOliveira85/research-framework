# Contract: Source Credibility Model

**Spec**: 055 — Source Credibility Model (Contextual Tiering)
**Status**: authored 2026-06-03 (post-clarify). Authoritative for the datum
schema, the resolution function, and the validator/calculator boundaries.
**Determinism**: every rule here is a pure function of recorded data. No LLM
judgement at gate/metric time (053 decision #4/#5; Principle IV).

---

## 1. The credibility level (CL-1)

A **4-value ordinal enum**. Higher rank = more credible.

| level          | rank | definition (FR-009 — the "draw the line consistently" bar) |
|----------------|:----:|------------------------------------------------------------|
| `primary`      | 3    | The authoritative origin for the claim, no COI: the artifact/data itself (code for behaviour; the ADR/spec for intent; a primary peer-reviewed study by a disinterested author for domain), or first-party official documentation. |
| `corroborated` | 2    | Reputable secondary, editorially- or peer-vetted, **in-field**, no disqualifying COI: a survey paper, a recognized standards body, an identified domain expert writing within their field. |
| `commentary`   | 1    | Identified-author opinion / discussion: a named practitioner's blog, a named HN/Reddit comment from a plausible expert, conference-talk hot-takes. Useful signal, not authoritative. |
| `unvetted`     | 0    | Anonymous / unknown author, unverifiable provenance, or promotional/marketing material. |

- **Ordinal**: `primary > corroborated > commentary > unvetted`. Ranks are the
  integer column (used by `min_rank` / `downgrade_one_step`; never serialized —
  the enum string is the stored value).
- **Boundary for 030's `tier2_source_ratio`**: "tier-1" = `{primary,
  corroborated}` (rank ≥ 2); "tier-2 / lower-authority" = `{commentary,
  unvetted}` (rank ≤ 1). 030 confirms this split at its implementation.

## 2. Where the datum lives (CL-2, CL-6)

### 2a. Per-citation (note frontmatter — primary surface)

Extends the **existing `source_urls` Tier-2 frontmatter list** (Principle IX).
`source_urls` entries today are *either* a plain URL string *or* an object
`{url, title}` (parser: `scripts/check_code_source_coverage.py::_source_urls`,
which accepts both). **To carry credibility, an entry MUST use the object form:**

```yaml
source_urls:
  - url: "https://github.com/acme/svc/blob/main/handler.py"   # plain string still allowed,
  - url: "https://news.ycombinator.com/item?id=12345"          # but credibility needs the object form:
    title: "HN: practitioner on retry semantics"
    credibility: commentary           # one of the 4 enum values (CL-1)
    coi: false                         # optional; default false (CL-3)
    credibility_rationale: "Named commenter, plausible expert, no COI."  # optional but recommended (053 'declare with rationale')
```

- `credibility` — REQUIRED to resolve a level for this citation **unless** the
  owning source declares a `default_credibility` (§2b). Plain-string entries
  carry no `credibility` and therefore rely on the source default.
- `coi` — optional boolean (default `false`). `true` ⇒ the COI cap (§4) applies.
- `credibility_rationale` — optional free text; the verifier checks presence only
  when policy requires it (see §5), never its content.

### 2b. Per-source default (optional)

A `data_sources[]` entry (`research.spec.md`) or a module `sources.yaml` source
MAY declare:

```yaml
default_credibility: corroborated   # one of the 4 enum values
```

Used when a citation resolving to that source omits an explicit `credibility`.
Resolution order is strict (FR-001): **explicit citation value → else source
`default_credibility` → else FAIL** (no silent fallback).

## 3. `off_field` predicate (CL-4 — topic-scoping, reuses 053)

```
off_field(citation, note) :=
    role_of(citation) is defined
    AND role_of(citation) != authoritative_role_of(note.note_type)
```

- `role_of(citation)` = `citation → source_id → owning data_source → role`
  (reuse spec-020 `manifest.source_id_from` + 053 `sources_loader.py`; the same
  resolution 053 FR-004 uses — **055 depends on 053 having shipped it**).
- `authoritative_role_of(note.note_type)` = the `note_type`'s declared
  authoritative `role` (053 FR-001).
- If `role_of(citation)` cannot be resolved (source not found / role undeclared)
  ⇒ `off_field` is **false** (we do not downgrade on missing data; the 053
  grounding gate is what enforces role presence — 055 never double-penalizes).

## 4. The resolution function (the single deterministic rule every consumer uses)

```python
def effective_level(citation, note, sources) -> Level:
    declared = citation.credibility \
        or owning_source(citation, sources).default_credibility
    if declared is None:
        raise CredibilityUnresolved(citation)          # FR-001 — no silent default

    after_coi = min_rank(declared, COMMENTARY) if citation.coi else declared   # §4 / FR-004

    if off_field(citation, note):                       # §3 / FR-005
        after_topic = downgrade_one_step(after_coi)     # floored at UNVETTED
    else:
        after_topic = after_coi

    return after_topic
```

- `min_rank(a, b)` → the lower-ranked of two levels (COI can only *lower*).
- `downgrade_one_step(L)` → `primary→corroborated→commentary→unvetted`, floor at
  `unvetted`.
- **Order matters**: COI cap is applied **before** the topic downgrade. (A
  `primary` source with COI → `commentary`; if also off-field → `unvetted`.)
- Pure function of recorded fields + the (frozen, spec-time) 053 declarations.
  Same inputs ⇒ same output, every run.

### Worked examples (the three motivating failures)

| case | declared | coi | off_field | effective | why |
|------|----------|-----|-----------|-----------|-----|
| HN expert comment on its topic | `commentary` | false | false | **`commentary`** | named expert, in-field, no COI — useful but not authoritative (per-instance, not "HN=tier2 blanket") |
| HN random opinion | `unvetted` | false | false | **`unvetted`** | same platform, different instance → different level (CL-2 point) |
| OpenAI paper "GPT is amazing" | `corroborated` | **true** | false | **`commentary`** | peer-reviewed but author has a stake → COI caps it |
| Industry leader off their field | `corroborated` | false | **true** | **`commentary`** | authoritative in field, off-topic here → one-step downgrade |
| Leader off-field *and* COI | `primary` | true | true | **`unvetted`** | cap to commentary, then downgrade |
| First-party official docs, in-field | `primary` | false | false | **`primary`** | authoritative origin |

## 5. Validator contract (verifier — shape only, never re-judges)

The verifier (`.agents/skills/verifier` + its deterministic checks) MUST, for
each note once the model ships:

- **PASS** when every Tier-2 `source_urls` citation resolves a level (explicit or
  via source default) and any present `credibility`/`coi` fields are well-formed
  (enum ∈ the 4 values; `coi` ∈ {true,false}).
- **FAIL** (`rule_id: IX-credibility-*`) when: a citation resolves to neither an
  explicit value nor a source default; `credibility` is not one of the 4 values;
  `coi` is non-boolean. (Mirrors the existing `IX-tier2-missing` rule shape in
  `tests/pipeline/test_verifier.py`.)
- The verifier **never** asserts that a *value* is "correct" — that is the
  authoring agent's recorded judgement (CL-5). It checks presence + shape only.

## 6. Calculator contract (spec 030 `tier2_source_ratio`)

```
tier2_source_ratio(cycle) =
    | { c in cycle.tier2_citations : effective_level(c) in {commentary, unvetted} } |
    --------------------------------------------------------------------------------
    | cycle.tier2_citations |          # 0 citations ⇒ degenerate 0.0 (document in baseline)
```

- Byte-deterministic float, truncated via the 030 `_helpers.truncate_float`
  helper; committed baseline + moderate regression gate (>15% fail / >5% warn),
  consistent with the other 3 `source_quality` metrics.
- Reads frozen frontmatter only; invokes no agent.

## 7. Ledger annotation contract (spec 048 v2 — optional, FR-008)

For each `USED` source row, the ledger MAY join the recorded per-citation level
(e.g. the max/most-trusted level among that source's citations this cycle).
Missing credibility data ⇒ the row renders **unannotated**, never an error
(read-only join; degrade gracefully).

## 8. Out of scope (this contract)

- Computing credibility from external signals (citation counts, follower counts).
- Any runtime LLM judgement of a level.
- Mutating `research.spec.md` (read declarations only).
- Back-filling historical notes.
