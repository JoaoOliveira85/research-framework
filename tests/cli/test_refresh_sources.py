from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests/fixtures/refresh_sources_vault"


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


def _copy_fixture(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    shutil.copytree(FIXTURE, vault)
    return vault


def _cli(*args: str, vault: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            str(vault / ".venv/bin/python"),
            "-m",
            "research_framework.cli",
            "refresh-sources",
            "--vault",
            str(vault),
            *args,
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )


def test_refresh_sources_exit_0_stub_collector_json(tmp_path: Path) -> None:
    vault = _copy_fixture(tmp_path)
    _venv(vault)
    proc = _cli("--json", vault=vault)
    assert proc.returncode == 0
    doc = json.loads(proc.stdout)
    assert doc["partial_failure"] is False
    assert doc["collectors"][0]["status"] == "ok"


def test_refresh_sources_exit_1_partial_failure_json(tmp_path: Path) -> None:
    vault = _copy_fixture(tmp_path)
    _venv(vault)
    (vault / "scripts/collect_fail.py").write_text(
        "import sys\nsys.exit(1)\n", encoding="utf-8"
    )
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 1\n  budget_usd: 1.0\nrefresh_sources:\n  collectors: [collect_stub.py, collect_fail.py]\n",
        encoding="utf-8",
    )
    proc = _cli("--json", vault=vault)
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["partial_failure"] is True


def test_refresh_sources_exit_2_missing_venv(tmp_path: Path) -> None:
    import argparse

    from research_framework.cli.refresh_sources import cmd_refresh_sources

    vault = _copy_fixture(tmp_path)
    args = argparse.Namespace(
        vault=vault,
        json=True,
        dry_run=False,
        only=None,
        verbose=False,
    )
    assert cmd_refresh_sources(args) == 2


def test_refresh_sources_exit_2_unknown_only_basename(tmp_path: Path) -> None:
    vault = _copy_fixture(tmp_path)
    _venv(vault)
    assert _cli("--only", "not_a_collector.py", "--json", vault=vault).returncode == 2


def test_refresh_sources_discovery_includes_reddit_rss_allowlist(
    tmp_path: Path,
) -> None:
    vault = _copy_fixture(tmp_path)
    _venv(vault)
    for p in vault.glob("scripts/collect_*.py"):
        p.unlink()
    (vault / "scripts/reddit_rss.py").write_text("# rss\n", encoding="utf-8")
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 1\n  budget_usd: 1.0\n", encoding="utf-8"
    )
    proc = _cli("--dry-run", "--json", vault=vault)
    names = [c["script"] for c in json.loads(proc.stdout)["collectors"]]
    assert "reddit_rss.py" in names


def test_refresh_sources_discovery_lexicographic_with_allowlist(
    tmp_path: Path,
) -> None:
    vault = _copy_fixture(tmp_path)
    _venv(vault)
    for p in vault.glob("scripts/collect_*.py"):
        p.unlink()
    (vault / "scripts/collect_youtube.py").write_text("# yt\n", encoding="utf-8")
    (vault / "scripts/reddit_rss.py").write_text("# rss\n", encoding="utf-8")
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 1\n  budget_usd: 1.0\n", encoding="utf-8"
    )
    names = [
        c["script"]
        for c in json.loads(_cli("--dry-run", "--json", vault=vault).stdout)[
            "collectors"
        ]
    ]
    assert names == sorted(["collect_youtube.py", "reddit_rss.py"])


def test_refresh_sources_never_traverses_modules_directory(tmp_path: Path) -> None:
    vault = _copy_fixture(tmp_path)
    _venv(vault)
    decoy = vault / "modules/decoy/collect_fake.py"
    decoy.parent.mkdir(parents=True)
    decoy.write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    names = [
        c["script"]
        for c in json.loads(_cli("--dry-run", "--json", vault=vault).stdout)[
            "collectors"
        ]
    ]
    assert "collect_fake.py" not in names


def test_refresh_sources_invokes_python_not_executable_bit(tmp_path: Path) -> None:
    vault = _copy_fixture(tmp_path)
    _venv(vault)
    stub = vault / "scripts/collect_stub.py"
    stub.chmod(stub.stat().st_mode & ~stat.S_IXUSR & ~stat.S_IXGRP & ~stat.S_IXOTH)
    assert _cli("--json", vault=vault).returncode == 0


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_refresh_sources_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--dry-run`` lists collectors; it ran each module's preflight and wrote
    ``_pipeline/preflight.json`` (spec 023 contract: "do not execute")."""
    import argparse

    import yaml

    from research_framework.cli import refresh_sources

    monkeypatch.setattr(refresh_sources, "_host_checks", lambda _vault: [])
    vault = _copy_fixture(tmp_path)
    (vault / ".venv/bin").mkdir(parents=True)
    (vault / ".venv/bin/python").write_text("", encoding="utf-8")
    mod = vault / "modules" / "rss"
    mod.mkdir(parents=True)
    (mod / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "rss",
                "version": "0.1.0",
                "description": "d",
                "triggers": [{"type": "url_pattern", "pattern": "rss"}],
                "entry_point": "extractor.py",
                "preflight": {"entry_point": "preflight.py", "timeout_seconds": 30},
                "default_value_tier": "routine",
                "schema_examples": "few-shot.md",
            }
        ),
        encoding="utf-8",
    )
    (mod / "preflight.py").write_text(
        "import json\n"
        'print(json.dumps({"schema_version": "1.0", "verdict": "success",'
        ' "corrections": [], "messages": []}))\n',
        encoding="utf-8",
    )
    before = _tree(vault)

    rc = refresh_sources.cmd_refresh_sources(
        argparse.Namespace(
            vault=vault, json=True, dry_run=True, only=None, verbose=False
        )
    )

    assert rc == 0
    assert not (vault / "_pipeline" / "preflight.json").exists()
    assert _tree(vault) == before


def test_refresh_sources_exit_2_when_every_collector_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Nothing ran, so it is not success (spec 077: 2 for "no collectors")."""
    import argparse

    from research_framework.cli import refresh_sources

    monkeypatch.setattr(refresh_sources, "_host_checks", lambda _vault: [])
    vault = _copy_fixture(tmp_path)
    (vault / ".venv/bin").mkdir(parents=True)
    (vault / ".venv/bin/python").write_text("", encoding="utf-8")
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 1\n  budget_usd: 1.0\nrefresh_sources:\n"
        "  collectors: [collect_gone.py, collect_typo.py]\n",
        encoding="utf-8",
    )

    rc = refresh_sources.cmd_refresh_sources(
        argparse.Namespace(
            vault=vault, json=True, dry_run=False, only=None, verbose=False
        )
    )

    assert rc == 2
    assert "collect_gone.py" in capsys.readouterr().err
