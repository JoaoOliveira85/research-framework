"""RED tests for precondition #6 — source preflight (T068 / US5). T072 turns these green."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from research_framework.pipeline.preconditions import check

_real_subprocess_run = subprocess.run


def _write_passing_preconditions_1_to_5(vault: Path) -> None:
    """Minimal layout so checks 1–5 succeed without hitting the real repo validator."""
    pl = vault / "_pipeline"
    pl.mkdir(parents=True)
    pl.joinpath("coverage-targets.json").write_text("{}", encoding="utf-8")
    pl.joinpath("budget-log.md").write_text("# budget\n", encoding="utf-8")
    vault.joinpath("CLAUDE.md").write_text(
        "# x\nnaming convention: test\n", encoding="utf-8"
    )

    scripts = vault / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "validate_vault.py").write_text(
        "import sys\nif __name__ == '__main__': sys.exit(0)\n",
        encoding="utf-8",
    )
    tests_dir = scripts / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_trivial.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )


def _research_spec_with_unreachable_required(vault: Path) -> None:
    bad = vault / "this-repo-path-does-not-exist-for-t068"
    assert not bad.exists()
    vault.joinpath("research.spec.md").write_text(
        "\n".join(
            [
                "---",
                'name: "PreflightGate"',
                "location: ./",
                "owner: t",
                "settings: {}",
                "---",
                "",
                "## Scope",
                "domain: d",
                "organization: o",
                "",
                "## Note Types",
                "- name: concept",
                "  description: d",
                '  folder: "01 - Concepts"',
                "",
                "## Data Sources",
                "- name: main-repo",
                "  type: internal",
                "  role: behaviour",
                "  required: true",
                "  access_method: local",
                "  repos:",
                f'    - name: r\n      url: ""\n      local_path: "{bad.as_posix()}"',
                "",
                "## Search Dimensions",
                "dimensions: []",
                "",
                "## Coverage Targets",
                "categories: []",
                "",
                "## Budget",
                "max_usd: 1",
                "max_cycles: 1",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_preflight_is_sixth_precondition_failure(tmp_path: Path) -> None:
    vault = tmp_path / "v-pre"
    _write_passing_preconditions_1_to_5(vault)
    _research_spec_with_unreachable_required(vault)

    ok, unmet = check(vault)
    assert not ok
    msg_blob = " ".join(unmet).lower()
    assert "precondition 6" in msg_blob or ("6" in msg_blob and "preflight" in msg_blob)
    assert "preflight" in msg_blob


def test_existing_five_pass_preflight_only_failure(tmp_path: Path) -> None:
    vault = tmp_path / "v-split"
    _write_passing_preconditions_1_to_5(vault)
    _research_spec_with_unreachable_required(vault)

    ok, unmet = check(vault)
    assert not ok
    preflight_msgs = [m for m in unmet if "preflight" in m.lower()]
    assert len(preflight_msgs) >= 1
    assert not any("precondition 1" in m for m in unmet)
    assert not any("precondition 2" in m for m in unmet)
    assert not any("precondition 3" in m for m in unmet)
    assert not any("precondition 4" in m for m in unmet)
    assert not any("precondition 5" in m for m in unmet)


def test_generate_would_stop_on_preflight_api_contract(tmp_path: Path) -> None:
    """cli.generate should consult check() and refuse Phase 2 when preflight fails (no CLI call)."""
    vault = tmp_path / "v-api"
    _write_passing_preconditions_1_to_5(vault)
    _research_spec_with_unreachable_required(vault)

    ok, unmet = check(vault)
    assert ok is False
    assert len(unmet) >= 1
    combined = " ".join(unmet).lower()
    assert "unreachable" in combined or "preflight" in combined or "missing" in combined
    assert isinstance(ok, bool)
    assert isinstance(unmet, list)


def test_precondition_order_pytest_still_runs_for_check_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanity: first precondition still invokes pytest when scripts/tests exists."""
    vault = tmp_path / "v-p1"
    _write_passing_preconditions_1_to_5(vault)

    def fake_run(cmd, **kwargs):
        if "pytest" in cmd and "scripts/tests" in " ".join(str(c) for c in cmd):
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        return _real_subprocess_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    # Satisfy preflight: reachable local repo
    repo = vault / "ok-repo"
    repo.mkdir(parents=True)
    vault.joinpath("research.spec.md").write_text(
        "\n".join(
            [
                "---",
                'name: "Ok"',
                "location: ./",
                "owner: t",
                "settings: {}",
                "---",
                "## Scope",
                "domain: d",
                "organization: o",
                "## Note Types",
                "- name: concept",
                "  description: d",
                '  folder: "01 - Concepts"',
                "## Data Sources",
                "- name: code",
                "  type: internal",
                "  role: behaviour",
                "  required: true",
                "  access_method: local",
                "  repos:",
                f'    - name: r\n      url: ""\n      local_path: "{repo.as_posix()}"',
                "## Search Dimensions",
                "dimensions: []",
                "## Coverage Targets",
                "categories: []",
                "## Budget",
                "max_usd: 1",
                "max_cycles: 1",
            ]
        ),
        encoding="utf-8",
    )

    ok, unmet = check(vault)
    assert ok
    assert unmet == []
