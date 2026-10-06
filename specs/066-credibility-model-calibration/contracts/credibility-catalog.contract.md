# Contract: Credibility domain catalog + vault override + resolution

**Spec**: 066 — Credibility-model calibration
**Status**: authored 2026-06-15 (post-clarify, Phase-1). Authoritative for the
catalog/override schema, the tier→`Level` mapping, the resolution order, and the
WARN/FAIL split. Extends — does not replace — spec-055
`contracts/credibility-model.contract.md` (the COI cap + off-field downgrade +
the `Level` enum stay exactly as 055 defines them).
**Determinism**: every rule here is a pure function of recorded data + shipped
data files. No LLM judgement at gate time (Principle IV; 053 #4/#5).

---

## 1. Tier vocabulary ↔ 055 `Level` (research D0)

The catalog and override speak operator-facing **tiers**; the resolver works in
the spec-055 `Level` enum. Mapping is applied at load:

| `tier` | `Level` | rank |
| --- | --- | --- |
| `tier_1` | `primary` | 3 |
| `tier_2` | `corroborated` | 2 |
| `tier_3` | `commentary` | 1 |
| *(unreachable)* | `unvetted` | 0 |

`unvetted` is **never** produced by the catalog. It remains the floor produced
only by an explicit citation declaration or by the COI/off-field operators that
run *after* the catalog supplies a level.

## 2. Entry schema (default catalog + override — one shape)

```yaml
- domain: "<pattern>"        # required
  tier: tier_1|tier_2|tier_3 # required
  match_type: exact|host_suffix|host_path   # optional, default "exact"
  min_segments: <int>        # optional, host_path only, default 2
  notes: "<free text>"       # optional, never read by the resolver
```

**Validation at load** (fail-closed; a bad entry is dropped with a WARN, never
crashes the verifier):
- `tier` ∉ {tier_1,tier_2,tier_3} ⇒ drop + WARN.
- `match_type == host_suffix` in the **default catalog** with `tier != tier_3`
  ⇒ drop + WARN (Q6 — wildcards are tier_3-only in the framework default). The
  **override** MAY put a wildcard at any tier (operator's prerogative, Q11).
- `domain` empty ⇒ drop.
- `host_suffix` patterns are written `*.dev` and matched `host.endswith(".dev")`.

## 3. Default catalog data file

- Path: `src/research_framework/data/credibility_catalog.yaml` (shipped; wheel
  force-include + bundle copy).
- Top-level: `entries: [ <Entry> ... ]`.
- Conservative (~50–80 entries, Q3). Seed list = research.md "Finalised FR1
  default catalog". Growth = a YAML PR to the framework.
- Loader is fail-closed: a missing/corrupt file ⇒ empty catalog ⇒ everything
  resolves `ungraded` (WARN under default policy), never an exception.

## 4. Vault override (`settings.yaml::credibility:`)

```yaml
credibility:
  unknown_domain_policy: warn        # warn (default) | reject
  trusted_domains: [ <Entry> ... ]   # default []
```

**Q11 full-override semantics**: a `trusted_domains` entry whose pattern
resolves host `H` **silently replaces** every default-catalog entry that would
resolve `H`, at whatever tier the override states — no warning, no audit note.
The default catalog is consulted only for hosts the override does not speak to.

## 5. Resolution order (extends 055 §4 `effective_level`)

```
declared =
    citation.credibility                              # 055 §2a (unchanged)
    or owning_source.default_credibility              # 055 §2b (unchanged)
    or override_catalog.lookup(citation.url)          # NEW — FR3/Q11
    or default_catalog.lookup(citation.url)           # NEW — FR1
# (override consulted before default; first hit wins)

if declared is None:                                  # catalog miss
    if malformed(citation.url):     -> IX-citation-malformed (FAIL)   # D2, unchanged
    elif policy == "reject":        -> IX-credibility-unresolved (FAIL)  # Q10
    else:                           -> IX-credibility-unresolved (WARN)  # FR2 default
else:
    after_coi   = min_rank(declared, COMMENTARY) if citation.coi else declared   # 055 §4
    effective   = downgrade_one_step(after_coi) if off_field(citation,note) else after_coi
    return effective
```

- `malformed(url)` ⇔ scheme ∉ {http,https} **or** host has no dot (D2).
- The COI cap + off-field downgrade are **unchanged** and apply on top of a
  catalog-supplied `declared` exactly as for a citation-declared one.
- Determinism: same citation + same catalog file + same `settings.yaml` ⇒ same
  level, every run.

### `lookup(url)` (Entity 3)
1. `host = urlparse(url).netloc.lower()` minus any `:port`.
2. host has no dot ⇒ return `None` flagged malformed (caller → IX-citation-malformed).
3. `exact[host]` → `host_path` (host == entry.domain AND
   `len(path_segments) >= min_segments`) → `host_suffix` (longest
   `host.endswith(pattern_without_star)`); first hit returns its `Level`.
4. no hit ⇒ `None` (⇒ ungraded).

## 6. Verifier WARN/FAIL split (FR2; data-model Entity 5)

`deterministic_credibility_violations` tags each unresolved-but-well-formed
`IX-credibility-unresolved` with `severity: "warn"` under
`unknown_domain_policy: warn` (default) and `severity: "fail"` under `reject`.
`_merge_verifier_verdict` forces `verifier_status: rejected` **only** on
`severity: "fail"` violations; `warn` violations attach as advisory
`verifier_notes` without flipping status. Malformed / bad-enum / bad-coi rules
keep `severity: "fail"` (unchanged). Absent `severity` defaults to `fail`
(back-compat).

## 7. Worked examples (against the real rc7 hosts)

| citation url | resolves via | declared | coi | off_field | effective | status |
| --- | --- | --- | --- | --- | --- | --- |
| `https://fastify.dev/` | default exact tier_2 | corroborated | — | — | **corroborated** | pass |
| `https://github.com/fastify/fastify` | default host_path(≥2) tier_2 | corroborated | — | — | **corroborated** | pass |
| `https://github.com/` (bare) | host_path needs ≥2 segs → miss | — (ungraded) | — | — | — | **WARN** (warn policy) |
| `https://en.wikipedia.org/wiki/CAP_theorem` | default exact tier_1 | primary | — | — | **primary** | pass |
| `https://spark.apache.org/docs/` | `*.apache.org` wildcard tier_3 | commentary | — | — | **commentary** | pass |
| `https://internal.companyhost.com/x` | **override** tier_1 | primary | — | — | **primary** | pass |
| `https://kubernetes.default.svc/` | catalog miss, well-formed | — | — | — | — | **WARN** / FAIL under reject |
| `http://prometheus:9090/` | host has no dot | — | — | — | — | **FAIL** (malformed, unchanged) |
| `https://wikipedia.org/...` w/ override tier_3 | **override replaces default** | commentary | — | — | **commentary** | pass (Q11 — no warning) |

## 8. Out of scope (this contract)
- Any runtime LLM judgement of a level (Principle IV).
- Mutating `research.spec.md` (catalog/override never touch the spec).
- Re-grading currently-accepted notes (Q8 — quarantine-only).
- External-signal reputation scoring (citation counts, stars) — 055 §8 holds.
