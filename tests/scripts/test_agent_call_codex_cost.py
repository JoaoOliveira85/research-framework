"""Spec 028 rc3 amendment — codex-runtime cost telemetry.

Pins the three properties of the amendment (plan A1/A2/A3):

* **A3** — every dispatch sidecar carries ``schema_version: "1.2"`` and a
  ``cost_source`` discriminator.
* **A2** — a real non-claude dispatch with no parseable cost falls back to the
  spec-033 estimator (``cost_source: "estimated"``), never a silent ``$0``.
* **A1** — when codex emits a parseable per-call cost signal it wins
  (``cost_source: "runtime"``); a total estimator failure degrades to
  ``cost_source: "none"`` and emits a WARNING.

We never spawn ``codex`` — the non-stream runner is patched so the tests verify
the cost-resolution wiring only.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "agent_call.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("agent_call", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_call"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def agent_call():
    return _load_module()


@pytest.fixture
def codex_vault(tmp_path: Path) -> Path:
    """A vault whose settings.yaml pins every stage to Codex (real kind)."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "pipeline:\n"
        "  max_cycles: 20\n"
        "  budget_usd: 50\n"
        "default_executor:\n"
        "  type: cli\n"
        "  runtime: codex\n"
        "  model: gpt-5.4\n"
        "stages:\n"
        "  scout:\n"
        "    model: gpt-5.4\n",
        encoding="utf-8",
    )
    return vault


def _cycle_dir(vault: Path, cycle: int = 2) -> Path:
    d = vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _run_codex_dispatch(
    agent_call,
    vault: Path,
    cycle_dir: Path,
    *,
    stdout: str = "",
    returncode: int = 0,
) -> Path:
    """Dispatch a codex stage with a patched (non-spawning) runner; return the
    written sidecar path."""
    fake = subprocess.CompletedProcess(["codex"], returncode, stdout, "")
    with patch.object(agent_call, "_run_in_session_with_timeout", return_value=fake):
        agent_call.dispatch(
            "scout",
            "a representative scout prompt with enough text to estimate",
            vault_dir=vault,
            cycle_dir=cycle_dir,
        )
    return cycle_dir / "agent-calls" / "scout.json"


# ---------------------------------------------------------------------------
# A3 — schema 1.2 + cost_source field
# ---------------------------------------------------------------------------


class TestSidecarShapeA3:
    def test_codex_dispatch_sidecar_has_schema_1_2_and_cost_source(
        self, agent_call, codex_vault
    ) -> None:
        cycle_dir = _cycle_dir(codex_vault)
        sidecar = _run_codex_dispatch(agent_call, codex_vault, cycle_dir)
        assert sidecar.is_file()
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        assert data["schema_version"] == "1.2"
        assert "cost_source" in data
        assert data["cost_source"] in {"runtime", "estimated", "none"}


# ---------------------------------------------------------------------------
# A2 — estimator fallback (no silent $0)
# ---------------------------------------------------------------------------


class TestEstimatorFallbackA2:
    def test_codex_no_signal_writes_estimated_cost_source(
        self, agent_call, codex_vault
    ) -> None:
        cycle_dir = _cycle_dir(codex_vault)
        # No JSON cost line in stdout ⇒ A1 misses ⇒ A2 estimate stands.
        with patch.object(agent_call, "_fallback_estimate", return_value=(0.42, 1234)):
            sidecar = _run_codex_dispatch(
                agent_call, codex_vault, cycle_dir, stdout="plain prose, no cost"
            )
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        assert data["cost_source"] == "estimated"
        assert data["cost_usd"] == pytest.approx(0.42)
        assert data["tokens_in"] == 1234

    def test_real_codex_estimate_is_non_zero_for_fresh_vault(
        self, agent_call, codex_vault
    ) -> None:
        # Exercises the real estimator (no patch) — a fresh codex vault must
        # still estimate a non-zero ceiling rather than silently record $0.
        cycle_dir = _cycle_dir(codex_vault)
        sidecar = _run_codex_dispatch(
            agent_call, codex_vault, cycle_dir, stdout="no cost here"
        )
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        assert data["cost_source"] == "estimated"
        assert data["cost_usd"] > 0.0


# ---------------------------------------------------------------------------
# A1 — best-effort first-class codex cost parse
# ---------------------------------------------------------------------------


class TestCodexParseA1:
    def test_parsed_codex_cost_is_runtime_source(self, agent_call, codex_vault) -> None:
        cycle_dir = _cycle_dir(codex_vault)
        # A JSON cost line embedded in the codex stdout.
        cost_line = json.dumps(
            {
                "total_cost_usd": 1.23,
                "usage": {"input_tokens": 100, "output_tokens": 50},
            }
        )
        stdout = f"some reasoning text\n{cost_line}\nmore text\n"
        # Patch the estimator to a sentinel that must NOT win when a real
        # signal is present.
        with patch.object(agent_call, "_fallback_estimate", return_value=(99.0, 1)):
            sidecar = _run_codex_dispatch(
                agent_call, codex_vault, cycle_dir, stdout=stdout
            )
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        assert data["cost_source"] == "runtime"
        assert data["cost_usd"] == pytest.approx(1.23)
        assert data["tokens_in"] == 100
        assert data["tokens_out"] == 50

    def test_no_signal_falls_back_to_estimated(self, agent_call, codex_vault) -> None:
        cycle_dir = _cycle_dir(codex_vault)
        with patch.object(agent_call, "_fallback_estimate", return_value=(0.07, 42)):
            sidecar = _run_codex_dispatch(
                agent_call, codex_vault, cycle_dir, stdout="no json cost object"
            )
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        assert data["cost_source"] == "estimated"
        assert data["cost_usd"] == pytest.approx(0.07)

    def test_total_estimate_failure_is_none_with_warning(
        self, agent_call, codex_vault, capsys
    ) -> None:
        cycle_dir = _cycle_dir(codex_vault)
        # Both A1 (no signal) and A2 (estimator unavailable) fail ⇒ none + WARN.
        with patch.object(agent_call, "_fallback_estimate", return_value=None):
            sidecar = _run_codex_dispatch(
                agent_call, codex_vault, cycle_dir, stdout="nothing parseable"
            )
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        assert data["cost_source"] == "none"
        assert data["cost_usd"] == pytest.approx(0.0)
        captured = capsys.readouterr()
        assert "WARN" in captured.err
        assert "cost_source=none" in captured.err


# ---------------------------------------------------------------------------
# A3 (consumer tolerance) — readers must not choke on the new field
# ---------------------------------------------------------------------------


class TestParseHelperUnit:
    def test_codex_cost_from_output_parses_total_cost_usd(self, agent_call) -> None:
        line = json.dumps({"total_cost_usd": 2.5, "tokens_in": 9, "tokens_out": 3})
        parsed = agent_call._codex_cost_from_output(f"prefix\n{line}\n")
        assert parsed == (2.5, 9, 3)

    def test_codex_cost_from_output_no_op_on_plain_text(self, agent_call) -> None:
        assert agent_call._codex_cost_from_output("just words, no json") is None
        assert agent_call._codex_cost_from_output("") is None
