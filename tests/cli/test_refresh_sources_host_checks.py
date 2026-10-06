"""Host-level preflight checks for refresh-sources sweep (spec 038 FR-012)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from research_framework.cli.refresh_sources import _host_checks


def _write_code_module(
    vault: Path,
    *,
    sources: dict | None = None,
    trigger_github: bool = True,
) -> None:
    mod = vault / "modules" / "code"
    mod.mkdir(parents=True)
    triggers = (
        [{"type": "url_pattern", "pattern": "(github\\.com|gitlab\\.com)/"}]
        if trigger_github
        else [{"type": "path_pattern", "pattern": ".*"}]
    )
    (mod / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "code",
                "version": "0.1.0",
                "description": "d",
                "triggers": triggers,
                "entry_point": "extractor.py",
                "preflight": {"entry_point": "preflight.py", "timeout_seconds": 30},
                "default_value_tier": "routine",
                "schema_examples": "few-shot.md",
            }
        ),
        encoding="utf-8",
    )
    (mod / "preflight.py").write_text(
        "import json, sys\n"
        'print(json.dumps({"schema_version":"1.0","verdict":"success","corrections":[],"messages":[]}))\n',
        encoding="utf-8",
    )
    if sources is not None:
        (mod / "sources.yaml").write_text(yaml.dump(sources), encoding="utf-8")


def test_gh_auth_unauthenticated_warns(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_code_module(
        vault,
        sources={
            "github_repos": [
                {"url": "https://github.com/example/repo", "value_tier": "routine"}
            ]
        },
    )

    def fake_run(cmd, **kwargs):
        assert cmd[:2] == ["gh", "auth"]
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not logged in")

    rows = _host_checks(
        vault,
        run_command=fake_run,
        connectivity_probe=lambda: (True, ""),
    )
    gh_rows = [r for r in rows if r["check"] == "gh_auth"]
    assert len(gh_rows) == 1
    assert gh_rows[0]["status"] == "warn"
    assert "gh" in gh_rows[0]["message"].lower()


def test_connectivity_probe_warns_on_failure(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    def fail_probe():
        return False, "connection refused"

    rows = _host_checks(vault, connectivity_probe=fail_probe)
    conn = next(r for r in rows if r["check"] == "connectivity")
    assert conn["status"] == "warn"
    assert conn["status"] != "fail"
    assert "connect" in conn["message"].lower() or "refused" in conn["message"].lower()


def test_missing_local_repo_path_warns(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    missing = str(tmp_path / "missing-clone")
    _write_code_module(
        vault,
        sources={"github_repos": [{"path": missing, "value_tier": "routine"}]},
        trigger_github=False,
    )

    rows = _host_checks(
        vault,
        run_command=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("gh should not run")
        ),
        connectivity_probe=lambda: (True, ""),
    )
    repo_rows = [r for r in rows if r["check"] == "local_repo_path"]
    assert len(repo_rows) == 1
    assert repo_rows[0]["status"] == "warn"
    assert missing in repo_rows[0]["message"]
