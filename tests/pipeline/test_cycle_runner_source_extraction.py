"""Cycle runner source-extraction step tests (FR-001/FR-002)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from research_framework.pipeline.cycle_runner import run_cycle_steps
from tests.pipeline.test_cycle_runner import _make_vault, _patch_cycle_runner_subprocess


def test_step_15_runs_before_scout_when_enabled(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    (vault / "settings.yaml").write_text(
        "stages:\n  source_extraction:\n    enabled: true\n",
        encoding="utf-8",
    )
    order: list[str] = []

    pipeline = vault / "_pipeline"
    (pipeline / "vault-metrics.json").write_text("{}", encoding="utf-8")
    cycles = pipeline / "cycles"
    (cycles / "cycle-001-scout.json").write_text("{}", encoding="utf-8")
    (cycles / "cycle-001-research.json").write_text("{}", encoding="utf-8")

    def _fake_run(cmd, **kwargs):
        script = Path(cmd[1]).name if len(cmd) > 1 else ""
        if script == "vault_metrics.py":
            (pipeline / "vault-metrics.json").write_text("{}", encoding="utf-8")
        if script == "source_bridge.py":
            order.append("source_bridge")
        elif script == "agent_call.py" and "--stage" in cmd:
            if cmd[cmd.index("--stage") + 1] == "scout":
                order.append("scout")
                (cycles / "cycle-001-scout.json").write_text(
                    '{"topics_found": {"new": [], "existing": []}, "cost_estimate_usd": 0}',
                    encoding="utf-8",
                )
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b"{}"
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        run_cycle_steps(vault, 1)

    assert order.index("source_bridge") < order.index("scout")


def test_cycle_runner_spawns_source_bridge_subprocess(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    (vault / "settings.yaml").write_text(
        "stages:\n  source_extraction:\n    enabled: true\n",
        encoding="utf-8",
    )
    seen: list[Path] = []

    pipeline = vault / "_pipeline"
    (pipeline / "vault-metrics.json").write_text("{}", encoding="utf-8")
    cycles = pipeline / "cycles"
    (cycles / "cycle-002-scout.json").write_text("{}", encoding="utf-8")
    (cycles / "cycle-002-research.json").write_text("{}", encoding="utf-8")

    def _fake_run(cmd, **kwargs):
        script = Path(cmd[1]).name if len(cmd) > 1 else ""
        if script == "vault_metrics.py":
            (pipeline / "vault-metrics.json").write_text("{}", encoding="utf-8")
        if script == "source_bridge.py":
            seen.append(Path(cmd[1]))
            assert "--vault" in cmd
            assert "--cycle" in cmd
        if script == "agent_call.py" and "--stage" in cmd:
            (cycles / "cycle-002-scout.json").write_text(
                '{"topics_found": {"new": [], "existing": []}, "cost_estimate_usd": 0}',
                encoding="utf-8",
            )
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b"{}"
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        run_cycle_steps(vault, 2)

    assert seen


def test_source_bridge_prefers_per_vault_script_when_present(tmp_path: Path) -> None:
    """Regression: the installed-package layout has
    ``Path(__file__).parents[3] == .venv/lib/python3.12/`` (NOT the repo
    root) so ``<parents[3]>/scripts/source_bridge.py`` does not exist.
    The runner must prefer ``<vault>/scripts/source_bridge.py`` (which
    ``generate.sh`` ships) over the dev-mode fallback.

    Discovered during the feeds-vault revival, 2026-05-30 post-mortem.
    """
    vault = _make_vault(tmp_path)
    (vault / "settings.yaml").write_text(
        "stages:\n  source_extraction:\n    enabled: true\n",
        encoding="utf-8",
    )
    # Ship a per-vault source_bridge.py so the patched path-preference
    # kicks in (would land here in production too via generate.sh).
    per_vault_bridge = vault / "scripts" / "source_bridge.py"
    per_vault_bridge.write_text("# stub\n", encoding="utf-8")

    pipeline = vault / "_pipeline"
    (pipeline / "vault-metrics.json").write_text("{}", encoding="utf-8")
    cycles = pipeline / "cycles"
    (cycles / "cycle-001-scout.json").write_text("{}", encoding="utf-8")
    (cycles / "cycle-001-research.json").write_text("{}", encoding="utf-8")

    bridge_paths_seen: list[Path] = []

    def _fake_run(cmd, **kwargs):
        script_path = Path(cmd[1]) if len(cmd) > 1 else None
        if script_path and script_path.name == "vault_metrics.py":
            (pipeline / "vault-metrics.json").write_text("{}", encoding="utf-8")
        if script_path and script_path.name == "source_bridge.py":
            bridge_paths_seen.append(script_path)
        if script_path and script_path.name == "agent_call.py" and "--stage" in cmd:
            if cmd[cmd.index("--stage") + 1] == "scout":
                (cycles / "cycle-001-scout.json").write_text(
                    '{"topics_found": {"new": [], "existing": []}, "cost_estimate_usd": 0}',
                    encoding="utf-8",
                )
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b"{}"
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        run_cycle_steps(vault, 1)

    assert bridge_paths_seen, "source_bridge.py was not invoked"
    # The runner must pick the per-vault copy — NOT a path computed from
    # Path(__file__).parents[3] (which points into site-packages on a
    # production install).
    assert bridge_paths_seen[0] == per_vault_bridge
