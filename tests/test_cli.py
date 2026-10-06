"""Smoke tests for research-framework's CLI entry point.

These tests exercise the spec-loading + scaffold plumbing only. They run with
`--dry-run --skip-gate` so we stop after Phase 1 and never invoke the real
research loop (which needs agent CLIs). E2E coverage is the user's job.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.cli import main

SIMPLE_SPEC = """---
name: "Smoke Test Vault"
owner: "pytest"
topic: "Unit-testing research-framework's CLI on a simple spec"
scope:
  include: ["smoke test the CLI", "verify scaffold writes"]
growth_mode: throwaway
---

Body ignored.
"""


def _write_spec(tmp_path: Path, body: str = SIMPLE_SPEC) -> Path:
    path = tmp_path / "research.spec.md"
    path.write_text(body, encoding="utf-8")
    return path


class TestGenerateSimpleSpec:
    def test_generate_dry_run_on_simple_spec_succeeds(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        spec_path = _write_spec(tmp_path)
        vault = tmp_path / "vault"
        rc = main(
            [
                "generate",
                "--spec",
                str(spec_path),
                "--output",
                str(vault),
                "--dry-run",
                "--skip-gate",
            ]
        )
        assert rc == 0
        # Scaffold actually ran:
        assert (vault / "data_vault").is_dir()
        assert (vault / ".gitignore").is_file()
        assert (vault / "_pipeline" / "coverage-targets.json").is_file()

    def test_generate_rejects_missing_topic_with_exit_2(self, tmp_path: Path) -> None:
        body = "---\nname: n\nowner: o\n---\n"
        rc = main(
            [
                "generate",
                "--spec",
                str(_write_spec(tmp_path, body)),
                "--output",
                str(tmp_path / "vault"),
                "--dry-run",
                "--skip-gate",
            ]
        )
        assert rc == 2

    def test_generate_output_flag_overrides_location(self, tmp_path: Path) -> None:
        spec_path = _write_spec(tmp_path)
        override = tmp_path / "override"
        rc = main(
            [
                "generate",
                "--spec",
                str(spec_path),
                "--output",
                str(override),
                "--dry-run",
                "--skip-gate",
            ]
        )
        assert rc == 0
        assert (override / "data_vault").is_dir()


class TestPhase1Gate:
    """The gate only runs in development mode (repo checkout).

    When the CLI is installed from the wheel, `tests/scripts/` does not
    exist on disk and the gate must skip cleanly — not crash trying to
    invoke a pytest that isn't there.
    """

    def test_gate_skipped_when_test_directory_is_missing(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Simulate installed-package layout: point the CLI at a "repo
        # root" with no tests/scripts dir, and run generate without
        # --skip-gate. It should succeed AND announce the skip.
        from research_framework import cli as cli_mod

        fake_repo_root = tmp_path / "fake-site-packages"
        fake_repo_root.mkdir()

        # Make _run_phase1_gate resolve its repo root to our fake tree
        # by patching the __file__ attribute the function reads.
        original_file = cli_mod.__file__
        fake_pkg_dir = fake_repo_root / "research_framework"
        fake_pkg_dir.mkdir()
        monkeypatch.setattr(cli_mod, "__file__", str(fake_pkg_dir / "cli.py"))

        spec_path = _write_spec(tmp_path)
        vault = tmp_path / "vault"
        rc = cli_mod.main(
            [
                "generate",
                "--spec",
                str(spec_path),
                "--output",
                str(vault),
                "--dry-run",
            ]
        )
        # Restore to avoid leaking state across tests.
        monkeypatch.setattr(cli_mod, "__file__", original_file)

        assert rc == 0
        out = capsys.readouterr().out
        assert "[phase 1 gate] skipped" in out
        # Skipped gate must NOT also log "passed" — that would mislead
        # users into thinking a real pytest run happened.
        assert "[phase 1 gate] passed" not in out
        # Vault still got scaffolded — the skip doesn't abort generation.
        assert (vault / "data_vault").is_dir()


class TestGenerateSettingsFlag:
    """`--settings` bakes a chosen settings.yaml into the vault.

    The flag now accepts ONLY a filesystem path (no aliases). The built-in
    Codex profile ships as `settings.codex.yaml` next to the installer, and
    users who want it pass its path explicitly.
    """

    def test_default_bakes_claude_profile(self, tmp_path: Path) -> None:
        spec_path = _write_spec(tmp_path)
        vault = tmp_path / "vault"
        rc = main(
            [
                "generate",
                "--spec",
                str(spec_path),
                "--output",
                str(vault),
                "--dry-run",
                "--skip-gate",
            ]
        )
        assert rc == 0
        settings_in_vault = (vault / "settings.yaml").read_text()
        assert "runtime: claude" in settings_in_vault
        assert "runtime: codex" not in settings_in_vault

    def test_bundled_codex_profile_path_bakes_codex_profile(
        self, tmp_path: Path
    ) -> None:
        """Passing the bundled codex profile by path still works."""
        from research_framework._assets import asset_path

        codex_profile = asset_path("settings.codex.yaml")
        spec_path = _write_spec(tmp_path)
        vault = tmp_path / "vault"
        rc = main(
            [
                "generate",
                "--spec",
                str(spec_path),
                "--output",
                str(vault),
                "--settings",
                str(codex_profile),
                "--dry-run",
                "--skip-gate",
            ]
        )
        assert rc == 0
        settings_in_vault = (vault / "settings.yaml").read_text()
        assert "runtime: codex" in settings_in_vault
        assert "gpt-5" in settings_in_vault

    def test_legacy_alias_exits_2_with_upgrade_hint(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """`--settings codex` used to work; now it errors with the new filename."""
        spec_path = _write_spec(tmp_path)
        vault = tmp_path / "vault"
        rc = main(
            [
                "generate",
                "--spec",
                str(spec_path),
                "--output",
                str(vault),
                "--settings",
                "codex",
                "--dry-run",
                "--skip-gate",
            ]
        )
        assert rc == 2
        err = capsys.readouterr().err
        assert "settings.codex.yaml" in err
        assert "alias" in err.lower()

    def test_unknown_path_exits_2_with_actionable_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        spec_path = _write_spec(tmp_path)
        vault = tmp_path / "vault"
        rc = main(
            [
                "generate",
                "--spec",
                str(spec_path),
                "--output",
                str(vault),
                "--settings",
                str(tmp_path / "missing.yaml"),
                "--dry-run",
                "--skip-gate",
            ]
        )
        assert rc == 2
        err = capsys.readouterr().err
        assert "missing.yaml" in err

    def test_custom_settings_file_path_is_accepted(self, tmp_path: Path) -> None:
        spec_path = _write_spec(tmp_path)
        custom = tmp_path / "my-settings.yaml"
        custom.write_text(
            "schema_version: 1\n"
            "default_executor:\n"
            "  type: cli\n"
            "  runtime: codex\n"
            "  model: gpt-5.4\n",
            encoding="utf-8",
        )
        vault = tmp_path / "vault"
        rc = main(
            [
                "generate",
                "--spec",
                str(spec_path),
                "--output",
                str(vault),
                "--settings",
                str(custom),
                "--dry-run",
                "--skip-gate",
            ]
        )
        assert rc == 0
        assert "runtime: codex" in (vault / "settings.yaml").read_text()


class TestGenerateOutputDir:
    """`output_dir` in settings.yaml backstops the `--output` CLI flag."""

    def test_settings_output_dir_is_used_when_output_flag_absent(
        self, tmp_path: Path
    ) -> None:
        spec_path = _write_spec(tmp_path)
        want_vault = tmp_path / "from-settings-vault"
        settings = tmp_path / "my-settings.yaml"
        settings.write_text(
            "schema_version: 1\n"
            f"output_dir: {want_vault}\n"
            "default_executor:\n"
            "  type: cli\n"
            "  runtime: claude\n"
            "  model: sonnet\n",
            encoding="utf-8",
        )
        rc = main(
            [
                "generate",
                "--spec",
                str(spec_path),
                "--settings",
                str(settings),
                "--dry-run",
                "--skip-gate",
            ]
        )
        assert rc == 0
        assert (want_vault / "data_vault").is_dir()

    def test_cli_output_flag_overrides_settings_output_dir(
        self, tmp_path: Path
    ) -> None:
        spec_path = _write_spec(tmp_path)
        ignored = tmp_path / "ignored-from-settings"
        override = tmp_path / "cli-wins"
        settings = tmp_path / "my-settings.yaml"
        settings.write_text(
            "schema_version: 1\n"
            f"output_dir: {ignored}\n"
            "default_executor:\n"
            "  type: cli\n"
            "  runtime: claude\n"
            "  model: sonnet\n",
            encoding="utf-8",
        )
        rc = main(
            [
                "generate",
                "--spec",
                str(spec_path),
                "--settings",
                str(settings),
                "--output",
                str(override),
                "--dry-run",
                "--skip-gate",
            ]
        )
        assert rc == 0
        assert (override / "data_vault").is_dir()
        assert not ignored.exists(), (
            "--output must fully override settings.output_dir (including "
            "the side-effect of not creating the settings-declared dir)"
        )

    def test_relative_output_dir_resolves_against_settings_parent(
        self, tmp_path: Path
    ) -> None:
        """Relative `output_dir:` values are resolved against the settings
        file's own parent directory, so a settings.yaml committed next to a
        spec stays portable when the user cd's elsewhere before running."""
        spec_path = _write_spec(tmp_path)
        settings_dir = tmp_path / "cfg"
        settings_dir.mkdir()
        settings = settings_dir / "my-settings.yaml"
        settings.write_text(
            "schema_version: 1\n"
            "output_dir: ./sibling-vault\n"
            "default_executor:\n"
            "  type: cli\n"
            "  runtime: claude\n"
            "  model: sonnet\n",
            encoding="utf-8",
        )
        rc = main(
            [
                "generate",
                "--spec",
                str(spec_path),
                "--settings",
                str(settings),
                "--dry-run",
                "--skip-gate",
            ]
        )
        assert rc == 0
        want = (settings_dir / "sibling-vault").resolve()
        assert (want / "data_vault").is_dir()


class TestCycleCommand:
    def test_cycle_accepts_target_topics_flag(self, tmp_path: Path) -> None:
        """--target-topics is accepted by the cycle subcommand (no 'unknown flag' error)."""
        from research_framework.cli import build_parser

        parser = build_parser()
        # Parse the args — if --target-topics is unrecognised, this raises SystemExit(2).
        args = parser.parse_args(
            [
                "cycle",
                "--vault",
                str(tmp_path),
                "--cycle",
                "1",
                "--target-topics",
                "Foo",
                "Bar",
            ]
        )
        assert args.target_topics == ["Foo", "Bar"]
        assert args.cycle == 1


def test_generate_settings_opencode_yaml_resolves() -> None:
    """Spec 064: `--settings settings.opencode.yaml` resolves to the bundled
    opencode profile and declares the opencode runtime (FR-004)."""
    from research_framework._assets import asset_path, settings_profile_path

    bundled = asset_path("settings.opencode.yaml")
    resolved = settings_profile_path(str(bundled))
    assert resolved == bundled
    assert resolved.is_file()
    assert "runtime: opencode" in resolved.read_text()


def test_reindex_on_a_missing_vault_creates_nothing_and_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A mistyped ``--vault`` got a fresh ``data_vault/`` and index files, rc 0."""
    typo = tmp_path / "valut"

    rc = main(["reindex", "--vault", str(typo)])

    assert rc == 2
    assert not typo.exists()
    assert str(typo) in capsys.readouterr().err
