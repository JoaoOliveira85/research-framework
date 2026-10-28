"""Unknown ``settings.yaml`` keys are reported, and refused in strict mode (#8).

``load_vault_settings`` used to copy every key it did not know into ``extras``
and say nothing, so a mistyped key looked applied while having no effect.
Default mode now warns with the key's dotted path and the closest known key;
``strict_settings: true`` turns the report into a refusal (exit 2) at the
point a research cycle would start.
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import pytest
import yaml

from research_framework.pipeline.settings import (
    SettingsError,
    UnknownSettingsKeyWarning,
    find_unknown_keys,
    load_vault_settings,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED_PROFILES: list[Path] = sorted(REPO_ROOT.glob("settings*.yaml"))
STRICT_EXIT = 2

_BASE = "pipeline:\n  max_cycles: 5\n  budget_usd: 10.0\n"


def _vault(tmp_path: Path, body: str = "") -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(_BASE + body, encoding="utf-8")
    return vault


def _unknown_warnings(vault: Path) -> list[str]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        load_vault_settings(vault)
    return [
        str(w.message)
        for w in caught
        if issubclass(w.category, UnknownSettingsKeyWarning)
    ]


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def test_top_level_typo_names_the_key_and_the_closest_known_one(tmp_path: Path):
    vault = _vault(tmp_path, "default_agnet: codex\n")
    msgs = _unknown_warnings(vault)
    assert len(msgs) == 1
    assert "default_agnet" in msgs[0]
    assert "default_agent" in msgs[0]


def test_nested_pipeline_typo_gives_the_dotted_path_and_suggestion(tmp_path: Path):
    vault = _vault(tmp_path, "  note_writer_batch_sise: 4\n")
    msgs = _unknown_warnings(vault)
    assert len(msgs) == 1
    assert "pipeline.note_writer_batch_sise" in msgs[0]
    assert "pipeline.note_writer_batch_size" in msgs[0]


def test_typo_inside_a_stage_block_is_reported(tmp_path: Path):
    vault = _vault(tmp_path, "stages:\n  verifier:\n    timeout_sec: 60\n")
    msgs = _unknown_warnings(vault)
    assert len(msgs) == 1
    assert "stages.verifier.timeout_sec" in msgs[0]
    assert "stages.verifier.timeout_s" in msgs[0]


def test_each_unknown_key_gets_its_own_message(tmp_path: Path):
    vault = _vault(tmp_path, "limits:\n  cycle_budjet_usd: 3\narchve: false\n")
    msgs = _unknown_warnings(vault)
    assert len(msgs) == 2
    assert any("limits.cycle_budjet_usd" in m for m in msgs)
    assert any("archve" in m and "archived" in m for m in msgs)


def test_a_key_with_no_close_match_is_reported_without_a_suggestion(tmp_path: Path):
    vault = _vault(tmp_path, "zzzzqqqq: 1\n")
    msgs = _unknown_warnings(vault)
    assert len(msgs) == 1
    assert "zzzzqqqq" in msgs[0]
    assert "did you mean" not in msgs[0]


def test_a_typo_is_reported_once_per_process_not_once_per_load(tmp_path: Path):
    vault = _vault(tmp_path, "default_agnet: codex\n")
    assert len(_unknown_warnings(vault)) == 1
    assert _unknown_warnings(vault) == []


def test_default_mode_still_loads_and_preserves_the_unknown_key(tmp_path: Path):
    """FR-006: a vault written for a newer framework must still load."""
    vault = _vault(tmp_path, "default_agnet: codex\n")
    with pytest.warns(UnknownSettingsKeyWarning):
        settings = load_vault_settings(vault)
    assert settings.max_cycles == 5
    assert settings.extras["default_agnet"] == "codex"


# --------------------------------------------------------------------------
# What must NOT be reported
# --------------------------------------------------------------------------

_PASS_THROUGH = """\
output_dir: ~/vaults/x
local_providers: [ollama]
default_executor:
  runtime: claude
  model: sonnet
  timeout_s: 600
  args: ["--foo"]
cycles:
  initial_max: 3
vault_commit:
  enabled: true
  push_on_complete: never
  retention:
    keep_last: 5
    max_age_days: 90
stages:
  my_custom_stage:
    model: sonnet
    timeout_s: 30
  source_manager:
    decay_after_n_cycles: 4
  topic_propose:
    enabled: true
    max_proposals: 5
tiers:
  basic: haiku
  my_own_label: opus
limits:
  tier_thresholds:
    anything_goes: 1.5
  estimator_calibration:
    some-new-runtime: 1.1
"""


def test_pass_through_and_user_keyed_entries_are_not_reported(tmp_path: Path):
    vault = _vault(tmp_path, _PASS_THROUGH)
    assert _unknown_warnings(vault) == []


def test_inert_but_shipped_keys_are_not_reported(tmp_path: Path):
    """D1 dead keys sit in every profile; reporting them would warn on all."""
    vault = _vault(
        tmp_path,
        "model_router:\n  enabled: false\n"
        "research_modes:\n  bootstrap:\n    note_action: create\n"
        "stages:\n  scout:\n    skill: scout\n",
    )
    assert _unknown_warnings(vault) == []


def test_find_unknown_keys_is_pure_and_returns_paths():
    unknown = find_unknown_keys(
        {"pipeline": {"max_cycles": 1, "max_cylces": 2}, "bugdet": {}}
    )
    assert {u.path for u in unknown} == {"pipeline.max_cylces", "bugdet"}
    by_path = {u.path: u.suggestion for u in unknown}
    assert by_path["pipeline.max_cylces"] == "pipeline.max_cycles"


def test_unknown_key_beneath_a_non_mapping_value_does_not_crash():
    assert find_unknown_keys({"limits": 3, "stages": {"x": None}}) == []


# --------------------------------------------------------------------------
# Every shipped profile is clean
# --------------------------------------------------------------------------


def test_repo_ships_the_expected_profile_set() -> None:
    """Guard the guard: an empty glob would make the test below vacuous."""
    assert len(SHIPPED_PROFILES) >= 6


@pytest.mark.parametrize("profile", SHIPPED_PROFILES, ids=lambda p: p.name)
def test_shipped_profile_has_no_unknown_keys(profile: Path):
    raw = yaml.safe_load(profile.read_text(encoding="utf-8"))
    assert [u.path for u in find_unknown_keys(raw)] == []


# --------------------------------------------------------------------------
# Strict mode
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body,expected", [("", False), ("strict_settings: true\n", True)]
)
def test_strict_settings_is_a_typed_boolean(tmp_path: Path, body: str, expected: bool):
    assert load_vault_settings(_vault(tmp_path, body)).strict_settings is expected


def test_non_boolean_strict_settings_is_rejected(tmp_path: Path):
    vault = _vault(tmp_path, "strict_settings: maybe\n")
    with pytest.raises(SettingsError):
        load_vault_settings(vault)


def _run_cycles(vault: Path, monkeypatch):
    from research_framework.cli._budget_resolve import BudgetResolution
    from research_framework.pipeline import orchestrator as orch
    from tests.pipeline.test_archived_vault import _spec

    ran: list[int] = []
    monkeypatch.setattr(
        orch, "run_single_cycle", lambda v, c, *a, **k: ran.append(c) or 2
    )
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)
    budget = BudgetResolution(
        max_cycles=5,
        max_cycles_source="settings",
        max_usd=10.0,
        max_usd_source="settings",
    )
    return orch.run_cycles(_spec(vault), vault, budget=budget), ran


def test_strict_mode_refuses_a_run_over_an_unknown_key(
    tmp_path: Path, monkeypatch, caplog: pytest.LogCaptureFixture
):
    vault = _vault(tmp_path, "strict_settings: true\ndefault_agnet: codex\n")
    with caplog.at_level(logging.ERROR):
        rc, ran = _run_cycles(vault, monkeypatch)
    assert rc == STRICT_EXIT
    assert not ran, "no cycle may start over an unknown key in strict mode"
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "default_agnet" in joined
    assert "default_agent" in joined


def test_strict_mode_refuses_before_any_side_effect(tmp_path: Path, monkeypatch):
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(tmp_path, "strict_settings: true\ndefault_agnet: codex\n")
    opened: list[str] = []
    monkeypatch.setattr(
        orch.vault_commit, "begin_run", lambda *a, **k: opened.append("branch")
    )
    _run_cycles(vault, monkeypatch)
    assert not opened


def test_strict_mode_with_a_clean_file_still_runs(tmp_path: Path, monkeypatch):
    vault = _vault(tmp_path, "strict_settings: true\n")
    _rc, ran = _run_cycles(vault, monkeypatch)
    assert ran


def test_default_mode_runs_over_an_unknown_key(tmp_path: Path, monkeypatch):
    vault = _vault(tmp_path, "default_agnet: codex\n")
    _rc, ran = _run_cycles(vault, monkeypatch)
    assert ran


def test_strict_mode_is_honoured_even_when_other_settings_are_invalid(
    tmp_path: Path, monkeypatch
):
    """Same posture as ``archived``: the flag is read raw, not via the loader."""
    vault = tmp_path / "vault"
    vault.mkdir()
    # No pipeline.max_cycles: the typed loader raises on this file.
    (vault / "settings.yaml").write_text(
        "strict_settings: true\ndefault_agnet: codex\n", encoding="utf-8"
    )
    rc, ran = _run_cycles(vault, monkeypatch)
    assert rc == STRICT_EXIT
    assert not ran
