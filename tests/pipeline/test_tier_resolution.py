"""Stage `tier` resolution tests (spec 020 D7; one vocabulary since issue #13)."""

from __future__ import annotations

import textwrap
import warnings
from pathlib import Path

import pytest
import yaml

from research_framework.pipeline.settings import SettingsError, load_vault_settings


def _write(vault_dir: Path, body: str) -> None:
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "settings.yaml").write_text(
        textwrap.dedent(body).strip() + "\n", encoding="utf-8"
    )


def test_schema_gen_executor_resolves_tier_to_model(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        tiers:
          basic: claude-haiku-4-5
          normal: claude-sonnet-5
          flagship: claude-opus-5
        stages:
          schema_gen:
            tier: basic
        """,
    )
    settings = load_vault_settings(tmp_path)
    assert settings.resolve_model("schema_gen") == "claude-haiku-4-5"


def test_source_extraction_executor_resolves_tier(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        tiers:
          basic: gpt-mini
          normal: gpt-normal
          flagship: gpt-flagship
        stages:
          source_extraction:
            tier: normal
            enabled: true
        """,
    )
    settings = load_vault_settings(tmp_path)
    assert settings.resolve_model("source_extraction") == "gpt-normal"


def test_tier_and_model_mutually_exclusive_raises(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        tiers:
          basic: haiku
          normal: sonnet
          flagship: opus
        stages:
          schema_gen:
            tier: normal
            model: sonnet
        """,
    )
    with pytest.raises(SettingsError):
        load_vault_settings(tmp_path)


def test_unknown_tier_name_raises_at_load(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        tiers:
          basic: haiku
          normal: sonnet
          flagship: opus
        stages:
          schema_gen:
            tier: nonexistent
        """,
    )
    with pytest.raises(SettingsError) as exc:
        load_vault_settings(tmp_path)
    assert "Unknown tier" in str(exc.value)


def test_tier_resolution_per_research_section_three(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        tiers:
          basic: model-a
          normal: model-b
          flagship: model-c
        stages:
          schema_gen:
            tier: flagship
          scout:
            model: legacy-sonnet
        """,
    )
    settings = load_vault_settings(tmp_path)
    assert settings.resolve_model("schema_gen") == "model-c"
    assert settings.stage("scout").extras.get("model") == "legacy-sonnet"


# ---------------------------------------------------------------------------
# Issue #13: `tier` has one meaning on every stage — a key in `tiers:`
# ---------------------------------------------------------------------------

_HEADER = """
pipeline:
  max_cycles: 3
  budget_usd: 1.0
tiers:
  basic: model-a
  normal: model-b
  flagship: model-c
stages:
"""


def _write_stages(vault_dir: Path, stages: str) -> None:
    """Write the common header plus *stages* (indented under ``stages:``)."""
    body = textwrap.indent(textwrap.dedent(stages).strip(), "  ")
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "settings.yaml").write_text(
        _HEADER.lstrip() + body + "\n", encoding="utf-8"
    )


def test_tier_resolves_through_tiers_on_every_stage(tmp_path: Path) -> None:
    """`tier` on a non-D7 stage is a model tier, not a complexity label."""
    _write_stages(
        tmp_path,
        """
        note_writer:
          tier: flagship
        """,
    )
    settings = load_vault_settings(tmp_path)
    assert settings.stage("note_writer").tier == "flagship"
    assert settings.resolve_model("note_writer") == "model-c"


@pytest.mark.parametrize("tier", ["normal", "flagship"])
def test_tier_and_model_on_any_stage_is_refused_naming_the_stage(
    tmp_path: Path, tier: str
) -> None:
    """A value only the new vocabulary defines cannot be the old label."""
    _write_stages(
        tmp_path,
        f"""
        scout:
          tier: {tier}
          model: sonnet
        """,
    )
    with pytest.raises(SettingsError) as exc:
        load_vault_settings(tmp_path)
    assert "stages.scout" in str(exc.value)
    assert exc.value.key == "stages.scout"


def test_unknown_tier_on_any_stage_is_refused_naming_stage_and_known_tiers(
    tmp_path: Path,
) -> None:
    _write_stages(
        tmp_path,
        """
        scout:
          tier: elite
        """,
    )
    with pytest.raises(SettingsError) as exc:
        load_vault_settings(tmp_path)
    message = str(exc.value)
    assert "'scout'" in message
    assert "basic, flagship, normal" in message
    assert exc.value.key == "stages.scout.tier"


@pytest.mark.parametrize("legacy", ["standard", "expert"])
def test_legacy_complexity_tier_warns_and_is_ignored(
    tmp_path: Path, legacy: str
) -> None:
    """One-release deprecation: the old complexity value warns, selects nothing."""
    _write_stages(
        tmp_path,
        f"""
        plan_narrator:
          tier: {legacy}
        """,
    )
    with pytest.warns(FutureWarning) as record:
        settings = load_vault_settings(tmp_path)
    message = str(record[0].message)
    assert "stages.plan_narrator.tier" in message
    assert repr(legacy) in message
    assert str(tmp_path / "settings.yaml") in message
    assert settings.stage("plan_narrator").tier is None
    assert settings.resolve_model("plan_narrator") is None


@pytest.mark.parametrize("legacy", ["basic", "standard", "expert"])
def test_legacy_complexity_tier_beside_model_warns_instead_of_refusing(
    tmp_path: Path, legacy: str
) -> None:
    """`tier` beside `model` was valid on 1.0.1 and can only be the old label."""
    _write_stages(
        tmp_path,
        f"""
        verifier:
          tier: {legacy}
          model: sonnet
        """,
    )
    with pytest.warns(FutureWarning, match="stages.verifier.tier") as record:
        settings = load_vault_settings(tmp_path)
    assert str(tmp_path / "settings.yaml") in str(record[0].message)
    assert settings.stage("verifier").tier is None
    assert settings.resolve_model("verifier") == "sonnet"


def test_stage_without_tier_is_unset_and_does_not_warn(tmp_path: Path) -> None:
    _write_stages(
        tmp_path,
        """
        scout:
          model: sonnet
        """,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        settings = load_vault_settings(tmp_path)
    assert settings.stage("scout").tier is None
    assert settings.stage("plan_narrator").tier is None


def test_profile_defined_standard_tier_is_a_model_tier(tmp_path: Path) -> None:
    """A profile that names a tier `standard` gets it resolved, not warned."""
    _write(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        tiers:
          standard: model-s
        stages:
          plan_narrator:
            tier: standard
        """,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        settings = load_vault_settings(tmp_path)
    assert settings.resolve_model("plan_narrator") == "model-s"


_SHIPPED_PROFILES = sorted(Path(__file__).resolve().parents[2].glob("settings*.yaml"))


@pytest.mark.parametrize("profile", _SHIPPED_PROFILES, ids=lambda p: p.name)
def test_shipped_profile_defines_tiers_for_every_stage_tier(profile: Path) -> None:
    raw = yaml.safe_load(profile.read_text(encoding="utf-8"))
    tiers = raw.get("tiers")
    assert isinstance(tiers, dict), f"{profile.name} has no `tiers:` map"
    assert {"basic", "normal", "flagship"} <= set(tiers), profile.name
    used = {
        str(cfg["tier"])
        for cfg in (raw.get("stages") or {}).values()
        if isinstance(cfg, dict) and cfg.get("tier") is not None
    }
    undefined = used - set(tiers)
    assert not undefined, f"{profile.name} uses undefined tiers {undefined}"


@pytest.mark.parametrize("profile", _SHIPPED_PROFILES, ids=lambda p: p.name)
def test_shipped_profile_loads_without_tier_warnings(
    profile: Path, tmp_path: Path
) -> None:
    (tmp_path / "settings.yaml").write_text(
        profile.read_text(encoding="utf-8"), encoding="utf-8"
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        load_vault_settings(tmp_path)


# ---------------------------------------------------------------------------
# Review of #13: a vault with no `tiers:` block never opted in
# ---------------------------------------------------------------------------

_CODEX_NO_TIERS = """
pipeline:
  max_cycles: 3
  budget_usd: 1.0
default_executor:
  runtime: codex
  model: gpt-5.4
stages:
  plan_narrator:
    tier: {tier}
"""


@pytest.mark.parametrize("tier", ["basic", "normal", "flagship", "standard", "expert"])
def test_no_tiers_block_reads_tier_as_the_legacy_label(
    tmp_path: Path, tier: str
) -> None:
    """A 1.0.1 codex/cursor/ollama/opencode vault has no `tiers:`; its `tier:`
    was metadata, so it must not start dispatching Anthropic model ids."""
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "settings.yaml").write_text(
        _CODEX_NO_TIERS.lstrip().format(tier=tier), encoding="utf-8"
    )
    with pytest.warns(FutureWarning) as record:
        settings = load_vault_settings(tmp_path)
    message = str(record[0].message)
    assert "stages.plan_narrator.tier" in message
    assert str(tmp_path / "settings.yaml") in message
    assert "add a tiers: block to opt in" in message
    assert settings.stage("plan_narrator").tier is None
    assert settings.resolve_model("plan_narrator") is None


def test_no_tiers_block_still_refuses_a_value_in_neither_vocabulary(
    tmp_path: Path,
) -> None:
    (tmp_path / "settings.yaml").write_text(
        _CODEX_NO_TIERS.lstrip().format(tier="elite"), encoding="utf-8"
    )
    with pytest.raises(SettingsError) as exc:
        load_vault_settings(tmp_path)
    assert exc.value.key == "stages.plan_narrator.tier"


_PARTIAL_TIERS = """
pipeline:
  max_cycles: 3
  budget_usd: 1.0
default_executor:
  runtime: {runtime}
  model: some-model
tiers:
  basic: own-basic
stages:
  scout:
    tier: flagship
"""


def test_backfilled_default_tier_on_a_non_claude_runtime_warns(
    tmp_path: Path,
) -> None:
    (tmp_path / "settings.yaml").write_text(
        _PARTIAL_TIERS.lstrip().format(runtime="codex"), encoding="utf-8"
    )
    with pytest.warns(UserWarning, match="claude-opus-5") as record:
        settings = load_vault_settings(tmp_path)
    message = str(record[0].message)
    assert "stages.scout.tier" in message
    assert "'codex'" in message
    assert str(tmp_path / "settings.yaml") in message
    assert settings.resolve_model("scout") == "claude-opus-5"


def test_backfilled_default_tier_on_claude_does_not_warn(tmp_path: Path) -> None:
    (tmp_path / "settings.yaml").write_text(
        _PARTIAL_TIERS.lstrip().format(runtime="claude"), encoding="utf-8"
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        settings = load_vault_settings(tmp_path)
    assert settings.resolve_model("scout") == "claude-opus-5"


def test_stage_runtime_override_decides_the_backfill_warning(tmp_path: Path) -> None:
    body = _PARTIAL_TIERS.lstrip().format(runtime="claude") + "    runtime: cursor-agent\n"
    (tmp_path / "settings.yaml").write_text(body, encoding="utf-8")
    with pytest.warns(UserWarning, match="'cursor-agent'"):
        load_vault_settings(tmp_path)
