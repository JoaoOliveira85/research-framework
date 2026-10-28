"""`strict_settings: true` refuses every CLI verb that dispatches cycles (#8).

The first cut enforced it only inside ``orchestrator.run_cycles``, which
``cycle`` never calls — ``./vault cycle N`` ran a cycle over an unknown key. The
refusal now lives in one shared check, ``strict_settings_refusal``, called by
``run_cycles`` and by each verb entry point *before* it has any side effect.
Verbs that only read or price (``--estimate-only``, ``pipeline status``) are not
refused.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from research_framework.cli import main

_BASE = "pipeline:\n  max_cycles: 3\n  budget_usd: 5.0\n"
_STRICT_TYPO = "strict_settings: true\ndefault_agnet: codex\n"


def _vault(tmp_path: Path, body: str) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    (vault / "settings.yaml").write_text(_BASE + body, encoding="utf-8")
    return vault


def _spy(monkeypatch: pytest.MonkeyPatch, target: str) -> list[Any]:
    calls: list[Any] = []

    def _fake(*a: Any, **k: Any) -> int:
        calls.append((a, k))
        return 0

    monkeypatch.setattr(target, _fake)
    return calls


def test_cycle_verb_refuses_over_an_unknown_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    vault = _vault(tmp_path, _STRICT_TYPO)
    calls = _spy(
        monkeypatch, "research_framework.pipeline.orchestrator.run_single_cycle"
    )

    rc = main(["cycle", "--vault", str(vault), "--cycle", "1"])

    assert rc == 2
    assert not calls, "`cycle` must not run a cycle over an unknown key"
    err = capsys.readouterr().err
    assert "default_agnet" in err
    assert "default_agent" in err
    assert "strict_settings" in err


def test_cycle_verb_runs_when_strict_and_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    vault = _vault(tmp_path, "strict_settings: true\n")
    calls = _spy(
        monkeypatch, "research_framework.pipeline.orchestrator.run_single_cycle"
    )
    assert main(["cycle", "--vault", str(vault), "--cycle", "1"]) == 0
    assert calls


def test_cycle_verb_runs_over_an_unknown_key_when_not_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    vault = _vault(tmp_path, "default_agnet: codex\n")
    calls = _spy(
        monkeypatch, "research_framework.pipeline.orchestrator.run_single_cycle"
    )
    assert main(["cycle", "--vault", str(vault), "--cycle", "1"]) == 0
    assert calls


def test_cycle_estimate_only_is_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Pricing a cycle dispatches nothing, so strict mode has nothing to stop."""
    vault = _vault(tmp_path, _STRICT_TYPO)
    calls = _spy(monkeypatch, "research_framework.cli.research_cycles._estimate_only")
    assert (
        main(["cycle", "--vault", str(vault), "--cycle", "1", "--estimate-only"]) == 0
    )
    assert calls


@pytest.mark.parametrize(
    "sub", ["full", "collect", "extract", "scout", "resume", "finish"]
)
def test_pipeline_run_verbs_refuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    sub: str,
):
    vault = _vault(tmp_path, _STRICT_TYPO)
    calls = [
        _spy(monkeypatch, f"research_framework.pipeline.runner.run_{name}")
        for name in ("full", "collect", "extract", "scout", "resume", "finish")
    ]

    rc = main(["pipeline", str(vault), sub])

    assert rc == 2
    assert not any(calls), f"`pipeline {sub}` must not start a phase"
    assert "default_agnet" in capsys.readouterr().err


def test_pipeline_status_is_not_refused(tmp_path: Path):
    vault = _vault(tmp_path, _STRICT_TYPO)
    assert main(["pipeline", str(vault), "status"]) != 2


def test_generate_resume_refuses_before_touching_the_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    vault = _vault(tmp_path, _STRICT_TYPO)
    calls = _spy(monkeypatch, "research_framework.pipeline.orchestrator.run_cycles")

    rc = main(
        [
            "generate",
            "--resume",
            "--spec",
            str(vault / "research.spec.md"),
            "--output",
            str(vault),
        ]
    )

    assert rc == 2
    assert not calls
    assert "default_agnet" in capsys.readouterr().err
