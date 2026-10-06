"""Spec 052 — cursor-agent estimator calibration + tiktoken branch.

Cursor is flat-rate (emits real tokens, no dollar at dispatch time), but the
spec-033 estimator still needs to produce a pre-dispatch dollar + token estimate
so the dollar cap and the metered-token cap both have a number to gate on.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from research_framework.pipeline.cost_estimator import (
    DEFAULT_ESTIMATOR_CALIBRATION,
    estimate_dispatch,
)
from research_framework.pipeline.settings import LimitsSettings


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


def test_cursor_calibration_default_present() -> None:
    assert DEFAULT_ESTIMATOR_CALIBRATION["cursor-agent"] == 1.0


def test_cursor_tiktoken_branch_returns_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_tiktoken(monkeypatch)
    vault = tmp_path / "vault"
    vault.mkdir()
    est = estimate_dispatch(
        vault_dir=vault,
        cycle_num=2,
        stage="note_writer",
        prompt_text="a representative prompt with some length to encode",
        agent="cursor-agent",
        tier="normal",
        limits=LimitsSettings(),
    )
    assert est.cost_usd > 0.0
    assert est.codex_tokens > 0  # estimated metered tokens feed the token cap
    assert est.vendor == "cursor-agent"


def test_cursor_metered_tokens_without_tiktoken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression (Copilot, PR #131): when the optional ``tiktoken`` extra is
    absent, the non-tiktoken fallback must STILL project a non-zero token
    estimate for cursor — otherwise the metered-token cap is a silent no-op for
    the flat-rate runtime. codex stays projected; claude stays 0 (not metered).
    """
    # Force the tiktoken import to fail (None in sys.modules ⇒ ImportError).
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    vault = tmp_path / "vault"
    vault.mkdir()

    def _estimate(agent: str):
        return estimate_dispatch(
            vault_dir=vault,
            cycle_num=1,  # cold start ⇒ default_ceiling path
            stage="note_writer",
            prompt_text="x" * 200,
            agent=agent,
            tier="normal",
            max_tokens=4096,
            limits=LimitsSettings(),
        )

    cursor = _estimate("cursor-agent")
    codex = _estimate("codex")
    claude = _estimate("claude")

    assert cursor.estimation_method == "default_ceiling"
    assert cursor.codex_tokens == 4096  # the cap now has a number for cursor
    assert codex.codex_tokens == 4096  # codex behaviour unchanged
    assert claude.codex_tokens == 0  # claude is not a metered-token runtime


def test_cursor_calibration_override_honoured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_tiktoken(monkeypatch)
    vault = tmp_path / "vault"
    vault.mkdir()
    base = estimate_dispatch(
        vault_dir=vault,
        cycle_num=2,
        stage="note_writer",
        prompt_text="x" * 500,
        agent="cursor-agent",
        tier="normal",
        limits=LimitsSettings(estimator_calibration={"cursor-agent": 1.0}),
    )
    scaled = estimate_dispatch(
        vault_dir=vault,
        cycle_num=2,
        stage="note_writer",
        prompt_text="x" * 500,
        agent="cursor-agent",
        tier="normal",
        limits=LimitsSettings(estimator_calibration={"cursor-agent": 4.0}),
    )
    # A larger calibration factor must not reduce the estimate (monotonic).
    assert scaled.cost_usd >= base.cost_usd
