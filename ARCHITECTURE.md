# research-framework — Architecture

> **Document scope**: How the whole system fits together. The constitution
> (`.specify/memory/constitution.md`) is the authoritative source of
> *constraints*; this document is the authoritative source of *structure*.
> When they conflict, the constitution wins.

> **Audience**: Anyone (human or agent) joining the project who needs to
> understand the design before touching code. Read this BEFORE reading any
> spec — specs assume the architecture is understood.

---

## 1. What this is

A Python CLI that takes a `research.spec.md` file as input and produces a
populated, validated, git-initialized **Obsidian-compatible knowledge
vault** as output. The framework drives an autonomous Claude / Codex
research loop over the sources you declare in the spec and writes the
results as interlinked notes.

**research-framework is a factory.** The vault it generates is the product.
The product is only as good as the factory's quality gates.

The same CLI also keeps generated vaults in sync as the framework evolves
(`./vault update`), runs deterministic + LLM-assisted audits, and exposes
a uniform `./vault` script for research / health / audit / query
operations from inside the vault.

### What it is NOT

- **Not a content generator.** It generates vault infrastructure and
  orchestrates research agents. It does not write knowledge content
  itself.
- **Not a documentation tool.** The vault enables decision-making — it is
  not for producing documents, code, or presentations.
- **Not opinionated about domain.** Domain-agnostic by construction (per
  Constitution 1.3.2). A vault may be about microservices, embedded
  firmware, childcare, legal research, or biology literature — the
  framework MUST produce the same quality of work regardless. The spec
  file is the ONLY source of domain knowledge.
- **Not a Phase 2/3 system.** Targets Phase 1 (foundation + population)
  only. FTS5 indexing and vector search are separate concerns.

---

## 2. Constitutional principles (summary)

The full text lives in `.specify/memory/constitution.md`. Treat these as
**inviolable**. Three are marked NON-NEGOTIABLE — they directly address
failure modes that have already occurred and cost us cycles to recover
from.

| # | Principle | Status | Captures |
|---|-----------|--------|----------|
| I | Script-Validated Quality Gates | **NON-NEGOTIABLE** | Agents don't self-validate. Scripts do. `validate_vault.py == 0` is a pass; "the notes look good" is not. |
| II | Phase Sequencing | NON-NEGOTIABLE | Phase 0 → 1 → 2 → 3 strict order. Loop continuation is orchestrator-owned, not agent-owned. |
| III | Test-First (TDD) | **NON-NEGOTIABLE** | Tests written before/alongside every script. `--dry-run` required for every vault-mutating script. F7 cost us 71 damaged files. |
| IV | Agent-Script Separation | Hard | Agents assess; scripts validate. Never conflate. |
| V | Offline-First, No External Persistence | Hard | All vault content is potentially proprietary. No telemetry, no cloud sync, no phone-home dependencies. |
| VI | No Duplicate Notes | Hard | `proposed_filenames` in scout JSON is the coordination mechanism. |
| VII | External Sources Are Mandatory | Hard | A vault without market + domain context is internal documentation. |
| VIII | No Placeholders / Stub-as-Fuel | Hard | Every shipped script is implemented; stub notes are *fuel for the next cycle*, not termination signals. |
| IX | Vault-First Citation | **NON-NEGOTIABLE** | Two-tier rendering: Tier 1 = vault wikilinks, Tier 2 = original source URLs in note frontmatter. Verifier rejects either tier missing. |
| X | (implicit, from 1.3.2) Domain-Agnostic by Construction | Hard | Canonical schemas and structural decisions MUST be derivable from the spec at runtime — never hardcoded in source. Few-shot prompts MAY reference specific tech for illustration; structure MUST NOT. |

**Why these principles exist**: section 5 of the constitution (Failure
Record Reference) lists 8 specific failures that occurred during the
system this framework was built to replace. Every NON-NEGOTIABLE principle
maps to at least one of those failures. Compliance is not aesthetic; it
is operational protection.

---

## 3. Pipeline architecture

### Three deliverable phases

```text
Phase 0 (parse)          → exit on invalid spec
Phase 1 (infrastructure) → pytest must pass before Phase 2
Phase 2 (research)       → cycles until termination + coverage met
Phase 3 (finalization)   → coverage-targets gate must pass first
```

**Strictly sequential** (Principle II). No parallelism between phases.
Within Phase 2, cycles are sequential. Within a cycle, scout and DFS
are sequential. Research agents within a DFS MAY run in parallel only
if their topic lists are non-overlapping.

### Within a cycle (Phase 2)

```text
Cycle N starts
├── Reconcile orphans (orchestrator)            # picks up partial work from any prior crash
├── Topic harvest (if not cycle 1)              # walk vault, find orphan wikilinks, rank by citations
├── Scout / BFS                                 # discover topics + sources
│   └── validate_cycle.py                       # five-dimension coverage gate, source consultation gate, etc.
├── Topic propose (skill)                       # scope-bounded tangent expansion
├── Source pre-flight                           # probe declared sources for reachability
├── (FUTURE — spec 020) Source extraction       # cached signal payloads from each source module
├── DFS / research per topic                    # one note per topic, batched 5-8 at a time
│   ├── note-writer (per batch)
│   ├── verifier (per note) → fail = re-write   # Principle IX gate
│   ├── wikilink case normalization              # auto-fix moved wikilinks (0.2.31, ADR-0005)
│   └── validate_vault.py                       # template compliance, summary length, frontmatter shape
├── End-of-cycle quality report                 # cycle-NNN-quality-report.json
├── End-of-cycle gate suite                     # SG-001..SG-005 / CG-001..CG-006
└── Cycle N ends → orchestrator decides: continue (Principle II loop conditions) or exit
```

The cycle architecture is defined across:

- `src/research_framework/pipeline/cycle_runner.py` — the Python-native cycle
  runner. It replaced a bash `run_cycle.sh` wrapper in spec 004; that
  wrapper kept shipping into generated vaults until it was deleted in #298.
- `src/research_framework/pipeline/orchestrator.py` — multi-cycle
  orchestration + resume logic + budget tracking.

### Loop continuation rules (Principle II)

The orchestrator runs another cycle whenever ANY of these is true:

- Latest scout's `topics_found.new` is non-empty.
- `_pipeline/research-backlog.md` has unresolved entries.
- Any note matches the stub criteria (Principle VIII).

ALL three must be false AND coverage targets must be met for clean
termination. Hitting budget / max-cycles with any of the three still true
is a **constrained exit** — the orchestrator exits with a punch-list so
the user can `--resume`.

---

## 4. Two-layer vault architecture

Every generated vault has exactly two layers:

- **Layer 1 — Query / Routing**: `AGENTS.md`, `_index.md`, `_concepts.md`,
  `_graph.md`. Structured index files agents read first. Simple queries
  may be answered from Layer 1 alone. Rebuilt after research cycles.
- **Layer 2 — Full Vault**: Obsidian-compatible notes with frontmatter,
  wikilinks, citations in `data_vault/` subfolders.

Layer 1 is always a **projection** of Layer 2. They are never
independent.

---

## 5. Five search dimensions

Every BFS scout MUST address all five. Missing a dimension is a scout
failure that `validate_cycle.py` rejects (exit code 2).

| Dimension | What it covers |
|-----------|----------------|
| Technical | Services, APIs, data flows, system architecture |
| Organizational | Teams, capabilities, org structure, decision flow |
| Domain | Industry fundamentals, terminology, concepts |
| Market | Competitors, market context, customer behavior |
| Temporal | Planned changes, migrations, historical decisions |

The Domain and Market dimensions are NOT secondary. A vault without
industry fundamentals and competitive context is incomplete regardless
of how many internal notes it has.

---

## 6. Single LLM dispatch surface

**All LLM calls MUST flow through `src/research_framework/pipeline/agent_call.py`.**
This is load-bearing for:

- **Cost capture** — every call's tokens, latency, model are recorded
  at this single point. A second dispatch surface bifurcates the cost
  story and makes hard budget caps unreachable.
- **Runtime selection** — `runtime: claude | codex | local` from
  `settings.yaml` is resolved here.
- **Tier resolution** (spec 020, D7) — `tier: basic | normal | flagship`
  is resolved against the `settings.yaml::tiers` block here.
- **Per-call audit logging** (spec 020 FR-024) — every invocation
  writes a full record (prompt + response + cost + latency) to
  `_pipeline/cycles/cycle-NNN/agent-calls/<ts>-<stage>-<call-id>.json`.

**Forbidden**: invoking `claude` / `codex` / any HTTP LLM client
directly from any other code path. New stages that "just need a
quick LLM call" MUST plumb through `agent_call.py` even if it feels
overkill. Once a second dispatch surface is added "temporarily," it
becomes permanent.

---

## 7. Two-tier citation system (Principle IX)

The vault's value is its source grounding. Responses that bypass
that grounding eliminate the vault's reason to exist.

**Concretely**:

| Tier | What | Where it lives |
|------|------|----------------|
| Tier 1 — Vault Sources | `[[wikilinks]]` or relative paths inside `data_vault/` | Every claim in an `/ask` answer or `/write` document MUST point at one |
| Tier 2 — Original Sources | External URLs (papers, code repos, transcripts, etc.) | Note's `source_urls` frontmatter; the URL the original information came from |

**Two-tier rendering**: agent responses and document outputs MUST
surface both tiers DISTINCTLY (e.g. a `Vault Sources` section listing
`[[notes]]` + an `Original Sources` section de-referencing the Tier 2
URLs). Burying Tier 2 inside Tier 1 prose is a violation.

**Verifier enforcement**: an independent verifier agent rejects any
output that (a) lacks Tier 1 citations, (b) references Tier 1 notes
whose frontmatter has zero Tier 2 sources, or (c) conflates the two
tiers in rendering. Verifier rejection is a hard stop.

---

## 8. Source-module architecture (spec 020, SHIPPED 0.4.0)

**Status**: shipped 2026-05-27 (PR #32, squash `27a8949`, released as
part of the Revival-sprint Wave 1 bump — see `specs/020-code-bridge/
spec.md` for the full ship record). First-party modules landed
progressively after: youtube / reddit / rss / oreilly by 0.6.0;
github / atlassian via spec 060 batch-1 at 1.0.0rc5. See
`docs/ROADMAP.md` "Source Modules roadmap" for the remaining ladder.

The framework adds **pluggable source modules** that pull structured
signals from data sources (code repos, YouTube videos, Reddit threads,
etc.) so the research pipeline can spend its tokens on intent-first
thinking instead of re-reading the same source on every cycle.

### Key contracts

| File | Purpose |
|------|---------|
| `<vault>/modules/<name>/manifest.yaml` | Module identity, triggers, entry point |
| `<vault>/modules/<name>/extractor.py` | Subprocess entry; stdin/stdout JSON contract |
| `<vault>/_pipeline/sources/<module>/facts-schema.json` | Per-(vault, module) JSON Schema generated from `research.spec.md` |
| `<vault>/_pipeline/sources/<module>/watermarks.json` | Per-source cache index |
| `<vault>/_pipeline/sources/<module>/signals/<source-stem>-<version>.json` | Per-extraction cache payload |
| `<vault>/_pipeline/sources/<module>/consensus/<source>-cycle-NNN.json` | Per-cycle consensus audit |

### Load-bearing decisions (spec 020 plan.md `[DECIDED]` markers)

| Marker | Decision |
|--------|----------|
| D1 | Dynamic per-vault, per-module schemas (NOT hardcoded buckets) — preserves domain-agnosticism (Constitution 1.3.2 "Not opinionated about domain" expansion; **NB**: not to be confused with Principle X which is the auto-commit invariant added in 1.4.0) |
| D2 | Value-tiered consensus: `routine` (N=1) / `important` (N=3) / `critical` (N=5). Odd N enforced. Majority vote + union of findings |
| D3 | 30-day GC of stale signal files; audit logs (consensus + agent-calls) never auto-GC'd |
| D4 | Per-call agent logging at the dispatch surface (FR-024, cross-cutting) |
| D5 | Permissive trust boundary in v1 + documented warning; subprocess sandbox is future work |
| D6 | Migrator auto-rebuilds installed modules on `./vault update`; modules NOT in `settings.yaml::modules:` are NOT auto-copied |
| D7 | Vendor-agnostic `tiers:` block in `settings.yaml` — stages reference tiers via `tier:` field; resolved at `agent_call.py` load time |
| D8 | Schema drift on manually-edited schemas: fail-closed cycle abort unless `--force-stale-schema` |
| D9 | Module-isolation policy: retry-once + salvage-and-continue on any module-subsystem unhandled exception; cycle NEVER aborts on per-source failure |

See `specs/020-code-bridge/research.md` for R1-R21 implementation
decisions and `specs/020-code-bridge/contracts/` for the 11 JSON
Schemas + protocol markdowns.

### Why modular?

**One architecture, many sources.** The 020 module contract is
deliberately shaped so every module — shipped (youtube, reddit,
oreilly, github, atlassian) or still on the ladder (arxiv, wikipedia,
podcasts, …) — drops in against the same interface. See
`docs/ROADMAP.md` "Source Modules roadmap" for the tiered ship list.

### What shipped

73 tasks across 10 blocks, all executed under the foreman verification
pattern. MVP scope (US1+US2+US3+US4 — the P1 block) = 46 tasks. P2
(US5+US6+US7 — validators + consensus + per-call logging validation) =
12 more. Polish (install wizard + docs; the original spec listed the
migrator here too but it was retired in 0.2.33) = 15 more.

---

## 9. Test pyramid (spec 018 shipped 0.2.30; spec 024 → seven tiers shipped 0.3.0; ADR-0008)

Seven layered tiers, each with a specific failure-class it catches.
Full rationale + tier decision tree + anti-patterns lives in
`docs/testing-strategy.md`.

| Tier | Purpose | Example | Speed |
|------|---------|---------|-------|
| 1 — Unit | Pure functions, no I/O, no LLM | `test_validators_yaml.py` | <100 ms each |
| 2 — Schema / contract | JSON Schema validation, prompt-shape contracts, lint guards (e.g. `test_llm_dispatch_guard.py`, `test_acceptance_coverage_guard.py`) | `test_manifest_contract.py` | <500 ms each |
| 3 — Integration | Multi-component, real filesystem, stubbed LLMs | `test_cycle_runner_phases.py` | <2 s each |
| 4 — Component integration | Cross-module orchestration on synthetic data, no real LLM | `test_cycle_runner.py` | <5 s each |
| 5 — Cycle e2e | One full cycle on a synthetic vault via `fake_agent.py` | `test_full_cycle_e2e.py` | <30 s each |
| 6 — Multi-cycle e2e | Multiple cycles on a fixture vault; also exercised by the spec-022 quality harness fixtures | `test_multi_cycle_e2e.py`, `test_fake_agent_interception.py` | <2 min each |
| 7 — Smoke gate | `build.sh` smoke gate + lint baseline + `--quality` regression check | meta-tests under `tests/build/` | ~5 min total |

> Tier numbers and names here MUST match `docs/adr/0008-testing-pyramid-restructure.md`'s
> decision table — that ADR is canonical; this table restates it with
> examples for a reader who hasn't opened the ADR.
> `tests/docs/test_one_source_per_fact.py` fails the suite if they drift.

Fast-loop and full-suite test counts are **not quoted here** — they
drift with every test added or removed. Run `pytest --collect-only -q`
(or `-m "not e2e"` for the fast-loop-only figure) for the live number;
`docs/testing-strategy.md`'s TL;DR is the one place a snapshot is
committed, and the same drift-guard test above keeps it honest.
`@pytest.mark.live_llm` tests are **skipped by default** by
`tests/conftest.py` and only run when `pytest --live-llm` or
`LIVE_LLM=1` is set (opt-in money-spending). `./build.sh` runs the
smoke gate first; `./build.sh --quality` additionally runs the
spec-022 quality harness across all three fixtures and fails on
>15% regression.

**Smoke gate in `build.sh` is mandatory; there is no `--skip-smoke`
flag** (ADR-0007). The gate also runs `ruff check .` and
`ruff format --check .` as a non-skippable lint baseline (added
in PR #5 / 0.3.2 post-foundation). The release pipeline (`release.yml`)
enforces `bash build.sh --quality` before any wheel is published.

### Test helpers

| File | What it does |
|------|--------------|
| `tests/_helpers/fake_agent.py` | Deterministic LLM stand-in; covers scout, note-writer, verifier, narrator, probe stages (spec 024 US2) |
| `tests/_helpers/vault_factory.py::build_minimal_vault` | Synthesizes a working vault on disk for integration / e2e tests |
| `tests/_helpers/llm_dispatch.py` | The single source of truth for "what counts as an LLM dispatch" — derives the binary set from `agent_call._LLM_AGENT_NAMES` and owns the subprocess + inference-URL predicates both guards read (issue #292) |
| `tests/_helpers/test_llm_dispatch_guard.py` | Static guard (spec 024 US1): refuses any subprocess invocation of a shipped LLM binary, and any HTTP call to a model-inference endpoint, outside an empty allowlist |
| `tests/_helpers/test_llm_dispatch_parity.py` | Builds every shipped executor's real dispatch shape and asserts the static and runtime guards classify all of them identically |
| `tests/quality/test_fake_agent_interception.py` | Tier-6 runtime guard: patches `subprocess.Popen` **and** `urllib.request.urlopen`, asserts it observed dispatch traffic, and that none of it reached a live model (ship-gated since PR #2 post-mortem) |
| `tests/_helpers/fake_repo.py` (spec 020) | Synthesizes a deterministic git repo |
| `tests/_helpers/fake_module.py` (spec 020) | Minimal source module with controllable exception injection |

**NEVER**: monkey-patch `run_cycle_steps`; call real `claude` / `codex`
from a test outside the smoke gate. Both lead to silent test poisoning
— the 0.3.2 hotfix existed because the `plan_narrator` bootstrap was
silently calling real `claude` during fixture cycles for a release.
Both are **guarded**, not merely written down:
`tests/_helpers/test_llm_dispatch_guard.py` for the dispatch, and
`tests/_helpers/test_cycle_runner_seam_guard.py` for the runner (#86 — the
prose rule had drifted to twelve live sites). A test that needs a stand-in
runner passes the keyword-only `cycle_runner=` seam on
`orchestrator.run_single_cycle` or the quality harness, with a stub from
`tests/_helpers/cycle_runner_stub.py`.

---

## 10. Quality + E2E harness (spec 022 — SHIPPED 0.3.0)

**Status**: SHIPPED 0.3.0 (2026-05-21); v2 metric retargeting in 0.3.1;
Tier-6 intercept fix in 0.3.2. Spec 030 covers the v3 expansions and is
deferred (`docs/ROADMAP.md` § Deferred carries its substance and its
trigger). See `docs/ROADMAP.md` § Shipped registry + the spec status header
at `specs/022-e2e-quality-harness/spec.md`.

### Why it exists

Spec 020's success criteria (e.g. SC-001 "topic count 2× baseline",
SC-003 "verifier rejection rate <15%") were unmeasurable before this
shipped. The harness lets every future feature be evaluated against
the same baselines so quality drift fails CI, not production.

### What ships (as of 0.3.2)

Three metric families, each with a published baseline + regression
gate, across three fixture vaults:

1. **Coverage** — % coverage_targets met, notes-per-category, spec-vs-vault drift.
2. **Note quality** — verifier acceptance rate, sources/note, tier-2 citation rate, placeholder-prose detection.
3. **Cycle health** — error rate by stage, retry rate, wall-clock per cycle, fail-closed rate, SG-NNN trip counts.

**Regression gate**: MODERATE. >15% regress = fail; >5% = warn.
Compared against committed baselines under
`tests/fixtures/quality/<fixture>/_pipeline/quality/`. Enforced by
`bash build.sh --quality` on every release.

**Fixture set (shipped)**: 3 fixtures —

| # | Fixture | What it probes |
|---|---------|----------------|
| 1 | `tech-lite` | Baseline; small Java payment-gateway domain (code-derived topics) |
| 2 | `source-poor` | Source-discovery escalation under thin source set |
| 3 | `source-rich` | Scaling + cache efficiency with deep source manifests |

The original spec lock (2026-05-20) targeted 4 metric families × 6
fixtures. The 3-family / 3-fixture set is what proved valuable enough
to ship; the remaining metrics + fixtures (embedded-firmware, childcare,
gaming, source quality) are queued under spec 030 — Quality Harness v3.

### Cost-tracking watch-item

Per-run `total_cost_usd` logged alongside the report but NOT gated
in v1. Cost-efficiency arc is now spec 033 (cost enforcement, URGENT
under the codex 2026-06-01 cap). Spec 028 (dispatch telemetry) lands
the honest cost data 033 needs to gate on.

---

## 11. ADRs — durable architectural decisions

Cross-cutting decisions live in `docs/adr/` as numbered files.
**ADRs are append-only** — to change a decision, write a new ADR that
supersedes the old one. Never edit accepted ADRs.

Current ADRs (read `docs/adr/README.md` for the full index):

| # | Decision | Origin |
|---|----------|--------|
| 0001 | Adopt ADRs for architectural decisions (the meta-ADR) | 2026-05-18 |
| 0002 | Phase-scoped `sources_consulted` validation | spec 019 / 0.2.30 |
| 0003 | Correction directives must be injected into prompts | spec 019 / 0.2.30 |
| 0004 | Verifier output parsing must tolerate non-strict JSON | spec 019 / 0.2.31 |
| 0005 | Wikilink case is normalized at cycle time | spec 019 / 0.2.31 |
| 0006 | Code access is cached infrastructure | spec 020 (planned 0.3.0) |
| 0007 | Smoke gate is mandatory and cannot be skipped | spec 018 / 019 |
| 0008 | Testing pyramid restructure — seven tiers, scope vs purpose markers | spec 024 / 0.3.0 |
| 0009 | Collectors vs modules reconciliation (020 supersedes 014/015) | spec 020 / 0.4.0 |
| 0010 | Foreman verification pattern | 2026-05-27 |
| 0011 | Operational config lives in `settings.yaml` | spec 061 / 1.0.0rc3 |
| 0012 | The acceptance-bullet format is not guarded | 2026-09-07 |
| 0013 | Cross-repo envelopes are additive within a major and carry `schema_version` | spec 036 / 1.3.0 |

**When to write an ADR**: a decision crosses spec boundaries, affects
multiple files in different specs, or reverses a prior decision.
Per-spec decisions belong in the spec's `research.md`, not as an ADR.

---

## 12. Vault Specialities (specced as 046, then subsumed — kept as rationale)

> **Status, 2026-06-02**: this was written as `specs/046-vault-specialities-plugin-model/`
> and **subsumed by spec 053** (source authority): vault-type differences turned
> out to be handled by *declared* source authority — 053's role/priority and its
> derived trunk — not by a plugin subsystem. 046 is archived and is not a
> candidate. The section below is kept because the distinction it draws
> (vault SHAPE vs data-source ADAPTERS) is still the right one and still
> load-bearing when reading spec 020.

The base vault structure is generic and context-agnostic. **Vault
Specialities** are opt-in plugins that enrich it for specific domains
(code repositories, recipes, scientific papers, legal documents, …).

Each Speciality contributes:

- Additional templates (`templates/specialities/<name>/`)
- Domain-specific validators (`scripts/specialities/<name>_*.py`)
- Agent skills / prompts that know how to extract structure from the
  domain's native sources
- Optional spec-time questions to elicit domain config

The existing **codebase-vault code-first** work (spec 002) is the
*reference* Speciality — it just happened to land as a core feature.
**Rule of three**: do NOT extract a plugin interface until a second
concrete Speciality is on the table. Premature interfaces here will
calcify around code's quirks.

**Not the same as source modules (spec 020).** Modules are about
data-source ADAPTERS (where signals come FROM). Specialities are
about vault SHAPE (how notes are organized for a domain). Both can
coexist; a future "recipes speciality" might use a hypothetical
"food-blogs source module" — distinct concerns.

---

## 13. Generated vault structure

What every vault contains. Generated at install; preserved across
`./vault update`.

```text
<vault-root>/
├── research.spec.md           # USER-OWNED — the input spec
├── settings.yaml              # USER-OWNED — runtime config, modules, tiers
├── AGENTS.md                  # Layer 1: orchestration prompt
├── CLAUDE.md                  # Claude Code workspace rules
├── _templates/                # Note templates (per type)
├── modules/                   # (spec 020) Installed source modules
│   ├── code/
│   └── ...
├── data_vault/                # Layer 2: the actual knowledge
│   ├── <category-1>/
│   ├── <category-2>/
│   ├── _index.md              # Generated; do not edit
│   ├── _concepts.md           # Generated
│   └── _graph.md              # Generated
├── _pipeline/                 # Pipeline state; not for end-user editing
│   ├── research-plan.md
│   ├── coverage-targets.json
│   ├── research-backlog.md
│   ├── sources.db             # SQLite source-quality DB
│   ├── sources/               # (spec 020) Per-module caches + signals
│   │   └── <module>/
│   │       ├── facts-schema.json
│   │       ├── watermarks.json
│   │       ├── signals/
│   │       └── consensus/
│   ├── runs/                  # (spec 080) One directory per `pipeline` run
│   │   └── <run_id>/
│   │       ├── run.json       # the receipt: durations, costs, artifact paths
│   │       ├── run-report.md  # its rendering for a human
│   │       ├── verify-report.json
│   │       ├── logs/<stage>.log
│   │       ├── prompts/<stage>.rendered.md
│   │       └── agent-calls/<stage>.json   # the cost sidecar
│   └── cycles/
│       └── cycle-NNN/
│           ├── batch-NNN.json
│           ├── quality-report.json
│           ├── summary.md
│           ├── run-report.md
│           └── agent-calls/   # (spec 020) Per-LLM-call audit records
├── raw_data/                  # Extracted source content; gitignored
├── scripts/                   # Per-vault validators (copy from framework)
├── vault                      # Uniform script: research / health / audit / ask / write
└── .vault-config.yaml         # Per-vault overrides
```

**Per-vault is self-contained**. The framework reads its state from
the vault root on each invocation; it never caches vault state between
runs. This is what enables multi-vault operation (spec 023 Phase 2, #43).

### `.claude/commands/` — one template owns each file

Every command file in a generated vault is written by
`agents.write_agents`, from `generate` and from `regenerate-agents` alike.
Two kinds live side by side:

| Kind | Source | Destination name |
|------|--------|------------------|
| Pipeline agent definitions (`scout`, `verify`, `report`, `extract`, `pipeline`) | `src/research_framework/agents/<name>.md.j2` | fixed — `<name>.md` |
| Renameable slash commands (`ask`, `research`, `write`) | `templates/commands/<name>.md.j2` | `spec.settings.commands.<name>` |

The split matters because the second kind is user-facing and the spec may
rename it. A second template rendering to the same file under a fixed name
would make `generate` and `regenerate-agents` disagree about what a vault's
`/research` *is* — the defect behind #252.

### The two research entry points

"Research" names two different things, deliberately:

- **`/research`** — interactive, one topic at a time. The operator names a
  topic; the command adds or updates a single note. Rendered from
  `templates/commands/research.md.j2`, renameable per spec.
- **The runner's `research` stage** — headless, driven by `/pipeline resume`.
  It reads the approved topics out of `_pipeline/scout-report.json` and
  dispatches the note-writer prompt built from
  `templates/prompts/dfs-prompt.md.j2` for the whole cycle. No slash command
  is involved and no human is asked anything mid-run.

Reach for the first when you know what you want written; reach for the second
when the pipeline decides. They share the corpus and the quality bar, nothing
else.

### The triage checkpoint

`pipeline full` stops after scout and waits for a human. That pause is the
pipeline's **only** human checkpoint, and until 2026-09-06 no document
described it — the pause message told the operator to "open the radar", which
a pipeline run never writes.

| Question | Answer |
|----------|--------|
| Where is the queue? | `<vault>/_pipeline/scout-report.json`, key `topics_found.new` |
| Who writes it? | the `scout` phase, from `_pipeline/extracted/context-tree.md` |
| Who reads it? | the runner's headless `research` stage, via `dfs-prompt.md` |
| How do I approve? | you don't — `resume` researches whatever is in the list |
| How do I defer? | delete the entry from `topics_found.new` before resuming; git keeps the original |
| Is there a cap? | no — one `resume` researches the whole list in a single pass |

The Topic Radar note (`00 - MOC/Topic Radar - <Month> <Year>.md`) is real, but
it belongs to the **cycle orchestrator** and the `/scout` slash command, not to
a `pipeline` run. `runner._STAGE_PROMPT_SOURCES` steers the research stage at
`scout-report.json` for exactly this reason.

"Delete the line you don't want" is a protocol, not a gate, and the absence of
a cap is why one live run was handed 107 topics in a single pass. A generated
triage artifact, a `pipeline triage --approve/--defer/--top N` verb, deferred
topics carried into `research-backlog.md` and a `resume` that refuses an empty
approval set are tracked in issue #240; that is a contract change across three
stages and wants its own spec.

---

## 14. CLI surface — shape, not the list

**[`specs/077-cli-contract/spec.md`](specs/077-cli-contract/spec.md) is the
owning document** for the verb list, the flags and the exit codes. This
section carries only the shape, because a list restated here drifts: until
2026-09-08 it showed 2 of 21 argparse verbs, omitted five `./vault` verbs, and
listed a `schema --acknowledge-drift` flag interface that does not match what
was built (077 D7/D8).

The shape:

- **One entry point**, `research-framework` (package `research_framework`,
  dispatched through `cli/__main__.py`), with a verb per unit of work —
  scaffolding a vault, running cycles, running the weekly pipeline, and the
  read-only surfaces (`status`, `digest`, `export`, `coverage`).
- **One shim per generated vault**, `./vault`, dispatching 18 verbs (077
  FR-008). Verbs that map 1:1 onto an argparse verb forward `--vault <vault>`
  plus the caller's arguments unchanged (FR-010); a verb whose backing script
  is absent says so and exits non-zero rather than appearing to succeed
  (FR-011) — `write` and `maintain` are in that state today and the docs say
  so rather than advertising them.
- **Three exit codes** (077 FR-012): `0` pass/continue, `1` fail/terminate
  (this unit of work is over), `2` abort (the operator must intervene).
- The shim shells out to `research-framework` plus standalone scripts in
  `scripts/`. Per-vault, per-machine. No global daemon.

---

## 15. Where to find what

If you're looking for... | Read...
---|---
The constitution (what we MUST NOT do) | `.specify/memory/constitution.md`
What comes next (roadmap) | `docs/ROADMAP.md`
The active TODO scratchpad | `docs/TODO.md`
How to contribute / spec-kit flow | `CONTRIBUTING.md` (you should read this NEXT)
Why a specific architectural decision was made | `docs/adr/`
The test pyramid + tier decision tree | `docs/testing-strategy.md`
A specific feature's design | `specs/NNN-name/spec.md` (+ plan.md + research.md + contracts/)
The current release notes | `CHANGELOG.md`
A specific failure mode + its constraint | Constitution §"Failure Record Reference"
A skill (note-tagger, scout, verifier, etc.) | `.agents/skills/<name>/SKILL.md`

---

## 16. Where things land in this repo

```text
research-framework/
├── ARCHITECTURE.md            # This file
├── CONTRIBUTING.md            # How to add a spec / feature / fix
├── CHANGELOG.md               # Release history
├── README.md                  # Repo entry point
├── CLAUDE.md                  # Just-in-time agent context (auto-updated)
├── pyproject.toml             # Package metadata + deps + dev tools
├── build.sh                   # Builds wheel + bundle; runs smoke gate
├── generate_vault.sh          # Bootstraps a new vault from this repo
├── install.sh                 # End-user installer (lands in bundle)
├── settings.yaml              # Framework default settings (Claude)
├── settings.codex.yaml        # Codex (OpenAI) runtime profile
├── settings.cursor.yaml       # Cursor (flat-rate) runtime profile
├── src/research_framework/
│   ├── cli.py                 # CLI entry point + subcommand dispatch
│   ├── pipeline/
│   │   ├── agent_call.py      # SINGLE LLM dispatch surface (Principle V critical)
│   │   ├── cycle_runner.py    # Per-cycle execution (Python-native, spec 004)
│   │   ├── orchestrator.py    # Multi-cycle + resume + budget tracking
│   │   ├── verifier.py        # Principle IX gate
│   │   ├── wikilinks.py       # ADR-0005 case normalization
│   │   ├── source_manager.py  # sources.db wrapper
│   │   ├── source_bridge/     # (spec 020, SHIPPED 0.4.0) module-bridge package
│   │   └── ...
│   ├── modules/               # (spec 020, SHIPPED 0.4.0) framework's module bundle
│   ├── skills/                # Agent skills (scout, note-writer, verifier, ...)
│   ├── templates/             # Vault templates by note type
│   └── ...
├── scripts/                   # CLI-callable scripts (validate_vault, vault_audit, ...)
├── tests/                     # Test pyramid tiers 1-7 (ADR-0008)
│   ├── _helpers/              # fake_agent, vault_factory, fake_repo, fake_module (spec 020)
│   ├── fixtures/              # Synthetic vault fixtures
│   └── ...
├── specs/                     # All feature specs (001..022)
├── docs/
│   ├── ROADMAP.md
│   ├── TODO.md
│   ├── testing-strategy.md
│   ├── adr/
│   │   ├── 0001-...md
│   │   └── ...
│   └── ...
├── .specify/
│   ├── memory/
│   │   └── constitution.md
│   ├── templates/             # spec / plan / tasks templates
│   └── scripts/bash/          # speckit workflow scripts
├── .agents/
│   └── skills/                # Agent skills (cycle-report, install-wizard, etc.)
└── dist-templates/            # Bundle template files
```

---

## 17. Strategic sequencing (historical decision, 2026-05-20 — fully executed)

The project had hit a complexity threshold where shipping new features
without measurement infrastructure risked adding noise rather than
quality. The arc decided then, for the historical record:

1. **Quality** — spec 022 (E2E quality harness) FIRST. Baseline 0.2.31.
2. **Features** — spec 020 (source modules), then spec 021 (coverage
   pursuit), then Tier 1 source modules (youtube, reddit, oreilly,
   arxiv), each gated by the 022 harness.
3. **Efficiency** — cost tracking + perf optimization, AFTER quality +
   features are settled.

**Since then**: 022 shipped 0.3.0, 020 shipped 0.4.0, and the Tier-1
source modules shipped by 0.6.0 — the "Features" step ran without waiting on
spec 021, which is still a draft blocked on six `[PROPOSED]` decisions and is
now deferred (`docs/ROADMAP.md` § Deferred). This section is a record of the
sequencing rationale at the time, not a live status — `docs/ROADMAP.md`'s
v1.1.0 and v1.2.0 tiers are what is in flight today.

---

## 18. How agents (human or LLM) should onboard

In order:

1. Read `.specify/memory/constitution.md` (v1.6.0) — the inviolables.
2. Read this file, `ARCHITECTURE.md` (you're here).
3. Read `CONTRIBUTING.md` for the spec-kit workflow.
4. Read `docs/testing-strategy.md` for the test pyramid.
5. Read `docs/ROADMAP.md`'s v1.1.0 tier for what comes next.
6. Skim `docs/adr/README.md` for the durable decisions index.
7. For any specific spec you're working on, read its `spec.md` →
   `plan.md` → `research.md` → `contracts/` → `tasks.md` in that
   order.

Total onboarding: ~1 hour. After that, you're current.
