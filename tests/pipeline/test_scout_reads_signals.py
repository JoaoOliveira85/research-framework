"""Scout reads cached signals (spec 020 US2)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from research_framework.pipeline.cycle_runner import _load_yaml_settings
from research_framework.pipeline.steps import CycleContext, run_scout
from tests.pipeline.test_cycle_runner import _make_vault, _patch_cycle_runner_subprocess


def _write_settings(vault: Path, *, enabled: bool = True) -> None:
    (vault / "settings.yaml").write_text(
        f"stages:\n  source_extraction:\n    enabled: {str(enabled).lower()}\n",
        encoding="utf-8",
    )


def _ctx(vault: Path, *, enabled: bool = True) -> CycleContext:
    _write_settings(vault, enabled=enabled)
    settings = _load_yaml_settings(vault / "settings.yaml")
    pipeline = vault / "_pipeline"
    cycles = pipeline / "cycles"
    cycle_3 = "001"
    return CycleContext(
        vault_dir=vault,
        cycle_num=1,
        cycle_dir=cycles / f"cycle-{cycle_3}",
        settings=settings,
        scripts_dir=vault / "scripts",
        pipeline_dir=pipeline,
        cycles_dir=cycles,
        prompts_dir=pipeline / "prompts",
        python_bin="python3",
        env={"RV_PYTHON": "python3"},
    )


def test_scout_prompt_includes_cached_signal_json(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_settings(vault)
    sidecar = vault / "_pipeline" / "cycles" / "cycle-001" / "source-signals.json"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        json.dumps({"cycle": 1, "signals": [{"module": "code", "source_id": "s"}]}),
        encoding="utf-8",
    )
    rendered = vault / "_pipeline" / "cycles" / "cycle-001-scout-prompt.rendered.md"
    scout_path = vault / "_pipeline" / "cycles" / "cycle-001-scout.json"

    def _fake_run(cmd, **kwargs):
        script = Path(cmd[1]).name if len(cmd) > 1 else ""
        if script == "agent_call.py" and "--stage" in cmd:
            if cmd[cmd.index("--stage") + 1] == "scout":
                scout_path.write_text(
                    json.dumps(
                        {
                            "topics_found": {
                                "new": [{"title": "T", "module": "code"}],
                                "existing": [],
                            },
                            "cost_estimate_usd": 0.0,
                        }
                    ),
                    encoding="utf-8",
                )
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        run_scout(_ctx(vault))

    assert "Cached source signals" in rendered.read_text(encoding="utf-8")
    assert "code" in rendered.read_text(encoding="utf-8")


def test_scout_stage_no_git_or_http_subprocess(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    forbidden = []

    def _fake_run(cmd, **kwargs):
        joined = " ".join(str(c) for c in cmd)
        if joined.startswith("git ") or " gh " in f" {joined} ":
            forbidden.append(joined)
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        if Path(cmd[1]).name == "agent_call.py":
            (vault / "_pipeline" / "cycles" / "cycle-001-scout.json").write_text(
                json.dumps(
                    {
                        "topics_found": {"new": [], "existing": []},
                        "cost_estimate_usd": 0,
                    }
                ),
                encoding="utf-8",
            )
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        run_scout(_ctx(vault))

    assert not forbidden


def test_scout_prompt_contains_cached_payload_no_git(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_settings(vault)
    sidecar = vault / "_pipeline" / "cycles" / "cycle-001" / "source-signals.json"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        '{"cycle": 1, "signals": [{"module": "code", "source_id": "s"}]}',
        encoding="utf-8",
    )
    rendered = vault / "_pipeline" / "cycles" / "cycle-001-scout-prompt.rendered.md"
    forbidden: list[str] = []

    def _fake_run(cmd, **kwargs):
        joined = " ".join(str(c) for c in cmd)
        if joined.startswith("git ") or " gh " in f" {joined} ":
            forbidden.append(joined)
        if Path(cmd[1]).name == "agent_call.py":
            (vault / "_pipeline" / "cycles" / "cycle-001-scout.json").write_text(
                '{"topics_found": {"new": [], "existing": []}, "cost_estimate_usd": 0}',
                encoding="utf-8",
            )
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        run_scout(_ctx(vault))

    text = rendered.read_text(encoding="utf-8")
    assert "Cached source signals" in text
    assert "code" in text
    assert not forbidden


def test_scout_routes_topics_by_payload_module_field(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    sidecar = vault / "_pipeline" / "cycles" / "cycle-001" / "source-signals.json"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        json.dumps({"cycle": 1, "signals": [{"module": "youtube"}]}),
        encoding="utf-8",
    )
    scout_path = vault / "_pipeline" / "cycles" / "cycle-001-scout.json"
    scout_path.write_text(
        json.dumps({"topics_found": {"new": [{"title": "Vid"}], "existing": []}}),
        encoding="utf-8",
    )

    def _fake_run(cmd, **kwargs):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        result = run_scout(_ctx(vault))

    doc = json.loads(scout_path.read_text(encoding="utf-8"))
    new = doc["topics_found"]["new"][0]
    assert new.get("module") == "youtube"
    assert result.exit_code == 0
