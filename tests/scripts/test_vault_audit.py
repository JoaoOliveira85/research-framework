"""Tests for scripts/vault_audit.py — unified vault audit script."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "vault_audit.py"
FIXTURE_VAULT = Path(__file__).parent.parent / "fixtures" / "vault"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Per-test copy of the fixture vault.

    vault_audit transitively invokes vault_health.py, which writes a
    `_pipeline/health-report.md` with a timestamp every run. Running it
    against the on-disk fixture mutates the fixture and pollutes
    ``git status`` with a regenerated timestamp on every test invocation.
    Copying the fixture into ``tmp_path`` per test isolates that write
    so the real fixture stays untouched.
    """
    dst = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, dst)
    return dst


def test_audit_exits_2_on_missing_vault(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "nonexistent")],
        capture_output=True,
    )
    assert result.returncode == 2


def test_audit_exits_0_or_1_on_fixture_vault(tmp_path, vault):
    out = tmp_path / "audit-report.md"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(vault), "--output", str(out)],
        capture_output=True,
        text=True,
    )
    assert result.returncode in (
        0,
        1,
    ), (
        f"expected 0 or 1, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_audit_writes_report_to_output_path(tmp_path, vault):
    out = tmp_path / "audit-report.md"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(vault), "--output", str(out)],
        capture_output=True,
        text=True,
    )
    assert result.returncode in (0, 1)
    assert out.exists()
    content = out.read_text()
    assert "## Summary" in content


def test_audit_output_flag_overrides_default(tmp_path, vault):
    out = tmp_path / "custom-report.md"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(vault), "--output", str(out)],
        capture_output=True,
    )
    assert result.returncode in (0, 1)
    assert out.exists()


def test_audit_no_llm_skips_llm_section(tmp_path, vault):
    out = tmp_path / "report.md"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(vault),
            "--full",
            "--no-llm",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode in (0, 1)
    assert out.exists()
    content = out.read_text()
    assert "## Summary" in content


def test_audit_report_contains_expected_sections(tmp_path, vault):
    out = tmp_path / "report.md"
    subprocess.run(
        [sys.executable, str(SCRIPT), str(vault), "--output", str(out)],
        capture_output=True,
    )
    content = out.read_text()
    for section in [
        "## Summary",
        "## Frontmatter Validation",
        "## Template Compliance",
        "## Acronym Links",
        "## Vault Health",
        "## Source Quality",
        "## Content Quality (Haiku)",
    ]:
        assert section in content, f"missing section: {section}"


def test_audit_full_with_no_llm_shows_skip(tmp_path, vault):
    out = tmp_path / "report.md"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(vault),
            "--full",
            "--no-llm",
            "--output",
            str(out),
        ],
        capture_output=True,
    )
    content = out.read_text()
    # LLM section should exist but note it was skipped
    assert "## Content Quality (Haiku)" in content
    assert "SKIP" in content


def test_audit_summary_table_present(tmp_path, vault):
    out = tmp_path / "report.md"
    subprocess.run(
        [sys.executable, str(SCRIPT), str(vault), "--output", str(out)],
        capture_output=True,
    )
    content = out.read_text()
    # Markdown table headers
    assert "| Category" in content
    assert "| Status" in content


def test_signal_killed_check_fails_the_audit(vault, monkeypatch):
    """A validator killed by a signal has a negative returncode. The report
    rendered it FAIL, but the exit gate tested ``rc > 0`` and exited 0."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("vault_audit_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_run_check", lambda name, cmd: {"rc": -9, "output": ""})

    with pytest.raises(SystemExit) as exc:
        mod.main([str(vault), "--output", str(vault / "audit.md")])

    assert exc.value.code == 1
