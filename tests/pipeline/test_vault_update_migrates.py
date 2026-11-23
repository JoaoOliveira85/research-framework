"""Spec 083 T011: ``./vault update`` migrates a vault through the hook old shims call."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from research_framework.pipeline import state_layout, vault_update
from tests._helpers.legacy_layout import (
    build_legacy_vault,
    git,
)

S = state_layout.STATE_DIR


def _fake_scripts(tmp_path: Path) -> Path:
    src = tmp_path / "pkg-scripts"
    src.mkdir()
    (src / "marker.py").write_text("# new\n", encoding="utf-8")
    return src


def test_an_old_shims_update_hook_migrates_the_vault(tmp_path: Path) -> None:
    vault = build_legacy_vault(tmp_path)
    # What the 2.0.1 shim does after pip upgrade: this one call, nothing else.
    changed = vault_update.sync_vault_scripts(vault, source=_fake_scripts(tmp_path))

    assert "marker.py" in changed
    assert not state_layout.is_legacy_layout(vault)
    assert (vault / S / "coverage-targets.json").is_file()
    assert git(vault, "log", "-1", "--format=%s").strip() == (
        "framework: migrate _pipeline layout"
    )
    # The upgrade commit comes after, as its own commit.
    from research_framework.pipeline import vault_commit

    (vault / "data_vault" / "x.md").write_text("x\n")
    vault_commit.commit_framework_change(vault, title="upgrade to 9.9.9")
    subjects = git(vault, "log", "-3", "--format=%s").splitlines()
    assert subjects[0] == "framework: upgrade to 9.9.9"
    assert subjects[1] == "framework: migrate _pipeline layout"


def test_a_failed_migration_fails_the_update_loudly(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    vault = build_legacy_vault(tmp_path)
    (vault / S).mkdir(parents=True)
    (vault / S / "propose-rejects.md").write_text("- different\n")
    with caplog.at_level(logging.ERROR, logger="research_framework"):
        with pytest.raises(vault_update.LayoutMigrationFailed) as exc:
            vault_update.sync_vault_scripts(vault, source=_fake_scripts(tmp_path))
    assert "propose-rejects.md" in str(exc.value)
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    # Scripts are still synced.
    assert (vault / "scripts" / "marker.py").is_file()
    # And nothing was half-moved.
    assert (vault / "_pipeline" / "coverage-targets.json").is_file()
