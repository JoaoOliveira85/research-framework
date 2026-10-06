"""Tier-2 cost_estimator tests (spec 033)."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from research_framework.pipeline.cost_estimator import estimate_dispatch
from research_framework.pipeline.settings import LimitsSettings

_OUTPUT_RATE_CLAUDE = 15.0 / 1_000_000


def _install_fake_tiktoken(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeEncoding:
        def encode(self, text: str) -> list[int]:
            return [0] * len(text or "")

    def get_encoding(name: str) -> _FakeEncoding:
        assert name in ("cl100k_base", "o200k_base")
        return _FakeEncoding()

    fake = types.ModuleType("tiktoken")
    fake.get_encoding = get_encoding
    monkeypatch.setitem(sys.modules, "tiktoken", fake)


def _seed_history(vault: Path, stage: str, costs: list[float]) -> None:
    for i, cost in enumerate(costs, start=1):
        cycle_dir = vault / "_pipeline/cycles/cycle-001/agent-calls"
        cycle_dir.mkdir(parents=True, exist_ok=True)
        (cycle_dir / f"{stage}-{i}.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.1",
                    "stage": stage,
                    "agent": "claude",
                    "agent_kind": "fake",
                    "tier": "standard",
                    "status": "ok",
                    "exit_code": 0,
                    "cost_usd": cost,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "latency_ms": 0,
                    "started_at": "2026-01-01T00:00:00Z",
                    "completed_at": "2026-01-01T00:00:01Z",
                    "cycle": 1,
                }
            ),
            encoding="utf-8",
        )


def test_estimate_dispatch_p95_history_with_three_samples(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _seed_history(vault, "scout", [0.10, 0.20, 0.30, 0.40])
    limits = LimitsSettings()
    est = estimate_dispatch(
        vault_dir=vault,
        cycle_num=2,
        stage="scout",
        prompt_text="hello",
        agent="claude",
        tier="standard",
        limits=limits,
    )
    assert est.estimation_method == "p95_history"
    assert est.cost_usd >= 0.30


def test_estimate_dispatch_default_ceiling_without_history(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    limits = LimitsSettings()
    est = estimate_dispatch(
        vault_dir=vault,
        cycle_num=1,
        stage="scout",
        prompt_text="",
        agent="claude",
        tier="standard",
        limits=limits,
    )
    assert est.estimation_method == "default_ceiling"
    assert est.cost_usd >= 0.80


def test_estimate_dispatch_tiktoken_when_budget_extra_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_tiktoken(monkeypatch)
    vault = tmp_path / "vault"
    vault.mkdir()
    limits = LimitsSettings()
    est = estimate_dispatch(
        vault_dir=vault,
        cycle_num=1,
        stage="scout",
        prompt_text="token estimate path",
        agent="claude",
        tier="standard",
        limits=limits,
    )
    assert est.estimation_method == "tiktoken"


def test_estimate_dispatch_fail_closed_to_ceiling_on_tiktoken_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    class Broken:
        @staticmethod
        def get_encoding(name: str) -> None:
            raise RuntimeError("boom")

    fake = type("tiktoken", (), {"get_encoding": Broken.get_encoding})
    monkeypatch.setitem(__import__("sys").modules, "tiktoken", fake)
    limits = LimitsSettings()
    est = estimate_dispatch(
        vault_dir=vault,
        cycle_num=1,
        stage="scout",
        prompt_text="x",
        agent="claude",
        tier="standard",
        limits=limits,
    )
    assert est.estimation_method in ("default_ceiling", "p95_history")


def test_estimate_dispatch_claude_calibration_factor_default_115(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_tiktoken(monkeypatch)
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "cost-estimates.yaml").write_text(
        "ceilings:\n  scout: 0.0\n  default: 0.0\n",
        encoding="utf-8",
    )
    prompt = "a" * 100
    limits = LimitsSettings(estimator_calibration={"claude": 1.15, "codex": 1.0})
    est = estimate_dispatch(
        vault_dir=vault,
        cycle_num=1,
        stage="scout",
        prompt_text=prompt,
        agent="claude",
        tier="standard",
        max_tokens=0,
        limits=limits,
    )
    assert est.estimation_method == "tiktoken"
    assert est.vendor == "claude"
    expected_in = int(len(prompt) * 1.15)
    assert est.cost_usd == pytest.approx(expected_in * _OUTPUT_RATE_CLAUDE, rel=1e-9)

    limits_unit = LimitsSettings(estimator_calibration={"claude": 1.0, "codex": 1.0})
    est_unit = estimate_dispatch(
        vault_dir=vault,
        cycle_num=1,
        stage="scout",
        prompt_text=prompt,
        agent="claude",
        tier="standard",
        max_tokens=0,
        limits=limits_unit,
    )
    assert est_unit.cost_usd == pytest.approx(
        len(prompt) * _OUTPUT_RATE_CLAUDE, rel=1e-9
    )
    assert est.cost_usd > est_unit.cost_usd
