# Phase 0 Research: Credibility-model calibration (spec 066)

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-06-15

Phase-0 inputs read: the rc7 reference-vault (`~/Documents/reference-vault-rc7/`) actual
citation log + quarantine state; spec 055 (`vault/credibility.py` +
`credibility-model.contract.md`); spec 062 (`pipeline/orchestrator.py`
quarantine seam + `data-model.md`); spec 063 (`cli/acceptance.py`
`build_citation_grading` / `credibility_ungraded` counter); the CLI topology
(`cli/_parser.py`) + `./vault` shim (`templates/vault-script.sh.j2`).

The clarifications (Q1–Q12) lock the *shape*. Phase-0 resolves the seven
implementation unknowns the spec deferred (`§Deferred to /speckit.plan`), plus
two **corrections** the live rc7 inspection forced (D5, D7).

---

## D0 — The terminology gap the spec left implicit (tier_N ↔ 055 enum)

**Finding.** Spec 066 talks about a domain **catalog** that grades URLs into
`tier_1 / tier_2 / tier_3` (FR1, FR3 schema). Spec 055 — the model 066
calibrates — has **no domain catalog and no `tier_N` vocabulary**. Its
credibility datum is a 4-value ordinal enum declared *per citation*:
`primary(3) > corroborated(2) > commentary(1) > unvetted(0)`
(`vault/credibility.py::Level`). The rc7 rejections happened because the
citations are **plain-string** `source_urls` (e.g. `https://fastify.dev/`) that
carry no inline `credibility`, and no `data_sources[].default_credibility`
covered them → `effective_level` raised `CredibilityUnresolved` →
`IX-credibility-unresolved` FAIL on every note.

**Decision (D0).** The catalog is a **new resolution layer that supplies a
domain-default credibility level** — it slots into the *exact* gap that raised
`CredibilityUnresolved`. The operator-facing `tier_N` vocabulary maps onto the
existing 055 enum (no second scale at gate time → determinism preserved,
Principle IV):

| catalog tier | 055 `Level` | meaning (Q6) |
| --- | --- | --- |
| `tier_1` | `primary` | authoritative origin / first-party docs / standards bodies |
| `tier_2` | `corroborated` | reputable secondary: project sites, OSS hosting, known authors |
| `tier_3` | `commentary` | likely-credible-but-not-authoritative floor (wildcards) |
| *(none)* | `unvetted` | **never assigned by the catalog** — stays the COI/off-field floor |

**Why this mapping.** Q6 itself frames tier_3 as
"likely-credible-but-not-authoritative" (= `commentary`, rank 1), tier_1 as
"authoritative" (= `primary`, rank 3), tier_2 as "reputable secondary / project
sites / known authors" (= `corroborated`, rank 2). The catalog never emits
`unvetted` — that rank is reserved for explicit author declarations and for the
COI-cap / off-field-downgrade results, which still run *on top of* a
catalog-supplied level (a `tier_1`=`primary` catalog hit that is also COI-tagged
on the citation still caps to `commentary`). This keeps 066 a pure
*input-supplier* to the 055 resolution function — it changes **where a level can
come from**, not **how levels combine**.

> ⚠️ **Flagged for the operator at `/speckit.tasks`.** The spec text says
> entries carry a tier "per spec 055's existing tiering"; since 055 has no
> `tier_N`, the mapping above is the plan's interpretation. It is the only
> mapping consistent with Q6's prose. If the operator wants the catalog to speak
> the 055 enum *directly* (drop `tier_N`, write `primary`/`corroborated`/
> `commentary` in the YAML), that is a one-line schema swap — but it would make
> the FR3 override schema (which the spec wrote in `tier_N`) inconsistent. The
> plan keeps `tier_N` as the operator-facing alias and maps internally.

---

## D1 — Resolution order (where the catalog slots in)

**Decision.** Extend `vault/credibility.py::effective_level` (via
`_lookup_default`) with two new fallback steps, strictly ordered. The first two
steps are **unchanged spec-055 behaviour**; steps 3–4 are new; step 5 is the
FR2 fail-open:

```
1. citation explicit `credibility`            (055 §2a — unchanged, strongest)
2. owning source `default_credibility`        (055 §2b — unchanged)
3. vault override trusted_domains[host]        (NEW — FR3/Q11; wins over step 4)
4. default catalog[host]                       (NEW — FR1; exact tier_1/2 → wildcard tier_3)
5. neither resolves:
     • well-formed URL  → `ungraded` ⇒ IX-credibility-unresolved is WARN  (FR2/Q1)
       (unless settings.credibility.unknown_domain_policy == "reject" ⇒ FAIL — Q10)
     • malformed URL    → IX-citation-malformed FAIL (existing, unchanged)
```

**Q11 "full override" falls out of the ordering for free.** Because the vault
override (step 3) is consulted *before* the default catalog (step 4) and the
first hit wins, a domain listed in `trusted_domains` *silently replaces* the
default-catalog entry at any tier, with no warning — exactly Q11. No
"downgrade-reason" bookkeeping needed.

**Precedence of catalog vs source default (step 2 vs 3/4).** The per-source
`default_credibility` (declared in `research.spec.md::data_sources`) stays
*stronger* than the domain catalog. Rationale: a source default is a specific,
already-shipped operator declaration bound to a declared source; the catalog
(default + override) is the *fallback layer* 066 adds for the long tail of
canonical domains nobody declared. The spec frames the catalog as used "only
when the vault has nothing to say" — a declared source default *is* the vault
saying something. (Flagged: if the operator wants the vault override to outrank
even source defaults, swap steps 2↔3 — but that would let `credibility.yaml`
silently override `research.spec.md`, which the spec's "spec is user-owned"
guardrail discourages.)

**COI / off-field still apply.** Steps 3–4 only supply the *declared* input to
the existing `effective_level` pipeline; `min_rank(declared, COMMENTARY)` for
COI and `downgrade_one_step` for off-field run unchanged afterward.

---

## D2 — Well-formed vs malformed URL (FR2 boundary)

**Decision.** A citation URL is **well-formed** (⇒ eligible for `ungraded`) when
`urlparse(url)` gives `scheme ∈ {http, https}` **and** the host (`netloc` minus
any `:port`) contains **≥ 1 dot**. Reuse the host extraction `acceptance.py`
already uses (`urlparse(url).netloc.lower()`).

Validated against the real rc7 host set (the messy tail matters):

| rc7 host | classification | grade |
| --- | --- | --- |
| `fastify.dev`, `en.wikipedia.org`, `docs.aws.amazon.com` | catalog hit | tiered |
| `kubernetes.default.svc` | well-formed (has dots), catalog miss | `ungraded` (WARN) |
| `prometheus:9090` | host `prometheus` has **no dot** | malformed (FAIL, unchanged) |
| `<domain>` | placeholder, no dot | malformed (FAIL, unchanged) |

This means the rc7 "internal/placeholder" citations (`prometheus:9090`,
`<domain>`) keep FAILing on the *existing* malformedness rule — correct, those
are genuinely bad citations — while the long tail of real-but-uncatalogued
public hosts degrades to a non-blocking WARN.

---

## D3 — Override surface: `settings.yaml::credibility:` (not a new file)

**Decision.** Ship the override as a **`credibility:` section inside the
existing `settings.yaml`**, not a standalone `<vault>/credibility.yaml`.

```yaml
# settings.yaml
credibility:
  unknown_domain_policy: warn        # warn (default) | reject (strict — Q10)
  trusted_domains:
    - domain: "internal.companyhost.com"
      tier: tier_1
    - domain: "someacquaintance.substack.com"
      tier: tier_3
      notes: "Senior architect; opinion not specs"
```

**Why settings.yaml over a new file.**
- The verifier already loads settings on the credibility path
  (`pipeline/settings.py::load_vault_settings`, called from
  `verifier.run_verifier_stage`) — zero new I/O path, zero new scaffold step in
  `install.sh`, zero new bundle-copy entry.
- `settings.yaml` is *already* the canonical typed per-vault config surface
  (spec 025 B7). A second config file is discovery cost + drift risk.
- The typed loader gets one new accessor (`Settings.credibility`); the catalog
  loader and the override loader then share one YAML schema (D4).

**Rejected:** `<vault>/credibility.yaml`. Better for a *very* long domain list
(keeps settings.yaml lean) but the realistic override is < ~20 domains, and the
proliferation/discovery cost outweighs the lean-file benefit. (If a vault ever
needs hundreds of trusted domains, a future `credibility.yaml: <path>` pointer
key under the section is a clean escape hatch — not built now.)

---

## D4 — Catalog data format: shipped YAML data file

**Decision.** The framework default catalog lives in a **YAML data file**
shipped in the package: `src/research_framework/data/credibility_catalog.yaml`,
loaded once and cached. **Not** a Python dict literal in `vault/credibility.py`.

**Why.**
- ~50–80 entries is *data*, not logic. A YAML file is operator-inspectable
  (Q3: "catalog grows via PR to the framework" — a YAML diff is the cleanest PR).
- The default catalog and the FR3 vault override then **share one entry schema +
  one loader/normaliser** (`{domain/pattern, tier, match_type}`), so the
  override-fully-replaces-default semantics (Q11) is a dict-merge on identical
  shapes.
- No new runtime dep — `pyyaml ≥ 6.0` is already required (Principle V intact).

**Packaging.** Add `credibility_catalog.yaml` to the wheel force-include +
bundle copy list, alongside the precedent set for `settings.*.yaml` (CLAUDE.md
spec-064 note: "wheel force-include + bundle copy list for `settings.*.yaml`").

**Rejected:** Python dict in `vault/credibility.py` — typing-safe but a wall of
literals, awkward to diff/review, and forces a code change (not a data change)
for every catalog growth.

---

## D5 — `./vault re-grade` reads in-note frontmatter (NOT `.failure.json`) — correction

**Finding (correction to FR4 wording).** FR4 says re-grade reads
`_pipeline/quarantine/<note>.failure.json`. **That artifact does not exist.**
The live rc7 quarantine (`~/Documents/reference-vault-rc7/_pipeline/quarantine/`) and
the spec-062 quarantine seam (`orchestrator._quarantine_rejected_notes`) store
the verdict **in the note's own frontmatter**:

```yaml
# _pipeline/quarantine/Fastify.md  (verbatim from rc7)
verifier_notes:
- citation lacks credibility and no source default applies
- citation lacks credibility and no source default applies
- citation lacks credibility and no source default applies
verifier_status: rejected
```

**Decision.** Re-grade reads `verifier_status` + `verifier_notes` from each
quarantined note's frontmatter. No sidecar JSON is read or written. The spec's
`.failure.json` reference is superseded by this Phase-0 finding (the spec's
own `§Deferred to /speckit.plan` authorises plan-stage to pick the artifact
shape; the actual spec-062 shape wins).

**Reinstatement criterion (deterministic, zero-LLM — Q4/Q8).** A quarantined
note is reinstated **iff both**:
1. **Every** recorded `verifier_note` is credibility-class (maps to an
   `IX-credibility-*` rule) — i.e. the note was rejected *only* on credibility,
   not on an agent-semantic violation that re-grade cannot re-judge without an
   LLM (FR4: "does NOT trigger any LLM calls"). A note carrying a
   non-credibility rejection stays quarantined.
2. Re-running the **post-066** deterministic credibility check
   (`deterministic_credibility_violations`, now backed by the grown catalog +
   override + warn-default) returns **zero** `IX-credibility-*` violations.

On reinstatement: restamp `verifier_status: verified`, drop the credibility
`verifier_notes`, move the file out of quarantine (D7), record in the cycle log.
Notes that still fail (or had non-credibility rejections) stay in quarantine;
their `verifier_notes` are refreshed to the current verdict.

---

## D6 — `./vault re-grade` UX (flags + output) + CLI wiring

**Decision.** New CLI module `cli/regrade.py` + subparser `re-grade`, registered
in `cli/_parser.py` exactly like `acceptance` (`--vault` required), and one new
`case` in `templates/vault-script.sh.j2` mirroring the `acceptance)` branch:

```bash
  re-grade)
    exec "${VENV_PYTHON}" -m research_framework.cli re-grade --vault "${VAULT_DIR}" "$@"
    ;;
```

Flags (the spec deferred these):

| flag | behaviour |
| --- | --- |
| `--vault PATH` | required (matches every other verb). |
| `--dry-run` | report what *would* be reinstated; touch nothing, no commit. |
| `--note PATH` | re-grade a single quarantined note (repeatable). Default: all. |
| `--json` | machine-readable summary (matches `acceptance`/`status`/`digest`). |

**Output** (table by default, JSON with `--json`):

```
Re-grade — reference-vault-rc7
  reinstated: 9   still-quarantined: 3   skipped (non-credibility): 0
  Fastify.md            → data_vault/06 - Frameworks/Fastify.md   (tier_2 via fastify.dev)
  Express.js.md         → data_vault/06 - Frameworks/Express.js.md (tier_2 via expressjs.com)
  Backtracking Algorithm.md  ⊘ still-quarantined (cp-algorithms.com ungraded; reject policy)
Committed regrade(2026-06-15): 9 notes reinstated  (abc1234)
```

**Commit (Q9).** Single `regrade(<YYYY-MM-DD>): N notes reinstated` commit via
the existing `pipeline.vault_commit` surface (the shim's `_vault_autocommit`
already wraps it for non-cycle verbs). `N == 0` ⇒ no commit, no empty-commit.
`--dry-run` ⇒ never commits. This matches the spec-050 invariant + the spec-062
quarantine-move atomicity (the rc7 GA-003 class of bug: never leave the move
uncommitted in the working tree — re-grade's move + restamp + commit are one
operation).

**Manual-only (Q12).** No lifecycle hook. `re-grade` is invoked from the shell;
nothing calls it on `update`/cycle/upgrade.

---

## D7 — re-grade destination (quarantine flattens the category path) — correction

**Finding.** `_quarantine_rejected_notes` moves
`data_vault/<NN - Category>/<stem>.md` → `_pipeline/quarantine/<stem>.md`,
**flattening** the path. The original folder is *not* recorded. So re-grade must
**re-derive** the destination `data_vault/<NN - Category>/`.

**Decision.** Resolve the destination folder from the note's `coverage_category`
frontmatter using the **existing category→folder convention**, reusing the logic
already in the codebase rather than inventing a new map:
- `pipeline/coverage.py::classify_note_category` — explicit `coverage_category`
  match → keyword overlap → largest-gap fallback (never silently drops a note).
- `quality/metrics/coverage.py::_count_notes_per_category_on_disk` — the
  `note_type → "NN - <Plural>"` suffix-match against existing `data_vault/`
  subdirs (e.g. rc7 `coverage_category: frameworks` → `data_vault/06 - Frameworks/`).

Concretely: re-grade matches `coverage_category` against the existing
`data_vault/<NN - DisplayName>/` folders (case-insensitive), ∪ the spec
`coverage_targets[].folder`/`note_type` hints; if unresolved, fall back to the
note's category-by-keyword (step-2/3 of `classify_note_category`). A shared
`resolve_category_folder(vault, frontmatter)` helper is extracted at
`/speckit.tasks` so both the metric and re-grade derive it identically (mirrors
the spec-053 `derive_trunk_dict` shared-helper pattern).

---

## D8 — Acceptance scorecard `credibility ungraded` counter (consideration, kept out of locked scope)

**Finding.** `cli/acceptance.py::build_citation_grading` currently counts
`credibility_ungraded` as "citations whose entry has no inline `credibility`
field" (`citation_credibility(entry) is None`). After 066 that over-counts:
*every* plain-string citation (the overwhelming majority — see rc7) counts as
ungraded even when the catalog cleanly grades its host. The spec's cross-ref
says "no scorecard change needed".

**Decision.** Keep the spec's stance — **no change in 066's locked scope** — but
note the refinement for the operator: to make the FR2 "ungraded = domains I
should review" signal *accurate*, the counter should count citations whose
**effective level is catalog-unresolved** (the true FR2 `ungraded` set), not
"lacks an inline field". This is a ~5-line change to `build_citation_grading`
(call the resolver, count the `ungraded` outcomes). Flagged as an **optional
in-scope refinement** to confirm at `/speckit.tasks`; if the operator wants the
scorecard signal to be meaningful day-one, fold it in; otherwise it ships as a
fast-follow. It does **not** gate the rc8 bug fix.

---

## Finalised FR1 default catalog (the seed list, now concrete)

Derived directly from the rc7 citation log (`~/Documents/reference-vault-rc7/`,
`data_vault/` ∪ `_pipeline/quarantine/`), applying the Q6 hybrid rule
(wildcards → tier_3 only; exact-match → tier_1/tier_2). **~12 wildcards +
~55 exact-match ≈ 67 entries** — within the FR1 ~50–80 target.

### Wildcards — `tier_3` (`commentary`) — "anyone can register / host here"
| pattern | match_type | rationale |
| --- | --- | --- |
| `*.dev` | host_suffix | freely-registrable project TLD (fastify.dev floor; promoted to tier_2 by exact entry) |
| `*.io` | host_suffix | freely-registrable (redis.io, duckdb.org-style) |
| `*.github.io` | host_suffix | GitHub Pages — any user (argoproj/netflix/google/llimllib in rc7) |
| `*.readthedocs.io` | host_suffix | community-hosted docs (argo-cd.readthedocs.io) |
| `*.readme.io` | host_suffix | hosted docs (resilience4j.readme.io) |
| `*.substack.com` | host_suffix | any author |
| `*.medium.com` | host_suffix | any author |
| `*.wordpress.com` / `*.blogspot.com` | host_suffix | any author |
| `*.apache.org` | host_suffix | OSS foundation subprojects (spark/flink/kafka/… ~15 in rc7); promote specific ones via PR |
| `*.edu` | host_suffix | academic (cs.utexas.edu, cs.cornell.edu, opendsa.cs.vt.edu) |
| `*.gnu.org` | host_suffix | GNU project sites (gcc.gnu.org) |

### Exact-match `tier_1` (`primary`) — authoritative origin / first-party / standards
- **Encyclopedic/reference**: `wikipedia.org`, `en.wikipedia.org` (+ lang
  subdomains via a `*.wikipedia.org` exact-family entry), `developer.mozilla.org`,
  `archive.org`.
- **Standards bodies**: `www.w3.org`, `datatracker.ietf.org`, `www.ietf.org`,
  `www.oasis-open.org`, `www.openapis.org`, `www.ecma-international.org`,
  `www.iso.org`.
- **First-party vendor docs**: `docs.aws.amazon.com`, `aws.amazon.com`,
  `cloud.google.com`, `learn.microsoft.com`, `docs.microsoft.com`,
  `www.microsoft.com`, `docs.oracle.com`, `docs.python.org`, `docs.rs`,
  `pkg.go.dev`, `docs.docker.com`, `docs.github.com`, `kotlinlang.org`,
  `docs.spring.io`, `docs.djangoproject.com`, `www.djangoproject.com`,
  `sre.google`, `opentelemetry.io`.

### Exact-match `tier_2` (`corroborated`) — reputable secondary / project / authors
- **OSS hosting (host + ≥2 path segments — the "org-scoped, not blanket" rule)**:
  `github.com`, `gitlab.com`, `sourceforge.net`, `bitbucket.org`.
- **Well-known project sites**: `fastify.dev`, `expressjs.com`, `vitejs.dev`,
  `nextjs.org`, `redis.io`, `clickhouse.com`, `duckdb.org`, `delta.io`,
  `docs.delta.io`, `swagger.io`, `pact.io`, `jepsen.io`, `axios-http.com`,
  `principlesofchaos.org`, `www.rabbitmq.com`, `www.postgresql.org`,
  `www.elastic.co`, `www.databricks.com`, `www.fluentd.org`, `docs.fluentd.org`,
  `www.asyncapi.com`, `refactoring.guru`, `cp-algorithms.com`, `launchdarkly.com`.
- **Well-known tech authors**: `martinfowler.com`, `martin.kleppmann.com`,
  `kleppmann.com`, `samnewman.io`, `www.allthingsdistributed.com`,
  `tom-e-white.com`, `www.domainlanguage.com`.

(The exact set is the data file's initial contents; growth is a YAML PR per Q3.
The host+path-segments rule for OSS-hosting entries is modelled in
data-model.md Entity 1's `match_type: host_path` with `min_segments: 2`.)

---

## Summary of decisions

| # | Decision |
| --- | --- |
| D0 | `tier_1/2/3` is the operator-facing alias → maps to 055 `primary/corroborated/commentary`; `unvetted` never catalog-assigned. **Flagged.** |
| D1 | Catalog slots as fallback steps 3 (override) + 4 (default) in `effective_level`, below explicit + source-default, above ungraded/reject. Q11 full-override = order-wins-for-free. |
| D2 | Well-formed = http(s) + host has ≥1 dot; else existing malformed FAIL. Validated on rc7's messy tail. |
| D3 | Override = `settings.yaml::credibility:` section (not a new file). |
| D4 | Default catalog = shipped `data/credibility_catalog.yaml`; shared schema+loader with the override; wheel+bundle include. |
| D5 | **Correction:** re-grade reads in-note `verifier_status`/`verifier_notes` (no `.failure.json`); reinstate iff credibility-only rejection AND now-clean. |
| D6 | `cli/regrade.py` + `re-grade` subparser + shim case; flags `--vault/--dry-run/--note/--json`; auto-commit `regrade(<date>): N`; manual-only. |
| D7 | **Correction:** quarantine flattens the path; re-grade re-derives `data_vault/<NN - Cat>/` from `coverage_category` via the existing category→folder convention (shared helper). |
| D8 | Scorecard `credibility ungraded` counter refinement noted as **optional**, kept out of locked scope per the spec's "no scorecard change needed". |
