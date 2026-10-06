# Quickstart — Post-Revival Hardening (spec 051)

How to exercise each FR end-to-end once implemented. Assumes a dev checkout and
`pip install -e .`.

---

## FR1 — Configurable cycle-yield model

**Configure** (`<vault>/settings.yaml`):
```yaml
cycle_yield:
  base_notes_per_cycle: 5
  cadence_factor:   { daily: 1.0, weekly: 3.0, biweekly: 5.0, monthly: 8.0 }
  coverage_factor:  { coverage_below_50pct: 1.5, coverage_50_to_80pct: 1.0, coverage_above_80pct: 0.5 }
  min_floor: 1
  max_ceiling: 50
```

**Observe** after a cycle:
```bash
# computed target + multipliers + actual, per cycle
jq '.[-1]' <vault>/_pipeline/yield-calibration.json
# same breakdown inside the gate report
jq '.gates["CG-001"]' <vault>/_pipeline/cycles/cycle-007-quality-report.json
```
Expect: a dormant 200-note vault (last cycle >14d ago, <50% coverage) computes
`target = clamp(ceil(5 * 8.0 * 1.5), 1, 50) = 50` → demands a real batch, not 5.
A daily re-run at >80% coverage computes `ceil(5 * 1.0 * 0.5) = 3`.

**Test:** `pytest tests/pipeline/test_cg001_yield_model.py`
**Baseline guard:** `./build.sh --quality` — the tech-lite fixture's regression
diff MUST NOT move (defaults are pinned to current behaviour).

---

## FR2 — Stale-venv detection on `./vault update`

**Reproduce the footgun:** point `.venv/pyvenv.cfg`'s `home =` at a deleted
build dir, then:
```bash
cd <vault>
./vault update                 # interactive: prompts "rebuild venv? [Y/n]" (default yes)
./vault update --auto-confirm  # CI/agent: rebuilds without prompting
```
Expect: stale `home =` (path missing) → rebuild prompt; after install, the
post-install sanity check imports `research_framework` and compares
`__version__` against the **bundled wheel's version** (parsed from the
`research_framework-<version>-*.whl` filename — the bundle ships no
`pyproject.toml`). On mismatch it exits non-zero, prints the `pyvenv.cfg` +
remediation (`rm -rf .venv && ./install.sh`), and (per spec 050) the upgrade
commit is one `git revert HEAD` away.

**Test:** `pytest tests/scripts/test_install_venv_staleness.py`
(sandbox-extraction + `pty.fork()` pattern from `test_install_sh_tty_handling.py`).

---

## FR3 — Inbound-link-aware stub policy

**Configure** (optional; default 5):
```yaml
stubs:
  anchor_link_threshold: 5
```

**Behaviour:** a short note with ≥5 inbound wikilinks (e.g. `[[Microsoft]]` with
30 backlinks) is classified `anchor-stub` → flagged `status: needs-research`,
surfaced in the research-backlog, **never deleted**. A short note with <5
inbound links is `deletable-stub`.

```python
from research_framework.pipeline.stubs import classify_stub, StubClassificationContext
classify_stub(
    StubClassificationContext(path=p, inbound_links_count=30, body_len=40),
    body_len_threshold=200, anchor_link_threshold=5,
)  # -> "anchor-stub"
```

**Test:** `pytest tests/pipeline/test_stub_classification.py`

---

## FR4 — Per-module preflight (MANDATORY contract)

**Manifest now requires it** — a module without a `preflight` block fails to
load (skipped with a WARN, cycle continues):
```yaml
# modules/youtube/manifest.yaml
preflight:
  entry_point: preflight.py   # spawned as an isolated subprocess (like the extractor)
  timeout_seconds: 30
```

**See corrections surface:** put a malformed source in
`modules/rss/sources.yaml` (e.g. `https://arxiv.org/list/cs.AI`) and run:
```bash
./vault refresh-sources --json | jq '.preflight'   # the sweep's per-module verdicts
# at cycle start, run_extraction spawns preflight per module BEFORE extracting;
# the verdict is recorded in that module's entry of the source-extraction summary.
```
Expect a `warning` verdict with a `SourceCorrection` suggesting
`rss.arxiv.org/rss/cs.AI`. A `fatal_fail` skips only that module (others run);
a crashing / timing-out / garbage-emitting preflight maps to `fatal_fail`
(fail-closed).

**Tests:**
```bash
pytest tests/modules/youtube/test_preflight.py \
       tests/modules/reddit/test_preflight.py \
       tests/modules/rss/test_preflight.py \
       tests/modules/oreilly/test_preflight.py
```

---

## FR5 — Regression locks (net-new)

```bash
pytest tests/pipeline/test_cycle_helpers_tree_kill.py   # _run_script grandchild path
pytest tests/cli/test_resume_completion_marker.py       # _highest_completed_cycle regex edges
```
> The two headline behaviours (process-tree kill, quality-report-only completion
> marker) are *already* locked by existing tests — see research.md D7. These add
> the two uncovered slices only.

---

## Full gate before PR

```bash
ruff check . && ruff format --check .   # both gates (separate!)
pytest -m "not e2e"                     # fast loop
./build.sh --quality                    # smoke gate + spec-022 quality harness (FR1 touches pipeline/)
```
