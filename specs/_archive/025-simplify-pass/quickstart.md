# Quickstart — Spec 025 Code Simplification Pass

**Audience**: developer implementing spec 025 (this session or a
follow-on) + reviewers of the resulting PRs.
**Prerequisites**: read `spec.md`, `plan.md`, `research.md`,
`data-model.md`, and the `contracts/*` files (~6,000 lines total,
~30 min reading).

This quickstart walks through how to actually execute the
refactor and how to verify each piece works. Sectioned by user
story to match `tasks.md`'s structure.

---

## § 0 — Worktree + branch setup

This Cursor session is already in the 025 worktree:

```text
~/src/research-framework-025/
├── branch: 025-simplify-pass
└── HEAD: 3ffa999 clarify(025): lock 9 decisions
```

Other live worktrees (do NOT modify from this session unless you
explicitly coordinate via the cycle-runner edit lock contract):

```text
~/src/research-framework         [022-e2e-quality-harness]
~/src/research-framework-024     [024-testing-infrastructure-v2]
```

For the **B3 sub-branch** (US6, Tier B), create a second
worktree at sub-branch time:

```bash
cd ~/src/research-framework-025
git worktree add ~/src/research-framework-b3 \
    -b 025-b3-step-extraction
```

Then announce the lock per
`contracts/cycle-runner-edit-lock.contract.md` § 2.1.

---

## § 1 — US1 + US2: A1/A2 — route LLM bypasses through `agent_call.py`

**Files touched**:
- `pipeline/plan_narrator.py` (A1)
- `pipeline/cycle_runner.py` lines ~1137–1252 (A2; verify exact
  range at impl time)
- `tests/_helpers/llm_dispatch_allowlist.yaml` (spec 024 owns;
  remove the two entries in the same commit)

**Step-by-step (A1)**:

1. Read `scripts/agent_call.py` to confirm the current dispatch
   signature. If there's a stage allowlist enum, plan to add
   `"plan_narrator"` to it.
2. Find the existing direct LLM call in `plan_narrator.py`:
   ```bash
   rg "subprocess\.(run|Popen).*(claude|codex)" pipeline/plan_narrator.py
   ```
3. Rewrite to use `agent_call.dispatch(stage="plan_narrator", ...)`.
   Pattern (see `contracts/llm-dispatch.contract.md` § 5):
   ```python
   from research_framework.scripts.agent_call import dispatch

   call_result = dispatch(
       stage="plan_narrator",
       prompt=prompt,
       tier=settings.stage("plan_narrator").tier,
       cycle_dir=cycle_dir,
   )
   narrative = call_result.stdout
   ```
4. Add the tier setting to `settings.yaml` templates (in
   `dist-templates/`) with default `"standard"`.
5. Write tests in `tests/pipeline/test_plan_narrator.py` per
   `contracts/llm-dispatch.contract.md` § 6.
6. Delete the allowlist entry for `pipeline/plan_narrator.py`
   from `tests/_helpers/llm_dispatch_allowlist.yaml`.

**Verification**:

```bash
# Tests pass
pytest tests/pipeline/test_plan_narrator.py -v

# The dispatch is the only LLM-bound call site for the narrator
rg "subprocess.*(claude|codex)" pipeline/plan_narrator.py
# Should return: no matches

# Run a cycle and confirm sidecar appears
RESEARCH_FRAMEWORK_DEFAULT_AGENT=codex \
    ./vault research --cycle 1 \
    --vault tests/fixtures/quality/fixtures/tech-lite/

ls _pipeline/cycles/cycle-001/agent-calls/
# Should include: plan_narrator.json (with agent: "codex")
```

**Step-by-step (A2)**: same pattern for the probe-retrieval
block in `cycle_runner.py`. Note: A2 is the LAST Tier A item
that COULD justify keeping a long-lived sub-branch — but it's
self-contained enough to ship as a normal small PR. Keep it
short.

---

## § 2 — US3: A6 — quality-report context-manager guard

**Files touched**:
- `pipeline/cycle_runner.py` (entire file; the wrapper plus 32
  call-site collapses)
- `tests/pipeline/test_cycle_runner_quality_report.py` (NEW)

**Step-by-step**:

1. Define `_quality_report_guard` and `QualityReportState` per
   `data-model.md` § 2.2.
2. Wrap `run_cycle_steps`' body:
   ```python
   def run_cycle_steps(vault_dir, cycle_num, ...):
       cycle_dir = vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_num:03d}"
       with _quality_report_guard(cycle_dir) as report_state:
           # ... existing body, but with all _write_cycle_quality_report
           #     calls REMOVED. Mutations now go to report_state. ...
           pass
   ```
3. Find and delete every `_write_cycle_quality_report(...)`
   call inside `run_cycle_steps`:
   ```bash
   rg -n "_write_cycle_quality_report" pipeline/cycle_runner.py
   # Should show ~32 matches pre-A6, ≤2 post-A6
   ```
4. Replace each deletion with the equivalent `report_state.<field> = ...`
   mutation. The `_quality_report_guard`'s `__exit__` does the
   final write.
5. Write tests covering every exit path:
   - Happy path → exit_status="success", report exists.
   - Scout failure → exit_status="failure", exception captured.
   - Note-writer failure → same.
   - Verifier reject every note → exit_status="success" with
     `report.research.notes_rejected` populated.
   - KeyboardInterrupt mid-cycle → exit_status="interrupted",
     report still written.

**Verification**:

```bash
pytest tests/pipeline/test_cycle_runner_quality_report.py -v

rg -n "_write_cycle_quality_report" pipeline/cycle_runner.py | wc -l
# Should be ≤ 2 (one in _quality_report_guard.__exit__; at most
# one progress-log call)

# Full sweep stays green
pytest -m "not e2e"
```

---

## § 3 — US4: A4 — auto-detect `--resume` cycle

**Files touched**:
- `cli.py` or `cli/research.py` (depending on B5 status —
  pre-B5 use cli.py; post-B5 use cli/research.py)
- Possibly `pipeline/state.py` (NEW helper if `_pipeline/state.json`
  doesn't have a read-side helper yet)
- `tests/cli/test_research_resume.py` (NEW)

**Step-by-step**:

1. Confirm `_pipeline/state.json::in_progress_cycle` exists or
   add the write-side hook at cycle start in `cycle_runner.py`:
   ```python
   def run_cycle_steps(vault_dir, cycle_num, ...):
       state_path = vault_dir / "_pipeline" / "state.json"
       _state_write(state_path, {"in_progress_cycle": cycle_num})
       try:
           # ... existing body ...
       finally:
           _state_write(state_path, {"in_progress_cycle": None})
   ```
2. Implement the resume handler:
   ```python
   def _resolve_resume_cycle(args) -> int:
       state_path = args.vault_dir / "_pipeline" / "state.json"
       try:
           state = json.loads(state_path.read_text())
       except FileNotFoundError:
           raise SystemExit(
               "no in-progress cycle found; use `--cycle <N>` to specify"
           )
       except json.JSONDecodeError as exc:
           raise SystemExit(
               f"_pipeline/state.json is corrupted: {exc}; "
               "use `--cycle <N>` to specify manually"
           )
       cycle = state.get("in_progress_cycle")
       if cycle is None:
           raise SystemExit(
               "no in-progress cycle found; use `--cycle <N>` to specify"
           )
       return cycle
   ```
3. Wire into `handle_resume`:
   ```python
   def handle(args) -> int:
       if args.resume and args.cycle is None:
           args.cycle = _resolve_resume_cycle(args)
       # ... existing logic ...
   ```
4. Write tests covering the 4 spec.md US4 scenarios.

**Verification**:

```bash
pytest tests/cli/test_research_resume.py -v

# Manual smoke
cd tests/fixtures/quality/fixtures/tech-lite/  # or any fixture
./vault research --cycle 1
# (let it run; Ctrl-C mid-cycle)
./vault research --resume   # should pick up cycle 1
```

---

## § 4 — US5: A5 — doc sync

**Files touched**:
- `.specify/memory/constitution.md`
- `docs/ROADMAP.md`
- `build.sh` (comments only)
- `tests/docs/test_doc_sync.py` (NEW)

**Step-by-step**:

1. Replace `run_cycle.sh` references in
   `.specify/memory/constitution.md`. See
   `research.md` D9 for the recommended replacement text.
2. Rewrite the QW-2 entry in `docs/ROADMAP.md` to match reality
   (smoke meta-tests are commented out in `build.sh`, not
   missing).
3. Update `build.sh` header comment to describe the current
   smoke-gate contract.
4. Write `tests/docs/test_doc_sync.py` with the two grep
   assertions:
   ```python
   def test_no_run_cycle_sh_references():
       result = subprocess.run(
           ["rg", "run_cycle\\.sh", ".specify/", "docs/"],
           capture_output=True, text=True,
       )
       assert result.returncode == 1, \
           f"Found stale run_cycle.sh references:\n{result.stdout}"

   def test_qw2_text_accurate():
       roadmap = Path("docs/ROADMAP.md").read_text()
       assert "files missing" not in roadmap, \
           "QW-2 still says 'files missing' — they're commented out, not missing"
   ```

**Verification**:

```bash
pytest tests/docs/test_doc_sync.py -v

# Manual check
rg "run_cycle\.sh" .specify/ docs/
# Should return: no matches

rg "files missing|files never committed" docs/ROADMAP.md
# Should return: no matches
```

---

## § 5 — Switch to Tier B (post-022-v1)

**Gate check**: before opening any Tier B PR, confirm:

```bash
# 022 v1 has shipped
git log --oneline origin/main | grep "spec 022 v1"
# OR check pyproject.toml for the bumped version

# Baselines exist
ls tests/fixtures/quality/baselines/
# Should show: source-poor.baseline.json, tech-lite.baseline.json,
# source-rich.baseline.json

# Local harness passes
./build.sh --quality
# exit 0 expected
```

If any of the above fails, Tier B PRs cannot merge per FR-016.

---

## § 6 — US6: B3 — extract cycle-runner steps (long-lived sub-branch)

**Files touched**: extensive; see `plan.md` Project Structure
section for the full list.

**Step-by-step** (high-level — `tasks.md` will enumerate):

1. Open the sub-branch + announce the edit lock per
   `contracts/cycle-runner-edit-lock.contract.md` § 2.1.
2. Create `pipeline/steps/_types.py` with `CycleContext`,
   `ScoutResult`, `ResearchResult`, `PostprocessResult` per
   `contracts/step-module-api.contract.md` § 2 + § 4.
3. Extract `run_scout` into `pipeline/steps/scout.py`. Run
   `pytest tests/pipeline/` to confirm nothing breaks (the
   orchestrator in cycle_runner.py still calls the original
   inline implementation; we're refactoring incrementally inside
   the sub-branch).
4. Switch `run_cycle_steps` to call `run_scout(ctx)`. Delete the
   inline implementation. Tests stay green.
5. Repeat for `run_research` and `run_postprocess`.
6. Confirm `wc -l pipeline/cycle_runner.py < 1500` (FR-008 / SC-004).
7. Run `./build.sh --quality` locally; confirm exit 0.
8. Open the ship PR per
   `contracts/cycle-runner-edit-lock.contract.md` § 2.4.

**Verification**:

```bash
wc -l pipeline/cycle_runner.py    # < 1500
wc -l pipeline/steps/*.py         # each module 200-400 LOC
pytest tests/pipeline/            # all preserved tests pass
./build.sh --quality              # post-022-v1 gate
```

---

## § 7 — US7: B4 — shared frontmatter parser

**Files touched**: `vault/frontmatter.py` (NEW),
`tests/vault/test_frontmatter.py` (NEW), plus 8+ call sites.

**Step-by-step**:

1. Implement `vault/frontmatter.py` per
   `contracts/frontmatter-parser.contract.md`. Ship all the
   tier-1 unit tests at the same time (TDD-aligned).
2. Run the inventory grep:
   ```bash
   rg -l "yaml\.safe_load.*frontmatter|^---$" \
       --type py src/research_framework/
   ```
3. Migrate each site one at a time. Each migration is a
   self-contained PR or commit:
   - Replace inline parser with
     `from research_framework.vault.frontmatter import parse_frontmatter`.
   - Replace the inline parse logic with `fm, body = parse_frontmatter(path)`.
   - Confirm the site's existing tests still pass.
4. Document holdouts with inline comments.

**Verification**:

```bash
rg -c "from research_framework.vault.frontmatter import" \
    src/research_framework/
# Should be ≥ 8 sites
```

---

## § 8 — US8: B5 — split `cli.py` into subpackage

**Files touched**: `cli.py` (shrunk to 1-line re-export),
`cli/` (NEW package with 5–8 modules),
`tests/cli/test_build_parser_stable.py` (NEW).

**Step-by-step**:

1. Capture the pre-refactor `--help` output as a golden file:
   ```bash
   ./vault --help > tests/cli/fixtures/help_output_pre_b5.txt
   for cmd in research audit vault quality; do
       ./vault $cmd --help \
           > tests/cli/fixtures/help_${cmd}_pre_b5.txt
   done
   ```
2. Create `cli/` package skeleton + `cli/__init__.py` shell.
3. Create `cli/_common.py` with the shared helpers (extract
   from `cli.py`).
4. Migrate each command group one at a time. After each
   migration, run the golden-file test to confirm byte-identical
   `--help` output.
5. When all groups are migrated, shrink `cli.py` to the
   re-export.

**Verification**:

```bash
wc -l src/research_framework/cli.py    # ≤ 200 (actually ~5 lines)
wc -l src/research_framework/cli/__init__.py    # ≤ 50
find src/research_framework/cli -name '*.py' -exec wc -l {} \;
# Each ≤ 250

pytest tests/cli/test_build_parser_stable.py -v

diff <(./vault --help) tests/cli/fixtures/help_output_pre_b5.txt
# Should be: no differences (byte-identical)
```

---

## § 9 — US9: B7 — shared settings loader

**Files touched**: `pipeline/settings.py` (NEW),
`tests/pipeline/test_settings_loader.py` (NEW), plus 6+ call sites.

**Step-by-step**: same pattern as B4. Implement canonical loader
+ tier-1 tests + migrate call sites + document holdouts.

**Verification**:

```bash
rg -c "from research_framework.pipeline.settings import load_vault_settings" \
    src/research_framework/
# Should be ≥ 6 sites

pytest tests/pipeline/test_settings_loader.py -v
```

---

## § 10 — US10 (meta): LLM dispatch guard allowlist reaches zero

**Files touched**: `tests/_helpers/llm_dispatch_allowlist.yaml`
(EMPTIED — should reach `[]` or just header comment).

**Step-by-step**:

1. Already deleted by US1 + US2 (each removes its own entry).
2. Run the spec-024-owned guard:
   ```bash
   pytest tests/_helpers/test_llm_dispatch_allowlist.py -v
   pytest tests/_helpers/test_llm_dispatch_guard.py -v
   ```
   Both must pass.

**Verification**:

```bash
cat tests/_helpers/llm_dispatch_allowlist.yaml
# Should show: '[]' or 'allowlist: []' or a comment-only file

# The guard catches any new bypass
grep -rE "subprocess\.(run|Popen).*\b(claude|codex)\b" \
    src/research_framework/ | grep -v "scripts/agent_call.py"
# Should return: no matches
```

---

## § 11 — Final verification (before declaring spec 025 done)

```bash
# All success criteria from spec.md must hold.

# SC-001: full sweep green
pytest

# SC-002: smoke green
./build.sh

# SC-003: allowlist empty
test -s tests/_helpers/llm_dispatch_allowlist.yaml && \
    head tests/_helpers/llm_dispatch_allowlist.yaml | \
        grep -E "^\s*-" && echo "ERROR: non-empty allowlist"

# SC-004: cycle_runner.py < 1500 lines
test "$(wc -l < src/research_framework/pipeline/cycle_runner.py)" -lt 1500 \
    || echo "ERROR: SC-004 violation"

# SC-005: cli.py < 200 lines
test "$(wc -l < src/research_framework/cli.py)" -lt 200 \
    || echo "ERROR: SC-005 violation"

# SC-006: _write_cycle_quality_report ≤ 2 call sites
test "$(rg -c '_write_cycle_quality_report\(' \
    src/research_framework/ | awk -F: '{s+=$2} END {print s}')" -le 2 \
    || echo "ERROR: SC-006 violation"

# SC-007: ≥ 8 frontmatter parser migrations
test "$(rg -l 'from research_framework.vault.frontmatter import' \
    src/research_framework/ | wc -l)" -ge 8 \
    || echo "ERROR: SC-007 violation"

# SC-008: ≥ 6 settings loader migrations
test "$(rg -l 'from research_framework.pipeline.settings import' \
    src/research_framework/ | wc -l)" -ge 6 \
    || echo "ERROR: SC-008 violation"

# SC-009: ./vault --help byte-identical (test runs this)
pytest tests/cli/test_build_parser_stable.py -v

# SC-010: --resume auto-detects (test runs this)
pytest tests/cli/test_research_resume.py -v

# SC-011: agent-calls sidecars have cost_usd > 0
# (tested in tests/pipeline/test_plan_narrator.py +
# test_cycle_runner_probe.py)

# SC-012: zero run_cycle.sh references
test "$(rg -c 'run_cycle\.sh' .specify/ docs/ 2>/dev/null \
    | awk -F: '{s+=$2} END {print s}')" -eq 0 \
    || echo "ERROR: SC-012 violation"

# SC-013: 022 v2 hook retargeting work (not testable in 025; done by
# 022 v2 follow-up)

# SC-014: post-022-v1 quality gate (for Tier B PRs)
./build.sh --quality   # exit 0

# SC-015: B3 sub-branch shipped within 7 days (audit at ship time)
```

If all of the above pass, spec 025 has met its acceptance bar.
Update the spec.md status header to:

```markdown
**Status**: SHIPPED v0.X.Y (2026-MM-DD)
```

…and follow the per-spec-kit-stage doc-update checklist in
`CLAUDE.md` (flip ROADMAP `[~]` → `[x]`, write CHANGELOG entry,
prune TODO entries the work resolved, etc.).

---

## § 12 — Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `pytest tests/pipeline/test_cycle_runner.py` fails after A6 wrapper | The wrapper's `__exit__` is writing the report with `exit_status=None` | Ensure all paths through the `try` body set `state.exit_status` OR rely on the context manager's exception-handling branch. |
| `--help` golden-file test fails after B5 | Subcommand registration order changed | Either preserve pre-B5 order (recommended) or update the golden file (requires signoff). See `contracts/cli-subpackage.contract.md` § 5. |
| `_quality_report_guard` swallows the original exception on KeyboardInterrupt | `_write_cycle_quality_report` raised during `finally:` | Wrap the final write in a `try/except Exception: log_and_swallow`. The original interrupt MUST propagate. |
| Frontmatter test `test_dump_parse_roundtrip` fails | YAML dump style differs from input | The roundtrip is at the dict-level, not string-level. Test should compare `parse_frontmatter_str(s_roundtrip) == (fm, body)`, not `s_roundtrip == s`. |
| B3 sub-branch has merge conflicts with main | Lock discipline failed (someone touched cycle_runner.py on main) | Follow escalation per `contracts/cycle-runner-edit-lock.contract.md` § 3.3. |
| LLM dispatch guard fails after A1/A2 | Allowlist entry wasn't deleted | Open `tests/_helpers/llm_dispatch_allowlist.yaml` and remove the relevant entry. |

For anything else, ask the architect or the spec author before
guessing.
