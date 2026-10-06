# research-framework — TODO (scratchpad)

> **Role of this file**: SCRATCHPAD + IMPLEMENTATION-DETAILS HOME.
> Two kinds of entries live here:
>
> 1. **Un-triaged ideas** — drop them here when they pop into your head;
>    triage to `docs/ROADMAP.md` (or a `specs/NNN-<name>/spec.md` stub)
>    when they're ready to be sequenced.
> 2. **Implementation details for items already on the ROADMAP queue** —
>    when an entry gets promoted to a ROADMAP queue item or QW, we leave
>    the rich design notes here (so the ROADMAP stays scannable) and add
>    a pointer to its ROADMAP tier row (the `QW-X` / `queue #N` numbering was
>    retired with the 2026-09-08 roadmap replacement) to the entry
>    heading.
>
> **`docs/ROADMAP.md` is always the source of truth** for what comes next
> and sequencing. This file holds the depth.
>
> **When an item fully ships**: DELETE its entry here (CHANGELOG + git
> history are the durable record). Per `CLAUDE.md` doc-discipline rule.
>
> **When an item is deferred, not shipped, and belongs to something already
> frozen** (a shipped spec, an ADR, a released version) — file a GitHub issue
> and delete the entry here, replacing it with a link. This file is a
> scratchpad: an item that only ever lives here has no durable owner, and
> deleting it on ship (or on drift, or by accident) is then a silent drop, not
> a resolution (#277). TODO.md is for ideas still too raw to have a home —
> the moment one has a clear owner (a spec, an ADR, a release), it earns
> either an entry there or a GitHub issue, not indefinite residence here.
>
> See `CONTRIBUTING.md` for the full documentation taxonomy.

---

## Open ideas (un-triaged)

This section is intentionally short. Promote items to `docs/ROADMAP.md`
or a `specs/NNN-<name>/spec.md` stub as soon as they're ready to be
sequenced.

### `rv generate --resume` UX paper-cut — first-run friendly default *(surfaced 2026-06-13, tracking issue #150)*

Surfaced live by the rc7 reference-vault validation run (`~/Documents/reference-vault-rc7/`).
The documented happy-path verb for re-running the cycle loop on an existing
vault is `rv generate --resume`. But on a **brand-new scaffolded vault with no
cycles yet**, `--resume` errors out:

```text
no in-progress cycle found; use `--cycle <N>` to specify
```

This is because the auto-detect in `cli/research_resume.py::_resume_cycle`
walks `_pipeline/state.json::in_progress_cycle` AND `max(cycle-NNN on disk) + 1`
— a fresh scaffold has neither, so the third branch hard-errors. The workaround
is `--resume --cycle 1` on the first invocation.

**Why this hurts**: `--resume` is the "safe to re-run if interrupted" flag
documented across the rc7 staging script + `docs/RELEASE.md`. Telling first-time
users "use `--resume` to start" then having it crash on the first run is the
worst possible onboarding bug. The fix is small and contained.

**Proposed fix** (one of):
1. **(preferred)** When `state.json::in_progress_cycle` is null AND there are no
   `cycle-NNN/` directories on disk, treat `--resume` as `--resume --cycle 1`
   silently (with an INFO log "no cycles on disk; starting at cycle 1"). This
   makes `--resume` idempotent across "first run", "interrupted resume", and
   "next cycle continuation" without the operator having to know which case
   they're in. ~15 LOC in `_resume_cycle()`, one test in
   `tests/cli/test_research_resume.py`.
2. **(alternative)** Keep the error but improve the message: "no cycles on disk;
   pass `--cycle 1` if this is the first invocation, or remove `--resume` to let
   Phase 0/1 scaffold."

The rc7 validation run's staging script (`run-reference-vault-validation.sh`)
already implements option 1 *outside* the CLI as a workaround. Closing this
TODO means deleting the workaround and using `--resume` directly.

**Effort**: trivial (~15 LOC + 1 test).
**Priority**: low-medium — annoying but the workaround is one extra flag, and
the staged script handles it for the validation campaign. Worth grouping with
other CLI ergonomics issues when one batch's worth accumulates.

### Codebase-vault rc1 — post-rc3 recovery + audit follow-ups *(operational, 2026-06-05)*

The 2026-06-05 codebase-vault rc1 acceptance evaluation's **framework findings are
now specs** (rc3 wave: **061** cycle-budget + **ADR-0011**, **062** vault-output
integrity, **063** acceptance harness, + amendments to **028** and **048 v2** — see
ROADMAP "v1.0.0 Release Checklist"). Remaining NON-framework / deferred items live
here until acted on:


### Foreman retro pass on already-shipped specs *(LOW priority)*

> ***(→ spec 057 "Foreman Retro Coverage — Tolerant Matching Mode". Mechanism
> SHIPPED [Unreleased] (PR #183, squash `c24cd22`, 2026-07-01) — `--tolerant`
> flag + `matching_mode` reporting, tested, strict mode unchanged. **Remaining**:
> SC-001 retro-rollout (T021–T025) — back-fill tolerant `### Testing
> Requirements` blocks onto specs 028/018/022/025 and run the verifier against
> each. Keep this entry until that rollout is acted on, then delete.)***

Strict-name foreman matching (ADR-0010 / `docs/foreman.md`) was too
brittle for retro on specs that shipped before the pattern existed.
The tolerant matcher (file-existence + at-least-one-passing-test per
file, ignoring exact function names) now exists — it would let us
validate specs 028/022/025/018 retroactively, but nobody has run it
against them yet. **Low priority** — shipped specs already passed
`./build.sh` smoke gate (ADR-0007), so retro is insurance not
diagnosis. Reference example preserved at unmerged branch
`test-design/028-retro` (commit `fc24a43`); delete when this TODO is
acted on.

### Cleanup — `td-028` worktree + branch *(deferred)*

`research-framework-td-028` worktree carries the 028-retro test-design
enrichment. Branch `test-design/028-retro` lives at commit `fc24a43`.
The tolerant matcher this was blocked on now exists (spec 057
mechanism, PR #183) — the retro pass above is unblocked. Still
unmerged until someone actually runs the retro-rollout above. Delete
when retro is acted on (or sooner if cluttering — the commit is still
preserved in `git reflog`).

---

## Implementation details (for active ROADMAP queue items)

---

## PR #2 Copilot review follow-ups *(tactical; ~9 items)*

Surfaced via Copilot's automated review on PR #2 (Foundation arc:
specs 022+024+025, merged 2026-05-22 as `f3db213`). None were merge
blockers (all describe behaviour already shipped, no fresh regression).
Worth picking off opportunistically when touching adjacent code.

### P2 — pick up next sprint (~0.25 day each)

- **#3 — `_probe_retrieval_enabled()` is too liberal**.
  `bool(stage_cfg.get("enabled"))` disables on `null`/`0`/`""` despite
  the docstring saying "unless explicitly false". Lives in
  `src/research_framework/pipeline/_cycle_helpers.py:1213`.
  **Fix**: `return stage_cfg.get("enabled") is not False`.
- **#6 — `_resolve_resume_cycle()` accepts `cycle <= 0`**. Validates
  `int` but not positivity. **Fix**: raise `SystemExit` for `cycle < 1`.
- **#8 — `live_llm` docstring vs enforcement mismatch**.
  `tests/processors/test_extract.py` docstring claims live tests are
  "skipped by default" but `@pytest.mark.live_llm` alone doesn't
  deselect. **Fix**: (a) add `-m "not live_llm"` to documented `pytest`
  commands in `CONTRIBUTING.md` / `CLAUDE.md`, OR (b) amend the
  docstring to reflect conditional-skip reality.

### P4 — when convenient

- **#4 — `_bootstrap_scripts_agent_call()` error message clarity**.
  Cosmetic / debuggability. Add `is_file()` check before
  `spec_from_file_location`, raise `ImportError(f"cannot find
  agent_call.py in any of: ...")`.

---

## Restoration notes — Tier-2 backlog index

<a id="restoration-notes"></a>

Items surfaced in the 2026-05-20 triage pass. Most have been promoted
to spec stubs or are referenced in active queue items; this index
shows where each lives now.

| Item | Promoted to |
|---|---|
| Decoupled raw URL capture (#10) | `specs/038-source-module-resilience/spec.md` |
| archive.org fallback (#11) | `specs/038-source-module-resilience/spec.md` |
| Per-module rate-limit + auth contract (#12) | `specs/038-source-module-resilience/spec.md` |
| Install preflight pain points (5 items) | `specs/038-source-module-resilience/spec.md` |
| AI-inferred frontmatter schema (#13) | `specs/_archive/046-vault-specialities-plugin-model/spec.md` *(rule-of-three blocked)* |
| Code-first validator bundle as speciality (#16) | `specs/_archive/046-vault-specialities-plugin-model/spec.md` |
| `DataSourceConfig.kind` field (#15) | ADR-0009 ACCEPTED (option A, 2026-06-01) — modules supersede collectors; fold into spec-020 manifest if still wanted |
| `.local.md` override mechanism (#4) | `specs/023-flow-separation/spec.md` Phase 2 (US4) |
| Headless `/ask` and `/write` contracts (#24) | `specs/023-flow-separation/spec.md` Phase 2 (US2) + `specs/036-assistant-framework-integration/spec.md` |
| Flat JSON active-sources export (#25) | `specs/023-flow-separation/spec.md` Phase 2 (US3) |
| Hybrid rebuild migration (#18) | Documentation pointer only (no spec). |
| Build-at-`-v2` pattern (#19) | Documentation pointer only (no spec). |
| Validate `prune` end-to-end (#21) | `specs/027-vault-update-hardening/spec.md` |
| Pre-maintenance planned-changes report (#22) | `specs/_archive/031-git-boundary/spec.md` |
| Query/audit findings → research-backlog (#23) | `specs/030-quality-harness-v3/spec.md` |
| Post-release seam-hotfix tracking (#8) | `specs/030-quality-harness-v3/spec.md` |
| Template section compliance (#26) | `specs/030-quality-harness-v3/spec.md` |
| Summary length compliance (#27) | `specs/030-quality-harness-v3/spec.md` |
| Budget under-spend (#28) | `specs/030-quality-harness-v3/spec.md` |
| Simple-spec `concept` collapse (#14) | `.agents/skills/vault-spec/SKILL.md` (taxonomy inference improvement) |
| Domain locks + dedup gate (#29) | Park alongside parallel-agent design when revived. |
| Multi-agent consensus abstraction | `specs/037-consensus-abstraction/spec.md` |

---

## Spec 072 FR5 retains every research branch, forever — MOVED

Migrated to #307
2026-09-06 (part of #277): this follow-up belongs to a shipped, frozen spec
(`specs/072-auto-merge-research-branch/spec.md`), and this file is a
scratchpad that gets deleted — the wrong durable home for it. See the issue
for the content that used to live here.

---

## Recently triaged out (cross-references)

- **Source modules roadmap** → `docs/ROADMAP.md` § Deferred, row "spec 060 tiers"
  (the tiered ladder moved there when the roadmap was replaced, 2026-09-08)
- **Cost efficiency phase** → `docs/ROADMAP.md` § Deferred, row `#61` / spec 045
  (`specs/045-cost-efficiency-v2/spec.md`)
- **Quality + E2E harness (spec 022)** → SHIPPED 0.3.0
- **Cross-project assistant-framework integration** → `specs/036-assistant-framework-integration/spec.md`
- **Future spec stub 035 cross-cycle-digest** → SHIPPED 1.0.0rc1 (`specs/035-cross-cycle-digest/spec.md`, PR #117)
