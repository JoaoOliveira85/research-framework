"""Tests for src/research_framework/generator/scaffold.py."""

from __future__ import annotations

import json
import os
from pathlib import Path

from research_framework.generator.scaffold import scaffold
from research_framework.spec.parser import parse


def test_scaffold_creates_folders(sample_spec_path: Path, tmp_path: Path) -> None:
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)
    for nt in spec.note_types:
        assert (vault / "data_vault" / nt.folder).is_dir()
    assert (vault / "_templates").is_dir()
    assert (vault / "_pipeline").is_dir()
    assert (vault / "_pipeline" / "cycles").is_dir()
    assert (vault / "_pipeline" / "prompts").is_dir()


def test_scaffold_spec_inside_vault_dir_is_not_clobbered(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """Regression: when the user drafts ``research.spec.md`` inside the bundle
    directory and then passes the same directory as ``--output``, the scaffold
    must not raise ``shutil.SameFileError`` trying to copy the file onto
    itself. The spec file is already in place; skip the copy silently."""
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    inplace_spec = vault / "research.spec.md"
    inplace_spec.write_text(sample_spec_path.read_text(), encoding="utf-8")

    scaffold(spec, vault, spec_source=inplace_spec)

    assert inplace_spec.exists()
    assert inplace_spec.read_text() == sample_spec_path.read_text()


def test_scaffold_settings_inside_vault_dir_is_not_clobbered(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """Same regression for ``settings.yaml`` — if the source path resolves to
    the destination, skip the copy rather than crashing."""
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    inplace_settings = vault / "settings.yaml"
    inplace_settings.write_text("schema_version: 1\n", encoding="utf-8")

    scaffold(spec, vault, settings_source=inplace_settings)

    assert inplace_settings.exists()
    assert "schema_version" in inplace_settings.read_text()


def test_scaffold_writes_cursor_cli_override(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """Every generated vault ships with a ``.cursor/cli.json`` at its root
    that blanket-allows Shell(**) inside this vault only. Each vault is its
    own git repo, so the override stays scoped to this directory.
    """
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)

    cli = vault / ".cursor" / "cli.json"
    assert cli.is_file()
    data = json.loads(cli.read_text(encoding="utf-8"))
    assert "Shell(**)" in data["permissions"]["allow"]


def test_scaffold_preserves_existing_cursor_cli_override(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """If a user has customized ``.cursor/cli.json`` in a vault, a re-run of
    scaffold must not overwrite it."""
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    (vault / ".cursor").mkdir(parents=True)
    custom = '{"permissions": {"allow": ["Shell(ls)"], "deny": []}}\n'
    (vault / ".cursor" / "cli.json").write_text(custom, encoding="utf-8")

    scaffold(spec, vault)

    assert (vault / ".cursor" / "cli.json").read_text(encoding="utf-8") == custom


def test_scaffold_creates_raw_data_mirror(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """raw_data/ must live INSIDE the vault so agents running under a
    workdir-scoped sandbox (e.g. Codex ``--sandbox workspace-write``) can
    write captures. The vault's .gitignore excludes it, so tracked history
    stays limited to data_vault/.
    """
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)

    raw = vault / "raw_data"
    assert raw.is_dir()
    assert (raw / "README.md").exists()
    assert (raw / ".gitignore").exists()
    assert not (vault.parent / "raw_data").exists(), (
        "raw_data/ must be inside the vault, not a sibling"
    )


def test_scaffold_writes_coverage_targets(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)
    targets_file = vault / "_pipeline" / "coverage-targets.json"
    assert targets_file.exists()
    data = json.loads(targets_file.read_text())
    assert len(data["categories"]) == len(spec.coverage_targets.categories)
    assert all(c["met_count"] == 0 for c in data["categories"])


def test_scaffold_writes_spec_parse_json(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)
    parse_file = vault / "_pipeline" / "spec-parse.json"
    assert parse_file.exists()
    data = json.loads(parse_file.read_text())
    assert data["name"] == spec.name


def test_scaffold_writes_budget_log(sample_spec_path: Path, tmp_path: Path) -> None:
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)
    assert (vault / "_pipeline" / "budget-log.md").exists()
    assert (vault / "_pipeline" / "research-backlog.md").exists()


def test_scaffold_writes_gitignore_tracking_only_data_vault(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)
    gi = vault / ".gitignore"
    assert gi.exists(), ".gitignore must be written at vault root"
    body = gi.read_text(encoding="utf-8")
    assert "/*" in body
    assert "!.gitignore" in body
    assert "!data_vault/" in body
    assert "!data_vault/**" in body


def test_scaffold_copies_spec_source_when_provided(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """spec_source → the vault carries its own `research.spec.md`."""
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault, spec_source=sample_spec_path)
    copied = vault / "research.spec.md"
    assert copied.exists(), "scaffold must copy the source spec into the vault"
    assert copied.read_text() == sample_spec_path.read_text()


def test_scaffold_skips_spec_copy_when_source_missing(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """Scaffold must not crash when the `spec_source` path doesn't exist."""
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault, spec_source=tmp_path / "nope.md")
    assert not (vault / "research.spec.md").exists()


def test_scaffold_copies_default_settings_yaml(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """Every fresh vault gets the generator's current settings.yaml defaults."""
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)
    settings = vault / "settings.yaml"
    assert settings.exists()
    body = settings.read_text(encoding="utf-8")
    # Sanity: the copied file contains the research_modes section added in M2.
    assert "research_modes" in body


def test_scaffold_accepts_custom_settings_source(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """Callers can override which settings.yaml ships with the vault."""
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    custom = tmp_path / "custom-settings.yaml"
    custom.write_text("# custom settings override\nmarker: unique\n")
    scaffold(spec, vault, settings_source=custom)
    body = (vault / "settings.yaml").read_text(encoding="utf-8")
    assert "marker: unique" in body


def test_scaffold_initializes_git_repo(sample_spec_path: Path, tmp_path: Path) -> None:
    """scaffold() must leave the vault as a trusted Git repo so Codex's
    workspace-write sandbox accepts it without manual `git init`."""
    import shutil

    if shutil.which("git") is None:
        import pytest

        pytest.skip("git not available in this environment")

    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)

    assert (vault / ".git").is_dir(), ".git directory missing after scaffold"


def test_claude_settings_json_created(sample_spec_path: Path, tmp_path: Path) -> None:
    """Every generated vault ships with a ``.claude/settings.json`` that
    pre-authorises normal operational tool calls for autonomous operation."""
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)

    settings = vault / ".claude" / "settings.json"
    assert settings.is_file(), ".claude/settings.json must exist after scaffold"
    body = settings.read_text(encoding="utf-8")
    assert "WebFetch(*)" in body, "WebFetch(*) must be in allow list"
    assert "git push *" in body, "git push * must appear in deny list"


def test_claude_settings_not_overwritten(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """If ``.claude/settings.json`` already exists (e.g. user customised it),
    a re-run of scaffold must not overwrite the file."""
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    (vault / ".claude").mkdir(parents=True)
    custom_content = '{"custom": "do not overwrite me"}\n'
    (vault / ".claude" / "settings.json").write_text(custom_content, encoding="utf-8")

    scaffold(spec, vault)

    assert (vault / ".claude" / "settings.json").read_text(
        encoding="utf-8"
    ) == custom_content


def test_sources_db_in_gitignore(sample_spec_path: Path, tmp_path: Path) -> None:
    """sources.db must be excluded from git so pipeline state stays out of
    version history."""
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)
    gi_body = (vault / ".gitignore").read_text(encoding="utf-8")
    assert "sources.db" in gi_body or "_pipeline/" in gi_body


def test_scaffold_git_init_is_idempotent(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """Re-scaffolding an existing vault must not blow away its .git dir."""
    import shutil

    if shutil.which("git") is None:
        import pytest

        pytest.skip("git not available in this environment")

    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)
    marker = vault / ".git" / "HEAD"
    original_mtime = marker.stat().st_mtime

    scaffold(spec, vault)

    assert marker.exists()
    assert marker.stat().st_mtime == original_mtime


def test_vault_script_created_and_executable(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)

    script = vault / "vault"
    assert script.exists(), "vault script must be created at vault root"
    assert os.access(script, os.X_OK), "vault script must be executable"
    content = script.read_text(encoding="utf-8")
    assert "research" in content, "vault script must contain 'research' command"
    assert str(vault.resolve()) in content, "vault script must embed vault_dir"


def test_vault_script_not_overwritten(sample_spec_path: Path, tmp_path: Path) -> None:
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    script = vault / "vault"
    custom_content = "#!/usr/bin/env bash\n# custom content — must not be overwritten\n"
    script.write_text(custom_content, encoding="utf-8")

    scaffold(spec, vault)

    assert script.read_text(encoding="utf-8") == custom_content, (
        "vault script must not be overwritten when it already exists"
    )


def test_systemd_service_created(sample_spec_path: Path, tmp_path: Path) -> None:
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)

    service = vault / "_pipeline" / "systemd" / "vault-research.service"
    assert service.exists(), "systemd unit must be created at _pipeline/systemd/"
    content = service.read_text(encoding="utf-8")
    assert spec.name in content, "systemd unit must reference spec.name"
    assert str(vault.resolve()) in content, "systemd unit must embed vault_dir"


def _assert_scaffold_preserves_user_owned_settings(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """FR-006: manifest user-owned settings.yaml must survive re-scaffold."""
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)
    settings = vault / "settings.yaml"
    edited = settings.read_bytes() + b"# user-owned marker\n"
    settings.write_bytes(edited)

    scaffold(spec, vault)

    assert settings.read_bytes() == edited


def test_scaffold_preserves_user_owned_settings_yaml(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    _assert_scaffold_preserves_user_owned_settings(sample_spec_path, tmp_path)


def test_scaffold_falls_back_when_manifest_snapshot_corrupt(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """Corrupt snapshot must not crash scaffold; fall back to bundled manifest."""
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)
    snapshot = vault / "_pipeline" / "scaffold-manifest-snapshot.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("{ truncated", encoding="utf-8")
    settings = vault / "settings.yaml"
    edited = settings.read_bytes() + b"# user-owned marker\n"
    settings.write_bytes(edited)

    scaffold(spec, vault)

    assert settings.read_bytes() == edited
