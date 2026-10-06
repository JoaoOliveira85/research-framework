# The spec corpus

Every feature in this repo is specified under `specs/NNN-kebab-name/`. This
file is the index: what exists, what state it is in, and where the history
went. `tests/docs/test_spec_index_completeness.py` fails if a folder is
missing from a table here or listed in the wrong one, so the index cannot
quietly rot the way an unchecked table does.

## How to read a row

The **Status** column reproduces the opening token of the spec's own
canonical `**Status**:` header — one of `planned`, `in-progress`,
`shipped(<date>, <ref>)`, `superseded(by <ref>)`, `archived` (CONTRIBUTING.md
§ 2; enforced by `tests/docs/test_spec_status_headers.py`). Nine specs make a
compound claim their header deliberately does not resolve — shipped *and*
some part of their own scope still open. Those show `_(compound — see the
spec)_` here and are named with a reason in that test's `KNOWN_AMBIGUOUS`
map. Trust the spec's own header over this column if they ever disagree; this
column is a convenience, the header is the record.

The **Title** column is the spec's own H1.

## The numbering rule

1. **Numbers are allocated once and never reused.** The next spec takes the
   next unused integer above the highest number in *either* table below —
   including archived ones. Archiving frees a folder from the active corpus,
   never its number: a reader who finds `spec 034` cited in a 2026-05 commit
   message must land on the same document that commit meant.
2. **A number never changes when a folder moves.** Archiving is a `git mv`
   into `_archive/`, keeping the `NNN-kebab-name` directory name intact, so
   the history follows the file and every citation is fixable by inserting
   one path segment.
3. **Letter suffixes (`015a`…`015h`) are closed.** They exist because spec
   015's consolidation was split into sub-specs mid-flight. Do not create
   new ones — a sub-feature that deserves its own spec deserves its own
   number.
4. **The branch takes the folder name** (`NNN-feature-name`, CONTRIBUTING.md
   § 8).

## Active corpus

The specs that describe the system as it is or as it is planned to be. These
are the ones the guards grade: acceptance coverage
(`tests/spec/test_acceptance_coverage_guard.py`), Status vocabulary, and the
shipped-task ledger.

| Spec | Title | Status |
| --- | --- | --- |
| [`001-speckit-implementation`](001-speckit-implementation/spec.md) | Speckit — Knowledge Vault Generator | _(compound — see the spec)_ |
| [`003-topic-harvest-stage`](003-topic-harvest-stage/spec.md) | Topic harvest stage (003) | shipped(2026-05-04, commit a3ef8dd) |
| [`009-linux-support`](009-linux-support/spec.md) | Cross-Platform Portability Guard + PR CI | shipped(2026-06-04, PR #113) |
| [`013-vault-migrator`](013-vault-migrator/spec.md) | Vault Migrator (PARTIALLY WITHDRAWN) | superseded(by ./vault update) |
| [`015f-processors-in-framework`](015f-processors-in-framework/spec.md) | Processors in the Framework | shipped(2026-05-21, commit e73b6de) |
| [`017-vault-quality-fix`](017-vault-quality-fix/spec.md) | Vault Quality Fix | _(compound — see the spec)_ |
| [`018-testing-strategy`](018-testing-strategy/spec.md) | Layered Testing Strategy | shipped(2026-05-17, version 0.2.23) |
| [`019-pipeline-architecture`](019-pipeline-architecture/spec.md) | Pipeline Architecture & Seam-Bug Elimination | _(compound — see the spec)_ |
| [`020-code-bridge`](020-code-bridge/spec.md) | Source-Module Architecture — Cached, Pluggable Data Source Access | shipped(2026-05-27, PR #32) |
| [`021-spec-driven-coverage`](021-spec-driven-coverage/spec.md) | Spec-Driven Coverage Pursuit | planned |
| [`022-e2e-quality-harness`](022-e2e-quality-harness/spec.md) | E2E Quality + Test Harness | _(compound — see the spec)_ |
| [`023-flow-separation`](023-flow-separation/spec.md) | Flow Separation + Multi-Vault + Assistant-Framework Integration | _(compound — see the spec)_ |
| [`024-testing-infrastructure-v2`](024-testing-infrastructure-v2/spec.md) | Testing Infrastructure v2 — Phase 2 + Discipline Layer | shipped(2026-05-21, version 0.3.0) |
| [`026-fixture-isolation`](026-fixture-isolation/spec.md) | Fixture Isolation Hardening | shipped(2026-06-04, PR #107) |
| [`027-vault-update-hardening`](027-vault-update-hardening/spec.md) | `./vault update` Hardening | shipped(2026-06-03, PR #99) |
| [`028-dispatch-telemetry`](028-dispatch-telemetry/spec.md) | `dispatch()` Telemetry Capture + Sidecar Collision Fix | shipped(2026-05-27, PR #28) |
| [`029-source-manager-correctness`](029-source-manager-correctness/spec.md) | Source Manager Correctness | shipped(2026-06-04, PR #108) |
| [`030-quality-harness-v3`](030-quality-harness-v3/spec.md) | Quality Harness v3 | planned |
| [`032-pipeline-reliability`](032-pipeline-reliability/spec.md) | Pipeline Reliability Hardening | shipped(2026-06-03, PR #100) |
| [`033-cost-enforcement`](033-cost-enforcement/spec.md) | Cost Enforcement | shipped(2026-05-27, PR #31) |
| [`035-cross-cycle-digest`](035-cross-cycle-digest/spec.md) | Cross-Cycle Digest | shipped(2026-06-04, PR #117) |
| [`036-assistant-framework-integration`](036-assistant-framework-integration/spec.md) | Assistant-Framework Integration | planned |
| [`037-consensus-abstraction`](037-consensus-abstraction/spec.md) | Multi-Agent Consensus Abstraction | planned |
| [`038-source-module-resilience`](038-source-module-resilience/spec.md) | Source-Module Resilience Polish | shipped(2026-06-03, PR #101) |
| [`039-installer-hardening`](039-installer-hardening/spec.md) | Installer Hardening | shipped(2026-06-04, PR #109) |
| [`040-vault-reports-delivery`](040-vault-reports-delivery/spec.md) | Rich Vault Reports + Delivery | shipped(2026-06-04, PR #118) |
| [`041-release-infrastructure-v2`](041-release-infrastructure-v2/spec.md) | Release Infrastructure v2 | planned |
| [`042-autonomous-mode-backend-defaults`](042-autonomous-mode-backend-defaults/spec.md) | Autonomous-Mode Backend Defaults | planned |
| [`043-obsidian-canvas-autogen`](043-obsidian-canvas-autogen/spec.md) | Obsidian Canvas Auto-Generation | planned |
| [`044-vault-mirror`](044-vault-mirror/spec.md) | Vault Mirror | planned |
| [`045-cost-efficiency-v2`](045-cost-efficiency-v2/spec.md) | Cost-Efficiency v2 | planned |
| [`048-observability-v1`](048-observability-v1/spec.md) | Observability v1 — Runtime Logging, Live Status, and Subprocess Audit | shipped(2026-05-29, version 0.5.0) |
| [`050-vault-auto-commit`](050-vault-auto-commit/spec.md) | Mandatory Vault Auto-Commit Invariant | shipped(2026-06-01, version 0.7.0) |
| [`051-post-revival-hardening`](051-post-revival-hardening/spec.md) | Post-Revival Hardening | shipped(2026-06-02, PR #91) |
| [`052-cursor-cli-executor`](052-cursor-cli-executor/spec.md) | Cursor CLI Executor — third cost-driven runtime | shipped(2026-06-08, PR #131) |
| [`053-source-authority-strategy`](053-source-authority-strategy/spec.md) | Plastic-but-Enforceable Source Authority | _(compound — see the spec)_ |
| [`054-mcp-managed-access`](054-mcp-managed-access/spec.md) | MCP-Managed Source Access | planned |
| [`055-source-credibility-model`](055-source-credibility-model/spec.md) | Source Credibility Model (Contextual Tiering) | shipped(2026-06-04, PR #112) |
| [`056-executor-benchmark`](056-executor-benchmark/spec.md) | Executor × Model Benchmarking Harness | shipped(2026-06-08, PR #139) |
| [`057-foreman-retro-matcher`](057-foreman-retro-matcher/spec.md) | Foreman Retro Coverage — Tolerant Matching Mode | _(compound — see the spec)_ |
| [`058-vault-spec-health-warning`](058-vault-spec-health-warning/spec.md) | Vault Control-File Git-Tracking Health Warning | shipped(2026-07-01, PR #183) |
| [`059-movable-data-vault`](059-movable-data-vault/spec.md) | Movable `data_vault/` (data outside the vault root) | planned |
| [`060-source-modules-tier2`](060-source-modules-tier2/spec.md) | Source-Module Tier 2+ Port Wave (governance umbrella) | _(compound — see the spec)_ |
| [`061-cycle-budget-config`](061-cycle-budget-config/spec.md) | Cycle-budget configuration consolidation | shipped(2026-06-06, PR #126) |
| [`062-vault-output-integrity`](062-vault-output-integrity/spec.md) | Vault output integrity on constrained exit | shipped(2026-06-06, PR #126) |
| [`063-acceptance-harness`](063-acceptance-harness/spec.md) | Acceptance harness | shipped(2026-06-06, PR #126) |
| [`064-opencode-executor`](064-opencode-executor/spec.md) | opencode Executor (provider-agnostic agentic runtime) | shipped(2026-06-13, PR #146) |
| [`065-local-model-agentic-fit`](065-local-model-agentic-fit/spec.md) | Local-Model Agentic Fit (spike) | planned |
| [`066-credibility-model-calibration`](066-credibility-model-calibration/spec.md) | Credibility-model calibration for canonical project domains | shipped(2026-06-15, PR #175) |
| [`067-acronym-wikilink-disambiguation`](067-acronym-wikilink-disambiguation/spec.md) | Acronym-wikilink disambiguation | shipped(2026-06-15, PR #172) |
| [`068-coverage-counting-correctness`](068-coverage-counting-correctness/spec.md) | Coverage counting correctness | shipped(2026-06-15, PR #171) |
| [`069-source-relevance-tuning`](069-source-relevance-tuning/spec.md) | Source-relevance tuning + declared-source validation | _(compound — see the spec)_ |
| [`070-strategy-hint-credibility-and-silent-resume`](070-strategy-hint-credibility-and-silent-resume/spec.md) | strategy_hint credibility grounding + non-silent resume | shipped(2026-08-27, PR #194) |
| [`071-archived-vaults`](071-archived-vaults/spec.md) | archived vaults | shipped(2026-08-27, PR #195) |
| [`072-auto-merge-research-branch`](072-auto-merge-research-branch/spec.md) | auto-land a completed run on `main` | shipped(2026-08-29, PR #204) |
| [`073-query-driven-spec-append`](073-query-driven-spec-append/spec.md) | query-driven spec append | shipped(2026-08-30, PR #201) |
| [`074-cycle-target-topics-discarded`](074-cycle-target-topics-discarded/spec.md) | Bug: `cycle --target-topics` has no effect | shipped(2026-08-30, PR #202) |
| [`075-pipeline-runner`](075-pipeline-runner/spec.md) | The weekly pipeline runner | shipped(2026-09-07, commit 6935644) |
| [`076-settings-schema`](076-settings-schema/spec.md) | The `settings.yaml` schema | shipped(2026-09-07, commit 6935644) |
| [`077-cli-contract`](077-cli-contract/spec.md) | The CLI contract — verbs, flags and exit codes | shipped(2026-09-07, commit 6935644) |
| [`078-dispatch-surface`](078-dispatch-surface/spec.md) | The `agent_call` dispatch surface | shipped(2026-09-07, commit 6935644) |
| [`079-note-format`](079-note-format/spec.md) | The note and frontmatter format | shipped(2026-09-08, commit 943c7d3) |
| [`080-run-receipt`](080-run-receipt/spec.md) | The run receipt — `_pipeline/runs/<run_id>/` | planned |
| [`081-triage-gate`](081-triage-gate/spec.md) | The triage gate | planned |
| [`082-spec-driven-verify`](082-spec-driven-verify/spec.md) | Spec-driven verify — the checkers read the vault's own declaration | planned |

## Archived corpus

History, not description. These folders record how the system got here and
are kept readable and citable — but they are not graded, not planned
against, and not a place to look for how anything works today. The rule that
put each one here, and where its subject lives now, is in
[`_archive/README.md`](_archive/README.md).

| Spec | Title | Status at archival |
| --- | --- | --- |
| [`004-python-pipeline`](_archive/004-python-pipeline/spec.md) | Python-Only Pipeline Orchestration + Verifier Wiring | shipped(2026-05-12, commit 604d192) |
| [`005-adaptive-sources`](_archive/005-adaptive-sources/spec.md) | Adaptive Sources | shipped(2026-05-13, commit 9d6f626) |
| [`006-vault-audit`](_archive/006-vault-audit/spec.md) | Vault Audit | shipped(2026-05-13, commit 3fd97a7) |
| [`007-autonomous-vault-settings`](_archive/007-autonomous-vault-settings/spec.md) | Autonomous Vault Operation Settings | shipped(2026-05-13, commit 102bdb5) |
| [`008-vault-script`](_archive/008-vault-script/spec.md) | Vault Unified Script | shipped(2026-05-13, commit 86339fe) |
| [`010-flow-separation`](_archive/010-flow-separation/spec.md) | Flow Separation & Active Maintenance | superseded(by spec 023) |
| [`011-llm-routing`](_archive/011-llm-routing/spec.md) | Per-Flow LLM Routing | superseded(by spec 025, spec 028, spec 033) |
| [`012-multi-vault`](_archive/012-multi-vault/spec.md) | Multi-Vault Pipeline | superseded(by spec 023) |
| [`014-reusable-collectors`](_archive/014-reusable-collectors/spec.md) | Reusable Collector Modules | superseded(by ADR-0009, spec 020) |
| [`015-pipeline-consolidation`](_archive/015-pipeline-consolidation/spec.md) | Pipeline Consolidation — Research Loop in the Framework | superseded(by ADR-0009, spec 020) |
| [`015a-corpus-folder-name`](_archive/015a-corpus-folder-name/spec.md) | Spec-Driven Corpus Folder Name | planned |
| [`015b-vault-inventory`](_archive/015b-vault-inventory/spec.md) | `research_vault inventory <vault>` | planned |
| [`015c-vault-onboarding`](_archive/015c-vault-onboarding/spec.md) | `research_vault onboard <vault>` | planned |
| [`015d-note-types-first-class`](_archive/015d-note-types-first-class/spec.md) | First-Class Note Type Taxonomies | planned |
| [`015e-agent-definitions-as-templates`](_archive/015e-agent-definitions-as-templates/spec.md) | Agent Definitions as Framework Templates | planned |
| [`015g-pipeline-orchestrator-command`](_archive/015g-pipeline-orchestrator-command/spec.md) | Pipeline Orchestrator as a Framework Command | superseded(by ADR-0009, spec 020, spec 023) |
| [`015h-retire-vault-local-scripts`](_archive/015h-retire-vault-local-scripts/spec.md) | Retire Vault-Local Scripts | shipped(2026-05-21, commit e73b6de) |
| [`025-simplify-pass`](_archive/025-simplify-pass/spec.md) | Code Simplification Pass (Tier A + B Refactor) | shipped(2026-05-22, version 0.3.1) |
| [`031-git-boundary`](_archive/031-git-boundary/spec.md) | Project-Wide Git Boundary Helper | superseded(by spec 050) |
| [`034-runtime-consolidation`](_archive/034-runtime-consolidation/spec.md) | Pipeline Runtime Consolidation | superseded(by ADR-0009, spec 020) |
| [`046-vault-specialities-plugin-model`](_archive/046-vault-specialities-plugin-model/spec.md) | Vault Specialities — Modular Plugin Model | superseded(by spec 053) |
| [`047-backend-agnostic-agent-layer`](_archive/047-backend-agnostic-agent-layer/spec.md) | Backend-Agnostic Agent Layer | superseded(by spec 064) |
| [`049-cycle-helpers-split`](_archive/049-cycle-helpers-split/spec.md) | `_cycle_helpers.py` God-Module Split | shipped(2026-06-03, PR #97) |

## What reads this file

| Reader | What it checks |
| --- | --- |
| `tests/docs/test_spec_index_completeness.py` | Every folder under `specs/` appears exactly once in the Active table and every folder under `specs/_archive/` exactly once in the Archived table — and nothing appears that is not a folder. |
| `tests/spec/test_acceptance_coverage_guard.py` | Grades the Active corpus only; `_archive/` is excluded by path segment. |
| `tests/docs/test_spec_status_headers.py` | Reads `specs/*/spec.md` (non-recursive), so it grades the Active corpus only. |
| `tests/docs/test_shipped_tasks_are_a_ledger.py` | Same non-recursive scope. |

Adding a spec means adding a row here in the same commit. The guard will tell
you if you forget.
