"""spec-019 / 0.2.29 — scout structural-error correction loop.

Background:

Pre-0.2.29, ``validate_cycle.py`` returning exit 2 on a scout report
aborted the whole cycle on the first failure (cycle_runner.py:1141).
The trial-run feedback that triggered this fix:

    [Step 2 - validating scout report]
    ============================================================
    CYCLE VALIDATION: ABORT
    ============================================================
    Reason: v2 report has 6 structural error(s)
      ERROR: required source 'hyperskill_knowledge_map' not in
             sources_consulted
      ... five more like it ...
    ABORT: scout report has structural errors. Fix and retry.

In every observed case the scout had already done the actual scouting
work (18 code topics, 19 intents, 10 generalized topics in the trial
cited above) — the report was just missing summary fields the validator
could name explicitly. Aborting the cycle threw away that work and a
non-trivial chunk of the user's token budget.

0.2.29 wires a correction loop: when validate_cycle.py exits 2, the
runner reads the validator's structured sidecar, builds a correction
directive listing every named error, re-renders the scout prompt, and
re-runs the scout. The loop caps at
``MAX_SCOUT_VALIDATION_RETRIES`` additional attempts.

These tests stub ``validate_cycle.py`` to fail on the first invocation
and pass on the second, then assert:
- the scout was re-run exactly once,
- the cycle succeeded,
- a correction-directive file was written so the agent had something
  to read.

The complementary cases (already verified by the existing
``test_scout_abort_halts_cycle``) cover the "no sidecar → can't
recover → abort" early-exit path.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from tests.pipeline.test_cycle_runner import (
    _make_vault,
    _patch_cycle_runner_subprocess,
)


def _write_sidecar_with_errors(scout_report: Path, errors: list[str]) -> None:
    sidecar = scout_report.with_suffix(scout_report.suffix + ".validation.json")
    sidecar.write_text(
        json.dumps(
            {
                "status": "ABORT",
                "reason": f"Report has {len(errors)} structural error(s)",
                "errors": errors,
                "warnings": [],
                "metrics_delta": {},
            }
        ),
        encoding="utf-8",
    )


def test_scout_structural_error_triggers_correction_loop(tmp_path: Path) -> None:
    """On first validate=2 the runner MUST re-prompt the scout and re-validate.

    Stubs:
    - validate_cycle.py: exit 2 on first call, 0 on second.
    - validate_cycle.py also writes the sidecar (the real validator does
      this in 0.2.29; we mimic it here so the helper has errors to read).
    - All other scripts return 0.
    """
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path)
    cycle_num = 1
    cycles_dir = vault / "_pipeline" / "cycles"
    cycle_3 = f"{cycle_num:03d}"
    scout_report = cycles_dir / f"cycle-{cycle_3}-scout.json"
    scout_report.write_text(json.dumps({"schema_version": "2.0"}), encoding="utf-8")
    (cycles_dir / f"cycle-{cycle_3}-research.json").write_text("{}")
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    validate_calls: list[int] = []
    scout_invocations: list[int] = []

    def _fake_run(cmd, **kwargs):
        script_name = Path(cmd[1]).name
        mock = MagicMock()
        mock.stdout = b""
        if script_name == "validate_cycle.py":
            validate_calls.append(1)
            if len(validate_calls) == 1:
                # Mimic the real validator's sidecar emission so the
                # correction loop has something actionable to read.
                _write_sidecar_with_errors(
                    scout_report,
                    [
                        "required source 'hyperskill_knowledge_map' not in sources_consulted",
                        "required source 'open_web' not in sources_consulted",
                    ],
                )
                mock.returncode = 2
            else:
                _write_sidecar_with_errors(scout_report, [])
                mock.returncode = 0
            return mock
        if script_name == "agent_call.py" and "--stage" in cmd:
            stage = cmd[cmd.index("--stage") + 1]
            if stage == "scout":
                scout_invocations.append(1)
        mock.returncode = 0
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        rc = run_cycle_steps(vault, cycle_num)

    assert rc == 0, "second validate=0 must let the cycle proceed to success"
    assert len(scout_invocations) == 2, (
        f"scout should be invoked once initially and once for the correction "
        f"retry; got {len(scout_invocations)} invocations"
    )
    assert len(validate_calls) >= 2, (
        f"validate_cycle.py must be called at least twice (initial + retry); "
        f"got {len(validate_calls)}"
    )

    # The correction directive must have been written by build_directive.
    # In 0.2.30+, after a successful retry the directive is archived
    # to corrections/applied/ (so it doesn't leak into later renders
    # this cycle or the first attempt of the next cycle). Look in
    # both places — either is acceptable evidence that the loop fired.
    corrections_dir = vault / "_pipeline" / "corrections"
    assert corrections_dir.exists(), (
        "correction loop must call build_directive, which creates "
        "_pipeline/corrections/"
    )
    active = list(corrections_dir.glob("cycle-*.json"))
    archived = list((corrections_dir / "applied").glob("*.json"))
    assert active or archived, (
        "correction loop must persist a directive (in corrections/ or "
        "corrections/applied/ after 0.2.30 GC). Found neither."
    )


def test_scout_correction_loop_aborts_after_max_retries(tmp_path: Path) -> None:
    """If the scout keeps failing validation, the cycle MUST eventually abort.

    Without this cap, a misconfigured spec (or a degenerate agent) could
    burn through the token budget retrying forever. The default cap is
    1 retry (= 2 total attempts); after exhaustion the runner falls back
    to the historic abort path.
    """
    from research_framework.pipeline.cycle_runner import (
        MAX_SCOUT_VALIDATION_RETRIES,
        run_cycle_steps,
    )

    vault = _make_vault(tmp_path)
    cycle_num = 1
    cycles_dir = vault / "_pipeline" / "cycles"
    cycle_3 = f"{cycle_num:03d}"
    scout_report = cycles_dir / f"cycle-{cycle_3}-scout.json"
    scout_report.write_text(json.dumps({"schema_version": "2.0"}), encoding="utf-8")
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    validate_calls: list[int] = []
    scout_invocations: list[int] = []

    def _fake_run(cmd, **kwargs):
        script_name = Path(cmd[1]).name
        mock = MagicMock()
        mock.stdout = b""
        if script_name == "validate_cycle.py":
            validate_calls.append(1)
            _write_sidecar_with_errors(
                scout_report,
                ["required source 'open_web' not in sources_consulted"],
            )
            mock.returncode = 2  # always fail
            return mock
        if script_name == "agent_call.py" and "--stage" in cmd:
            stage = cmd[cmd.index("--stage") + 1]
            if stage == "scout":
                scout_invocations.append(1)
        mock.returncode = 0
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        rc = run_cycle_steps(vault, cycle_num)

    assert rc == 2, "persistent validation failure must eventually abort"
    expected_validate_calls = 1 + MAX_SCOUT_VALIDATION_RETRIES
    expected_scout_calls = 1 + MAX_SCOUT_VALIDATION_RETRIES
    assert len(validate_calls) == expected_validate_calls, (
        f"expected {expected_validate_calls} validate calls "
        f"(1 initial + {MAX_SCOUT_VALIDATION_RETRIES} retries); "
        f"got {len(validate_calls)}"
    )
    assert len(scout_invocations) == expected_scout_calls, (
        f"expected {expected_scout_calls} scout invocations; "
        f"got {len(scout_invocations)}"
    )


def test_empty_sidecar_falls_back_to_immediate_abort(tmp_path: Path) -> None:
    """If validate exit 2 but no sidecar (or empty errors), MUST abort fast.

    Mirrors the existing ``test_scout_abort_halts_cycle`` invariant but
    locks in the new code path's safety: we never loop on an empty
    error signal (which would either spin forever or feed the scout a
    meaningless directive).
    """
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path)
    cycle_num = 1
    cycles_dir = vault / "_pipeline" / "cycles"
    cycle_3 = f"{cycle_num:03d}"
    scout_report = cycles_dir / f"cycle-{cycle_3}-scout.json"
    scout_report.write_text(json.dumps({"schema_version": "2.0"}), encoding="utf-8")
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    scout_invocations: list[int] = []

    def _fake_run(cmd, **kwargs):
        script_name = Path(cmd[1]).name
        mock = MagicMock()
        mock.stdout = b""
        if script_name == "validate_cycle.py":
            # No sidecar written → helper has no error list to feed back.
            mock.returncode = 2
            return mock
        if script_name == "agent_call.py" and "--stage" in cmd:
            stage = cmd[cmd.index("--stage") + 1]
            if stage == "scout":
                scout_invocations.append(1)
        mock.returncode = 0
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        rc = run_cycle_steps(vault, cycle_num)

    assert rc == 2
    # Only the initial scout, no retry: the helper must NOT loop when
    # it has no errors to propagate.
    assert len(scout_invocations) == 1, (
        f"empty sidecar must NOT trigger a retry loop; got "
        f"{len(scout_invocations)} scout invocations"
    )
