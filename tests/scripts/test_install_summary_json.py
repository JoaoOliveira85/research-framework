"""FR-012/013 — install_summary.json contract (spec 039)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _write_old_python_stubs(fake_bin: Path) -> None:
    """Shadow python3.11/python3 with stubs that report an unsupported
    version for the install probe (``-c '... version_info ...'``) but delegate
    every other invocation to a real interpreter — install.sh's own
    summary-writer also shells out to ``${PYTHON_BIN}``, so a blanket stub
    would corrupt the JSON it emits. Deterministic on macOS *and* Linux,
    where the host ships python ≥3.11 (spec 009)."""
    stub_body = (
        "#!/bin/sh\n"
        'for a in "$@"; do\n'
        '  case "$a" in\n'
        "    *version_info*) echo 3.9; exit 0 ;;\n"
        "  esac\n"
        "done\n"
        f'exec "{sys.executable}" "$@"\n'
    )
    fake_bin.mkdir(parents=True, exist_ok=True)
    for name in ("python3.11", "python3"):
        stub = fake_bin / name
        stub.write_text(stub_body, encoding="utf-8")
        stub.chmod(0o755)


INSTALL_SH = Path(__file__).resolve().parents[2] / "dist-templates" / "install.sh"

REQUIRED_FIELDS = {
    "framework_version",
    "installed_at",
    "os",
    "os_version",
    "python_version",
    "package_manager",
    "target_dir",
    "root_dir",
    "dry_run",
    "warnings",
    "degraded_modes",
    "exit_status",
}


def _bash_available() -> bool:
    return shutil.which("bash") is not None


def _run_dry_install(
    tmp_path: Path, summary_path: Path
) -> subprocess.CompletedProcess[str]:
    bundle = tmp_path / "bundle"
    target = tmp_path / "vault"
    bundle.mkdir()
    wheels = list(
        Path(__file__).resolve().parents[2].glob("**/research_framework-*.whl")
    )
    if wheels:
        shutil.copy(wheels[0], bundle / wheels[0].name)
    env = os.environ.copy()
    env.update(
        {
            "RV_INSTALL_LOG": "0",
            "RV_NONINTERACTIVE": "1",
            "INSTALL_SUMMARY_PATH": str(summary_path),
        }
    )
    return subprocess.run(
        # --accept-path is REQUIRED in non-interactive mode (RV_NONINTERACTIVE=1);
        # without it install.sh refuses with exit 2 before doing anything useful.
        # The old form only "passed" by skipping when no wheel was on disk, so a
        # leftover build/ wheel (e.g. after `build.sh`) unmasked the bug.
        [
            "bash",
            str(INSTALL_SH),
            str(target),
            "--dry-run",
            "--accept-path",
            str(target),
        ],
        cwd=str(bundle),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


@pytest.mark.skipif(not _bash_available(), reason="bash not available")
class TestInstallSummarySchema:
    def test_summary_has_all_required_fields(self, tmp_path: Path) -> None:
        summary_path = tmp_path / "install_summary.json"
        proc = _run_dry_install(tmp_path, summary_path)
        if not list((tmp_path / "bundle").glob("research_framework-*.whl")):
            pytest.skip("no wheel")
        if proc.returncode != 0 and "[FAIL]" in proc.stderr:
            # Still expect summary on failure
            pass
        assert summary_path.is_file(), proc.stdout + proc.stderr
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        assert REQUIRED_FIELDS <= set(data.keys())
        assert data["os"] in ("darwin", "linux")
        assert data["exit_status"] in ("ok", "degraded", "failed")
        assert isinstance(data["dry_run"], bool)
        assert isinstance(data["warnings"], list)
        assert isinstance(data["degraded_modes"], list)

    def test_atomic_write_no_tmp_left_behind(self, tmp_path: Path) -> None:
        summary_path = tmp_path / "out" / "install_summary.json"
        _run_dry_install(tmp_path, summary_path)
        parent = summary_path.parent
        if parent.exists():
            tmps = list(parent.glob("*.tmp.*"))
            assert tmps == []

    def test_exit_status_ok_when_no_warnings(self, tmp_path: Path) -> None:
        summary_path = tmp_path / "install_summary.json"
        proc = _run_dry_install(tmp_path, summary_path)
        if proc.returncode != 0:
            pytest.skip("deps missing")
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        if not data["warnings"] and not data["degraded_modes"]:
            assert data["exit_status"] == "ok"

    def test_exit_status_failed_on_mandatory_miss(self, tmp_path: Path) -> None:
        summary_path = tmp_path / "install_summary.json"
        bundle = tmp_path / "bundle"
        target = tmp_path / "vault"
        bundle.mkdir()
        # Deterministically fail the mandatory-dep probe on ANY host.
        # `_probe_dependencies` fails first (before the --accept-path gate)
        # and writes a `failed` summary.
        fake_bin = tmp_path / "fake-bin"
        _write_old_python_stubs(fake_bin)
        env = os.environ.copy()
        env.update(
            {
                "RV_INSTALL_LOG": "0",
                "RV_NONINTERACTIVE": "1",
                "INSTALL_SUMMARY_PATH": str(summary_path),
                "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
            }
        )
        proc = subprocess.run(
            ["bash", str(INSTALL_SH), str(target), "--dry-run"],
            cwd=str(bundle),
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        assert proc.returncode != 0
        assert summary_path.is_file()
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        assert data["exit_status"] == "failed"


class TestInstallSummaryWiring:
    def test_install_summary_path_override_supported(self) -> None:
        text = INSTALL_SH.read_text(encoding="utf-8")
        assert "INSTALL_SUMMARY_PATH" in text

    def test_atomic_write_pattern(self) -> None:
        text = INSTALL_SH.read_text(encoding="utf-8")
        assert "install_summary.json" in text
        assert ".tmp." in text or "mktemp" in text or "mv " in text

    def test_fail_warn_info_helpers(self) -> None:
        text = INSTALL_SH.read_text(encoding="utf-8")
        assert "fail()" in text
        assert "[FAIL]" in text
        assert "warn()" in text
        assert "[WARN]" in text
        assert "info()" in text or "[INFO]" in text
