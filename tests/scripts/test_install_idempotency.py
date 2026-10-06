"""FR-010/011 + SC-003 — idempotent re-run (spec 039 US4)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parents[2] / "dist-templates" / "install.sh"


def _bash_available() -> bool:
    return shutil.which("bash") is not None


@pytest.mark.skipif(not _bash_available(), reason="bash not available")
class TestIdempotentRerun:
    def test_fast_rerun_exits_zero_under_five_seconds(self, tmp_path: Path) -> None:
        target = tmp_path / "vault"
        target.mkdir()
        venv = target / ".venv"
        venv.mkdir()
        py3 = shutil.which("python3") or "/usr/bin/python3"
        home = str(Path(py3).resolve().parent)
        (venv / "pyvenv.cfg").write_text(f"home = {home}\n", encoding="utf-8")
        pipeline = target / "_pipeline"
        pipeline.mkdir()
        summary = pipeline / "install_summary.json"
        summary.write_text(
            json.dumps(
                {
                    "framework_version": "0.9.0",
                    "installed_at": "2026-06-01T00:00:00Z",
                    "os": "darwin",
                    "os_version": "",
                    "python_version": "3.11.0",
                    "package_manager": "brew",
                    "target_dir": str(target.resolve()),
                    "root_dir": str(tmp_path / "bundle"),
                    "dry_run": False,
                    "warnings": [],
                    "degraded_modes": [],
                    "exit_status": "ok",
                }
            ),
            encoding="utf-8",
        )

        bundle = tmp_path / "bundle"
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
            }
        )
        start = time.monotonic()
        proc = subprocess.run(
            [
                "bash",
                str(INSTALL_SH),
                str(target),
                "--non-interactive",
                "--accept-path",
                str(target),
            ],
            cwd=str(bundle),
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        elapsed = time.monotonic() - start
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert elapsed < 5.0, f"re-run took {elapsed:.1f}s, expected <5s"
        combined = proc.stdout + proc.stderr
        assert "already installed" in combined.lower()

    def test_failed_previous_install_does_not_take_the_fast_path(
        self, tmp_path: Path
    ) -> None:
        """A summary recording ``exit_status: failed`` is not "already installed".

        The fast path keyed only on ``.venv`` + ``install_summary.json``
        existing, and every failure exit after venv creation (version-mismatch
        sanity check, check-skills preflight) writes that summary. A plain
        re-run then printed "already installed", exited 0 and rewrote the
        record as ``ok`` without re-running the step that failed.
        """
        target = tmp_path / "vault"
        venv = target / ".venv"
        venv.mkdir(parents=True)
        py3 = shutil.which("python3") or "/usr/bin/python3"
        home = str(Path(py3).resolve().parent)
        (venv / "pyvenv.cfg").write_text(f"home = {home}\n", encoding="utf-8")
        summary = target / "_pipeline" / "install_summary.json"
        summary.parent.mkdir()
        summary.write_text(
            json.dumps(
                {"framework_version": "0.9.0", "exit_status": "failed"}, indent=2
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.update({"RV_INSTALL_LOG": "0", "RV_NONINTERACTIVE": "1"})

        proc = subprocess.run(
            [
                "bash",
                str(INSTALL_SH),
                str(target),
                "--non-interactive",
                "--dry-run",
                "--accept-path",
                str(target),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        combined = proc.stdout + proc.stderr
        assert "already installed" not in combined.lower(), combined
        assert "[dry-run] would" in combined, combined

    def test_missing_wheel_exit_is_recorded_as_failed(self, tmp_path: Path) -> None:
        """The missing-wheel exit runs after the venv exists and writes the
        summary, but never set ``INSTALL_FAILED`` — so the record said ``ok``
        (or ``degraded``), and the next plain run took the fast path: "already
        installed", exit 0, with nothing installed.

        No venv is built and no network is touched: the pre-created
        ``.venv/bin/activate`` puts a ``python`` stub first on PATH, which is
        what the installer's ``python -m pip install --upgrade pip`` then hits.
        """
        bundle = tmp_path / "bundle"  # install.sh with no wheel beside it
        target = tmp_path / "vault"
        fakebin = tmp_path / "fakebin"
        for d in (bundle, target / ".venv" / "bin", fakebin):
            d.mkdir(parents=True)
        shutil.copy2(INSTALL_SH, bundle / "install.sh")
        (target / ".venv" / "bin" / "activate").write_text(
            f'export PATH="{fakebin}:$PATH"\n', encoding="utf-8"
        )
        stub = fakebin / "python"
        stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
        env = os.environ.copy()
        env.update({"RV_INSTALL_LOG": "0", "RV_NONINTERACTIVE": "1"})
        cmd = [
            "bash",
            str(bundle / "install.sh"),
            str(target),
            "--non-interactive",
            "--accept-path",
            str(target),
        ]

        first = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        assert first.returncode == 2, first.stdout + first.stderr
        assert "no research_framework-*.whl" in first.stderr
        summary = json.loads(
            (target / "_pipeline" / "install_summary.json").read_text(encoding="utf-8")
        )
        assert summary["exit_status"] == "failed"

        second = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, env=env
        )
        combined = second.stdout + second.stderr
        assert "already installed" not in combined.lower(), combined
        assert second.returncode == 2, combined

    def test_fast_path_skips_venv_create(self) -> None:
        text = INSTALL_SH.read_text(encoding="utf-8")
        assert "already installed" in text.lower()
        assert "install_summary.json" in text


# Issue #288/#290: `TestUserAuthoredPreservation` (a permanently
# `@pytest.mark.skip`-ped class with a `pytest.fail("027-gated — should be
# skipped")` body) used to sit here, "gated on spec 027 user_authored flag".
# Spec 027 shipped months before this backlog was filed — but at a different
# surface than the one this class exercised. Its own fixture wrote
# `user_authored: true` as YAML CONTENT inside `settings.yaml` and ran it
# through `install.sh`; the real mechanism spec 027 shipped
# (`vault_update.is_user_owned`, keyed off the scaffold manifest's
# `is_user_owned_after_first_write` flag on the file's PATH, checked by
# `./vault update`/`generate --resume`'s scaffold-diff apply step) is content-
# and install.sh-independent — install.sh never writes `settings.yaml` at
# all (see `SETTINGS_FILE` above: read, never overwritten). There was never
# an installer-side scenario for this class to cover; unskipping and
# rewriting it against install.sh would still test nothing real. The actual
# behaviour is exercised end-to-end at the surface that owns it:
# `tests/cli/test_vault_update.py::test_user_owned_file_survives_upgrade`
# (a real `./vault update --force` over an edited `settings.yaml`), backed by
# the unit-level matrix in
# `tests/pipeline/test_vault_update_user_owned.py`. Removed rather than kept
# as a "should be skipped" placeholder that read as coverage in the
# installer battery without exercising anything.
