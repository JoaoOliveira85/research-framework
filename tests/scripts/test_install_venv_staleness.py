"""Regression tests for stale-venv detection in ``dist-templates/install.sh``
(spec 051 FR2, US4).

Background: the feeds-vault revival showed a `./vault update` against a venv whose
interpreter had been moved/deleted (`pyvenv.cfg::home =` pointing at a gone
directory) silently reused the broken venv and produced confusing import
errors. FR2 adds ``_detect_stale_venv()`` (rebuild the venv when its recorded
``home`` no longer exists or no longer matches the current interpreter) + a
``--auto-confirm`` non-interactive alias + a post-install version sanity check.

Test strategy mirrors ``test_install_sh_tty_handling.py``: the detection logic
is extracted from ``install.sh`` and exercised in isolation via a small bash
harness (no pty needed — runs in any environment), while the full-flow
behaviours (prompt plumbing, version-mismatch remediation) are asserted
structurally against the script text. The handful of cases that need a real
interactive run are pty-gated and skip where a pty is unavailable (the same
environmental limitation as the existing TTY suite).
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parents[2] / "dist-templates" / "install.sh"


def _bash_available() -> bool:
    return shutil.which("bash") is not None


def _extract_function_block(install_sh_text: str, fn_name: str) -> str:
    """Return the ``fn_name() { ... }`` definition from install.sh, by brace
    depth. Raises (via assert) when the function is absent — that's the RED
    state before FR2 adds it."""
    lines = install_sh_text.splitlines()
    out: list[str] = []
    in_fn = False
    depth = 0
    for line in lines:
        if not in_fn and line.startswith(f"{fn_name}()"):
            in_fn = True
        if in_fn:
            out.append(line)
            depth += line.count("{") - line.count("}")
            if depth == 0 and "{" in "\n".join(out):
                break
    assert out, f"{fn_name}() not found in install.sh"
    return "\n".join(out)


def _run_detection(
    tmp_path: Path, *, home_value: str | None
) -> subprocess.CompletedProcess[str]:
    """Build a bash harness that defines the extracted ``_detect_stale_venv``,
    lays down a fake ``$VENV_DIR/pyvenv.cfg`` with the given ``home =`` value
    (or no .venv at all when ``home_value is None``), and runs the detection.

    Convention under test: ``_detect_stale_venv`` exits 0 when the venv is
    STALE (rebuild needed), non-zero when it is fine / absent.
    """
    fn = _extract_function_block(
        INSTALL_SH.read_text(encoding="utf-8"), "_detect_stale_venv"
    )
    venv_dir = tmp_path / ".venv"
    if home_value is not None:
        (venv_dir / "bin").mkdir(parents=True, exist_ok=True)
        (venv_dir / "pyvenv.cfg").write_text(
            f"home = {home_value}\nversion = 3.11.0\n", encoding="utf-8"
        )
    harness = tmp_path / "harness.sh"
    harness.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -uo pipefail
            VENV_DIR="{venv_dir}"
            PYTHON_BIN="python3"
            {fn}
            if _detect_stale_venv; then echo "STALE"; else echo "FRESH"; fi
            """
        ),
        encoding="utf-8",
    )
    return subprocess.run(
        ["bash", str(harness)], capture_output=True, text=True, timeout=30
    )


# ---------------------------------------------------------------------------
# Detection behaviour (bash harness — runs in any environment)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _bash_available(), reason="bash not available")
class TestDetectStaleVenv:
    def test_home_points_at_existing_interpreter_is_fresh(self, tmp_path: Path) -> None:
        """A venv whose ``home =`` resolves on disk is NOT stale."""
        real_bindir = shutil.which("python3") or "/usr/bin"
        existing = str(Path(real_bindir).resolve().parent)
        proc = _run_detection(tmp_path, home_value=existing)
        assert proc.returncode == 0, proc.stderr
        assert "FRESH" in proc.stdout

    def test_home_points_at_deleted_dir_is_stale(self, tmp_path: Path) -> None:
        """``home =`` pointing at a directory that no longer exists ⇒ stale."""
        gone = str(tmp_path / "deleted-python" / "bin")
        proc = _run_detection(tmp_path, home_value=gone)
        assert proc.returncode == 0, proc.stderr
        assert "STALE" in proc.stdout

    def test_no_venv_is_not_stale(self, tmp_path: Path) -> None:
        """A fresh install (no ``.venv``) is not 'stale' — the normal creation
        path handles it; detection must no-op rather than false-positive."""
        proc = _run_detection(tmp_path, home_value=None)
        assert proc.returncode == 0, proc.stderr
        assert "FRESH" in proc.stdout


# ---------------------------------------------------------------------------
# Full-flow wiring (structural assertions against the script text)
# ---------------------------------------------------------------------------


class TestStaleVenvWiring:
    def _text(self) -> str:
        return INSTALL_SH.read_text(encoding="utf-8")

    def test_auto_confirm_flag_is_accepted(self) -> None:
        """``--auto-confirm`` MUST be a recognised arg that forces
        non-interactive mode (alias of the existing ``--non-interactive``)."""
        text = self._text()
        assert "--auto-confirm" in text, "install.sh must accept --auto-confirm"
        # The case arm carrying --auto-confirm (from its pattern line to the
        # next `;;`) must set NON_INTERACTIVE=1.
        idx = text.find("--auto-confirm")
        arm = text[idx : text.find(";;", idx)]
        assert "NON_INTERACTIVE=1" in arm, (
            "--auto-confirm must set NON_INTERACTIVE=1 in its case arm"
        )

    def test_detection_runs_before_venv_creation(self) -> None:
        """``_detect_stale_venv`` must be consulted before the
        ``[[ ! -d VENV_DIR ]]`` create block so a stale venv is torn down
        and rebuilt rather than reused."""
        text = self._text()
        assert "_detect_stale_venv" in text, "FR2 detection function missing"
        idx_detect = text.find("if _detect_stale_venv")
        idx_create = text.find('source "${VENV_DIR}/bin/activate"')
        assert idx_detect > 0, "detection must be invoked (if _detect_stale_venv ...)"
        assert idx_detect < idx_create, (
            "stale-venv detection must run BEFORE the venv is activated/reused"
        )

    def test_stale_rebuild_removes_and_recreates_venv(self) -> None:
        """On stale detection the script must rm -rf + recreate the venv."""
        text = self._text()
        assert 'rm -rf "${VENV_DIR}"' in text, (
            "stale rebuild must remove the broken venv"
        )

    def test_post_install_version_sanity_check_with_remediation(self) -> None:
        """After the wheel install, the script MUST verify the installed
        ``research_framework.__version__`` matches the bundle and, on
        mismatch, print the pyvenv.cfg + ``rm -rf .venv`` remediation and
        exit non-zero."""
        text = self._text()
        assert "import research_framework" in text and "__version__" in text, (
            "post-install version sanity check missing"
        )
        assert "rm -rf .venv" in text or 'rm -rf "${VENV_DIR}"' in text, (
            "version-mismatch path must point the user at rebuilding the venv"
        )
