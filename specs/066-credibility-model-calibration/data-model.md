# Phase 1 Data Model: Credibility-model calibration (spec 066)

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Research**: [research.md](./research.md) | **Date**: 2026-06-15

No new credibility **enum** (066 reuses spec-055 `Level`:
`primary > corroborated > commentary > unvetted`). One new shipped data file,
one new `settings.yaml` section, one in-memory resolved-catalog object, and a
re-grade result record. No `schema_version` bump anywhere (additive only).

---

## Entity 1 — Catalog entry (default catalog + override share this shape)

The default catalog (`data/credibility_catalog.yaml`, D4) and the FR3 vault
override (`settings.yaml::credibility.trusted_domains`, D3) parse into the **same
entry shape** so Q11 "override fully replaces default" is a dict-merge on
identical keys.

```yaml
# entry (YAML, both surfaces)
- domain: "github.com"      # host pattern (see match_type)
  tier: tier_2              # tier_1 | tier_2 | tier_3  (operator-facing alias, D0)
  match_type: host_path     # exact | host_suffix | host_path   (default: exact)
  min_segments: 2           # host_path only: required path segments (default 2)
  notes: "OSS hosting — org-scoped, not blanket github.com/"   # free text, optional
```

| field | type | required | notes |
| --- | --- | --- | --- |
| `domain` | str | yes | the pattern. For `host_suffix`, written as `*.dev` (matched as `host.endswith('.dev')`). |
| `tier` | enum | yes | `tier_1`/`tier_2`/`tier_3`. Override entries: any tier. Default-catalog wildcards: **`tier_3` only** (Q6 — validated at load; a wildcard at tier_1/2 is a catalog authoring error → load-time WARN + dropped). |
| `match_type` | enum | no (def `exact`) | `exact` (host equality), `host_suffix` (wildcard), `host_path` (host + ≥`min_segments` path parts). |
| `min_segments` | int | no (def `2`) | `host_path` only. |
| `notes` | str | no | operator/maintainer annotation; never read by the resolver. |

**Tier → `Level` mapping (D0)** — applied at load, internal representation is the
055 `Level`:

| `tier` | `Level` |
| --- | --- |
| `tier_1` | `Level.PRIMARY` |
| `tier_2` | `Level.CORROBORATED` |
| `tier_3` | `Level.COMMENTARY` |

**Match precedence within a single lookup** (deterministic): `exact` host →
`host_path` (host match + segment count) → `host_suffix` (longest matching
suffix wins). The override table is consulted before the default table (D1
step 3 before step 4); first hit wins overall.

---

## Entity 2 — `settings.yaml::credibility:` section (FR3, additive)

```yaml
credibility:
  unknown_domain_policy: warn          # warn (default) | reject   (Q10/FR2)
  trusted_domains:                     # list[Entity 1]  (Q2/Q11)
    - domain: "internal.companyhost.com"
      tier: tier_1
      notes: "Internal Confluence wiki"
```

| key | type | default | notes |
| --- | --- | --- | --- |
| `unknown_domain_policy` | enum | `warn` | `warn` ⇒ catalog-miss well-formed URL → `IX-credibility-unresolved` is **WARN** (FR2). `reject` ⇒ restores pre-066 **FAIL** (Q10). Catalog-hit URLs are unaffected either way. |
| `trusted_domains` | list[Entity 1] | `[]` | augments+replaces the default catalog (Q11 full-override). |

Surfaced on the typed loader as `Settings.credibility` (new accessor in
`pipeline/settings.py`); absent section ⇒ `unknown_domain_policy=warn`,
`trusted_domains=[]` (i.e. pure default-catalog behaviour). **No
`schema_version` change** — the loader tolerates the section's absence on every
existing vault.

---

## Entity 3 — Resolved catalog (in-memory, built once, cached)

```python
@dataclass(frozen=True)
class ResolvedCatalog:
    exact: dict[str, Level]                       # host -> level
    suffix: tuple[tuple[str, Level], ...]         # (".dev", COMMENTARY), longest-first
    host_path: tuple[tuple[str, int, Level], ...] # (host, min_segments, level)
    unknown_domain_policy: str                    # "warn" | "reject"

    def lookup(self, url: str) -> Level | None: ...   # None ⇒ ungraded
```

Construction = `load_default_catalog()` (parse the shipped YAML, map tiers to
`Level`, validate wildcard-tier_3-only) **overlaid by** the vault override
(`Settings.credibility`): an override entry for host `H` removes every default
entry that resolves `H` and inserts the override's (Q11). Cached per
`(vault_dir, settings-mtime)` so repeated verifier/re-grade calls don't re-parse.

`lookup(url)`:
1. extract `host = urlparse(url).netloc.lower()` minus `:port`.
2. if `host` not well-formed (no dot) ⇒ return `None` *and* the caller treats it
   as the existing **malformed** class (D2) — distinct from `ungraded`.
3. `exact[host]` → `host_path` (host match + `len(path_segments) >= min)` →
   `suffix` (longest `host.endswith(sfx)`); first hit returns its `Level`.
4. no hit ⇒ `None` (⇒ `ungraded`; FAIL only if `unknown_domain_policy=reject`).

This object is the new **step 3+4** input to
`vault/credibility.py::_lookup_default` (research D1).

---

## Entity 4 — Re-grade result record (FR4, in-memory + cycle-log line)

Produced by `cli/regrade.py` per quarantined note; not persisted as its own
schema — summarised to stdout (D6) and reflected on disk by the file move +
frontmatter restamp + the auto-commit.

```python
@dataclass
class RegradeOutcome:
    note: str                 # quarantine-relative filename
    action: str               # "reinstated" | "still_quarantined" | "skipped_non_credibility"
    destination: str | None   # data_vault/<NN - Cat>/<stem>.md  (reinstated only)
    catalog_basis: str | None # "tier_2 via fastify.dev"         (reinstated only)
    remaining: list[str]      # current verifier_notes           (still_quarantined only)
```

| `action` | meaning (research D5) |
| --- | --- |
| `reinstated` | rejected *only* on credibility AND post-066 check is clean ⇒ moved to `data_vault/`, `verifier_status` restamped `verified`, credibility notes dropped. |
| `still_quarantined` | credibility-only rejection that *still* fails (e.g. catalog miss under `unknown_domain_policy: reject`) ⇒ stays; `verifier_notes` refreshed. |
| `skipped_non_credibility` | carried a non-credibility `verifier_note` ⇒ left untouched (re-grade is LLM-free; cannot re-judge agent-semantic rejections). |

**Frontmatter mutation on reinstatement** (atomic, via `pipeline/atomic_write`):
```yaml
# before (in _pipeline/quarantine/Fastify.md)
verifier_status: rejected
verifier_notes: ["citation lacks credibility and no source default applies", ...]
# after  (moved to data_vault/06 - Frameworks/Fastify.md)
verifier_status: verified
# (credibility verifier_notes removed; any non-credibility notes would have blocked reinstatement)
```

**Destination resolution (D7)**: `resolve_category_folder(vault, frontmatter)` —
match `coverage_category` against existing `data_vault/<NN - DisplayName>/`
dirs (∪ spec `coverage_targets` hints), falling back to
`coverage.classify_note_category`. Shared helper extracted at tasks-stage.

---

## Entity 5 — Verifier credibility outcome vocabulary (FR2 — WARN vs FAIL split)

Today `deterministic_credibility_violations` returns only FAIL-shaped
`IX-credibility-*` dicts, and `_merge_verifier_verdict` forces `rejected` on any.
066 splits the unresolved case by severity:

| condition | rule_id | severity | note status impact |
| --- | --- | --- | --- |
| catalog/declaration resolves a level | — | (pass) | none |
| catalog miss, well-formed, policy `warn` | `IX-credibility-unresolved` | **WARN** | **not** rejected (FR2) |
| catalog miss, well-formed, policy `reject` | `IX-credibility-unresolved` | **FAIL** | rejected (Q10) |
| malformed URL (no dot) | `IX-citation-malformed` | FAIL | rejected (existing, unchanged) |
| bad enum / non-bool coi | `IX-credibility-malformed` | FAIL | rejected (existing, unchanged) |

A violation dict gains an optional `"severity": "warn" | "fail"` (default `fail`
for back-compat). `_merge_verifier_verdict` only forces `rejected` on
`severity == "fail"` violations; `warn` ones are attached to the verdict /
stamped as advisory `verifier_notes` without flipping status. This is the single
behavioural seam that stops the rc7 100%-reject.

---

## Migration / compatibility

- **No `schema_version` bump**: the `credibility:` settings section, the catalog
  YAML, the `severity` violation field, and `Level` reuse are all additive.
- **Existing vaults pre-066**: with no `credibility:` section, behaviour is
  default-catalog + `warn` — i.e. the rc7 symptom is fixed for *every* vault on
  upgrade with no operator action. A vault wanting the old strict behaviour adds
  `credibility.unknown_domain_policy: reject`.
- **Quarantined notes from pre-066 runs**: cleared by `./vault re-grade`
  (manual, Q12), idempotent (Entity 4); a clean vault ⇒ no-op, no commit.
- **`data/credibility_catalog.yaml`** must be added to the wheel force-include +
  bundle copy (D4) or installed vaults won't find it; the loader fails closed
  (empty catalog ⇒ everything `ungraded`/WARN, never a crash).
