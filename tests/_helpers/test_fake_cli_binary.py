"""Contract for the CLI-binary fake seam (issue #270).

The point of the seam is *what runs for real*. Under the wholesale
``fake_agent.install_shim`` swap the vault's ``scripts/agent_call.py`` IS the
fake, so argv construction, the stream-json framing, the cost parser and the
sidecar-v1.2 writer never execute in any test that drives a cycle — which is
how a ``NameError`` in the shim's ``dispatch`` (#259) and a missing ``model``
kwarg (#262) both shipped. Here the vault keeps the REAL dispatcher and only
the leaf binary is fake, so every assertion below is a statement about
production code.

Tier 2 (contract) except where marked; the tier-5 proof that a whole cycle
runs on this seam lives in ``tests/e2e/test_cli_binary_seam.py``.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests._helpers import fake_cli_binary
from tests._helpers.vault_factory import build_minimal_vault

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# argv contract — the fake exists to *check* what the real adapter emits
# ---------------------------------------------------------------------------


def test_claude_stub_accepts_the_argv_the_real_adapter_builds() -> None:
    """``agent_call._claude_cmd`` is the authority; parse its actual output."""
    agent_call = fake_cli_binary.load_agent_call()
    cmd = agent_call._claude_cmd({"model": "sonnet", "args": []})
    shape = fake_cli_binary.parse_argv("claude", cmd[1:])
    assert shape.model == "sonnet"
    assert shape.stream_json is False


def test_claude_stub_recognises_the_stream_json_variant() -> None:
    agent_call = fake_cli_binary.load_agent_call()
    cmd = agent_call._claude_cmd_with_cost({"model": "sonnet", "args": []})
    shape = fake_cli_binary.parse_argv("claude", cmd[1:])
    assert shape.stream_json is True


def test_codex_stub_accepts_the_argv_the_real_adapter_builds(tmp_path: Path) -> None:
    agent_call = fake_cli_binary.load_agent_call()
    cmd = agent_call._codex_cmd({"model": "gpt-5", "args": []}, tmp_path)
    shape = fake_cli_binary.parse_argv("codex", cmd[1:])
    assert shape.model == "gpt-5"


def test_claude_stub_rejects_argv_without_print() -> None:
    """A dispatcher that stopped emitting ``--print`` would hang the real CLI
    waiting on an interactive session; the fake must not paper over it."""
    with pytest.raises(fake_cli_binary.ArgvContractError, match="--print"):
        fake_cli_binary.parse_argv("claude", ["--model", "sonnet"])


def test_claude_stub_rejects_argv_without_a_model() -> None:
    with pytest.raises(fake_cli_binary.ArgvContractError, match="--model"):
        fake_cli_binary.parse_argv("claude", ["--print"])


def test_codex_stub_rejects_argv_without_the_exec_subcommand() -> None:
    with pytest.raises(fake_cli_binary.ArgvContractError, match="exec"):
        fake_cli_binary.parse_argv("codex", ["--model", "gpt-5"])


# ---------------------------------------------------------------------------
# fail-closed: no call context ⇒ no silent success
# ---------------------------------------------------------------------------


def test_stub_fails_closed_without_a_call_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(fake_cli_binary.VAULT_ENV, raising=False)
    monkeypatch.delenv(fake_cli_binary.STAGE_ENV, raising=False)
    out = io.StringIO()
    rc = fake_cli_binary.stub_main(
        "claude",
        ["--model", "sonnet", "--print"],
        stdin=io.StringIO("prompt"),
        stdout=out,
    )
    assert rc == 2
    assert out.getvalue() == ""


# ---------------------------------------------------------------------------
# installation
# ---------------------------------------------------------------------------


def test_install_writes_executables_for_each_profile(tmp_path: Path) -> None:
    installed = fake_cli_binary.install(tmp_path / "bin")
    assert set(installed) == {"claude", "codex"}
    for runtime, path in installed.items():
        assert path.name == runtime, "the binary must be named as the CLI it fakes"
        assert os.access(path, os.X_OK)


def test_activate_puts_the_stubs_on_path_and_in_the_per_profile_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = fake_cli_binary.activate(monkeypatch, tmp_path / "bin")
    assert os.environ["CLAUDE_BIN"] == str(installed["claude"])
    assert os.environ["CODEX_BIN"] == str(installed["codex"])
    assert str((tmp_path / "bin").resolve()) in os.environ["PATH"].split(os.pathsep)


# ---------------------------------------------------------------------------
# the real dispatcher, driving the fake binary
# ---------------------------------------------------------------------------


def _run_real_dispatcher(
    vault: Path,
    stage: str,
    prompt: str,
    *,
    cost_sidecar: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Spawn the vault's REAL ``scripts/agent_call.py`` exactly as the runner does."""
    prompt_file = vault / "_pipeline" / f"{stage}-prompt.md"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(prompt, encoding="utf-8")
    cmd = [
        sys.executable,
        str(vault / "scripts" / "agent_call.py"),
        "--vault",
        str(vault),
        "--stage",
        stage,
        "--prompt-file",
        str(prompt_file),
    ]
    if cost_sidecar is not None:
        cmd += ["--cost-sidecar", str(cost_sidecar)]
    return subprocess.run(
        cmd, capture_output=True, text=True, env=env or os.environ.copy()
    )


def _binary_seam_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    vault = build_minimal_vault(
        tmp_path,
        num_categories=1,
        num_targets_per_category=2,
        max_cycles=1,
        install_fake_agent=False,
    )
    fake_cli_binary.activate(monkeypatch, tmp_path / "bin")
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv("PYTHONPATH", str(_REPO_ROOT))
    return vault


def test_vault_factory_can_keep_the_real_dispatcher(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path, max_cycles=1, install_fake_agent=False)
    body = (vault / "scripts" / "agent_call.py").read_text(encoding="utf-8")
    assert "delegates to tests/_helpers/fake_agent.py" not in body
    assert "_RUNTIME_ADAPTERS" in body, "the vault must hold the real dispatcher"


def test_real_dispatcher_drives_the_stub_and_the_stage_writes_its_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _binary_seam_vault(tmp_path, monkeypatch)
    scout_report = vault / "_pipeline" / "cycles" / "cycle-001" / "scout-report.json"
    proc = _run_real_dispatcher(
        vault,
        "scout",
        f"Cycle 1 scout. Write {scout_report}.\n",
    )
    assert proc.returncode == 0, proc.stderr
    assert scout_report.is_file(), proc.stderr


def test_the_real_sidecar_writer_records_a_real_claude_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sidecar is written by ``agent_call``, not by the fake.

    ``agent_kind: real`` is the load-bearing assertion: under the wholesale
    shim every sidecar in every test said ``fake``, so the production branch
    that stamps a real dispatch was never taken.
    """
    vault = _binary_seam_vault(tmp_path, monkeypatch)
    monkeypatch.setenv(fake_cli_binary.COST_ENV, "0.25")
    sidecar = (
        vault / "_pipeline" / "cycles" / "cycle-001" / "agent-calls" / "scout.json"
    )
    scout_report = vault / "_pipeline" / "cycles" / "cycle-001" / "scout-report.json"
    proc = _run_real_dispatcher(
        vault,
        "scout",
        f"Cycle 1 scout. Write {scout_report}.\n",
        cost_sidecar=sidecar,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.2"
    assert payload["agent"] == "claude"
    assert payload["agent_kind"] == "real"
    assert payload["status"] == "ok"
    assert payload["cost_source"] == "runtime"
    assert payload["cost_usd"] == pytest.approx(0.25)
    assert payload["tokens_in"] > 0, "the real stream parser must read usage"


def test_a_failing_stage_reaches_the_real_failure_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _binary_seam_vault(tmp_path, monkeypatch)
    sidecar = (
        vault / "_pipeline" / "cycles" / "cycle-001" / "agent-calls" / "unknown.json"
    )
    proc = _run_real_dispatcher(
        vault,
        "no_such_stage",
        "Cycle 1.\n",
        cost_sidecar=sidecar,
    )
    assert proc.returncode != 0
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["exit_code"] != 0


def test_the_codex_profile_reaches_the_codex_stub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-profile half of the seam: a codex vault must spawn ``codex``,
    through ``_codex_cmd``'s real ``exec`` + ``--cd`` argv."""
    vault = build_minimal_vault(
        tmp_path,
        num_categories=1,
        num_targets_per_category=2,
        max_cycles=1,
        install_fake_agent=False,
        settings_text=(
            "default_executor:\n"
            "  runtime: codex\n"
            "  model: gpt-5\n"
            "  timeout_s: 60\n"
            "stages:\n"
            "  verifier:\n"
            "    enabled: false\n"
        ),
    )
    fake_cli_binary.activate(monkeypatch, tmp_path / "bin")
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv("PYTHONPATH", str(_REPO_ROOT))
    scout_report = vault / "_pipeline" / "cycles" / "cycle-001" / "scout-report.json"
    proc = _run_real_dispatcher(
        vault, "scout", f"Cycle 1 scout. Write {scout_report}.\n"
    )
    assert proc.returncode == 0, proc.stderr
    assert scout_report.is_file()


# ---------------------------------------------------------------------------
# the seam's own enabling contract in agent_call.py
# ---------------------------------------------------------------------------


def test_agent_call_publishes_the_call_context_to_its_child() -> None:
    """The dispatcher tells the runtime child which vault and stage it is
    running. Without it a leaf-binary fake would have to guess both out of
    prompt prose, and the seam could not exist."""
    agent_call = fake_cli_binary.load_agent_call()
    agent_call._set_call_context(Path("/tmp/vault-x"), "scout")
    try:
        env = agent_call._child_env()
        assert env["RESEARCH_FRAMEWORK_VAULT"] == "/tmp/vault-x"
        assert env["RESEARCH_FRAMEWORK_STAGE"] == "scout"
        assert "PATH" in env, "the child must still inherit the ambient environment"
    finally:
        agent_call._set_call_context(None, None)


def test_call_context_is_not_leaked_into_this_process_environment() -> None:
    agent_call = fake_cli_binary.load_agent_call()
    agent_call._set_call_context(Path("/tmp/vault-y"), "research")
    try:
        assert "RESEARCH_FRAMEWORK_VAULT" not in os.environ
    finally:
        agent_call._set_call_context(None, None)
