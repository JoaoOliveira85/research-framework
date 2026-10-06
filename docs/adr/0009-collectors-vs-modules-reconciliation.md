# ADR 0009 — Reconciling 014/015 Collectors vs 020 Source Modules

**Status**: ACCEPTED 2026-06-01 — option A (020 supersedes 014/015 collectors). The transition criterion ("post first 020 module port + production use") is met: spec 020 shipped (PR #32, 0.4.0), all five Tier-1 modules ported (0.6.0), and the Feeds-Vault revival cycle ran end-to-end (2026-05-30→06-01) on real data. The reconciliation held up in practice; no amendment needed.
**Date**: 2026-05-22 (drafted) · 2026-05-26 (clarified)
**Tags**: pipeline, source-ingestion, design-decision, revival-sprint
**Evidence base**: 2026-05-26 feeds-vault archaeology pass — see `docs/TODO.md` "Archaeology findings 2026-05-26" entry (findings F6 + F11 are the load-bearing evidence).

## Context

The project has accumulated two pipeline mental models that describe how external data enters a vault:

1. **Specs 014 (reusable collectors) + 015 (pipeline consolidation) + 015g (orchestrator command)** —
   describe a *framework-owned* ingest pipeline. Collectors live under
   `research_framework.collectors` (currently `_fetch.py`, `_dedupe.py`,
   `_sources.py`, `_frontmatter.py`, `rss.py`). The 7-phase `pipeline.runner.run`
   orchestrator drives them. Source modules are *first-class framework code*
   shipped with the package.

2. **Spec 020 (source-module architecture / code-bridge)** —
   moves source access into *per-vault modules* under `<vault>/modules/<name>/`.
   Each module is subprocess-isolated, sandbox-friendly, and lives inside the
   VAULT — not the framework. The bridge spawns module-owned extractors via
   stdin/stdout JSON contract.

Both models propose to handle the same Tier 1 source set (`youtube`, `reddit`,
`oreilly`, `arxiv`). Without an explicit decision, the project risks:

- Building the same adapter twice (once as a 014/015 framework collector,
  once as a 020 vault module).
- Confusing contributors about where new sources live.
- Confusing existing-vault operators when a new module ships.
- ROADMAP queue item 3 (spec 020 implementation) and queue item 7
  (Tier 1 source modules) shipping under the wrong contract.

This ADR's job is to **decide which model wins** so subsequent work is
contract-stable.

## Decision

**Option A wins** — 020 source-module architecture supersedes the
014/015 collector lineage. Recorded 2026-05-26 via `/speckit.clarify`;
formal ACCEPTED transition queued until first 020 module ships and
runs against a real vault (see Status above for why).

### Decision summary

- **Architecture**: All new source ingestion ships as 020 modules
  living under `<vault>/modules/<name>/` (copied from the framework's
  `src/research_framework/modules/<name>/` at install per spec 020's
  locked design). The 020 manifest contract + `tiers:` block +
  value-tiered consensus + schema-drift fail-closed are the canonical
  shape for source access.
- **Legacy surface preservation**: The partial in-tree 014/015 code
  (`src/research_framework/collectors/rss.py` + `_fetch.py` + `_dedupe.py`
  + `_frontmatter.py` + `_sources.py`; `pipeline/runner.py`; the
  `migration/superseded_paths.py` map) stays exactly as-is during the
  revival sprint. **No deprecation banner, no scheduled deletion.**
  020 modules supplant the legacy surface *organically* as each Tier-1
  source ports.
- **Transition mechanism**: `./vault refresh-sources` (spec 023
  minimum subset, feeds-vault archaeology F2 + F6) is the user-facing
  verb that invokes legacy collectors during the transition. Vaults
  with a ported 020 module use it; vaults without one fall back to
  the legacy collector unchanged.
- **In-tree spec disposition**: Tombstone-with-banner (the existing
  `specs/_archive/010-flow-separation/` + `specs/_archive/012-multi-vault/` precedent)
  applied to the directly-subsumed drafts ONLY: 014, 015 umbrella,
  015g, 034. Other 015a-e drafts cover orthogonal pipeline-consolidation
  concerns (corpus folder naming, vault inventory, vault onboarding,
  note types, agent templating) and are NOT subsumed by ADR-0009.
  Their disposition belongs to spec 023's flow-separation arc.

### Options considered (preserved for posterity)

The three candidate options the draft ADR weighed:

### Option A — 020 supersedes 014/015 collectors

- All source ingestion lives in `<vault>/modules/<name>/`.
- 014/015 collectors become a *legacy raw-capture layer* preserved for
  back-compat (`pipeline.runner.run`'s `collect` phase invokes existing
  collectors during a transition period).
- New sources ship as 020 modules from day one; existing 014/015 collectors
  get migrated incrementally OR remain as a documented historical layer.
- `pipeline/runner.py` either gets retired (subsumed by 020's bridge) or
  becomes a back-compat shim.

**Pros**: Single mental model; vault-local modules are portable; sandbox-friendly.
**Cons**: Migration work for existing collectors; framework loses a centralized
quality-assurance surface for collectors.

### Option B — 014/015 collectors + 020 modules coexist as distinct layers

- 014/015 collectors handle DETERMINISTIC raw-capture (no LLM in the loop).
- 020 modules handle SIGNAL EXTRACTION (LLM-mediated, consensus-validated).
- `pipeline.runner.run`'s `collect` phase (014/015 collectors) feeds raw data;
  `pipeline.orchestrator.run_cycles`'s scout (020 modules) extracts signals
  from the raw data.
- Two layers, two responsibilities, clearly documented.

**Pros**: Separation of concerns; legacy paths preserved; framework-side
collectors stay quality-assurable.
**Cons**: Two mental models to maintain; risk of duplicate adapter
implementations; harder to onboard new contributors.

### Option C — 020 absorbs the legacy collector responsibilities

- 020 modules expand scope to include deterministic raw-capture.
- 014/015 collectors are retired (deleted or marked superseded).
- `pipeline/runner.py` is retired; the 7-phase flow is reshaped as a 020-driven
  pipeline.
- `pipeline.orchestrator.run_cycles` becomes the canonical workflow entry point.

**Pros**: Cleanest architecture; one mental model; aligns with spec 020's
"domain-agnostic by construction" intent.
**Cons**: Biggest migration; risks breaking the existing 015a-h work; spec 020
needs scope expansion before implementation starts.

## Evidence

The 2026-05-26 feeds-vault archaeology pass produced two load-bearing
findings that turned the decision from "argued from principles" to
"argued from a worked example". From
`docs/TODO.md` "ADR-0009 — option A strongly evidenced" entry:

- **F6 — collector prior art exists**: The feeds-vault has 8 collector
  scripts under `scripts/` (`collect_youtube.py` 468 lines,
  `collect_rss.py` 962 lines, `reddit_rss.py` 697 lines,
  `reddit_scraper.py` 363 lines, `collect_oreilly.py` 430 lines,
  plus 3 processors). Each is a 1-2 file Python script targeting one
  source family with hand-tuned channel lists, retry logic, and
  rate-limiting. These are *exactly* the shape spec 020 is trying to
  standardise — the 020 module is a 1-to-1 mapping per script:
  `collect_youtube.py` → `modules/youtube/` with a `manifest.yaml`
  declaring tier rules and a `signals.json` schema declaring the
  extraction shape.
- **F11 — historical specs confirm shared origin**: The feeds-vault
  contains 16 historical specs under `specs/` including a
  `014-reusable-collectors/` empty directory — placeholder reserved
  when spec 014 was spun out of the vault into the framework. The
  framework's spec 014, 015, and 015g lineage all began in that
  vault. So "014 collectors" and "020 modules" are not two competing
  architectures — they're the same architecture at two different
  maturity stages.

The architectural argument (spec 020's manifest contract is a strict
superset of what the legacy collectors produce) and the migration
path (pin the 020 contract → port one-collector-at-a-time → users
keep working via `./vault refresh-sources` during transition) closed
the case.

## Why option B was rejected

Option B (coexist as distinct layers) would let a vault have BOTH a
framework-owned 014/015 collector AND a vault-local 020 module for
the same source. There's no realistic scenario where that's
desirable — vault authors would have to specify which one to use per
source per vault, doubling the configuration surface for marginal
benefit. **The ambiguity itself is the cost.**

## Why option C was rejected

Option C (020 absorbs collectors immediately, retire 014/015 in this
ADR) is too big a scope for the current sprint. Two reasons:

1. **Codex cap timing**: 2026-06-01 is a hard deadline; option C
   would push the 020 first-port past that window. Option A ships
   the contract first and ports incrementally.
2. **Migration risk**: `pipeline/runner.py` is wired into the CLI
   today (`cli/research_cycles.py` line 30). Deleting it in this ADR
   would break the revival sprint mid-flight. Option A keeps it
   running while 020 modules port.

Option C may be the right *long-term* destination but is wrong as
the *next decision*.

## Consequences

### Effective immediately (no code/CI changes)

1. **Spec 020 implementation** is unblocked. Phase 1 (bridge subsystem
   + manifest contract) + first module port (`collect_youtube.py` →
   `modules/youtube/`) can start without further ADR-level dependency.
2. **Spec 023 minimum subset** (`./vault refresh-sources` verb) gains
   load-bearing status as the transition mechanism — vaults run
   legacy collectors via this verb until a 020 port lands for that
   source.
3. **Spec 034** (runtime consolidation) is explicitly tombstoned as
   subsumed by ADR-0009 + spec 020. Its concerns either fold into
   020 directly or wait until post-revival sequencing.
4. **ROADMAP queue items #0, #3, #7** become unambiguous: #0 is this
   decision, #3 is 020 implementation, #7 is the Tier-1 ports under
   the 020 contract. No queue ambiguity remains.

### In-tree code (deliberately deferred)

5. **`src/research_framework/collectors/*` + `pipeline/runner.py` +
   `migration/superseded_paths.py` stay exactly as-is during the
   revival sprint.** No deprecation banner in docstrings, no
   scheduled deletion. Rationale: keeping the CLI surface stable
   during the sprint matters more than signalling-to-readers that
   the path is legacy. As 020 modules port (youtube first, then
   reddit/rss/oreilly/arxiv), the legacy collector for that source
   becomes dead code naturally and can be deleted in a single
   batched cleanup after the revival sprint completes.
6. **`_SUPERSEDED_BY` map** (`migration/superseded_paths.py`) does
   NOT get an entry added in this ADR. Its purpose is documenting
   vault-local script → framework-module mappings AFTER the
   framework module ships; for now no 020 modules have shipped so
   the map stays unchanged. When the first 020 module lands, that
   spec's PR is the right place to add (`scripts/collect_youtube.py`
   → `research_framework.modules.youtube`) etc.

### In-tree specs (tombstoned now)

7. The following draft specs get a `🗄️ SUBSUMED BY ADR-0009 + spec
   020` banner at the top of each `spec.md`, matching the existing
   `specs/_archive/010-flow-separation/` + `specs/_archive/012-multi-vault/`
   precedent. Content stays readable for historical reference.

   - `specs/_archive/014-reusable-collectors/spec.md` — directly subsumed
     (collector module contract → 020 manifest contract).
   - `specs/_archive/015-pipeline-consolidation/spec.md` — partially
     subsumed (the source-ingestion + orchestrator parts; corpus
     naming + note types + onboarding belong elsewhere). Banner
     clarifies the partial scope.
   - `specs/_archive/015g-pipeline-orchestrator-command/spec.md` — the
     `/pipeline` slash-command + 7-phase orchestrator framing is
     superseded; the canonical entry point becomes `./vault
     refresh-sources` (spec 023) + 020-driven scout.
   - `specs/_archive/034-runtime-consolidation/spec.md` — explicitly downstream
     of this ADR per the original draft (line 90 of the original
     ADR text).

8. **Out of scope for this ADR** (deliberately untouched):

   - `specs/_archive/015a-corpus-folder-name/`, `015b-vault-inventory/`,
     `015c-vault-onboarding/`, `015d-note-types-first-class/`,
     `015e-agent-definitions-as-templates/` — orthogonal pipeline-
     consolidation concerns; their disposition belongs to spec 023
     (flow separation) or future ADRs.
   - `specs/015f-processors-in-framework/`, `015h-retire-vault-local-scripts/`
     — already shipped per `migration/superseded_paths.py` mechanism;
     their status header is stale ("Draft") but fixing that requires
     finding a CHANGELOG entry pinning the ship date, deferred to a
     separate cleanup PR (see `docs/TODO.md` follow-up entry).

### Cross-document follow-ups (this PR)

9. `docs/ROADMAP.md` queue item #0 status: flip from `[?]` to `[~]`
   (decision recorded, formal ACCEPTED pending end of sprint), with
   a cross-reference to this ADR's Decision block.
10. `docs/TODO.md` "ADR-0009 — option A strongly evidenced" entry
    annotated with "DECISION RECORDED 2026-05-26" + cross-reference
    to this ADR. Section is retained for archaeological context.
11. `CLAUDE.md` "Active ADRs" already lists ADR-0009 — no change
    needed there. "Recent Changes" gets a one-line note about the
    clarify session.
12. **Open follow-up** (not blocking this PR): `docs/TODO.md` gets a
    new entry capturing the 015f + 015h doc-drift (Status: Draft
    despite shipped) for a separate cleanup PR.

## Tests

None. This ADR's Decision was organisational — which architecture new source
ingestion uses going forward — and its own Consequences block scoped itself
to "no code/CI changes" at acceptance time. No test asserts that a new source
ships as a 020 module rather than a 014/015 collector, and none checks that
the legacy `collect` phase is actually shrinking as 020 modules port. That gap
is not theoretical: #223 found the weekly pipeline still running the
legacy RSS-only `collect` phase three months after this ADR called it a
transition-period layer to be reshaped around 020 — nothing enforced the
transition because nothing was asked to. Recorded here honestly rather than
retrofitted with a test that would only assert what happens to be true today;
see #278's invariant-to-mechanism table.

## Clarification record

`/speckit.clarify` session held 2026-05-26 (project maintainer +
Claude Opus 4.7). Four questions; answers verbatim:

- **Q1 — Confirm option A?** → **a_option_a**: Confirm option A
  (recommended; pre-made by evidence).
- **Q2 — In-tree code disposition?** → **keep_no_action**: Keep
  collectors + `pipeline/runner.py` as-is, no deprecation banner;
  let 020 supplant them organically as ports land. *(Trade-off
  accepted: no in-code signal that the path is legacy, but
  CLI stability during the revival sprint is more important.)*
- **Q3 — In-tree specs disposition?** → **narrow** (after a
  refinement question): tombstone-with-banner ONLY 014, 015,
  015g, 034. Leave 015a-e alone — they cover orthogonal concerns.
- **Q3b — 015f/015h shipped doc-drift?** → **fix_only_if_quick**:
  Fix only if a CHANGELOG entry pins the ship date; otherwise
  defer. *(No CHANGELOG entry found; deferred to a separate
  cleanup PR.)*
- **Q4 — Status timing?** → **accept_after_revival**: ACCEPTED
  once the entire Feeds-Vault Revival Sprint completes (fully evidenced
  by production use). Decision recorded now; formal ACCEPTED
  transition pending.
