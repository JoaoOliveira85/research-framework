"""Spec 083 T013 / US4: the state-paths guard fires on a planted literal."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GUARD = REPO / "scripts" / "guards" / "state_paths.py"


def _load():
    spec = importlib.util.spec_from_file_location("state_paths_guard", GUARD)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _fake_repo(
    tmp_path: Path, body: str, name: str = "src/research_framework/x.py"
) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    (tmp_path / "scripts").mkdir(exist_ok=True)
    return tmp_path


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD), "--root", str(root)],
        capture_output=True,
        text=True,
    )


def test_a_planted_literal_fails_and_the_tree_passes(tmp_path: Path) -> None:
    real = _run(REPO)
    assert real.returncode == 0, real.stderr
    assert "0 finding(s)" in real.stdout

    planted = _fake_repo(
        tmp_path,
        'def p(vault):\n    return vault / "_pipeline" / "propose-rejects.md"\n',
    )
    result = _run(planted)
    assert result.returncode == 1
    assert "propose-rejects.md" in result.stderr and "x.py:2" in result.stderr


def test_docstrings_and_prose_are_not_flagged(tmp_path: Path) -> None:
    guard = _load()
    names = guard.artefact_names()
    src = (
        '"""Reads coverage-targets.json."""\n'
        "def f():\n"
        '    """Writes sources.db."""\n'
        '    print("see _pipeline/sources.db for details")\n'
        "    return 1\n"
    )
    assert guard.scan_source(src, "m.py", names) == []
    assert guard.scan_source('p = "_pipeline/sources.db"\n', "m.py", names)
    assert guard.scan_source('p = f"{v}/coverage-targets.json"\n', "m.py", names)


def test_the_markdown_backlog_is_exempt_and_the_json_one_is_allowlisted(
    tmp_path: Path,
) -> None:
    guard = _load()
    names = guard.artefact_names()
    assert "research-backlog.md" not in names
    json_literal = 'p = "research-backlog.json"\n'
    assert guard.scan_source(json_literal, "elsewhere.py", names)
    allowed = guard.ALLOWED_IN_FILE["src/research_framework/pipeline/backlog.py"]
    assert (
        guard.scan_source(
            json_literal,
            "src/research_framework/pipeline/backlog.py",
            names,
            allowed=allowed,
        )
        == []
    )
    assert guard.scan_source('p = "research-backlog.md"\n', "elsewhere.py", names) == []


def test_every_registry_artefact_is_covered() -> None:
    guard = _load()
    names = guard.artefact_names()
    for expected in (
        "coverage-targets.json",
        "propose-rejects.md",
        "sources.db",
        "quarantine",
        "facts-schema.json",
        "archive-snapshots.json",
        "approval-decisions.json",
        "cycle-ledger.json",
        "research-backlog.json",
    ):
        assert expected in names


def test_the_battery_runs_the_guard() -> None:
    sys.path.insert(0, str(REPO))
    from scripts.guards import run_all

    assert "state-paths" in {g.name for g in run_all.guard_battery()}
