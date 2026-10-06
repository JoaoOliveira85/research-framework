"""FR3/FR4 (spec 061): the ``--max-cycles`` / ``--max-usd`` last-word flags.

Covers the CLI surface (the flags exist on the single ``generate`` subparser that
also serves ``--resume`` + inline phase-3), the precedence threading into
``run_cycles`` (flag > settings > default), invalid-value rejection (exit 2), and
the reworded constrained-exit hint (names ``pipeline.max_cycles`` + ``--max-cycles``,
never the removed ``budget.*`` keys).
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from research_framework.cli._budget_resolve import BudgetResolution
from research_framework.cli._parser import build_parser
from research_framework.spec.schema import SpecConfig

# ---------------------------------------------------------------------------
# T011 — CLI surface (Tier 2): the flags are declared on the generate subparser.
# ---------------------------------------------------------------------------


def test_generate_parser_declares_max_cycles_option() -> None:
    ns = build_parser().parse_args(["generate", "--spec", "x", "--max-cycles", "5"])
    assert ns.max_cycles == 5


def test_generate_parser_declares_max_usd_option() -> None:
    ns = build_parser().parse_args(["generate", "--spec", "x", "--max-usd", "50.0"])
    assert ns.max_usd == 50.0


def test_resume_and_phase3_parsers_declare_max_cycles() -> None:
    """Topology note: there is ONE ``generate`` subparser — ``--resume`` is a flag
    on it and phase-3 runs inline after ``run_cycles`` in the same invocation, so
    the resume AND phase-3 entry points ARE the generate subparser. Assert it
    accepts both flags in a ``--resume`` invocation (plan D3 — all three paths)."""
    ns = build_parser().parse_args(
        ["generate", "--resume", "--spec", "x", "--max-cycles", "5", "--max-usd", "50"]
    )
    assert ns.resume is True
    assert ns.max_cycles == 5
    assert ns.max_usd == 50.0


# ---------------------------------------------------------------------------
# Tier-3 helper: drive the real generate budget-resolution seam with the heavy
# phases (scaffold/render/scripts/phase3) stubbed, capturing what is threaded
# into run_cycles. The vault's settings.yaml is the only on-disk budget source.
# ---------------------------------------------------------------------------


def _drive_generate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    settings_body: str,
    flag_max_cycles: int | None = None,
    flag_max_usd: float | None = None,
    spec: Any = None,
) -> tuple[int, BudgetResolution | None, Any]:
    import research_framework.cli.research_generate as rg

    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "settings.yaml").write_text(settings_body, encoding="utf-8")

    if spec is None:
        spec = SimpleNamespace(name="t", location=vault)
    else:
        object.__setattr__(spec, "location", vault)

    captured: dict[str, Any] = {}

    def _fake_run_cycles(
        spec_arg: Any, vd: Path, *, budget: BudgetResolution, **_: Any
    ) -> int:
        captured["spec"] = spec_arg
        captured["budget"] = budget
        return 0

    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_cycles",
        _fake_run_cycles,
        raising=True,
    )
    monkeypatch.setattr(rg, "load_spec", lambda *a, **k: spec, raising=True)
    monkeypatch.setattr(rg, "validate", lambda *a, **k: None, raising=True)
    monkeypatch.setattr(rg, "scaffold", lambda *a, **k: None, raising=True)
    monkeypatch.setattr(rg, "render_all", lambda *a, **k: None, raising=True)
    monkeypatch.setattr(rg, "copy_scripts", lambda *a, **k: None, raising=True)
    monkeypatch.setattr(rg, "_run_phase3", lambda *a, **k: 0, raising=True)

    args = SimpleNamespace(
        regenerate_plan_only=False,
        legacy_cycle_runner=False,
        spec=vault / "research.spec.md",
        dry_run=False,
        resume=False,
        output=vault,
        settings=None,
        prepopulate=None,
        skip_gate=True,
        max_cycles=flag_max_cycles,
        max_usd=flag_max_usd,
    )
    rc = rg._cmd_generate(args)
    return rc, captured.get("budget"), captured.get("spec")


# ---------------------------------------------------------------------------
# T013 — precedence threading (Tier 3): flag > settings > default; invalid → 2.
# ---------------------------------------------------------------------------


def test_flag_beats_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rc, budget, _ = _drive_generate(
        monkeypatch,
        tmp_path,
        settings_body="pipeline:\n  max_cycles: 12\n  budget_usd: 10.0\n",
        flag_max_cycles=3,
    )
    assert rc == 0
    assert budget is not None
    assert budget.max_cycles == 3
    assert budget.max_cycles_source == "flag"


def test_flag_beats_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rc, budget, _ = _drive_generate(
        monkeypatch,
        tmp_path,
        settings_body="pipeline:\n  budget_usd: 10.0\n",  # no cycle key
        flag_max_cycles=4,
    )
    assert rc == 0
    assert budget is not None
    assert budget.max_cycles == 4
    assert budget.max_cycles_source == "flag"


def test_absent_flag_falls_through_to_settings_then_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two cases inlined (NOT ``@parametrize``-d: the foreman Arm A verifier
    matches a single bare nodeid, which a parametrized ``[param]`` suffix
    defeats): (a) settings 12 ⇒ 12/settings; (b) no cycle key ⇒ default 20."""
    rc, budget, _ = _drive_generate(
        monkeypatch,
        tmp_path / "a",
        settings_body="pipeline:\n  max_cycles: 12\n  budget_usd: 10.0\n",
    )
    assert rc == 0
    assert budget is not None
    assert (budget.max_cycles, budget.max_cycles_source) == (12, "settings")

    rc, budget, _ = _drive_generate(
        monkeypatch,
        tmp_path / "b",
        settings_body="pipeline:\n  budget_usd: 10.0\n",  # no cycle key
    )
    assert rc == 0
    assert budget is not None
    assert (budget.max_cycles, budget.max_cycles_source) == (20, "default")


def test_invalid_max_cycles_zero_or_negative_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """0 and -1 inlined (single nodeid for the foreman verifier). Each MUST exit
    2 with a clear positive-integer message and never start a run."""
    for i, bad in enumerate((0, -1)):
        rc, budget, _ = _drive_generate(
            monkeypatch,
            tmp_path / f"bad{i}",
            settings_body="pipeline:\n  max_cycles: 12\n  budget_usd: 10.0\n",
            flag_max_cycles=bad,
        )
        assert rc == 2
        # MUST NOT start a run — run_cycles was never reached.
        assert budget is None
        assert "positive integer" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# T014 — orchestrator is fully param-driven (Tier 3): a stray spec budget field
# is NOT honoured; the threaded settings value wins.
# ---------------------------------------------------------------------------


def test_orchestrator_uses_threaded_params_not_spec_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A real parsed spec carrying stray budget fields (dropped by the schema).
    spec = SpecConfig.from_dict(
        {"name": "t", "location": "/tmp/x", "budget": {"max_cycles": 999}}
    )
    rc, budget, spec_seen = _drive_generate(
        monkeypatch,
        tmp_path,
        settings_body="pipeline:\n  max_cycles: 7\n  budget_usd: 10.0\n",
        spec=spec,
    )
    assert rc == 0
    assert budget is not None
    assert budget.max_cycles == 7  # settings, NOT the stray spec 999
    assert not hasattr(spec_seen.budget, "max_cycles")


# ---------------------------------------------------------------------------
# T018 — the constrained-exit hint names the new keys, never the removed ones.
# ---------------------------------------------------------------------------


def test_constrained_exit_hint_names_pipeline_max_cycles_and_flag(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from research_framework.pipeline.orchestrator import _constrained_exit

    with caplog.at_level(logging.INFO):
        rc = _constrained_exit(
            tmp_path,
            reason="max_cycles (3) reached",
            new_topics=[],
            followups=[],
            stubs_count=0,
            health_count=0,
            coverage_met=True,  # avoids the unmet_targets I/O path
        )
    assert rc == 1
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "pipeline.max_cycles" in msgs
    assert "--max-cycles" in msgs
    # The removed spec keys must NOT appear in the user-facing hint.
    assert "budget.max_cycles" not in msgs
    assert "budget.max_usd" not in msgs
