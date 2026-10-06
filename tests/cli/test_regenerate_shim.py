from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests._helpers.vault_factory import build_minimal_vault

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests/fixtures/broken_shim_vault"


def _venv(vault: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "venv", str(vault / ".venv")],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [str(vault / ".venv/bin/pip"), "install", "-q", "-e", str(REPO)],
        check=True,
        capture_output=True,
    )


def _cli(*args: str, vault: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            str(vault / ".venv/bin/python"),
            "-m",
            "research_framework.cli",
            "regenerate-shim",
            "--vault",
            str(vault),
            *args,
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )


def test_regenerate_shim_double_run_byte_identical(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    _venv(vault)
    assert _cli("--force", vault=vault).returncode == 0
    first = (vault / "vault").read_bytes()
    assert _cli("--force", vault=vault).returncode == 0
    assert (vault / "vault").read_bytes() == first


def test_regenerate_shim_exit_2_unverified_without_force(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    _venv(vault)
    shim = vault / "vault"
    shim.write_text(shim.read_text() + "\n", encoding="utf-8")
    assert _cli(vault=vault).returncode == 2


def test_regenerate_shim_exit_2_customized_without_force(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    _venv(vault)
    (vault / "vault").write_text("#!/bin/bash\n# customized\n", encoding="utf-8")
    proc = _cli(vault=vault)
    assert proc.returncode == 2
    assert "--force" in proc.stderr


def test_regenerate_shim_repairs_broken_shim_fixture(tmp_path: Path) -> None:
    import shutil

    vault = tmp_path / "v"
    shutil.copytree(FIXTURE, vault)
    _venv(vault)
    assert _cli("--force", vault=vault).returncode == 0
    assert "research_framework.cli" in (vault / "vault").read_text()


def test_regenerate_shim_preserves_user_scripts_bytes(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    _venv(vault)
    custom = vault / "scripts/custom_collector.py"
    payload = b"# keep\n"
    custom.write_bytes(payload)
    assert _cli("--force", vault=vault).returncode == 0
    assert custom.read_bytes() == payload


def test_regenerate_shim_writes_shim_via_atomic_write_mode_755(tmp_path: Path) -> None:
    from unittest.mock import patch

    vault = build_minimal_vault(tmp_path)
    with patch("research_framework.cli.regenerate_shim.write_text") as aw:
        import argparse

        from research_framework.cli.regenerate_shim import cmd_regenerate_shim

        args = argparse.Namespace(vault=vault, json=False, dry_run=False, force=True)
        assert cmd_regenerate_shim(args) == 0
        aw.assert_called()
        mode = aw.call_args.kwargs.get("mode")
        if mode is None and len(aw.call_args[0]) > 2:
            mode = aw.call_args[1].get("mode")
        assert mode == 0o755


def test_regenerate_shim_writes_shim_fingerprint_json(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    import argparse

    from research_framework.cli.regenerate_shim import cmd_regenerate_shim

    args = argparse.Namespace(vault=vault, json=False, dry_run=False, force=True)
    assert cmd_regenerate_shim(args) == 0
    fp = vault / "_pipeline/shim-fingerprint.json"
    doc = json.loads(fp.read_text())
    assert {"path", "sha256", "framework_version", "rendered_at"}.issubset(doc)


def test_regenerate_shim_preserves_user_owned_settings_yaml(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    _venv(vault)
    settings = vault / "settings.yaml"
    edited = settings.read_bytes() + b"# user-owned marker\n"
    settings.write_bytes(edited)
    assert _cli("--force", vault=vault).returncode == 0
    assert settings.read_bytes() == edited


def _mark_vault_shim_user_owned_in_snapshot(vault: Path, *, user_owned: bool) -> None:
    from research_framework.generator.scaffold import write_scaffold_manifest_snapshot

    write_scaffold_manifest_snapshot(vault)
    snap_path = vault / "_pipeline" / "scaffold-manifest-snapshot.json"
    doc = json.loads(snap_path.read_text(encoding="utf-8"))
    for entry in doc["entries"]:
        if entry["path"] == "vault":
            entry["is_user_owned_after_first_write"] = user_owned
    snap_path.write_text(json.dumps(doc), encoding="utf-8")


def test_regenerate_shim_preserves_user_owned_vault_shim(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    _venv(vault)
    _mark_vault_shim_user_owned_in_snapshot(vault, user_owned=True)
    shim = vault / "vault"
    original = shim.read_bytes() + b"# user shim marker\n"
    shim.write_bytes(original)
    proc = _cli("--force", vault=vault)
    assert proc.returncode == 0
    assert "preserving user-owned vault" in proc.stderr
    assert shim.read_bytes() == original


def test_regenerate_shim_regenerates_when_vault_not_user_owned(
    tmp_path: Path,
) -> None:
    vault = build_minimal_vault(tmp_path)
    _venv(vault)
    shim = vault / "vault"
    shim.write_text(shim.read_text() + "\n# broken\n", encoding="utf-8")
    assert _cli(vault=vault).returncode == 2
    proc = _cli("--force", vault=vault)
    assert proc.returncode == 0
    assert "preserving user-owned vault" not in proc.stderr
    assert "research_framework.cli" in shim.read_text()
