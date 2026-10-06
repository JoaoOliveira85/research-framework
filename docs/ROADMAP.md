# research-framework — Roadmap

Status: **replaced wholesale on 2026-09-08** after a review of the private
line's 1.2.0 (decision D3); version numbers restarted at the public 1.0.0
(2026-10-06). The previous file was a v1.0.0 release checklist, an rc
status matrix, three wave narratives and a `#N`-numbered queue — all shipped
history dressed as a plan, with nothing on it that had not already landed and
nothing on it from the issues that had. Shipped work belongs in `CHANGELOG.md`
and the per-spec `**Status**:` headers; this file owns **sequencing** only.

Three parts, in reading order:

1. **Shipped registry** — one row per version, so a reader can place any spec
   number in time without opening the changelog.
2. **The next two releases as tiers** — `v1.1.0` and `v1.2.0`, each an ordered
   list with the dependency that fixes the order. A tier names *who the work
   serves*, not how big it is.
3. **Deferred** — one row per parked spec, carrying its substance and the
   concrete trigger that un-parks it. Their tracking issues are closed
   (2026-09-08, owner decision D12); the row is where the idea now lives, so
   nothing that was in an issue body is lost.

Specs own design depth (`specs/NNN-*/spec.md`; the index is
[`specs/README.md`](../specs/README.md)); durable decisions are ADRs
(`docs/adr/`); un-triaged ideas are `docs/TODO.md`. Nothing under `tests/` or
`scripts/guards/` reads this file, so its shape can change freely — its
*truthfulness* is a review-time obligation (CLAUDE.md § Documentation
discipline).

**Status convention**: `[ ]` planned · `[~]` in progress · `[x]` shipped ·
`[?]` blocked on a named decision.

---

## Sequencing decisions

Settled 2026-09-08; they constrain every tier below.

**The weekly pipeline must run unattended before anything is built on top
of it.** That is the whole of the v1.1.0 operator tier and the reason the
contracts tier (v1.2.0) waits: a consumer building against a vault that a
human still has to babysit through `full` → `resume` → `finish` is building
against an unfinished surface.

**A local or decentralised model option is always supported** (constitution
1.6.0, D8). Every model-backed capability keeps a self-hosted provider path;
degraded is acceptable, absent is a violation. The shipped
`settings.ollama.yaml` profile is the proof and ships with every release
(packaged 2026-09-08, D11). Hardware weakness — spec 065's finding that local
27–30B models do not yet *complete* the autonomous stages — is a reason to
keep spiking, not a reason to drop the path.

**Claims export is additive and versioned** (D5). `./vault export --claims`
ships an envelope with a `schema_version` field as a safeguard, not acted on
yet; the ADR precedes the schema. It is one verb, not spec 036's whole
integration surface.

**Branch retention is a policy, not a prompt** (D10, #307). Cap-N (5) *and*
age (> 3 months), checked when a vault session starts, with a manual `prune`
verb kept. Because every completed research cycle now merges to `main` and
returns the checkout there (spec 072), open research branches are records,
not work, and are safe to delete.

**The spec corpus index and archive are the consolidation** (D6, #274). The
~16-folder absorption the issue asked for is authoring, not housekeeping; it
is recorded as a clean-room task and #274 closes with a ledger.

**CI runs on version tags and by hand only** (CLAUDE.md § CI budget). The
merge gate is the local suite; a PR reports its own counts.

---

## Shipped registry

Every row up to private 1.2.0 shipped from the private development
repository (see `CHANGELOG.md` § Before the public release); the public line
restarts at 1.0.0. Dates are **tag** dates, which `docs/RELEASE.md` makes the
CHANGELOG heading convention too (D14).

| Version | Tagged | What shipped |
| --- | --- | --- |
| private 0.2.18 – 0.2.33 | 2026-05-16 → 05-21 | The pre-spec-kit pipeline: Python cycle runner (004), adaptive sources (005), audit/settings/`./vault` script (006–008), consolidation 015x, vault quality fix (017), pipeline architecture + ADR-0002–0005 (019). 0.2.33 renamed `research_vault` → `research_framework` and retired the spec-013 migrator. |
| private 0.3.0 – 0.3.2 | 2026-05-21 → 05-22 | Foundation arc: E2E quality harness (022, `build.sh --quality`), testing infra v2 (024, LLM dispatch guard, fake agent), simplify pass (025), ADR-0007 (smoke gate mandatory), ADR-0008 (seven-tier pyramid). |
| private 0.4.0 | 2026-05-27 | Wave 1: source-module architecture (020), flow separation P1 (023), dispatch telemetry (028), cost enforcement (033), foreman pattern (ADR-0010). |
| private 0.5.0 | 2026-05-29 | Observability v1 (048): `--log-level`, `bridge.log`, source-consideration ledger. |
| private 0.6.0 – 0.6.3 | 2026-05-30 → 05-31 | Tier-1 module ports: `youtube`, `reddit`, `rss` (subsumes `arxiv`), `oreilly`; feeds-vault revival fixes. |
| private 0.7.0 | 2026-06-01 | Mandatory vault auto-commit (050, Principle X); constitution 1.4.0. |
| private 0.8.0 | 2026-06-02 | Post-revival hardening (051): yield model, source preflight, stale-venv detection. |
| private 0.9.0 | 2026-06-03 | Source authority (053), source ledger (048 v2), cycle-helpers split (049), pipeline reliability (032), `./vault update` hardening (027), source-module resilience (038). |
| private 0.10.0 | 2026-06-04 | Fixture isolation (026), source-manager correctness (029), installer hardening (039), Linux portability guard + `docs/PORTABILITY.md` (009 — its per-PR CI was later reversed by the CI-budget rule), `vault status` (048 v1.1), source credibility model (055). |
| private 1.0.0rc1 – rc11 | 2026-06-04 → 07-31 | rc1: cross-cycle digest (035), vault reports + delivery (040). rc3: cycle-budget config (061, ADR-0011), output integrity (062), acceptance harness (063), 028/048 amendments. rc4: Cursor executor (052). rc5: `github` + `atlassian` modules (060 batch 1), Ollama HTTP dispatch (047 v1), executor benchmark (056). rc6: Jira endpoint migration, wikilink/YAML hygiene. rc7: opencode executor (064) + local-model spike (065). rc8/rc9: the rc7-validation wave — credibility calibration (066), acronym disambiguation (067), coverage counting (068), source-relevance tuning (069). rc10: foreman `--tolerant` (057 mechanism), control-file health warning (058). rc11: quarantine-on-refresh fix. |
| private 1.0.0 | 2026-08-27 | Live validation campaign across six vaults; strategy-hint credibility + non-silent resume (070); archived vaults (071); Claude 5 tier ids; `./vault update` script refresh fixed. |
| private 1.1.0 | 2026-08-30 | Auto-merge research branch (072), query-driven spec append (073), `cycle --target-topics` fixed (074). |
| private 1.1.1 | 2026-09-08 | Every shipped profile now seeds `limits:` (spec 033 enforcement had been off in all six); constitution failure F9; #213 #215 #216. |
| private 1.2.0 | 2026-09-08 | Verify verdict semantics — flag classes, the vault's own note format, a real FAIL path (#327); one budget ladder for every run verb, `pause show\|clear`, `--estimate-only` (#331); `budget_usd: 0` = unlimited (#320); `pipeline status --json`, empty-branch cleanup (#321); CI on tags and by hand only (#323, #324); guard battery + agent-asset lint + JSON-schema wiring + branch retention v0 (#326); CLI-binary fake + parser-flag consumer guard (#329); spec index, archive and trunk specs 075–079 (#328); constitution 1.5.0; review-backlog minors (#332). |

| **1.0.0** | 2026-10-06 | **First public release** — private 1.2.0 plus the post-1.2.0 work (run receipt 080, review fixes), in a recreated repository with personal and workplace details removed. |
---

## v1.1.0 — the weekly pipeline runs unattended (operator)

Two groups. The first is the truth patch (shipped in 1.0.0); the
second is the operator surface, in dependency order — each item is a
precondition of the one after it, and #249 composes all of them.

### Truth patch (maintainer)

| # | Item | Status | Notes |
| --- | --- | --- | --- |
| 1 | Docs truth: the 22 stale files from the 2026-09-08 review | `[x]` | README, CLAUDE.md, CONTRIBUTING, RELEASE, testing-strategy, skills inventory, this file (2026-09-08). The remainder (2026-09-10): ARCHITECTURE §§ 9–18, `tests/README.md`, `docs/PORTABILITY.md`, `docs/TODO.md`, `release.yml`'s header, and spec 041's premise banner. |
| 2 | `settings.ollama.yaml` packaged in wheel + bundle (D11) | `[x]` | Guard: `tests/build/test_settings_profiles_packaged.py`. |
| 3 | Constitution 1.6.0 (D8) | `[x]` | Enforcement Register truth (tracked pre-commit hook + `run_all.py`, no PR gate), rows I/III/IV/VI/X/XI/XII re-verified, cross-repo note-format row, failure record F10, Principle XIII candidate, and the new local-model principle. |
| 4 | Specs 080 / 081 / 082 + spec 036 answers + ADR-0013 (D5, D7) | `[x]` | 080 run receipt (absorbs 078 T005 and 075 T005), 081 triage gate, 082 spec-driven verify (#226). #221 #224 #246 #247 #248 #249 re-homed as standalone `type:spec` issues; trackers #211 / #214 then close with ledgers (D4). |
| 5 | Branch retention policy (#307, D10) and `./vault export --claims` (#189, D5) | `[x]` | See Sequencing decisions. |
| 7 | #86 — retire the last three `run_cycle_steps` monkeypatch sites | `[x]` | Twelve, not three: the roadmap counted the attribute spelling, and nine more used the dotted one. All now pass a keyword-only `cycle_runner=` seam (`run_single_cycle`; the quality harness's `run` / `collect_fixture_current` / `_invoke_cycles`), with stubs in `tests/_helpers/cycle_runner_stub.py` and `tests/_helpers/test_cycle_runner_seam_guard.py` in the battery so the count cannot drift back up. |
| 8 | #295 — relocate the JSON Schemas tests load out of `specs/_archive/` | `[x]` | One schema, not several: `pipeline-state.schema.json` → `specs/075-pipeline-runner/contracts/` (075 supersedes 015g as the runner's owning document). The archive rule's second half is now a guard, not prose. |

### Operator surface (dependency order)

| # | Item | Spec | Depends on | Status |
| --- | --- | --- | --- | --- |
| 1 | **#221** — a run leaves a receipt: `_pipeline/runs/<run_id>/` with a sidecar and a per-phase log | 080 | — | `[x]` |
| 2 | **#224** — the `report` phase describes the run that just happened, not `git log` | 080 US4 | 1 | `[x]` — shipped with 1, not after it: sixty lines on the receipt's plumbing, and nothing feeds a report until the receipt exists |
| 3 | **Triage as a real gate** — `_pipeline/triage.json`, `--approve` / `--defer` / `--top N` | 081 | 1 | `[ ]` — deferred in #305 when #240 closed; `rg triage.json src/` is empty today |
| 4 | **#248** — publish the exit-code contract and lint it; split `digest`'s malformed-date error from its empty-range result | 077 T002–T005 | — | `[x]` — the **lint** shipped; the second copy of the table did not, deliberately (077 tasks § On "publish") |
| 5 | **#246** — `pipeline doctor`, a preflight before spending money | new | pairs with `--estimate-only` | `[ ]` |
| 6 | **#247** — `fleet status` / `fleet run` across vaults | new | 1, 3; groundwork `pause show --json`, `pipeline status --json` | `[ ]` |
| 7 | **#249** — `pipeline run --until <phase> --auto-approve top:N --max-usd X`, delivering the outcome through spec 040's SMTP / report delivery | new | 1–6; **absorbs spec 042** (#58, D12): the auto-approval policy *is* the autonomy level 042 wanted as a per-vault setting | `[ ]` — last, by construction |

**Batchable alongside** (no ordering constraint, each a day or less):

- 077 T001 — `./vault write`: ship `scripts/generate_doc.py` or delete the verb
  from the shim. Today the shim lists it and execs a script that does not
  exist; the docs now say so rather than advertise it.
- 077 T006 — wire or delete the orphaned `schema acknowledge-drift` CLI.
- 076 T001 — dead settings keys, and a strict mode (#271's other half).
- 079 T001 / T002 — the note template emits 4 frontmatter keys where the
  validator requires 8.
- 078 T001 / T002 — every reference to a `pipeline/agent_call.py` that never
  existed (the dispatch surface is `scripts/agent_call.py`), and
  ARCHITECTURE's audit-log filename.
- #226's wider contract (`required_sections`, `coverage_targets`) → spec 082,
  or a 079 amendment if 079 already owns it.
- #306 / #320 residuals: fake-agent scenario env in the release runner →
  re-bless `verifier_reject_rate`; `budget_usd: 0` in the install-wizard
  skill; ADR-0013 vs a 061 amendment.
- #270's fake-CLI-binary write-up folded into spec 078.
- 075 T005 tick (satisfied by 080).

**Closes** #211 and #214 (with ledgers, after re-homing), #307, #189, #86,
#295.

---

## v1.2.0 — contracts a consumer can build against (sibling repos, clean-room)

| # | Item | Spec | Depends on | Status |
| --- | --- | --- | --- | --- |
| 1 | `tests/contracts/vault-ask-1.0.schema.json` — the `./vault ask` envelope as a schema, which constitution Principle XI marks "Not met" | 036 (Q1–Q3 answered 2026-09-08, D5) | ADR-0013 | `[ ]` |
| 2 | First consumer of `--claims`: `consumer_pipeline/pipeline/vault_import.py` reads the versioned envelope | 036 / #189 | 1.1.0 item 5 | `[ ]` |
| 3 | **#43** — spec 023 Phase 2: `VaultHandle`, `active-sources.json`, `.local.md`, FR-009/010/011/012/016/017 | 023 | 1, 2 — the contract must exist before the engine serves N vaults through it | `[ ]` |
| 4 | **#274** remainder — the ~16-folder absorption, recorded as a clean-room authoring task | — | D6 | `[ ]` — the index + archive shipped in private 1.2.0; #274 closes with a ledger |
| 5 | Clean-room reader gaps: the two runtimes (075 D1), generator/scaffold + `research.spec.md` contract, standalone source-module contract, verifier/gate rule catalogue (IX-*, SG/CG/GA), budget/cost operator doc, `_pipeline/` artifact + schema index, weekly-run operator runbook, quality-harness `unmeasured` semantics, cross-repo contracts (XI), a CI/CD doc | — | — | `[ ]` — each a doc, not a feature |

**Closes** #217's residue, #43, #52.

---

## v2.0.0 candidates — only if a break is taken

| Item | Spec | Notes |
| --- | --- | --- |
| **#57** — release infrastructure v2: PyPI publication + manifest-diff release gate | 041 | 041's premise (per-PR CI, auto-detect on `pyproject` bump) is superseded by the tag-time regime; re-scope before planning. A minor-version row if the CLI surface is untouched. |

Spec 034 / #50 is not here: superseded by ADR-0009 + 020, archived, and 075
records the runner as first-class (the naming collision is 075 T002).

---

## Deferred

Every row carries the substance of the issue it replaces — what it was, why
it stopped, and the concrete event that un-parks it. Issues closed 2026-09-08
with a comment pointing here (D12). A spec folder stays in the active corpus
with `**Status**: planned` until the trigger fires or a superseding spec names
it back (the archive rule in `specs/_archive/README.md` needs both banners).

| Id | Was | Substance | Why deferred | What un-defers it |
| --- | --- | --- | --- | --- |
| **#42** / spec 021 | Spec-driven coverage pursuit | Sibling of 020: close the 0.2.30 audit's "0% coverage on N categories" gap by pursuing the spec's declared coverage targets directly, not only via scouted tangents. Six `[PROPOSED]` decisions block `/clarify`. The 2026-09-03 review comment on the issue conflated this with *test*-coverage guards; that half is delivered — ADR-0012 records that the flat `## Acceptance` format is not guard-enforced, #313 shipped the status-vocabulary guard and the shipped-tasks ledger, #315 made the acceptance guard fail closed. Still open from that comment: teaching the acceptance guard the bullet format (or leaving ADR-0012 as the answer), an evidence row per acceptance item that asserts the named test exists *and is collected*. | Coverage on live vaults has been met by the existing loop (068 fixed the counting; 073 appends discovered ground to the spec). No run has stalled on it. | The 022 harness, or a live vault's `coverage-targets.json`, showing coverage stalling below target across cycles with the backlog empty — the condition 021 exists for. Then answer the six decisions. |
| **#47** / spec 030 | Quality harness v3 | A fourth metric family `source_quality` (Shannon entropy of sources, broken-source rate, spec-source utilisation; `tier2_source_ratio` already shipped in 055), three fixtures (`embedded-firmware`, `childcare`, `gaming`), an opt-in with-vault-vs-without-vault `/ask` comparison. The 2026-09-03 review found the harness "green and structurally unable to fail": `_delta_pct(0, x)` → `'n/a'` → pass (#267), one cycle per fixture (#268), step-gate aborts recorded as NA (#269), the source-poor failure mode exercised by nothing (#265). Those four landed as point fixes (#300, #304, #306). What 030 still owns: bless real baselines (3-cycle runs, non-zero `note_quality` / `tier2` values), prune metric families that measure nothing (`acronym_link_pct`, `tier2_source_ratio` at 0.0 baselines) from `baseline_subset`, and define the `/ask` compare. #266 (where the gate runs) is answered by the tags-only regime and `tests/build/test_e2e_tier_runs_in_automation.py`. | The point fixes removed the "cannot fail" defect; the remaining scope is a new instrument, not a repair. | A quality regression that `build.sh --quality` passes — i.e. a metric family the release gate lacks, observed on a real vault. |
| **#53** / spec 037 | Multi-agent consensus abstraction | Extract spec 020's M-of-N consensus into `pipeline/consensus.py` for reuse: verifier-N, scout exhaustion, `/ask` cross-check, N-drafter + verifier. The spec is a full design-space document (API/contract, reuse candidates, load-bearing constraints) with a `🚧 BLOCKED` callout. | Rule of three: one concrete use case (020) is not an abstraction. | A **second** concrete M-of-N use case shipping. Do not run `/speckit.plan` before that. |
| **#58** / spec 042 | Autonomous-mode backend defaults | Per-vault `autonomy_level: interactive \| semi-auto \| full-auto` driving the scaffolder to write sensible auto-accept defaults across `.claude/`, `.codex/` and Ollama configs, with discoverable warnings in the vault's `CLAUDE.md`. Spec 007 pre-authorised tool calls; 042 sets the default *mode*. Three open questions with proposed defaults. | **Folded into #249** (D12): the unattended verb's `--auto-approve` policy is the autonomy level, and a per-vault settings key for it belongs to that spec, not a parallel one. | #249's spec is written — it names 042 back, and 042's folder then archives as `superseded(by …)`. |
| **#59** / spec 043 | Obsidian Canvas auto-generation | Two canvases per vault: `research-pipeline.canvas` (install-time, static — the configured pipeline) and `vault-state.canvas` (cycle-end refresh — newly added content, source-health gauges, open backlog), with strict preservation of user-owned nodes. Three open questions. | UX polish, not pipeline foundation; nothing depends on it. | An operator of a live vault asking for it. |
| **#60** / spec 044 | Vault mirror | Cycle-end optional `rsync -a --delete` of the full vault tree to a configured destination (cloud-synced folder, NAS, another machine); read-only; non-blocking on failure; pairs with 042 for unattended vaults needing a backup path. | **Tombstoned** 2026-09-08 (D12). Spec 040 ships the report mirror (`reports.mirror.target`), and the whole-tree copy is `./vault sync` — every vault is a git repo (Principle X) and pushing it is the backup path. | A need for a non-git full-tree copy that `./vault sync` plus 040's mirror cannot satisfy. Revive as a new spec; do not un-tombstone. |
| **#61** / spec 045 | Cost-efficiency v2 (post-033) | Spec 033 shipped the enforcement half (caps, approval gates; private 1.2.0 finished the ladder). 045 is the efficiency half: a cache-hit-ratio gate, `cost_per_substantive_note` as a gated 022 metric (already a live gated metric today), per-tier baselined guardrails. Four open questions. Soft-blocked by 030. | Spend is capped, not optimised; no vault has reported spend as its constraint. | A live vault whose limiting factor is cost the ladder cannot fix — i.e. a run that finishes under budget but with a `cost_per_substantive_note` the operator will not pay again. |
| **#147** / spec 065 | Local-model agentic fit (spike) | The first live opencode + local-Ollama validation (2026-06-12/13, on the back of 064) showed the plumbing clean — opencode dispatches, ~32 tok/s once the box's VRAM was un-wedged, 0 orphans — but local 27–30B models do not *complete* the autonomous structured stages: they research (grep/webfetch work) then chat-summarise instead of writing the scout JSON. Root-cause hypotheses: vendor-skewed prompts and bloated global agent context (the spec-047 Q1 debt), opencode's chat-posture `build` agent, tool-protocol mismatch. Spike directions: lean vendor-neutral local prompts, an output-forcing agent profile, **OpenHands** as an alternative agentic frontend, a spec-056 local capability sweep. Not a gate for private 1.0.0 (its validation campaign ran on `cursor-agent`). | A spike needs a chosen direction and a box to run on; `/speckit.plan` waits for the greenlight. | A local model that completes `scout` end-to-end on the shipped profile. Constitution 1.6.0 makes the local path a standing obligation, so this row is the one whose trigger the project actively works toward — spec 056's sweep is the instrument. |
| spec 059 | Movable `data_vault/` | `data_vault/` outside the vault root via symlink. Clarified 2026-06-03 (non-gating tensions), analysed, parked. | Principle X: relocated data must remain under append-only git history, and a symlink target outside the repo is not. Spec 044's use case ("a copy elsewhere") is covered by `./vault sync`. | A concrete reason the data must *primarily* live outside the root — storage tier, encryption, sharing — plus the Principle X resolution written as an ADR. |
| spec 054 | MCP-managed source access | Per-module `managed: true` routing a fetch to an MCP-capable subagent (Principle IV); three open questions (transport, agent-emits-what, declaration granularity). No tracking issue. | The 2026-06-08 MCP-free pivot: `github` and `atlassian` became REST modules and every live vault's sources are reachable without MCP. | A declared source reachable **only** through MCP. |
| spec 060 tiers | Source-module Tier 2-later / 3 / 4 | Tier 2-later: `newsletters`, `hackernews`, `wikipedia`, `blog_posts`, `conference_talks`, `github_extras`. Tier 3: `pdfs`, `podcasts`, `epub`, `twitter`, `mastodon`/`bluesky`. Tier 4: `social_bookmarklet` (CSV import). Parked: slack/discord exports, email, notion, goodreads. Governed by 060's prioritisation criteria, the per-module acceptance bar (020 five-file template, hermetic contract tests, 022 non-regression, mandatory 051 `preflight()`, zero new deps) and the 020 contract-amendment gate. | Demand-driven: the two batches that shipped (`youtube`/`reddit`/`rss`/`oreilly`; `github`/`atlassian`) were what live vaults declared. | A live vault declaring a source of that kind. One green ship before parallel ports (060's kickoff rule). |

---

## What left this file, and where it went

- The private line's **v1.0.0 release checklist**, the **rc1 pipeline status matrix**, the
  **wave narratives** and **"Completed (recent)"** → the shipped registry
  above and `CHANGELOG.md`; per-spec detail is in each spec's `**Status**:`
  header.
- The **`#N` queue numbering** → gone. Cross-references of the form
  "queue #18 / spec 041" now cite the spec number alone; the specs that carry
  the old numbers are frozen history and were not edited.
- **"Strategic Sequencing"** (2026-06-04) → the arc it described is complete;
  the registry is its record. The current ordering rationale is
  § Sequencing decisions.
- **Issue conventions and the label taxonomy** → `CONTRIBUTING.md` § 8.
- **"Notes on decisions already made"** → they are ADRs and constitution
  principles now (single dispatch surface = Principle IV / spec 078;
  flat-file interfaces = spec 075; cost cap at `agent_call` = spec 033;
  foreman = ADR-0010).
