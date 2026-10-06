"""Tests for `research_framework._assets` — the runtime asset resolver.

The resolver needs to work in two modes:

1. Source tree (``<repo>/templates/``, ``<repo>/scripts/``, …) during dev.
2. Packaged wheel (``research_framework/_data/…``) after install.

We can't easily fake an install inside a unit test, so these tests verify that
(a) the dev-tree lookup finds the real assets shipped in this repo, and
(b) a missing asset raises a clear, actionable error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework import _assets


class TestAssetPath:
    def test_templates_dir_is_resolvable(self) -> None:
        path = _assets.asset_path("templates")
        assert path.exists()
        assert path.is_dir()
        assert (path / "CLAUDE.md.j2").exists(), (
            "templates dir must contain CLAUDE.md.j2"
        )

    def test_scripts_dir_is_resolvable(self) -> None:
        path = _assets.asset_path("scripts")
        assert path.exists()
        assert path.is_dir()
        assert (path / "validate_vault.py").exists()

    def test_agents_dir_is_resolvable(self) -> None:
        path = _assets.asset_path(".agents")
        assert path.exists()
        assert path.is_dir()

    def test_topic_propose_skill_is_bundled(self) -> None:
        """Phase 2 skill is part of the runtime asset bundle."""
        path = _assets.asset_path(".agents") / "skills" / "topic-propose" / "SKILL.md"
        assert path.exists(), f"topic-propose SKILL.md missing at {path}"
        text = path.read_text(encoding="utf-8")
        assert "name: topic-propose" in text
        assert "scope-bounded" in text.lower()

    def test_settings_yaml_is_resolvable(self) -> None:
        path = _assets.default_settings_path()
        assert path.exists()
        assert path.is_file()
        assert path.name == "settings.yaml"

    def test_codex_settings_profile_is_resolvable(self) -> None:
        """The codex profile ships alongside settings.yaml in the bundle."""
        path = _assets.asset_path("settings.codex.yaml")
        assert path.exists()
        assert path.is_file()
        text = path.read_text()
        # Sanity-check the payload so a blank/placeholder file can't pass.
        assert "runtime: codex" in text
        assert "gpt-5" in text

    def test_unknown_asset_raises_clear_error(self) -> None:
        with pytest.raises(FileNotFoundError) as exc:
            _assets.asset_path("does-not-exist")
        msg = str(exc.value)
        assert "does-not-exist" in msg
        assert "packaged" in msg or "source tree" in msg


class TestDualLookup:
    """The resolver tries packaged first, then falls back to source tree."""

    def test_packaged_takes_precedence_over_source_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_packaged = tmp_path / "packaged"
        fake_source = tmp_path / "source"
        fake_packaged.mkdir()
        fake_source.mkdir()
        (fake_packaged / "templates").mkdir()
        (fake_source / "templates").mkdir()
        (fake_packaged / "templates" / "marker.txt").write_text("packaged")
        (fake_source / "templates" / "marker.txt").write_text("source")

        monkeypatch.setattr(_assets, "_PACKAGED_DATA", fake_packaged)
        monkeypatch.setattr(_assets, "_SOURCE_ROOT", fake_source)

        resolved = _assets.asset_path("templates")
        assert (resolved / "marker.txt").read_text() == "packaged"

    def test_falls_back_to_source_when_packaged_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_packaged = tmp_path / "packaged"
        fake_source = tmp_path / "source"
        fake_source.mkdir()
        (fake_source / "templates").mkdir()
        (fake_source / "templates" / "marker.txt").write_text("source")

        monkeypatch.setattr(_assets, "_PACKAGED_DATA", fake_packaged)
        monkeypatch.setattr(_assets, "_SOURCE_ROOT", fake_source)

        resolved = _assets.asset_path("templates")
        assert (resolved / "marker.txt").read_text() == "source"


class TestSettingsProfilePath:
    """`--settings` accepts only filesystem paths now (no aliases)."""

    def test_custom_path_is_accepted_when_it_exists(self, tmp_path: Path) -> None:
        custom = tmp_path / "my-settings.yaml"
        custom.write_text("schema_version: 1\n")
        resolved = _assets.settings_profile_path(str(custom))
        assert resolved == custom

    def test_tilde_paths_are_expanded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        custom = tmp_path / "my-settings.yaml"
        custom.write_text("schema_version: 1\n")
        resolved = _assets.settings_profile_path("~/my-settings.yaml")
        assert resolved == Path(str(custom))

    def test_env_var_paths_are_expanded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        custom = tmp_path / "my-settings.yaml"
        custom.write_text("schema_version: 1\n")
        monkeypatch.setenv("RV_SETTINGS_DIR", str(tmp_path))
        resolved = _assets.settings_profile_path("$RV_SETTINGS_DIR/my-settings.yaml")
        assert resolved == Path(str(custom))

    def test_legacy_alias_raises_with_replacement_filename(self) -> None:
        """The `codex` alias used to work; the error now points at the file."""
        with pytest.raises(FileNotFoundError) as exc:
            _assets.settings_profile_path("codex")
        msg = str(exc.value)
        assert "settings.codex.yaml" in msg
        assert "alias" in msg.lower()

    def test_unknown_path_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "definitely-not-a-file.yaml"
        with pytest.raises(FileNotFoundError) as exc:
            _assets.settings_profile_path(str(missing))
        msg = str(exc.value)
        assert "definitely-not-a-file.yaml" in msg


# The smallest file the canonical loader accepts: with only ``schema_version``
# it raises, and the helpers below fall back to reading the named file.
_VALID_SETTINGS = "pipeline:\n  max_cycles: 3\n  budget_usd: 0\n"


class TestLoadOutputDirFromSettings:
    """`output_dir:` in settings.yaml backstops the `--output` CLI flag."""

    def test_absent_key_returns_none(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.yaml"
        settings.write_text("schema_version: 1\n")
        assert _assets.load_output_dir_from_settings(settings) is None

    def test_null_value_returns_none(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.yaml"
        settings.write_text("schema_version: 1\noutput_dir: null\n")
        assert _assets.load_output_dir_from_settings(settings) is None

    def test_empty_string_returns_none(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.yaml"
        settings.write_text('schema_version: 1\noutput_dir: ""\n')
        assert _assets.load_output_dir_from_settings(settings) is None

    def test_absolute_path_is_returned_verbatim(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.yaml"
        target = tmp_path / "my-vault"
        settings.write_text(f"schema_version: 1\noutput_dir: {target}\n")
        assert _assets.load_output_dir_from_settings(settings) == target

    def test_relative_path_resolves_against_settings_parent(
        self, tmp_path: Path
    ) -> None:
        cfg_dir = tmp_path / "cfg"
        cfg_dir.mkdir()
        settings = cfg_dir / "settings.yaml"
        settings.write_text("schema_version: 1\noutput_dir: ./the-vault\n")
        resolved = _assets.load_output_dir_from_settings(settings)
        assert resolved == (cfg_dir / "the-vault").resolve()

    def test_tilde_is_expanded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        settings = tmp_path / "settings.yaml"
        settings.write_text("schema_version: 1\noutput_dir: ~/the-vault\n")
        resolved = _assets.load_output_dir_from_settings(settings)
        assert resolved == Path(str(tmp_path / "the-vault"))

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        """A caller that asks about a file that isn't there gets None, not a
        crash — the setting is advisory, not load-bearing."""
        assert _assets.load_output_dir_from_settings(tmp_path / "nope.yaml") is None

    def test_a_profile_is_not_answered_from_the_settings_yaml_beside_it(
        self, tmp_path: Path
    ) -> None:
        """``--settings settings.codex.yaml`` reads ``settings.codex.yaml``.

        The value came from the canonical loader, which takes a directory and
        reads the ``settings.yaml`` in it: with a valid one beside the profile
        — as in the install folder, where they ship together — the vault went
        to the OTHER profile's ``output_dir``.
        """
        (tmp_path / "settings.yaml").write_text(
            _VALID_SETTINGS + f"output_dir: {tmp_path / 'claude-vault'}\n"
        )
        codex = tmp_path / "settings.codex.yaml"
        codex.write_text(_VALID_SETTINGS + f"output_dir: {tmp_path / 'codex-vault'}\n")

        assert _assets.load_output_dir_from_settings(codex) == tmp_path / "codex-vault"

    def test_a_valid_settings_yaml_is_still_read_through_the_loader(
        self, tmp_path: Path
    ) -> None:
        settings = tmp_path / "settings.yaml"
        settings.write_text(_VALID_SETTINGS + f"output_dir: {tmp_path / 'vault'}\n")

        assert _assets.load_output_dir_from_settings(settings) == tmp_path / "vault"


class TestLoadCycleLimitsFromSettings:
    """``cycles.initial_max`` / ``cycles.update_max`` let a settings file
    override the growth-mode default for ``spec.budget.max_cycles``."""

    def test_missing_file_returns_nones(self, tmp_path: Path) -> None:
        assert _assets.load_cycle_limits_from_settings(tmp_path / "nope.yaml") == (
            None,
            None,
        )

    def test_missing_cycles_block_returns_nones(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.yaml"
        settings.write_text("schema_version: 1\n")
        assert _assets.load_cycle_limits_from_settings(settings) == (None, None)

    def test_reads_both_limits(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.yaml"
        settings.write_text(
            "schema_version: 1\ncycles:\n  initial_max: 6\n  update_max: 3\n"
        )
        assert _assets.load_cycle_limits_from_settings(settings) == (6, 3)

    def test_rejects_non_positive(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.yaml"
        settings.write_text(
            "schema_version: 1\ncycles:\n  initial_max: 0\n  update_max: -2\n"
        )
        assert _assets.load_cycle_limits_from_settings(settings) == (None, None)

    def test_rejects_non_int(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.yaml"
        settings.write_text(
            'schema_version: 1\ncycles:\n  initial_max: "six"\n  update_max: true\n'
        )
        assert _assets.load_cycle_limits_from_settings(settings) == (None, None)

    def test_a_profile_is_not_answered_from_the_settings_yaml_beside_it(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "settings.yaml").write_text(
            _VALID_SETTINGS + "cycles:\n  initial_max: 7\n"
        )
        codex = tmp_path / "settings.codex.yaml"
        codex.write_text(_VALID_SETTINGS + "cycles:\n  initial_max: 2\n")

        assert _assets.load_cycle_limits_from_settings(codex) == (2, None)


def test_settings_opencode_yaml_bundled_in_wheel_data() -> None:
    """Spec 064 (FR-004): the opencode profile ships alongside the others."""
    path = _assets.asset_path("settings.opencode.yaml")
    assert path.exists()
    assert path.is_file()
    text = path.read_text()
    # Sanity-check the payload so a blank/placeholder file can't pass.
    assert "runtime: opencode" in text
    assert "ollama/" in text


def test_settings_cursor_claude_yaml_bundled_in_wheel_data() -> None:
    """The cursor+claude profile ships alongside settings.yaml / .codex / .opencode.

    Authored for the v1.0.0 reference-vault validation run: cursor-agent's
    flat-rate billing + `--workspace` containment paired with Claude
    models end-to-end. Mirrors the bundling test for the opencode
    profile so a missing force-include or build.sh copy can't silently
    drop the file out of the wheel.
    """
    path = _assets.asset_path("settings.cursor-claude.yaml")
    assert path.exists()
    assert path.is_file()
    text = path.read_text()
    assert "runtime: cursor-agent" in text
    assert "claude-4.6-sonnet-medium-thinking" in text
