# Contributing to research-framework

> **Read these first**:
> 1. `.specify/memory/constitution.md` — the inviolable principles (15 min).
> 2. `ARCHITECTURE.md` — how the system fits together (20 min).
> 3. This file — how to actually contribute.
>
> Total prerequisite reading: ~1 hour. Do not skip this — most "obvious"
> implementation choices are explicitly forbidden somewhere in the
> constitution.

---

## 1. Project setup

```bash
git clone <repo>
cd research-framework
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -m "not e2e"           # fast loop (count: docs/testing-strategy.md TL;DR marker)
pytest -m e2e                 # tier-5/6 cycle e2e (fake agent; no money)
pytest                        # full sweep (live_llm skipped by default)
python scripts/guards/run_all.py   # guard battery — what the pre-commit hook runs
pytest --live-llm             # opt-in: actually call real claude/codex (real money)
ruff check .                  # must be clean (zero errors)
ruff format --check .         # format baseline (enforced in build.sh as of PR #5)
./build.sh                    # smoke gate (mandatory on pipeline-touching changes)
./build.sh --quality          # smoke + spec-022 quality harness (3 fixtures, regression diff)
./scripts/install-git-hooks.sh # one-time: point git at the tracked .git-hooks/ pre-commit hook
```

Run `./scripts/install-git-hooks.sh` once per clone (or per worktree —
`git config` is local to each `.git` directory): it points git at the
tracked `.git-hooks/` directory so every commit runs
`python scripts/guards/run_all.py` (the full guard battery — portability
+ every corpus-level guard test, one pass/fail summary naming which
guard failed) before it lands. That local battery IS the merge gate:
since #323/#324 `ci.yml` runs only on version tags and by hand, so a PR
reports its own local run and CI showing nothing on a PR is expected.
See `docs/testing-strategy.md` § Guard battery aggregator for what the
battery does and does not cover.

Python 3.11+ required (per `pyproject.toml`). Type hints required.
Formatted with `ruff format` (PEP 8, 88 chars). Linted with `ruff
check`. Tested with `pytest`. Both `ruff check` and `ruff format
--check` are non-skippable gates inside `build.sh` (added in PR #5,
2026-05-25).

---

## 2. Documentation taxonomy

Multiple doc files exist; each has a specific job. Confusion here
duplicates work and silently outdates references. The rules:

| File | Scope | Lifespan | Source of truth for... |
|------|-------|----------|------------------------|
| `README.md` | Repo entry point | Long | "What is this project?" + install links |
| `ARCHITECTURE.md` | System design | Long | "How does the whole thing fit together?" |
| `CONTRIBUTING.md` (this file) | Dev workflow | Long | "How do I add a feature / spec / fix?" |
| `CHANGELOG.md` | Release history | Long | "What shipped in each version?" |
| `docs/ROADMAP.md` | Shipped registry + the next two releases as tiers + Deferred | Long; replaced wholesale 2026-09-08 | **THE source of truth for "what comes next"** |
| `docs/TODO.md` | Scratchpad | **Throwaway**; often empty | Capture ideas BEFORE they're triaged into ROADMAP or a GitHub issue |
| `docs/RELEASE.md` | Release procedure + user install/update | Long | "How is a version cut, and how does a vault take it?" — the only copy of the procedure |
| `docs/adr/NNNN-*.md` (+ `docs/adr/README.md`, the guarded index) | Architectural decisions | Long, append-only | "Why did we choose X over Y?" |
| `docs/testing-strategy.md` | Test pyramid + the one committed test count + the guard battery | Long | "How do we test? Which tier for what? What runs where?" |
| `docs/PORTABILITY.md` | macOS/Linux rules + the portability guard | Long | "Will this shipped script run on the other OS?" |
| `docs/foreman.md` | Foreman parser contract (ADR-0010) | Long | "What does `### Testing Requirements` have to look like?" |
| `docs/observability-strategy.md`, `docs/sandbox-detection.md`, `docs/source-credibility.md` | Topic references (specs 048 / 032 / 055) | Long | Operator-facing detail a spec is too formal for |
| `docs/prompts/` | **Generated** prompt corpus (`scripts/render_prompt_corpus.py --check` guards it) | Regenerated, never hand-edited | "What text does the model actually see?" |
| `.specify/memory/constitution.md` | Inviolable principles | Long, amended carefully | The principles, plus the Enforcement Register (what actually enforces each) and the Cross-Repo Obligations register |
| `specs/README.md`, `specs/_archive/README.md` | Guarded spec indexes | Long | "Which specs exist, in what state, and why is that one archived?" |
| `specs/NNN-name/spec.md` | Per-feature scope | Long, frozen at ship | "What should this feature do?" |
| `specs/NNN-name/plan.md` | Per-feature implementation | Long, frozen at ship | "How will we build it?" |
| `specs/NNN-name/research.md` | Per-feature decisions | Long, frozen at ship | "Why these implementation choices?" |
| `specs/NNN-name/tasks.md` | Per-feature task list | Long, frozen at ship | "What's the work breakdown?" |
| `specs/NNN-name/contracts/` | Per-feature interfaces | Long, frozen at ship | "What's the JSON shape / prompt template?" |
| `CLAUDE.md` | Agent context — generated digest + hand-maintained discipline sections | Corrected per release | Just-in-time context; the guarded sources win where they disagree |
| `tests/README.md` | Test-tree map + marker/automation matrix | Long | "Where does a test go, and what runs it?" |
| `.agents/skills/README.md` | Skill inventory + file shape | Long | "Which prompts exist and where does each run?" |
| `AGENTS.md` | Spec-kit placeholder (4 lines) | — | Nothing yet; generated vaults get a real `AGENTS.md` from the template |

**Every `spec.md` carries exactly one canonical `Status` field** (the
`**Status**:` bold field the template puts near the top; the handful of
"simple spec" files that also carry a terse YAML frontmatter `status:` tag
treat that bold field as authoritative — see `scripts/normalize_spec_status.py`).
Its value MUST open with one of five tokens, each a closed state plus the
evidence that earned it: `planned`, `in-progress`,
`shipped(<YYYY-MM-DD>, <PR #N | commit <sha> | version <X.Y.Z[rcN]>>)`,
`superseded(by <ref>)`, `archived`. Free text may follow the token — only
the opening token is checked — so nothing a spec already said has to be
cut to comply. `tests/docs/test_spec_status_headers.py` enforces this on
every spec; a header whose claim is genuinely compound (shipped AND some
part of its own scope still open) is named in that test's
`KNOWN_AMBIGUOUS` map with the reason, rather than forced into a token
that would misstate it. A spec's `tasks.md` follows the same honesty rule
once its `spec.md` reaches `shipped(...)`: `- [x]` boxes become a plain,
unchecked-marker-free ledger (`scripts/ledgerize_shipped_tasks.py`,
enforced by `tests/docs/test_shipped_tasks_are_a_ledger.py`) instead of
pretending to be a live gate nothing reads; a leftover `- [ ]` is left
alone because on a shipped spec that is real signal, not noise.

### Where to put a new piece of information

```text
Is it an inviolable principle?
└── YES → constitution.md (rare; requires SC v1 → v2 amendment)
└── NO ↓

Is it a per-feature design decision?
└── YES → specs/NNN/research.md or specs/NNN/spec.md
└── NO ↓

Does it cross spec boundaries OR reverse a prior decision?
└── YES → docs/adr/NNNN-...md (new ADR)
└── NO ↓

Is it a future-work idea (no spec yet)?
└── triaged? → docs/ROADMAP.md
└── unsorted? → docs/TODO.md (scratchpad)

Is it a description of HOW the system works?
└── high-level structure → ARCHITECTURE.md
└── how-to-contribute → CONTRIBUTING.md (this file)
└── how-to-test specifics → docs/testing-strategy.md
```

**Do not duplicate.** If you find yourself writing the same paragraph in
two places, one of them should reference the other instead.

---

## 3. The spec-kit workflow

This project uses **spec-kit** for feature development. Every feature
goes through the same lifecycle of slash commands:

```text
/speckit.specify     → drafts specs/NNN-name/spec.md (the WHAT)
/speckit.clarify     → interactive Q&A; locks open decisions in spec.md
/speckit.plan        → drafts specs/NNN-name/plan.md (the HOW)
                        + research.md (decisions)
                        + data-model.md (entities)
                        + contracts/ (schemas + prompts)
                        + quickstart-*.md (user guides)
/speckit.tasks       → drafts specs/NNN-name/tasks.md (work breakdown)
/speckit.implement   → executes the tasks
```

Each command auto-commits via `.specify/extensions.yml` hooks. You can
defer commits by declining the prompt.

### Sketch of a new feature (the canonical flow)

```bash
# 1. Draft the spec
/speckit.specify
#    → A conversation. The agent will ask scope questions and produce
#      specs/NNN-feature-name/spec.md.

# 2. Lock the open questions
/speckit.clarify
#    → The agent identifies [NEEDS DECISION] markers and runs an
#      interactive Q&A to resolve each. Answers land in spec.md
#      "Clarifications" section.

# 3. Plan implementation
/speckit.plan
#    → The agent writes plan.md (implementation arc) and produces the
#      design artifacts (research.md, data-model.md, contracts/,
#      quickstart-*.md).

# 4. Break into tasks
/speckit.tasks
#    → The agent writes tasks.md with a numbered TDD-aware task list.

# 5. Implement
/speckit.implement
#    → The agent executes tasks one at a time, writing tests first
#      per Principle III, and committing per task or per block.
```

### When NOT to use spec-kit

- **Bug fixes <1 day of work**: just open a branch, write the test,
  fix the bug, PR. No spec needed. (If the bug reveals a design flaw,
  THAT may warrant an ADR.)
- **Doc-only changes**: same — no spec needed.
- **Refactors with no behavior change**: same.

**Use spec-kit when**: the change adds a new capability, changes a
contract, or touches multiple stages of the pipeline.

---

## 4. TDD discipline (Principle III, NON-NEGOTIABLE)

Tests MUST be written before or alongside every new script. Three
rules, no exceptions:

1. **Test first, then implementation.** If you find yourself writing
   implementation before a failing test exists, stop and write the
   test first. This is the rule that catches design errors before they
   ship.
2. **`--dry-run` for every vault-mutating script.** Dry-run testing on
   fixtures must occur before running any fix script on real vault
   data. F7 (the failure that cost us 71 damaged files) was caused by
   a script run without dry-run on a real vault.
3. **Run the suite before claiming "done."** `pytest -m "not e2e"`
   must pass. `ruff check .` must be clean. The smoke gate
   (`bash build.sh`) must pass for any change touching the
   pipeline's core.

### Choosing a test tier

`docs/adr/0008-testing-pyramid-restructure.md` is canonical for the seven
tiers and `docs/testing-strategy.md` carries the decision tree with worked
examples (and the one committed test count). This file used to carry its
own five-row table; it predated ADR-0008, inverted Tier 5's meaning — Tier 5
is *cycle e2e* through the hermetic `fake_agent.py`; a real `claude` /
`codex` call is the cross-cutting `@pytest.mark.live_llm` marker, not a
tier — and drifted, so it is a pointer now (#281: one source per fact).

If you're spending more than 10 minutes deciding the tier, read
`docs/testing-strategy.md` — it has a tier-decision flowchart with
worked examples.

### Test helpers you should use

- `tests/_helpers/fake_agent.py` — deterministic LLM stand-in.
  **Don't** monkey-patch `run_cycle_steps` directly; use `fake_agent`.
- `tests/_helpers/vault_factory.py::build_minimal_vault` — produces
  a working vault on disk in <100 ms. Use this instead of hand-rolling
  fixtures.
- `tests/_helpers/fake_repo.py` and `tests/_helpers/fake_module.py`
  (spec 020) — source-module test doubles.
- `tests/_helpers/fake_cli_binary.py` (#270) — fakes at the CLI-binary
  seam, for the runtimes `scripts/agent_call.py` spawns.

---

## 5. Code style

| Rule | Enforced by |
|------|-------------|
| Python 3.11+ | `pyproject.toml::requires-python` |
| Type hints on every function signature | Reviewer (no `mypy` in CI yet) |
| Format with `ruff format` (88-char line, PEP 8) | `ruff format --check .` (build.sh gate) |
| Lint with `ruff` | `ruff check` |
| No `print(...)` in library code; use `logging` | Reviewer |
| No `time.sleep(...)` in tests | Reviewer; use proper synchronization or fixtures |
| Imports sorted (`isort`-style) | `ruff` |

### Forbidden patterns

| Pattern | Why forbidden | Use instead |
|---------|---------------|-------------|
| Direct `claude` / `codex` / HTTP LLM calls outside `agent_call.py` | Bifurcates the cost story; breaks single-dispatch invariant | `agent_call.py` (see ARCHITECTURE.md §6) |
| Hardcoded domain vocabulary in templates / prompts / canonical schemas | Violates the domain-agnostic invariant (Constitution 1.3.2 expansion; NB: this is _not_ the post-1.4.0 Principle X, which is the auto-commit invariant) | Derive from spec at runtime; few-shot examples are OK for illustration |
| Skipping `--dry-run` testing of a vault-mutating script | F7 cost us 71 damaged files | `--dry-run` is mandatory; test on fixtures first |
| Adding an external runtime dependency without justification | Violates Principle V; offline-first invariant | Stdlib first; declare + justify any new dep in PR description |
| A second package root (a top-level `research_vault/`, the pre-0.2.33 name, or anything outside `src/research_framework/`) | The rename shipped in 0.2.33; two roots fork imports and the wheel's force-include | Everything net-new goes under `src/research_framework/`; vault-facing scripts under `scripts/` |
| Empty function bodies or `# TODO` stubs in deliverables | Violates Principle VIII (No Placeholders) | Implement now or don't ship now |
| Treating cycle TERMINATE as Phase 1 complete | Violates Principle II | Re-enter Phase 2 with targeted prompt; check coverage-targets.json |
| macOS-only constructs in shipped scripts/code (`sed -i ''`, `/opt/homebrew`, bash-4 `${v^^}`) | Breaks Linux + non-Homebrew macOS; the framework is macOS-first but Linux-parity | Run `python scripts/check_portability.py`; see [`docs/PORTABILITY.md`](docs/PORTABILITY.md) |

### Required patterns

- **All LLM calls go through `agent_call.py`.** If your stage needs a
  cheap call, add a tier to `settings.yaml::tiers` and reference it
  via `tier: basic` in your stage config — DON'T import a vendor SDK.
- **All vault-mutating scripts have `--dry-run`.** And `--verbose`.
- **All scripts have exit codes 0 (pass), 1 (TERMINATE), 2 (abort)**
  per the constitution's Script Exit Code Model.
- **All vault paths derived from `vault_root` parameter**, never
  hardcoded. Serving N vaults through one engine is spec 023 Phase 2
  (`docs/ROADMAP.md` v1.2.0); respect the invariant now.

---

## 6. Adding an ADR

ADRs (Architecture Decision Records) capture cross-cutting decisions
in `docs/adr/`. They're **append-only**: to change an ADR's decision,
write a new one that supersedes it.

### When to write an ADR

| Decision type | Goes in... |
|---------------|------------|
| Crosses spec boundaries (affects multiple specs / files in different specs) | **ADR** |
| Reverses a prior decision (constitutional or architectural) | **ADR** |
| Adds an invariant that downstream specs must respect | **ADR** + possibly a constitution amendment |
| Limited to one spec | `specs/NNN/research.md`, NOT an ADR |
| Per-feature decision with no downstream impact | `specs/NNN/spec.md` "Clarifications" section |

### How to add one

1. Pick the next sequential number — read it off `docs/adr/README.md`'s
   index (the number is not quoted here because it goes stale).
2. Write `docs/adr/NNNN-kebab-title.md` using the MADR-ish format from
   `docs/adr/README.md`.
3. Status starts as `Accepted` (we don't draft separately; if you're
   writing an ADR, the decision has been made).
4. Date is the date you wrote it.
5. Add a row to the index table in `docs/adr/README.md`.
6. Commit. **Do not edit accepted ADRs later** — supersede them
   instead (write a new ADR; mark the old one
   `Superseded by ADR-NNNN`).

---

## 7. Constitution amendments

Changes to `.specify/memory/constitution.md` follow a stricter
process than other files because the constitution is the agent's
reference for what's inviolable.

### Versioning

- **MAJOR** (1.x.x → 2.0.0): backward-incompatible governance or
  principle removals/redefinitions
- **MINOR** (1.3.x → 1.4.0): new principle, new section, or
  materially expanded guidance — **and any enforcement downgrade**:
  discovering that a mechanism the constitution cited never ran, could
  not fail, or was narrower than the principle it sat under. Finding
  out a rule was never enforced is material, not cosmetic. This is what
  1.4.0 → 1.5.0 was.
- **PATCH** (1.3.1 → 1.3.2): clarifications, wording, typo fixes,
  non-semantic refinements

### Amendment procedure

1. **Immutable Architecture Decisions** (the section by that name in
   the constitution) require an ADR before any change.
2. **All other amendments** require a version bump and a **Sync Impact
   Report** prepended as an HTML comment at the top of the file. Look
   at the existing reports for the format (you can copy v1.3.2 as a
   template).
3. **Dependent templates** (`plan-template.md`, `spec-template.md`,
   `tasks-template.md`) MUST be reviewed when principles change. If
   they need updates, do them in the same commit. Record each by name
   with its verdict in the Sync Impact Report.
4. **Re-verify the Enforcement Register.** Any amendment touching a
   principle must check that principle's row (invariant → mechanism →
   failure mode → status) against the code, in the same PR. Rows are
   dated claims about the tree; unchecked, they rot into the exact
   fiction the register was added to remove.
5. **Cross-repo contracts are mirrored, not shared** (Principle XI).
   An amendment that changes a row in § Cross-Repo Obligations must
   name the sibling repo's mirrored copy and say whether it changed.

---

## 8. Branching & commits

| When | Branch name pattern |
|------|---------------------|
| Spec-kit feature | `NNN-feature-name` (the spec number + kebab name) |
| Bug fix | `fix/short-description` |
| Documentation | `docs/short-description` |
| Refactor | `refactor/short-description` |

### Commit hooks

`.specify/extensions.yml` registers `before_*` / `after_*` hooks on
spec-kit commands. Auto-commit is **OPT-IN** at each prompt; you can
decline if you're mid-fix. The hooks exist because losing context
between sessions is the project's #1 pain point — the auto-commits
give us recoverable session boundaries.

### Issue labels

Four namespaces; an issue carries exactly one `epic:`, one `priority:` and
one `type:`, plus optional `kind:` facets. The set as of 2026-09-08:

| Group | Labels |
|-------|--------|
| `epic:` (13) | `budget-enforcement`, `docs-readiness`, `failure-reporting`, `future-stubs`, `harness-fidelity`, `horizon-2`, `horizon-3`, `operator-surface`, `post-revival-sweep`, `revival-sprint`, `vault-contract`, `verify-correctness`, `wave-2-modules` |
| `priority:` (4) | `critical`, `high`, `medium`, `low` |
| `type:` (5) | `spec`, `bug`, `cleanup`, `housekeeping`, `infrastructure` |
| `kind:` (9) | `budget-guard`, `cli-verb`, `correctness`, `docs-corpus`, `operator-ux`, `telemetry`, `test-fidelity`, `tier-1-module`, `tier-2-module` |

One issue per spec (title `Spec NNN: <title>`, or a `type:spec` issue whose
body names its spec); the merging PR carries `Closes #N`. Milestones are all
closed and new issues take none. `CLAUDE.md` § GitHub issue + milestone
hygiene has the per-stage checklist.

### Commit message style

```text
<type>: <short imperative summary>

Optional body — what changed, why, and any constraint preserved.
Reference spec number if applicable.

Refs: spec-NNN, ADR-NNNN, ROADMAP item
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`,
`research`, `spec`, `audit`, `migration`.

### Pre-PR checklist

Before opening a PR:

- [ ] `pytest -m "not e2e"` passes, and `pytest -m e2e` if you touched
      the cycle path
- [ ] `python scripts/guards/run_all.py` passes (the pre-commit hook
      runs it; run it by hand if the hook is not wired)
- [ ] `ruff check .` and `ruff format --check .` both clean — they are
      separate gates
- [ ] If touching pipeline core: `bash build.sh` smoke gate passes
- [ ] Tests written for new functionality (Principle III)
- [ ] `--dry-run` exists for any new vault-mutating script
- [ ] If invariant added: ADR drafted
- [ ] If principle touched: constitution amended with Sync Impact Report
- [ ] If new ADR / spec: added to its index table
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] If this ships a spec: PR body contains `Closes #<spec-issue>`
      so the tracking issue auto-closes on merge (see
      `CLAUDE.md` "GitHub issue + milestone hygiene")
- [ ] Branch up-to-date with `main`; the PR body carries the real
      local counts (CI runs only on version tags — see below)

### Cutting a release

`docs/RELEASE.md` is the procedure and the only copy of it. The short
form: bump `pyproject.toml`, promote `[Unreleased]` to
`[X.Y.Z] - <tag date>` in `CHANGELOG.md`, run the local gates, merge the
`release: X.Y.Z` PR, then tag the merge commit `vX.Y.Z` and push the tag —
**the tag is the release trigger.** Every workflow runs
on `v*` tags and `workflow_dispatch` only; there is no push-to-`main`
auto-detect, and adding a `pull_request` / `push` / `schedule` trigger is
forbidden (`CLAUDE.md` § CI budget). The local suite is the merge gate.

After the run, the Release appears at
`https://github.com/<owner>/<repo>/releases/tag/vX.Y.Z` with three
artifacts:

| Artifact | What it's for |
|----------|---------------|
| `research-framework-X.Y.Z.tar.gz` | Install bundle (run `./install.sh`) — what most users want |
| `research_framework-X.Y.Z-py3-none-any.whl` | Pip-installable wheel (CLI access only, no bundle) |
| `research_framework-X.Y.Z.tar.gz` | Python sdist |

---

## 9. Common gotchas

These are the rakes we've stepped on. Avoid stepping on them again.

### Single LLM dispatch surface (Principle IV; spec 078)

Every LLM call goes through `scripts/agent_call.py` — there has never been
a `pipeline/agent_call.py`, whatever older docs say (078 T001).
"Just this once" exceptions become permanent and break:
- Cost capture (no per-call cost recording)
- Hard budget cap (un-enforceable past a second dispatch surface)
- Tier resolution (spec 020 D7)
- Per-call audit logging (spec 020 FR-024)

If you need a quick LLM call, plumb through `agent_call.py`. The
overhead is negligible.

### Domain-agnosticism (Constitution 1.3.2 expansion; **NB**: distinct from the post-1.4.0 Principle X, which is the auto-commit invariant)

Canonical schemas and structural decisions MUST be derivable from the
spec at runtime — never hardcoded. Spec 020 ran headfirst into this
during clarification: we initially wrote example `facts` schemas with
web-vocabulary buckets ("api_protocols", "external_services"). The
clarification process caught it and pivoted to dynamic schema-gen
per (vault, module) pair so a childcare vault and an embedded-firmware
vault each get a different schema derived from THEIR spec.

When in doubt, ask: "Would this code work the same way for a vault
about embedded firmware? Childcare? Legal research?" If no, refactor
to read from the spec.

### Two-tier citation (Principle IX, NON-NEGOTIABLE)

The verifier rejects any output that doesn't render BOTH tiers
distinctly. Don't bury Tier-2 (original source URLs) inside Tier-1
(vault wikilink) prose — the verifier sees this as a violation. Use
the dedicated `Vault Sources` and `Original Sources` sections in
`/ask` and `/write` outputs.

### Stub-as-Fuel (Principle VIII, since 1.3.0)

Stubs no longer abort runs — they're CONTINUATION TRIGGERS. The
orchestrator runs another cycle as long as ANY of these is true:
- Scout discovered new topics
- `_pipeline/research-backlog.md` is non-empty
- Any note matches stub criteria (low word count, no Tier-2 sources,
  verifier `pending`/`rejected`, lifecycle `draft`)

A vault is "done" ONLY when all three are false AND coverage targets
are met. If you find yourself writing "abort on stub," you're
inverting the principle.

### Scout topic enumeration

When extending the scout's topic-discovery loop, every topic MUST be
tagged with both a dimension (Technical / Organizational / Domain /
Market / Temporal) and a note-type. If your code synthesizes topics
without dimension+type tags, `validate_cycle.py` will reject the run.

### Wikilink case (ADR-0005)

Wikilinks are case-sensitive on Linux but case-insensitive on macOS.
Cycle-time normalization (`src/research_framework/pipeline/wikilinks.py`)
handles this so vaults are portable. **Don't add code that
manipulates wikilinks without going through this module** — it's
the single source of normalization rules.

---

## 10. Useful commands

```bash
# Run all tests except e2e
pytest -m "not e2e"

# Run a specific test
pytest tests/pipeline/test_orchestrator_retry.py -v

# Run the full sweep including e2e (slow, ~5 min)
pytest

# Lint
ruff check .

# Format
ruff format .

# Build + smoke gate
bash build.sh

# Generate a new vault from a spec (for local testing)
./generate_vault.sh examples/research.spec.md --output ~/vaults/test-vault

# Update CLAUDE.md from current spec
.specify/scripts/bash/update-agent-context.sh claude
```

---

## 11. Where to ask for help

| Question | Where to look |
|----------|---------------|
| "How does X work?" | `ARCHITECTURE.md` |
| "Why is X this way?" | `docs/adr/` (search) or `specs/NNN/research.md` |
| "What's the next thing to ship?" | `docs/ROADMAP.md` — the first `[ ]` row in the v1.1.0 tier |
| "Is X allowed?" | `.specify/memory/constitution.md` — read its Enforcement Register table first; it is the index |
| "How do I test this?" | `docs/testing-strategy.md` |
| "What was decided about Y in spec-020?" | `specs/020-code-bridge/research.md` |

If after all that you're still stuck: open a GitHub issue with
context (what you tried, what you read, where you got stuck). Good
issues describe the *gap* in the documentation as much as the
question — every "where do I look for X?" is a doc-improvement
opportunity.
