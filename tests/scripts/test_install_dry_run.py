"""FR-008/009 + SC-002 — dry-run mode (spec 039 US3)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _write_old_python_stubs(fake_bin: Path) -> None:
    """Shadow python3.11/python3 with stubs reporting an unsupported version
    for the install probe (``-c '... version_info ...'``), delegating all
    other calls to a real interpreter (install.sh's summary-writer also shells
    out to ``${PYTHON_BIN}``). Deterministic on macOS and Linux (spec 009)."""
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


def _bash_available() -> bool:
    return shutil.which("bash") is not None


def _run_install(
    tmp_path: Path,
    target: Path,
    *extra_args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    bundle = tmp_path / "bundle"
    bundle.mkdir(parents=True, exist_ok=True)
    wheels = list(
        Path(__file__).resolve().parents[2].glob("**/research_framework-*.whl")
    )
    if wheels:
        shutil.copy(wheels[0], bundle / wheels[0].name)
    run_env = os.environ.copy()
    run_env.update(
        {
            "RV_INSTALL_LOG": "0",
            "RV_NONINTERACTIVE": "1",
            "INSTALL_SUMMARY_PATH": str(tmp_path / "summary.json"),
        }
    )
    if env:
        run_env.update(env)
    return subprocess.run(
        # --accept-path is REQUIRED under RV_NONINTERACTIVE=1; without it
        # install.sh refuses (exit 2) before the dry-run. The old form only
        # "passed" by skipping when no wheel was on disk, so a leftover build/
        # wheel (e.g. after `build.sh`) unmasked the bug.
        [
            "bash",
            str(INSTALL_SH),
            str(target),
            "--dry-run",
            "--accept-path",
            str(target),
            *extra_args,
        ],
        cwd=str(bundle),
        capture_output=True,
        text=True,
        timeout=60,
        env=run_env,
    )


@pytest.mark.skipif(not _bash_available(), reason="bash not available")
class TestDryRunNoMutation:
    def test_zero_files_under_target_excluding_summary_redirect(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "vault"
        _run_install(tmp_path, target)
        if not list((tmp_path / "bundle").glob("research_framework-*.whl")):
            pytest.skip("no wheel for dry-run harness")
        # With INSTALL_SUMMARY_PATH redirected, target must stay empty
        if target.exists():
            files = list(target.rglob("*"))
            assert files == [] or all(p.is_dir() for p in files), (
                f"dry-run must not write vault files: {files}"
            )

    def test_emits_dry_run_would_lines(self, tmp_path: Path) -> None:
        target = tmp_path / "vault"
        proc = _run_install(tmp_path, target)
        if not list((tmp_path / "bundle").glob("research_framework-*.whl")):
            pytest.skip("no wheel for dry-run harness")
        combined = proc.stdout + proc.stderr
        assert "[dry-run] would" in combined

    def test_exit_zero_when_deps_present(self, tmp_path: Path) -> None:
        target = tmp_path / "vault"
        proc = _run_install(tmp_path, target)
        if not list((tmp_path / "bundle").glob("research_framework-*.whl")):
            pytest.skip("no wheel for dry-run harness")
        if proc.returncode != 0 and "[FAIL]" in proc.stderr:
            pytest.skip("mandatory deps missing in test env")
        assert proc.returncode == 0, proc.stderr

    def test_missing_mandatory_dep_exits_nonzero(self, tmp_path: Path) -> None:
        target = tmp_path / "vault"
        # Deterministically trip the mandatory-dep gate on ANY host. The probe
        # (`_probe_dependencies`) runs BEFORE the --accept-path gate, so this
        # is the failure exercised. Relying on the host *lacking* python only
        # "worked" on macOS (/usr/bin/python3 is 3.9); Linux ships ≥3.11.
        fake_bin = tmp_path / "fake-bin"
        _write_old_python_stubs(fake_bin)
        proc = _run_install(
            tmp_path,
            target,
            env={"PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"},
        )
        assert proc.returncode != 0
        assert "[FAIL]" in proc.stderr


@pytest.mark.skipif(not _bash_available(), reason="bash not available")
class TestDryRunDefaultSummaryPath:
    """Regression: a dry-run against a fresh target with the DEFAULT summary
    path (``<target>/_pipeline/install_summary.json``, i.e. no
    ``INSTALL_SUMMARY_PATH`` redirect) must still create the summary's parent
    dir and land the audit record. The earlier implementation ``run``-wrapped
    that ``mkdir -p`` so it was skipped in dry-run while the write stayed
    unconditional → ``No such file or directory`` and a non-zero exit."""

    def _run_default(
        self, tmp_path: Path, target: Path
    ) -> subprocess.CompletedProcess[str]:
        bundle = tmp_path / "bundle"
        bundle.mkdir(parents=True, exist_ok=True)
        wheels = list(
            Path(__file__).resolve().parents[2].glob("**/research_framework-*.whl")
        )
        if wheels:
            shutil.copy(wheels[0], bundle / wheels[0].name)
        run_env = os.environ.copy()
        run_env.update({"RV_INSTALL_LOG": "0", "RV_NONINTERACTIVE": "1"})
        run_env.pop("INSTALL_SUMMARY_PATH", None)
        return subprocess.run(
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
            env=run_env,
        )

    def test_fresh_target_dry_run_writes_summary_and_exits_zero(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "fresh-vault"
        proc = self._run_default(tmp_path, target)
        if proc.returncode != 0 and "[FAIL]" in proc.stderr:
            pytest.skip("mandatory deps missing in test env")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        summary = target / "_pipeline" / "install_summary.json"
        assert summary.is_file(), (
            "dry-run must land the audit summary at the default path: "
            + proc.stdout
            + proc.stderr
        )

    def test_fresh_target_dry_run_writes_no_other_files(self, tmp_path: Path) -> None:
        target = tmp_path / "fresh-vault"
        proc = self._run_default(tmp_path, target)
        if proc.returncode != 0 and "[FAIL]" in proc.stderr:
            pytest.skip("mandatory deps missing in test env")
        files = [p for p in target.rglob("*") if p.is_file()]
        # The summary is the install AUDIT RECORD (contract §1 dry-run note),
        # not an install mutation — it is the ONLY file dry-run may write.
        assert files == [target / "_pipeline" / "install_summary.json"], (
            f"dry-run wrote unexpected files: {files}"
        )


class TestDryRunWiring:
    def test_run_wrapper_present(self) -> None:
        text = INSTALL_SH.read_text(encoding="utf-8")
        assert "run()" in text
        assert "[dry-run] would" in text
        assert "INSTALL_DRY_RUN" in text

    def test_dry_run_flag_parsed(self) -> None:
        text = INSTALL_SH.read_text(encoding="utf-8")
        assert "--dry-run" in text
