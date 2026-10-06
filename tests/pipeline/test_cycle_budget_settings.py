"""Tier-2 settings-layer tests for the canonical cycle budget (spec 061 FR1).

Exercises the file-level resolver entry (``resolve_cycle_budget_from_path``) so
the raw-YAML reading + the four precedence cases are pinned end-to-end from an
actual ``settings.yaml`` on disk: canonical-only, deprecated-only (migrated +
warned), both-present (canonical wins + warns), neither (built-in default).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from research_framework.cli._budget_resolve import (
    DEFAULT_MAX_CYCLES,
    resolve_cycle_budget_from_path,
)


def _write_settings(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "settings.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_canonical_only_uses_pipeline_max_cycles(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings = _write_settings(tmp_path, "pipeline:\n  max_cycles: 12\n")
    with caplog.at_level(logging.WARNING):
        res = resolve_cycle_budget_from_path(settings)
    assert res.max_cycles == 12
    assert res.max_cycles_source == "settings"
    # No deprecated keys ⇒ no deprecation WARNING.
    assert res.deprecated_keys_seen == []
    assert not [r for r in caplog.records if "deprecated" in r.getMessage().lower()]


def test_deprecated_only_migrates_with_single_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings = _write_settings(tmp_path, "cycles:\n  initial_max: 6\n")
    with caplog.at_level(logging.WARNING):
        res = resolve_cycle_budget_from_path(settings)
    assert res.max_cycles == 6
    assert res.max_cycles_source == "settings"
    assert "cycles.initial_max" in res.deprecated_keys_seen
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "pipeline.max_cycles" in warnings[0].getMessage()


def test_both_present_canonical_wins_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings = _write_settings(
        tmp_path, "pipeline:\n  max_cycles: 12\ncycles:\n  initial_max: 6\n"
    )
    with caplog.at_level(logging.WARNING):
        res = resolve_cycle_budget_from_path(settings)
    assert res.max_cycles == 12  # canonical wins; the deprecated 6 is NOT used
    assert res.max_cycles_source == "settings"
    assert "cycles.initial_max" in res.deprecated_keys_seen
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "ignored" in warnings[0].getMessage().lower()


def test_neither_key_uses_builtin_default(tmp_path: Path) -> None:
    # A settings file that carries neither the canonical nor the deprecated key.
    settings = _write_settings(tmp_path, "pipeline:\n  budget_usd: 5.0\n")
    res = resolve_cycle_budget_from_path(settings)
    assert res.max_cycles == DEFAULT_MAX_CYCLES
    assert res.max_cycles_source == "default"


# ---------------------------------------------------------------------------
# FR4 (T016): an override is a LOUD logging.WARNING, never a buried print, and
# it is suppressible by the global `--log-level error`.
# ---------------------------------------------------------------------------


def test_budget_override_emits_logging_warning_not_print(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A deprecated-key override surfaces as a captured WARNING and emits NOTHING
    to stdout — the rc1 pain was a buried/silent line, not a loud log record."""
    settings = _write_settings(tmp_path, "cycles:\n  initial_max: 6\n")
    with caplog.at_level(logging.WARNING):
        res = resolve_cycle_budget_from_path(settings)
    assert res.max_cycles == 6  # the override still applies
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "an override MUST emit a logging.WARNING"
    assert any("pipeline.max_cycles" in r.getMessage() for r in warnings)
    # MUST NOT be a bare print to stdout (FR4 buried-line fix).
    assert "max_cycles" not in capsys.readouterr().out


def test_override_warning_suppressed_at_log_level_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """`--log-level error` silences the override WARNING (emulated by raising the
    ``research_framework`` logger to ERROR) while resolution still applies."""
    settings = _write_settings(tmp_path, "cycles:\n  initial_max: 6\n")
    with caplog.at_level(logging.ERROR, logger="research_framework"):
        res = resolve_cycle_budget_from_path(settings)
    assert res.max_cycles == 6  # effective budget unchanged
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []
