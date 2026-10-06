"""After an upgrade, vault-local `scripts/` must match the installed package.

`_resolve_script` prefers the VAULT copy and only falls back to the packaged
one when the vault file is *missing*. So a stale vault script silently shadows
the fixed packaged copy — a fix shipped in the wheel simply does not run.

That is exactly what happened here: all five live vaults had the branch build in
their venv while `scripts/validate_cycle.py` was still the released rc11,
so spec 070's F4 fix was installed but never executed.

The update verb cannot rely on `install.sh` for this. That installer needs a
built wheel beside it (release-tarball layout); a `RV_GITHUB_REF` git archive
has no wheel, so it exits before syncing anything. Syncing from the
just-installed package's `_data/scripts` is both simpler and strictly more
correct: it is the code that will actually run.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.pipeline.vault_update import sync_vault_scripts


def _vault(tmp: Path) -> Path:
    v = tmp / "vault"
    (v / "scripts").mkdir(parents=True)
    return v


def _pkg(tmp: Path, files: dict[str, str]) -> Path:
    d = tmp / "pkg_scripts"
    d.mkdir()
    for name, body in files.items():
        (d / name).write_text(body, encoding="utf-8")
    return d


def test_stale_script_is_refreshed(tmp_path: Path) -> None:
    """The regression: a tampered/stale vault copy must be overwritten."""
    v = _vault(tmp_path)
    (v / "scripts" / "validate_cycle.py").write_text("OLD\n", encoding="utf-8")
    src = _pkg(tmp_path, {"validate_cycle.py": "NEW\n"})

    changed = sync_vault_scripts(v, source=src)

    assert (v / "scripts" / "validate_cycle.py").read_text() == "NEW\n"
    assert changed == ["validate_cycle.py"]


def test_identical_script_is_not_rewritten(tmp_path: Path) -> None:
    """Report only real changes, so the operator sees signal not noise."""
    v = _vault(tmp_path)
    (v / "scripts" / "a.py").write_text("SAME\n", encoding="utf-8")
    src = _pkg(tmp_path, {"a.py": "SAME\n"})

    assert sync_vault_scripts(v, source=src) == []


def test_missing_script_is_restored(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    src = _pkg(tmp_path, {"new_helper.py": "BODY\n"})

    assert sync_vault_scripts(v, source=src) == ["new_helper.py"]
    assert (v / "scripts" / "new_helper.py").read_text() == "BODY\n"


def test_vault_only_extras_are_left_alone(tmp_path: Path) -> None:
    """Operator-added scripts are not the framework's to delete."""
    v = _vault(tmp_path)
    (v / "scripts" / "my_collector.py").write_text("MINE\n", encoding="utf-8")
    src = _pkg(tmp_path, {"a.py": "A\n"})

    sync_vault_scripts(v, source=src)

    assert (v / "scripts" / "my_collector.py").read_text() == "MINE\n"


def test_executable_bit_is_preserved(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    src = _pkg(tmp_path, {"run.py": "#!/usr/bin/env python\n"})
    (src / "run.py").chmod(0o755)

    sync_vault_scripts(v, source=src)

    assert (v / "scripts" / "run.py").stat().st_mode & 0o111


def test_missing_scripts_dir_is_created(tmp_path: Path) -> None:
    v = tmp_path / "vault"
    v.mkdir()
    src = _pkg(tmp_path, {"a.py": "A\n"})

    assert sync_vault_scripts(v, source=src) == ["a.py"]
    assert (v / "scripts" / "a.py").is_file()


def test_missing_source_is_a_noop(tmp_path: Path) -> None:
    """Never fail an upgrade over a regenerable artifact."""
    v = _vault(tmp_path)
    assert sync_vault_scripts(v, source=tmp_path / "nope") == []


def test_env_opt_out_leaves_scripts_alone(tmp_path: Path, monkeypatch) -> None:
    """RV_SKIP_SCRIPT_SYNC is the documented escape hatch for a customised vault."""
    monkeypatch.setenv("RV_SKIP_SCRIPT_SYNC", "1")
    v = _vault(tmp_path)
    (v / "scripts" / "a.py").write_text("MINE\n", encoding="utf-8")
    src = _pkg(tmp_path, {"a.py": "PACKAGED\n"})

    assert sync_vault_scripts(v, source=src) == []
    assert (v / "scripts" / "a.py").read_text() == "MINE\n"


def test_opt_out_is_off_by_default(tmp_path: Path, monkeypatch) -> None:
    """Staleness is the dangerous default, so the sync must be opt-OUT."""
    monkeypatch.delenv("RV_SKIP_SCRIPT_SYNC", raising=False)
    v = _vault(tmp_path)
    (v / "scripts" / "a.py").write_text("OLD\n", encoding="utf-8")
    src = _pkg(tmp_path, {"a.py": "NEW\n"})

    assert sync_vault_scripts(v, source=src) == ["a.py"]
