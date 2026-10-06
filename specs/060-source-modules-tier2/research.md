# Research & Decisions: Source-Module Tier 2+ Port Wave (Spec 060)

**Date**: 2026-06-03 · **Stage**: post-clarify (Q1–Q5), pre-implement
**Context**: Governance umbrella after Wave-2 Tier-1 ports (0.6.0). Governs ROADMAP ladder;
does not re-spec 020.

## Decisions

### D1 — Prioritization rubric (Q1)

Four criteria, fixed weights (sum 100%):

| Criterion | Weight | Scoring guide |
|-----------|--------|---------------|
| Real vault demand | **40%** | 3 = explicit Milestone A/B/C or feeds-vault/codebase-vault signal; 2 = roadmap intent; 1 = speculative |
| 020 contract fit | **25%** | 3 = reuses shipped Tier-1 pattern (RSS/HTTP/subprocess JSON); 2 = minor manifest mapping; 1 = needs 020 amendment |
| Porting effort | **20%** | 3 = ≤2 days stdlib; 2 = 3–5 days; 1 = >5 days or unclear upstream |
| Dependency cost | **15%** | 3 = stdlib-only; 2 = optional-extra plausible; 1 = hard dep or auth wall |

**Re-rank rule**: multiply scores × weights, sort desc; ties break on higher demand then
lower effort. Re-running the rubric may reorder the ladder but **must not** change the
acceptance bar.

### D2 — Locked Tier-2 ranking (Q1)

| Rank | Module | Weighted rationale (one line) |
|------|--------|-------------------------------|
| 1 | **hackernews** | High feeds-vault demand; Algolia/RSS-style fetch fits reddit/rss precedent; stdlib; ~2d effort |
| 2 | **wikipedia** | High demand; stable MediaWiki API; stdlib `urllib`; no new deps |
| 3 | **newsletters** | Medium demand; format fragmentation; moderate effort |
| 4 | **blog_posts** | Medium demand; scraping variance; harder hermetic fixtures |
| 5 | **conference_talks** | Overlaps youtube metadata patterns; lower marginal coverage |
| 6 | **github_extras** | Useful but auth + API surface; oreilly-style gate; dep cost = 1 |

**Batch-1 kickoff**: rank **#1 `hackernews` only**. Rank **#2 `wikipedia`** starts after
one Tier-2 port ships green against the acceptance contract (validates the bar, not a new
speckit spec).

### D3 — Dependency-exception policy (Q2)

| Tier | Default | Exception path |
|------|---------|----------------|
| **Tier 2** | **Stdlib-only; no exceptions** | If a dep is unavoidable → **defer** module (do not ship) |
| **Tier 3+** | **Defer** until stdlib path exists | Optional-extra via **020-amendment gate** (see contract): named extra `research-framework[modules-<name>]`, `pyproject.toml` change, maintainer approval, port PR documents Principle V exception |
| **Core runtime** | **Forbidden** | Never add unconditional deps to `[project].dependencies` |

Precedent: `[budget]` → `tiktoken`, `[reports]` → `fpdf2` — opt-in extras only.

**Tier-3 modules likely needing extras** (defer until gate approves):

| Module | Likely extra | Default action |
|--------|--------------|----------------|
| pdfs | `[modules-pdf]` (parser TBD) | defer |
| epub | `[modules-epub]` | defer |
| podcasts | feed fetch stdlib possible; transcribe may need extra | defer transcribe path |
| twitter / mastodon | API client may tempt dep | prefer stdlib HTTP + defer if not hermetic |

### D4 — Umbrella scope boundary (Q3)

060 delivers: rubric, acceptance contract, amendment gate, ladder contract, kickoff port.
060 does **not** deliver: per-module `specs/NNN-*/` trees, tasks per module, or 020 schema
changes (those flow through FR-003 gate into spec 020).

### D5 — Tier 4 / Parked (Q4)

Listed on `tier-ladder.contract.md` with status `future` or `parked`. **No active port
tasks** in 060. Un-parking requires the same amendment gate if 020 contracts don't fit.

### D6 — Spec 038 sequencing (Q5)

| Spec | Owns |
|------|------|
| **060** | Which module, when, pass/fail acceptance bar, ladder truth |
| **038** | Resilience polish: EMPTY≠FAILED, rate limits, raw capture, install probes |

038 is **not** in the 060 acceptance checklist. Schedule 038 `/speckit.clarify` after the
first Tier-2 port validates 060 end-to-end (hackernews ship). Ports may cherry-pick 038
patterns early (e.g. auth probe shape) but cannot ship without passing the **060** bar.

## Reference — spec-020 five-file template

Shipped precedent (`src/research_framework/modules/youtube/`):

| File | Role |
|------|------|
| `manifest.yaml` | Module metadata; **`preflight` required** (spec 051) |
| `extractor.py` | Subprocess stdin/stdout JSON contract |
| `preflight.py` | Mandatory preflight subprocess |
| `few-shot.md` | Scout/research examples |
| `README.md` | Operator docs |
| `sources.yaml.template` | Per-vault source enumeration template |

Vault copy path: `<vault>/modules/<name>/` (synced from stock on `./vault update`).

## Alternatives rejected

| Alternative | Why rejected |
|-------------|--------------|
| Speckit sub-spec per module | Violates project practice; 020 template is the per-module surface |
| Parallel Tier-2 ports before bar validation | Risks bar drift across ports |
| Fold 038 into 060 acceptance bar | Duplicates 038; blocks ports on unfinished resilience spec |
| Unconditional Tier-3 parser deps | Violates Principle V default |
