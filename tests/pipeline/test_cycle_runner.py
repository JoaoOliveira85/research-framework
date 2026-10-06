"""Tests for the cycle_runner module (pipeline phase execution)."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _patch_cycle_runner_subprocess(fake_run):
    """Patch BOTH ``subprocess.run`` and ``subprocess.Popen`` inside
    :mod:`research_framework.pipeline.cycle_runner` so tests see every
    subprocess invocation regardless of which path the runner takes.

    Background: v0.2.23 routes log-file-bearing invocations (scout,
    note_writer) through ``subprocess.Popen`` for real-time streaming
    while keeping fire-and-forget invocations (validators, metrics) on
    ``subprocess.run``. Tests that only patched ``subprocess.run`` lost
    visibility into agent_call.py calls. This helper bridges both paths
    by feeding the same ``fake_run`` callable to a synthetic Popen mock
    that immediately yields no stdout and reports the canned returncode.
    """

    def _fake_popen(cmd, **kwargs):
        # Run the same recording callback as subprocess.run so the test
        # sees the call. Then build a Popen-shaped mock that satisfies
        # _run_script's streaming loop without doing any I/O.
        completed = fake_run(cmd, **kwargs)
        popen_mock = MagicMock()
        popen_mock.pid = 4242
        popen_mock.stdout = iter([])  # empty iterator → streaming loop exits
        popen_mock.returncode = completed.returncode
        popen_mock.wait = MagicMock(return_value=completed.returncode)
        popen_mock.poll = MagicMock(return_value=completed.returncode)
        popen_mock.terminate = MagicMock()
        popen_mock.kill = MagicMock()
        return popen_mock

    cm = contextlib.ExitStack()
    cm.enter_context(
        patch(
            "research_framework.pipeline.cycle_runner.subprocess.run",
            side_effect=fake_run,
        )
    )
    cm.enter_context(
        patch(
            "research_framework.pipeline.cycle_runner.subprocess.Popen",
            side_effect=_fake_popen,
        )
    )
    return cm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vault(
    tmp_path: Path, *, scout_prompt: bool = True, dfs_prompt: bool = True
) -> Path:
    """Create a minimal vault structure for testing."""
    vault = tmp_path / "vault"
    scripts = vault / "scripts"
    scripts.mkdir(parents=True)

    prompts = vault / "_pipeline" / "prompts"
    prompts.mkdir(parents=True)

    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)

    # Create stub script files so _run_script won't crash on missing files
    for script_name in [
        "vault_metrics.py",
        "agent_call.py",
        "validate_cycle.py",
        "validate_vault.py",
        "check_template_compliance.py",
        "check_acronym_links.py",
        "topic_harvest.py",
    ]:
        (scripts / script_name).write_text("# stub\n")

    if scout_prompt:
        (prompts / "scout-prompt.md").write_text(
            "Scout prompt for cycle {CYCLE_NUM}. Report: {SCOUT_REPORT}.\n"
        )
    if dfs_prompt:
        (prompts / "dfs-prompt.md").write_text(
            "DFS prompt for cycle {CYCLE_NUM}. Scout: {SCOUT_REPORT}. Research: {RESEARCH_REPORT}.\n"
        )

    return vault


def _make_subproc_run(returncode_map: dict[str, int] | None = None):
    """Return a mock for subprocess.run that returns the given return codes.

    ``returncode_map`` maps a substring of the command's script name to an int.
    Anything not matched returns 0.
    """
    rc_map = returncode_map or {}

    def _fake_run(cmd, **kwargs):
        # cmd[1] is the script path
        script_name = Path(cmd[1]).name if len(cmd) > 1 else ""
        # Check for stage argument for agent_call
        stage = None
        if "--stage" in cmd:
            stage_idx = cmd.index("--stage")
            if stage_idx + 1 < len(cmd):
                stage = cmd[stage_idx + 1]

        # Match by key in returncode_map
        for key, rc in rc_map.items():
            if key in script_name:
                # For agent_call, optionally match by stage
                if script_name == "agent_call.py" and ":" in key:
                    _, expected_stage = key.split(":", 1)
                    if stage == expected_stage:
                        mock = MagicMock()
                        mock.returncode = rc
                        mock.stdout = b""
                        return mock
                    continue
                mock = MagicMock()
                mock.returncode = rc
                mock.stdout = b""
                return mock

        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    return _fake_run


# ---------------------------------------------------------------------------
# T010-1: test_steps_execute_in_order
# ---------------------------------------------------------------------------


def test_steps_execute_in_order(tmp_path: Path) -> None:
    """All subprocess calls happen in the required order when all succeed."""
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path)
    cycle_num = 1
    cycles_dir = vault / "_pipeline" / "cycles"

    # Pre-create the reports that the runner checks for after agent calls
    cycle_3 = f"{cycle_num:03d}"
    (cycles_dir / f"cycle-{cycle_3}-scout.json").write_text("{}")
    (cycles_dir / f"cycle-{cycle_3}-research.json").write_text("{}")
    # Pre-create vault-metrics.json so shutil.copy doesn't fail
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    script_calls: list[str] = []

    def _fake_run(cmd, **kwargs):
        # Record script name (and stage for agent_call)
        script_name = Path(cmd[1]).name
        if script_name == "agent_call.py" and "--stage" in cmd:
            stage_idx = cmd.index("--stage")
            stage = cmd[stage_idx + 1]
            script_calls.append(f"agent_call.py --stage {stage}")
        else:
            script_calls.append(script_name)
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        rc = run_cycle_steps(vault, cycle_num)

    assert rc == 0

    # Expected order (from the spec):
    expected = [
        "vault_metrics.py",  # Step 0 pre-metrics
        "agent_call.py --stage scout",  # Step 1 scout
        "validate_cycle.py",  # Step 2 validate scout
        "agent_call.py --stage note_writer",  # Step 3 research DFS
        "validate_vault.py",  # Step 4 post-DFS validation
        "check_template_compliance.py",
        "check_acronym_links.py",
        "vault_metrics.py",  # Step 5 post-metrics
        "validate_cycle.py",  # Step 6 validate research
        "topic_harvest.py",  # Step 7 topic harvest
    ]

    assert script_calls == expected, f"Got: {script_calls}"


# ---------------------------------------------------------------------------
# T010-2: test_scout_abort_halts_cycle
# ---------------------------------------------------------------------------


def test_scout_abort_halts_cycle(tmp_path: Path) -> None:
    """validate_cycle returns 2 on scout report → function returns 2, note_writer never called."""
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path)
    cycle_num = 1
    cycles_dir = vault / "_pipeline" / "cycles"
    cycle_3 = f"{cycle_num:03d}"
    (cycles_dir / f"cycle-{cycle_3}-scout.json").write_text("{}")
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    note_writer_called = []

    def _fake_run(cmd, **kwargs):
        script_name = Path(cmd[1]).name
        if script_name == "agent_call.py" and "--stage" in cmd:
            stage_idx = cmd.index("--stage")
            if cmd[stage_idx + 1] == "note_writer":
                note_writer_called.append(True)
        mock = MagicMock()
        # validate_cycle returns 2
        if script_name == "validate_cycle.py":
            mock.returncode = 2
        else:
            mock.returncode = 0
        mock.stdout = b""
        return mock

    with patch(
        "research_framework.pipeline.cycle_runner.subprocess.run", side_effect=_fake_run
    ):
        rc = run_cycle_steps(vault, cycle_num)

    assert rc == 2
    assert not note_writer_called, "note_writer should never be called on scout ABORT"


# ---------------------------------------------------------------------------
# T010-3: test_scout_terminate_skips_dfs
# ---------------------------------------------------------------------------


def test_scout_terminate_skips_dfs(tmp_path: Path) -> None:
    """validate_cycle returns 1 on scout → returns 1, DFS skipped, post-metrics captured."""
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path)
    cycle_num = 1
    cycles_dir = vault / "_pipeline" / "cycles"
    cycle_3 = f"{cycle_num:03d}"
    (cycles_dir / f"cycle-{cycle_3}-scout.json").write_text("{}")
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    script_calls: list[str] = []

    def _fake_run(cmd, **kwargs):
        script_name = Path(cmd[1]).name
        if script_name == "agent_call.py" and "--stage" in cmd:
            stage_idx = cmd.index("--stage")
            stage = cmd[stage_idx + 1]
            script_calls.append(f"agent_call.py --stage {stage}")
        else:
            script_calls.append(script_name)
        mock = MagicMock()
        if script_name == "validate_cycle.py":
            mock.returncode = 1
        else:
            mock.returncode = 0
        mock.stdout = b""
        return mock

    with patch(
        "research_framework.pipeline.cycle_runner.subprocess.run", side_effect=_fake_run
    ):
        rc = run_cycle_steps(vault, cycle_num)

    assert rc == 1
    assert "agent_call.py --stage note_writer" not in script_calls, (
        "DFS must NOT run on TERMINATE"
    )
    # Post-metrics must still be captured (vault_metrics called twice: pre + post)
    vault_metrics_calls = [c for c in script_calls if c == "vault_metrics.py"]
    assert len(vault_metrics_calls) == 2, (
        f"Expected 2 vault_metrics calls, got: {vault_metrics_calls}"
    )


# ---------------------------------------------------------------------------
# T010-4: test_research_exit_code_propagated
# ---------------------------------------------------------------------------


def test_research_exit_code_propagated(tmp_path: Path) -> None:
    """validate_cycle returns 0 on scout, 1 on research → function returns 1."""
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path)
    cycle_num = 1
    cycles_dir = vault / "_pipeline" / "cycles"
    cycle_3 = f"{cycle_num:03d}"
    (cycles_dir / f"cycle-{cycle_3}-scout.json").write_text("{}")
    (cycles_dir / f"cycle-{cycle_3}-research.json").write_text("{}")
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    validate_call_count = [0]

    def _fake_run(cmd, **kwargs):
        script_name = Path(cmd[1]).name
        mock = MagicMock()
        mock.stdout = b""
        if script_name == "validate_cycle.py":
            validate_call_count[0] += 1
            # First call (scout) returns 0, second call (research) returns 1
            mock.returncode = 0 if validate_call_count[0] == 1 else 1
        else:
            mock.returncode = 0
        return mock

    with patch(
        "research_framework.pipeline.cycle_runner.subprocess.run", side_effect=_fake_run
    ):
        rc = run_cycle_steps(vault, cycle_num)

    assert rc == 1


# ---------------------------------------------------------------------------
# T010-5: test_rv_python_env_var_set
# ---------------------------------------------------------------------------


def test_rv_python_env_var_set(tmp_path: Path) -> None:
    """RV_PYTHON env var is set to sys.executable in every subprocess call."""
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path)
    cycle_num = 1
    cycles_dir = vault / "_pipeline" / "cycles"
    cycle_3 = f"{cycle_num:03d}"
    (cycles_dir / f"cycle-{cycle_3}-scout.json").write_text("{}")
    (cycles_dir / f"cycle-{cycle_3}-research.json").write_text("{}")
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    envs_seen: list[dict] = []

    def _fake_run(cmd, **kwargs):
        env = kwargs.get("env") or {}
        envs_seen.append(dict(env))
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with patch(
        "research_framework.pipeline.cycle_runner.subprocess.run", side_effect=_fake_run
    ):
        run_cycle_steps(vault, cycle_num)

    assert envs_seen, "no subprocess.run calls recorded"
    for i, env in enumerate(envs_seen):
        assert "RV_PYTHON" in env, f"call {i}: RV_PYTHON missing from env"
        assert env["RV_PYTHON"] == sys.executable, (
            f"call {i}: RV_PYTHON={env['RV_PYTHON']!r} != sys.executable={sys.executable!r}"
        )


# ---------------------------------------------------------------------------
# T010-6: test_scout_prompt_placeholders_substituted
# ---------------------------------------------------------------------------


def test_scout_prompt_placeholders_substituted(tmp_path: Path) -> None:
    """Rendered scout prompt file has {CYCLE_NUM} and {SCOUT_REPORT} replaced."""
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = tmp_path / "vault"
    scripts = vault / "scripts"
    scripts.mkdir(parents=True)
    prompts = vault / "_pipeline" / "prompts"
    prompts.mkdir(parents=True)
    cycles_dir = vault / "_pipeline" / "cycles"
    cycles_dir.mkdir(parents=True)

    for script_name in [
        "vault_metrics.py",
        "agent_call.py",
        "validate_cycle.py",
        "validate_vault.py",
        "check_template_compliance.py",
        "check_acronym_links.py",
        "topic_harvest.py",
    ]:
        (scripts / script_name).write_text("# stub\n")

    # Scout prompt with placeholders
    (prompts / "scout-prompt.md").write_text(
        "Cycle: {CYCLE_NUM}. Report at: {SCOUT_REPORT}.\n"
    )
    (prompts / "dfs-prompt.md").write_text(
        "DFS {CYCLE_NUM} {SCOUT_REPORT} {RESEARCH_REPORT}\n"
    )

    cycle_num = 1
    cycle_3 = f"{cycle_num:03d}"
    (cycles_dir / f"cycle-{cycle_3}-scout.json").write_text("{}")
    (cycles_dir / f"cycle-{cycle_3}-research.json").write_text("{}")
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    def _fake_run(cmd, **kwargs):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with patch(
        "research_framework.pipeline.cycle_runner.subprocess.run", side_effect=_fake_run
    ):
        run_cycle_steps(vault, cycle_num)

    rendered = cycles_dir / f"cycle-{cycle_3}-scout-prompt.rendered.md"
    assert rendered.exists(), f"rendered scout prompt not found at {rendered}"
    content = rendered.read_text()
    assert "{CYCLE_NUM}" not in content, "placeholder {CYCLE_NUM} was not substituted"
    assert "{SCOUT_REPORT}" not in content, (
        "placeholder {SCOUT_REPORT} was not substituted"
    )
    assert str(cycle_num) in content, "cycle number not in rendered content"
    assert "cycle-001-scout.json" in content, (
        "scout report path not in rendered content"
    )


# ---------------------------------------------------------------------------
# T010-7: test_missing_scout_prompt_returns_abort
# ---------------------------------------------------------------------------


def test_missing_scout_prompt_returns_abort(tmp_path: Path) -> None:
    """No scout-prompt.md → returns 2, zero agent_call subprocesses spawned."""
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path, scout_prompt=False)
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    agent_calls: list = []

    def _fake_run(cmd, **kwargs):
        script_name = Path(cmd[1]).name
        if script_name == "agent_call.py":
            agent_calls.append(cmd)
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with patch(
        "research_framework.pipeline.cycle_runner.subprocess.run", side_effect=_fake_run
    ):
        rc = run_cycle_steps(vault, 1)

    assert rc == 2
    assert not agent_calls, (
        "agent_call.py should not be called when scout prompt is missing"
    )


# ---------------------------------------------------------------------------
# T010-8: test_missing_dfs_prompt_returns_abort
# ---------------------------------------------------------------------------


def test_missing_dfs_prompt_returns_abort(tmp_path: Path) -> None:
    """scout succeeds, validate_cycle succeeds, no dfs-prompt.md → returns 2."""
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path, dfs_prompt=False)
    cycle_num = 1
    cycles_dir = vault / "_pipeline" / "cycles"
    cycle_3 = f"{cycle_num:03d}"
    (cycles_dir / f"cycle-{cycle_3}-scout.json").write_text("{}")
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    def _fake_run(cmd, **kwargs):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with patch(
        "research_framework.pipeline.cycle_runner.subprocess.run", side_effect=_fake_run
    ):
        rc = run_cycle_steps(vault, cycle_num)

    assert rc == 2


@pytest.mark.regression
def test_research_abort_is_not_masked_by_an_earlier_research_report(
    tmp_path: Path,
) -> None:
    """The research step aborts (rc 2) and a research.json is already on disk.

    An earlier attempt at the same cycle — a CG-001 retry, or the run a
    ``--resume`` picks up — leaves ``cycle-NNN-research.json`` behind.
    ``run_research`` dropped the step's exit code, so the only thing standing
    between its abort and a CONTINUE was "does the report exist", and the
    leftover answered yes: postprocess validated last attempt's report and the
    cycle returned 0.
    """
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path, dfs_prompt=False)
    cycles_dir = vault / "_pipeline" / "cycles"
    (cycles_dir / "cycle-001-scout.json").write_text("{}")
    (cycles_dir / "cycle-001-research.json").write_text(
        '{"notes_created": [], "notes_updated": []}'
    )
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    scripts: list[str] = []

    def _fake_run(cmd, **kwargs):
        scripts.append(Path(cmd[1]).name)
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        rc = run_cycle_steps(vault, 1)

    assert rc == 2
    assert "topic_harvest.py" not in scripts, "postprocess ran on an aborted research"


# ---------------------------------------------------------------------------
# T017: test_verifier_called_after_dfs
# ---------------------------------------------------------------------------


def test_verifier_called_after_dfs(tmp_path: Path) -> None:
    """verifier is invoked after note_writer (DFS); ordering is enforced."""
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path)
    cycle_num = 1
    cycles_dir = vault / "_pipeline" / "cycles"
    cycle_3 = f"{cycle_num:03d}"
    (cycles_dir / f"cycle-{cycle_3}-scout.json").write_text("{}")
    (cycles_dir / f"cycle-{cycle_3}-research.json").write_text(
        '{"notes_created": [], "notes_updated": []}'
    )
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    # Enable verifier in settings
    (vault / "settings.yaml").write_text("stages:\n  verifier:\n    enabled: true\n")

    call_order: list[tuple[str, ...]] = []

    def _fake_run(cmd, **kwargs):
        script_name = Path(cmd[1]).name if len(cmd) > 1 else ""
        if script_name == "agent_call.py" and "--stage" in cmd:
            stage_idx = cmd.index("--stage")
            call_order.append(("subprocess", cmd[stage_idx + 1]))
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    def _fake_verifier(
        vault_dir, cycle_num, report, *, scripts_dir=None, settings=None
    ):
        call_order.append(("verifier",))
        from research_framework.pipeline.verifier import VerifierSummary

        return VerifierSummary(cycle=cycle_num)

    with (
        _patch_cycle_runner_subprocess(_fake_run),
        patch(
            "research_framework.pipeline.verifier.run_verifier_stage",
            side_effect=_fake_verifier,
        ),
    ):
        rc = run_cycle_steps(vault, cycle_num)

    # note_writer must appear in subprocess call_order
    note_writer_pos = next(
        (i for i, c in enumerate(call_order) if c == ("subprocess", "note_writer")),
        None,
    )
    assert note_writer_pos is not None, "note_writer must be called"

    # verifier must be called at least once
    verifier_entries = [c for c in call_order if c == ("verifier",)]
    assert len(verifier_entries) >= 1, (
        f"verifier must be called at least once, call_order={call_order}"
    )

    # verifier must be called AFTER note_writer
    verifier_pos = next(
        (i for i, c in enumerate(call_order) if c == ("verifier",)), None
    )
    assert verifier_pos is not None, "verifier must be in call_order"
    assert verifier_pos > note_writer_pos, (
        f"verifier must be called after note_writer: note_writer at {note_writer_pos}, "
        f"verifier at {verifier_pos}, call_order={call_order}"
    )

    assert rc == 0


# ---------------------------------------------------------------------------
# T020: test_cycle_runner_handles_missing_agent_report
# ---------------------------------------------------------------------------


def test_cycle_runner_handles_missing_agent_report(tmp_path: Path) -> None:
    """subprocess exits 0 but never creates scout.json → function returns 2 (ABORT)."""
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path)
    # Pre-create vault-metrics.json so Step 0 copy succeeds
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    # subprocess.run always returns 0 — but NO output files are ever created
    def _fake_run(cmd, **kwargs):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with patch(
        "research_framework.pipeline.cycle_runner.subprocess.run", side_effect=_fake_run
    ):
        rc = run_cycle_steps(vault, cycle_num=1)

    assert rc == 2, f"Expected ABORT (2) when scout report is never written, got {rc}"


# ---------------------------------------------------------------------------
# T021: test_source_manager_called_after_research_validate
# ---------------------------------------------------------------------------


def test_source_manager_called_after_research_validate(tmp_path: Path) -> None:
    """source_manager.record_cycle is called after Step 6 (validate research) on a successful cycle."""
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path)
    cycle_num = 1
    cycles_dir = vault / "_pipeline" / "cycles"
    cycle_3 = f"{cycle_num:03d}"
    (cycles_dir / f"cycle-{cycle_3}-scout.json").write_text("{}")
    research_report = cycles_dir / f"cycle-{cycle_3}-research.json"
    research_report.write_text('{"notes_created": [], "notes_updated": []}')
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    record_calls: list[tuple] = []

    def _fake_record_cycle(vault_dir, cycle_n, report_data, *, notes_dir=None):
        record_calls.append((vault_dir, cycle_n, report_data))

    def _fake_run(cmd, **kwargs):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with (
        patch(
            "research_framework.pipeline.cycle_runner.subprocess.run",
            side_effect=_fake_run,
        ),
        patch(
            "research_framework.pipeline.source_manager.record_cycle",
            side_effect=_fake_record_cycle,
        ),
    ):
        rc = run_cycle_steps(vault, cycle_num)

    assert rc == 0
    assert len(record_calls) == 1, (
        f"Expected 1 record_cycle call, got {len(record_calls)}"
    )
    called_vault_dir, called_cycle_num, _ = record_calls[0]
    assert called_cycle_num == cycle_num, (
        f"Expected cycle_num={cycle_num}, got {called_cycle_num}"
    )
    assert called_vault_dir == vault, (
        f"Expected vault_dir={vault}, got {called_vault_dir}"
    )


# ---------------------------------------------------------------------------
# An unloadable settings.yaml fails closed (exit 2), it does not uncap the run
# ---------------------------------------------------------------------------

_CAPPED_SETTINGS = (
    "pipeline:\n  max_cycles: 2\n  budget_usd: 10.0\n"
    "limits:\n  cycle_budget_usd: 1.0\n"
    "approval_gates: [scout]\n"
)


@pytest.mark.regression
@pytest.mark.parametrize(
    "settings_text",
    [
        # One invalid key that has nothing to do with the budget.
        _CAPPED_SETTINGS + "default_agent: 42\n",
        # Not YAML at all.
        _CAPPED_SETTINGS + "stages: [unclosed\n",
        # A required key is missing (spec 076 FR-004).
        "pipeline:\n  budget_usd: 10.0\nlimits:\n  cycle_budget_usd: 1.0\n",
    ],
    ids=["invalid-unrelated-key", "yaml-parse-error", "missing-required-key"],
)
def test_unloadable_settings_aborts_the_cycle_before_any_dispatch(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, settings_text: str
) -> None:
    """A settings.yaml the typed loader rejects carries caps nobody can read.

    The runner used to catch the ``SettingsError`` and carry on with no budget
    session: the dollar, token and wall-clock caps and the approval gates were
    all dropped, silently, and every agent dispatched. It must abort instead.
    """
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path)
    (vault / "settings.yaml").write_text(settings_text, encoding="utf-8")
    cycles_dir = vault / "_pipeline" / "cycles"
    (cycles_dir / "cycle-001-scout.json").write_text("{}")
    (cycles_dir / "cycle-001-research.json").write_text("{}")
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    dispatched: list[str] = []

    def _fake_run(cmd, **kwargs):
        if Path(cmd[1]).name == "agent_call.py":
            dispatched.append(cmd[cmd.index("--stage") + 1])
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with (
        caplog.at_level("ERROR", logger="research_framework"),
        _patch_cycle_runner_subprocess(_fake_run),
    ):
        rc = run_cycle_steps(vault, 1)

    assert rc == 2
    assert dispatched == [], f"agents dispatched without their caps: {dispatched}"
    assert any(
        "settings.yaml" in rec.getMessage() and rec.levelname == "ERROR"
        for rec in caplog.records
    ), "the abort must name settings.yaml at ERROR (spec 077 FR-017)"
