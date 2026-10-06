"""Quality harness orchestrator (spec 022)."""

from __future__ import annotations

import argparse
import dataclasses
import os
import shutil
import sys
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_framework.pipeline.cycle_runner import (
    get_last_cycle_results,
    run_cycle_steps,
)
from research_framework.pipeline.steps._types import SafetyGateTrip

from .baseline import (
    coverage_targets_hash,
    diff_against_baseline,
    load_baseline_json,
    merge_regression_reports,
)
from .determinism import assert_deterministic, canonical_json_write
from .exceptions import (
    BaselineMissingError,
    BaselineStaleError,
    CycleRunnerCrashError,
    FixtureNotInitialisedError,
    HarnessFailure,
    RegressionFailure,
)
from .metrics import REGISTERED_METRIC_FAMILIES
from .models import CurrentJSON, CycleOutput, Fixture, RegressionReport
from .report import print_regression_summary, write_regression_report

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURES_ROOT = _REPO_ROOT / "tests" / "fixtures" / "quality"
_BASELINES_DIR = _REPO_ROOT / "tests" / "fixtures" / "quality" / "baselines"
_DEFAULT_OUTPUT_DIR = _REPO_ROOT / "_pipeline" / "quality"
# Spec 026 FR-001/FR-002: cycle writes land in this gitignored, *under-repo*
# workspace — never the committed source-of-truth fixture tree. Keeping it
# under the repo lets the committed (machine-agnostic, ``_BAKED_REPO_ROOT =
# None``) fake-agent shim resolve ``tests/_helpers/fake_agent`` via its
# walk-up strategy, so the runner never needs to import a tests-only module.
#
# Issue #288 (reported PLAUSIBLE, not reproduced in isolation): this used to
# be one process-independent constant, ``_DEFAULT_OUTPUT_DIR / "work"`` —
# every invocation resolved the exact same ``_pipeline/quality/work/<fixture>``
# path, and :func:`isolate_fixture` unconditionally ``rmtree``\\ s then
# ``copytree``\\ s it. Two harness invocations running concurrently in one
# checkout (a local run overlapping a background one, two worktrees sharing
# `_pipeline/` through a symlink, etc.) would ``rmtree`` out from under each
# other's in-flight cycle. Salting the root with :func:`os.getpid` gives each
# PROCESS its own subtree — concurrent processes can no longer collide,
# without changing anything about a single process's own repeated use of the
# same root across fixtures (FR-006's crash-preserved workspace is still one
# discoverable path for the lifetime of the run that hit it — the crash
# message below still prints it).
_WORK_ROOT = _DEFAULT_OUTPUT_DIR / f"work-{os.getpid()}"

# The value is the failure mode the fixture actually exercises, and it has to
# stay that way to be worth recording. source-poor was registered as
# ``gap-pursuit-substitution`` (spec 022 FR-011), which nothing exercised: its
# canned scout concentrates every topic in one coverage category, so SG-002
# fires and aborts the cycle immediately after scout — ``note_writer`` is never
# dispatched, and no substitution can occur. Renamed to what the three cycles
# do (issue #265). ``failure_mode`` is descriptive metadata: it is not part of
# ``current.json`` or any baseline, so the rename moves no metric.
REGISTERED_FIXTURES: dict[str, str] = {
    "tech-lite": "code-derived-topic-discovery",
    "source-poor": "low-diversity-scout-abort",
    "source-rich": "source-quality-pruning",
}

_NOTE_COUNT_TARGETS: dict[str, int] = {
    "tech-lite": 18,
    "source-poor": 17,
    "source-rich": 20,
}

#: The one call the harness makes into the pipeline. Named so the seam that
#: replaces it in a harness test (``cycle_runner=``) has a type rather than a
#: bare ``Callable`` — the stub must accept the budget pair the harness pins,
#: and a signature that could not would hide that (issue #86 / #268).
CycleRunner = Callable[..., int]


HARNESS_MAX_CYCLES = 3
"""Cycles driven per fixture in a harness run.

Spec 022 plan.md § Performance Goals caps a harness run at ``max_cycles: 3``
per fixture, its acceptance scenarios are written against "the 3-cycle harness
run", and its data model reads ``Fixture (1) ──< CycleOutput (N, one per cycle
in the harness run)``. ``tests/quality/conftest.run_fixture_cycles`` has always
driven three. This runner drove ONE, so the release gate was a third of the
documented gate (issue #268) — a fixture whose failure mode only appears on a
later cycle could not surface it.

This constant is the single source of that number: the pytest wrapper imports
it rather than keeping a second copy.
"""

HARNESS_BUDGET_CAP_USD = 10.0
"""Dollar ceiling the harness runs its fixtures under.

The harness used to pass no budget at all and inherit ``run_cycle_steps``'
hardcoded ``10.0`` — a number that came from nowhere, and that issue #233
removed so every real run resolves the spec-061 ladder instead. A regression
fixture is the one caller that should NOT resolve that ladder: its baselines
have to measure the pipeline, not whichever ceiling the shipped settings
carry this month, or a routine settings change re-cuts three baselines and
tells you the pipeline regressed.

So the harness pins its own, explicitly, at the value the baselines were cut
against.
"""

HARNESS_CYCLE_CEILING = 5
"""``max_cycles`` the harness passes into each cycle.

Distinct from :data:`HARNESS_MAX_CYCLES` (3), which is how many cycles the
harness *drives*. This is the ceiling handed to the cycle itself, where it
feeds CG-001's yield model and ``validate_cycle.py``'s Condition A. Pinned for
the same reason as the dollar cap, at the value the baselines were cut
against — and deliberately above the drive count, so a fixture's third cycle
is measured on its own merits rather than terminating on Condition A.
"""

__all__ = (
    "HARNESS_BUDGET_CAP_USD",
    "HARNESS_CYCLE_CEILING",
    "HARNESS_MAX_CYCLES",
    "REGISTERED_FIXTURES",
    "collect_fixture_current",
    "isolate_fixture",
    "main",
    "resolve_fixture",
    "run",
)


def resolve_fixture(name: str) -> Fixture:
    """Build a :class:`Fixture` for a registered harness name."""
    if name not in REGISTERED_FIXTURES:
        registered = ", ".join(sorted(REGISTERED_FIXTURES))
        raise KeyError(
            f"unknown quality fixture {name!r}; registered fixtures: {registered}"
        )
    vault_dir = (_FIXTURES_ROOT / name).resolve()
    return Fixture(
        name=name,
        vault_dir=vault_dir,
        spec_path=vault_dir / "research.spec.md",
        settings_path=vault_dir / "settings.yaml",
        coverage_targets_path=vault_dir / "coverage-targets.json",
        fake_agent_responses_dir=vault_dir / "fake_agent_responses",
        note_count_target=_NOTE_COUNT_TARGETS[name],
        failure_mode=REGISTERED_FIXTURES[name],
    )


def isolate_fixture(fixture: Fixture, dest_root: Path) -> Fixture:
    """Copy *fixture*'s vault into ``dest_root/<name>`` and retarget every path.

    Spec 026 FR-001/FR-002: the quality harness must run against a throwaway
    copy so the committed source-of-truth tree under ``tests/fixtures/quality/``
    is never mutated by a cycle. The returned :class:`Fixture` points entirely
    at the copy, so both ``run_cycle_steps`` (which writes) and the metric
    ``compute_fn``\\ s (which read ``fixture.vault_dir``) operate on the same
    isolated vault.

    *dest_root* is a gitignored under-repo workspace (the ``runner`` path) or a
    pytest ``tmp_path`` (the ``conftest`` path). A stale destination from a
    crash-preserved prior run is replaced.
    """
    dest = (dest_root / fixture.name).resolve()
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture.vault_dir, dest)
    return dataclasses.replace(
        fixture,
        vault_dir=dest,
        spec_path=dest / fixture.spec_path.name,
        settings_path=dest / fixture.settings_path.name,
        coverage_targets_path=dest / fixture.coverage_targets_path.name,
        fake_agent_responses_dir=dest / fixture.fake_agent_responses_dir.name,
    )


def run(
    fixtures: list[str] | None = None,
    *,
    output_dir: Path | None = None,
    color: bool | None = None,
    cycle_runner: CycleRunner | None = None,
) -> int:
    """Run the quality harness over *fixtures*; return exit code 0 / 1 / 2.

    ``cycle_runner`` is the injectable seam a harness test uses to exercise
    the harness's own control flow — cycle count, crash handling, the
    regression gate — without driving a real cycle. ``None`` (production, and
    every ``build.sh --quality`` run) resolves the real ``run_cycle_steps``.
    It exists so no test has to monkeypatch the module global (issue #86,
    guarded by ``tests/_helpers/test_cycle_runner_seam_guard.py``).
    """
    names = sorted(fixtures or REGISTERED_FIXTURES.keys())
    out_dir = (output_dir or _DEFAULT_OUTPUT_DIR).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    run_ts = _utc_now_iso()

    reports: list[RegressionReport] = []
    crashed: list[str] = []

    try:
        for name in names:
            try:
                report, did_crash = _run_fixture(
                    name, out_dir, run_ts, cycle_runner=cycle_runner
                )
                reports.append(report)
                if did_crash:
                    crashed.append(name)
            except HarnessFailure as exc:
                _emit_stderr(exc, name)
                return 2
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 2

    if crashed:
        # A crash is not a measurement. This used to exit 2 only when EVERY
        # fixture crashed and leave a partial crash to the metric diff, which
        # books it as one failed cycle — against a baseline that already
        # fails (source-poor: three SG-002 aborts) that reads as an
        # improvement, and the gate printed "Verdict: PASS".
        exc = CycleRunnerCrashError(cycle_number=1)
        _emit_stderr(exc, crashed[0])
        return 2

    combined = merge_regression_reports(reports)
    write_regression_report(combined, out_dir)
    print_regression_summary(combined, color=color)

    if combined.verdict == "fail":
        first_fail = _first_regression_failure(combined)
        if first_fail is not None:
            _emit_stderr(first_fail, first_fail._fixture)
        else:
            exc = RegressionFailure(
                metric="unknown",
                delta_pct="n/a",
                baseline_value=0.0,
                current_value=0.0,
                _fixture=names[0],
            )
            _emit_stderr(exc, names[0])
        return 1
    return 0


def collect_fixture_current(
    name: str,
    *,
    output_dir: Path | None = None,
    run_ts: str | None = None,
    cycle_runner: CycleRunner | None = None,
) -> tuple[CurrentJSON, bool]:
    """Run one fixture and write ``<fixture>.current.json`` (no regression gate)."""
    fixture = resolve_fixture(name)
    _assert_fixture_initialised(fixture)
    out_dir = (output_dir or _DEFAULT_OUTPUT_DIR).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = run_ts or _utc_now_iso()
    # Hash the committed (source) coverage-targets.json: the baseline-staleness
    # check is anchored to the tracked fixture, not the throwaway per-run copy.
    current_hash = coverage_targets_hash(fixture.coverage_targets_path)
    # FR-001/FR-002: run cycles + compute metrics against an isolated copy so
    # the tracked tree stays pristine (SC-001). Both must see the same vault —
    # cycles WRITE there and metric compute_fns READ fixture.vault_dir.
    work_fixture = isolate_fixture(fixture, _WORK_ROOT)
    cycle_outputs, crashed = _invoke_cycles(work_fixture, cycle_runner=cycle_runner)
    metrics = _compute_metrics(work_fixture, cycle_outputs)
    if crashed:
        health = metrics.setdefault("cycle_health", {})
        health["cycles_fail"] = int(health.get("cycles_fail", 0)) + 1
        # FR-006: keep the workspace on crash so the failure is debuggable.
        print(
            f"[quality] {name}: cycle crashed — workspace preserved at "
            f"{work_fixture.vault_dir}",
            file=sys.stderr,
        )
    current = CurrentJSON(
        schema_version="1.0",
        fixture=name,
        run_timestamp=ts,
        coverage_targets_hash=current_hash,
        metrics=metrics,
    )
    current_payload = _current_to_dict(current)
    assert_deterministic(current_payload, f"{name}.current.json")
    canonical_json_write(out_dir / f"{name}.current.json", current_payload)
    if not crashed:
        # FR-007: a clean run leaves no workspace behind.
        shutil.rmtree(work_fixture.vault_dir, ignore_errors=True)
    return current, crashed


def _run_fixture(
    name: str, out_dir: Path, run_ts: str, *, cycle_runner: CycleRunner | None = None
) -> tuple[RegressionReport, bool]:
    fixture = resolve_fixture(name)
    _assert_fixture_initialised(fixture)

    baseline_path = _BASELINES_DIR / f"{name}.baseline.json"
    try:
        baseline = load_baseline_json(baseline_path)
    except BaselineMissingError:
        raise

    current_hash = coverage_targets_hash(fixture.coverage_targets_path)
    if baseline.coverage_targets_hash != current_hash:
        raise BaselineStaleError(
            baseline_hash=baseline.coverage_targets_hash,
            current_hash=current_hash,
        )

    current, crashed = collect_fixture_current(
        name, output_dir=out_dir, run_ts=run_ts, cycle_runner=cycle_runner
    )
    report = diff_against_baseline(current, baseline)
    return report, crashed


def _assert_fixture_initialised(fixture: Fixture) -> None:
    required = (
        fixture.spec_path,
        fixture.settings_path,
        fixture.coverage_targets_path,
        fixture.fake_agent_responses_dir,
    )
    for path in required:
        if not path.exists():
            raise FixtureNotInitialisedError(f"missing {path.name} for {fixture.name}")


def _invoke_cycles(
    fixture: Fixture,
    *,
    max_cycles: int = HARNESS_MAX_CYCLES,
    cycle_runner: CycleRunner | None = None,
) -> tuple[list[CycleOutput], bool]:
    """Run *max_cycles* cycles; return outputs and whether the runner crashed.

    A non-zero cycle exit (TERMINATE or a step-gate abort) does NOT stop the
    run: the harness measures a fixed number of cycles so a fixture's failure
    mode is exercised on each of them, which is what spec 022's source-poor
    acceptance scenario ("at least one cycle in the 3-cycle harness run trips
    SG-002") asks for. Only a crash stops it — the outputs collected so far are
    returned so the metrics still describe what did run.
    """
    runner = cycle_runner or run_cycle_steps
    outputs: list[CycleOutput] = []
    for cycle_num in range(1, max_cycles + 1):
        try:
            exit_code = runner(
                fixture.vault_dir,
                cycle_num,
                budget_cap=HARNESS_BUDGET_CAP_USD,
                max_cycles=HARNESS_CYCLE_CEILING,
            )
        except Exception:
            return outputs, True
        outputs.append(_cycle_output(fixture, cycle_num, exit_code))
    return outputs, False


def _cycle_output(fixture: Fixture, cycle_num: int, exit_code: int) -> CycleOutput:
    """Collect one cycle's typed step results into a :class:`CycleOutput`."""
    cycle_tag = f"{cycle_num:03d}"
    pipeline = fixture.vault_dir / "_pipeline"
    results = get_last_cycle_results(cycle_num)
    scout_result = results.get("scout")
    research_result = results.get("research")
    postprocess_result = results.get("postprocess")
    notes_written = (
        list(research_result.notes_written) if research_result is not None else []
    )
    return CycleOutput(
        fixture_name=fixture.name,
        cycle_number=cycle_num,
        exit_code=exit_code,
        quality_report_path=pipeline
        / "cycles"
        / f"cycle-{cycle_tag}-quality-report.json",
        research_report_path=pipeline / "cycles" / f"cycle-{cycle_tag}-research.json",
        notes_written=notes_written,
        sg_trips=_sg_trip_ids(scout_result.sg_trips if scout_result else []),
        scout_result=scout_result,
        research_result=research_result,
        postprocess_result=postprocess_result,
    )


def _sg_trip_ids(trips: list[SafetyGateTrip]) -> list[str]:
    out: list[str] = []
    for trip in trips:
        gid = str(trip.gate_id or "").strip()
        status = str(trip.status or "").upper()
        if gid and status in {"FAIL", "WARN"}:
            out.append(gid)
    return out


def _compute_metrics(
    fixture: Fixture,
    cycle_outputs: list[CycleOutput],
) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for family in REGISTERED_METRIC_FAMILIES:
        merged[family.name] = family.compute_fn(fixture, cycle_outputs)
    return merged


def _current_to_dict(current: CurrentJSON) -> dict[str, Any]:
    return {
        "schema_version": current.schema_version,
        "fixture": current.fixture,
        "run_timestamp": current.run_timestamp,
        "coverage_targets_hash": current.coverage_targets_hash,
        "metrics": current.metrics,
    }


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _first_regression_failure(report: RegressionReport) -> RegressionFailure | None:
    for fixture_name, fx in sorted(report.fixtures.items()):
        for metric_key, diff in sorted(fx.metric_diffs.items()):
            if diff.verdict != "fail":
                continue
            return RegressionFailure(
                metric=metric_key,
                delta_pct=diff.delta_pct,
                baseline_value=diff.baseline,
                current_value=diff.current,
                _fixture=fixture_name,
            )
    return None


def _emit_stderr(exc: HarnessFailure, fixture: str) -> None:
    line = (
        f"HARNESS FAILED: {exc.category}. "
        f"Reproduce with: ./build.sh --quality --fixture {fixture}"
    )
    print(line, file=sys.stderr)
    print(exc.format_stderr_line(fixture), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """CLI entry for ``python -m research_framework.quality.runner``."""
    parser = argparse.ArgumentParser(
        prog="research-framework.quality.runner",
        description="Spec 022 quality regression harness.",
    )
    parser.add_argument(
        "--fixture",
        default="all",
        choices=[*sorted(REGISTERED_FIXTURES), "all"],
        help="Limit to one fixture (default: all registered fixtures).",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colour in harness stdout.",
    )
    args = parser.parse_args(argv)
    fixtures = None if args.fixture == "all" else [args.fixture]
    color = False if args.no_color else None
    return run(fixtures=fixtures, color=color)


if __name__ == "__main__":
    sys.exit(main())
