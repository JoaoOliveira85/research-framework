# Phase 1 — Data Model: Acronym-wikilink disambiguation (067)

067 adds no persisted schema. It refines in-memory structures in
`pipeline/wikilinks.py` and adds one deterministic predicate + one sweep action
record. The alias-stub frontmatter shape (spec-062) is **unchanged** (no
`schema_version` bump).

## Entity 1 — AcronymMap (in-memory, existing — refined)

Built by `build_acronym_map(vault_dir)`.

| Field | Type | Notes |
| --- | --- | --- |
| `mapping` | `dict[str, str]` | `ACRONYM (upper) → target stem`. **Invariant (FR1):** only acronyms with exactly ONE title-initials claim appear here. |
| `ambiguous` | `list[str]` | Acronyms with ≥2 claims — never linked, never stubbed. (Already produced today; 067 makes it authoritative for the sweep + stub refusal.) |
| `claims` | `dict[str, set[str]]` | `ACRONYM → {candidate stems}` — the pre-collapse evidence; needed by FR2/FR4 to detect *became-ambiguous* transitions. |

**Refinement (FR2):** before mapping, the builder also records, per acronym, whether
a stem **equals a note's own title-stem** so `_rewrite_acronym_body` can apply
self-title protection.

## Entity 2 — AliasStub (persisted, existing — lifecycle refined)

A `note_type: alias` note (e.g. `cap.md`). Frontmatter shape unchanged:

```yaml
title: CAP
note_type: alias
redirect_to: <stem>
verifier_status: exempt
```

**Lifecycle (067 additions in bold):**

1. **Created** by `_write_redirect_stub` when an acronym maps unambiguously.
   **(FR1) Refused** if the acronym is currently ambiguous.
2. **Became-ambiguous** — a later cycle adds a 2nd claim. **(FR2)** the stale stub is
   marked orphaned (its `redirect_to` no longer single-valued) and its body links are
   plain-texted on the next `resolve_acronym_links` pass.
3. **Swept (FR4/FR5)** — `./vault wikilinks --fix`:
   - **fixable** (exactly one valid expansion) → `redirect_to` re-pointed.
   - **orphan/unfixable** (no inbound links AND ambiguous/no-expansion) → **deleted**.
   - else untouched.

State transitions:

```
absent ──maps unambiguously──▶ live
live ──acronym becomes ambiguous──▶ stale (orphan candidate)
stale ──sweep, single valid expansion──▶ live (re-pointed)
stale ──sweep, no inbound + ambiguous──▶ deleted
```

## Entity 3 — TitleCorruptionViolation (FR3, transient)

Returned by the new `deterministic_wikilink_violations(vault_dir, note_rel, body)`,
mirroring `deterministic_credibility_violations`'s `{rule_id, location, message}`
shape.

| Field | Type | Value |
| --- | --- | --- |
| `rule_id` | `str` | `"IX-wikilink-title-corruption"` (**LOCKED, analyze A1** — `IX-` prefix mirrors the Principle-IX credibility-rule twin; not the bare form) |
| `location` | `str` | note path + the offending first `[[...]]` token |
| `message` | `str` | e.g. `"first body wikilink [[cache-aside pattern]] renames this note's own title 'CAP Theorem' (acronym CAP)"` |

**Predicate (deterministic, D2):** let `A = _derive_acronym(title)`,
`self_stem = stem(title)`. FAIL iff the **first** `[[...]]` token `T` in the body
(outside code fences) satisfies `_derive_acronym_or_upper(T) == A` AND
`AcronymMap.mapping.get(A, T_stem) != self_stem`. Any shape violation ⇒ verdict
`"rejected"` (binary verifier — no WARN tier in `pipeline/verifier.py`).

## Entity 4 — SweepActionRecord (FR4/FR5, transient/`--json`)

The sweep's report row (printed in dry-run, emitted in `--json`, applied under
`--fix`).

| Field | Type | Notes |
| --- | --- | --- |
| `path` | `str` | affected note/stub |
| `action` | `enum` | `repoint_stub` \| `delete_stub` \| `plaintext_body_link` \| `noop` |
| `acronym` | `str` | the acronym involved |
| `from` / `to` | `str` | old → new target (or `"<plain text>"`) |
| `reason` | `str` | `"became ambiguous"` / `"orphan, no valid expansion"` / `"single valid expansion"` |

## Validation rules

- **FR1** — an acronym in `ambiguous` MUST NOT appear in `mapping`, MUST NOT get a
  stub, MUST NOT rewrite any body `[[...]]`.
- **FR2** — `_rewrite_acronym_body` MUST NOT rewrite a token whose acronym is the
  containing note's own title-acronym to a non-self stem.
- **FR3** — the predicate MUST be deterministic and MUST NOT fire on a legitimate
  first link to a *different* concept (only own-title-acronym rewrites).
- **FR4** — the sweep MUST be idempotent (a second `--fix` run produces zero actions).

## Migration

None at the data layer. The sweep (FR4) is the migration for existing corrupted
vaults; it is manual and idempotent. No `_pipeline/` artifact added; alias-stub
frontmatter unchanged.
