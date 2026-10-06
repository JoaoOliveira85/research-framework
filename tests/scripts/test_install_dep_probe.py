"""FR-005/009 — three-tier dependency probe (spec 039 US2)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parents[2] / "dist-templates" / "install.sh"


def _bash_available() -> bool:
    return shutil.which("bash") is not None


def _extract_function_block(install_sh_text: str, fn_name: str) -> str:
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


def _dep_probe_harness(tmp_path: Path, *, path_prefix: str, extra: str = "") -> str:
    probe_fn = _extract_function_block(
        INSTALL_SH.read_text(encoding="utf-8"), "_probe_dependencies"
    )
    fail_fn = _extract_function_block(INSTALL_SH.read_text(encoding="utf-8"), "fail")
    warn_fn = _extract_function_block(INSTALL_SH.read_text(encoding="utf-8"), "warn")
    info_fn = _extract_function_block(INSTALL_SH.read_text(encoding="utf-8"), "info")
    pm_fn = _extract_function_block(
        INSTALL_SH.read_text(encoding="utf-8"), "_detect_package_manager"
    )
    os_fn = _extract_function_block(
        INSTALL_SH.read_text(encoding="utf-8"), "_detect_os"
    )
    cmd_fn = _extract_function_block(
        INSTALL_SH.read_text(encoding="utf-8"), "_install_cmd_for"
    )
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -uo pipefail
        export PATH="{path_prefix}"
        INSTALL_FAILED=0
        DEGRADED_MODES=()
        INSTALL_WARNINGS=()
        PYTHON_BIN="python3"
        {pm_fn}
        {os_fn}
        {cmd_fn}
        {fail_fn}
        {warn_fn}
        {info_fn}
        {probe_fn}
        OS=$(_detect_os)
        PACKAGE_MANAGER=$(_detect_package_manager "$OS")
        {extra}
        """
    )


def _link_deps(bindir: Path, names: tuple[str, ...]) -> None:
    """Populate an isolated PATH directory with `names`, plus what the probe
    itself needs to run at all.

    The harness sets PATH to *only* this directory, which is deliberate — the
    tests below assert on which dependencies are missing. But two things in it
    are not dependencies under test, and stripping them broke the probe before
    it could reach the behaviour being asserted:

    * ``uname`` — ``_detect_os()`` shells out to it. Without it, OS detection
      returns "unsupported", ``_detect_package_manager`` finds nothing, and
      every ``_install_cmd_for`` falls back to a generic comment. The WARN and
      INFO tiers were never reached, so those tests failed with a mandatory
      python3.11 FAIL instead.
    * ``python3`` resolved via ``shutil.which`` can be a version-manager SHIM
      (pyenv, asdf, mise). A shim re-execs helpers such as ``tr`` and ``sed``
      off PATH — exactly what this harness removes — so it dies before
      reporting a version. ``sys.executable`` is a real interpreter and runs
      standalone, and being the interpreter running these tests it is by
      definition a supported version.

    Both failures were machine-dependent: they appear only where python3 is a
    shim, which is why CI stayed green while local runs failed.
    """
    bindir.mkdir(exist_ok=True)
    uname = shutil.which("uname") or "/usr/bin/uname"
    (bindir / "uname").symlink_to(uname)
    for name in names:
        if name == "python3":
            (bindir / "python3").symlink_to(sys.executable)
            continue
        src = shutil.which(name)
        if src:
            (bindir / name).symlink_to(src)


@pytest.mark.skipif(not _bash_available(), reason="bash not available")
class TestMandatoryTier:
    def test_missing_git_fails_with_install_cmd(self, tmp_path: Path) -> None:
        bindir = tmp_path / "bin"
        _link_deps(bindir, ("python3",))
        (bindir / "curl").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
        (bindir / "curl").chmod(0o755)
        script = tmp_path / "harness.sh"
        script.write_text(
            _dep_probe_harness(
                tmp_path,
                path_prefix=str(bindir),
                extra='_probe_dependencies || true\necho "FAILED=$INSTALL_FAILED"',
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            ["bash", str(script)], capture_output=True, text=True, timeout=15
        )
        assert "[FAIL]" in proc.stderr
        assert "git" in proc.stderr.lower()
        assert "install via:" in proc.stderr.lower() or "install" in proc.stderr.lower()
        assert "FAILED=1" in proc.stdout

    def test_missing_curl_fails(self, tmp_path: Path) -> None:
        bindir = tmp_path / "bin"
        _link_deps(bindir, ("python3", "git"))
        script = tmp_path / "harness.sh"
        script.write_text(
            _dep_probe_harness(
                tmp_path,
                path_prefix=str(bindir),
                extra='_probe_dependencies || true\necho "FAILED=$INSTALL_FAILED"',
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            ["bash", str(script)], capture_output=True, text=True, timeout=15
        )
        assert "[FAIL]" in proc.stderr
        assert "curl" in proc.stderr.lower()


@pytest.mark.skipif(not _bash_available(), reason="bash not available")
class TestWarnAndInfoTiers:
    def test_missing_claude_warns_and_continues(self, tmp_path: Path) -> None:
        bindir = tmp_path / "bin"
        _link_deps(bindir, ("python3", "git", "curl"))
        script = tmp_path / "harness.sh"
        script.write_text(
            _dep_probe_harness(
                tmp_path,
                path_prefix=str(bindir),
                extra=(
                    "_probe_dependencies\n"
                    'echo "FAILED=$INSTALL_FAILED"\n'
                    'echo "DEGRADED=${DEGRADED_MODES[*]}"'
                ),
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            ["bash", str(script)], capture_output=True, text=True, timeout=15
        )
        assert proc.returncode == 0, proc.stderr
        assert "[WARN]" in proc.stderr
        assert "claude" in proc.stderr.lower()
        assert "claude" in proc.stdout.lower() or "DEGRADED" in proc.stdout

    def test_missing_codex_is_info_only(self, tmp_path: Path) -> None:
        bindir = tmp_path / "bin"
        _link_deps(bindir, ("python3", "git", "curl", "rsync", "claude"))
        script = tmp_path / "harness.sh"
        script.write_text(
            _dep_probe_harness(
                tmp_path,
                path_prefix=str(bindir),
                extra='_probe_dependencies\necho "FAILED=$INSTALL_FAILED"',
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            ["bash", str(script)], capture_output=True, text=True, timeout=15
        )
        assert "[INFO]" in proc.stdout
        assert "codex" in proc.stdout.lower()
        assert "FAILED=0" in proc.stdout


@pytest.mark.skipif(not _bash_available(), reason="bash not available")
class TestPresenceCheckOnly:
    def test_poisoned_claude_on_path_is_not_invoked(self, tmp_path: Path) -> None:
        """A ``claude`` that exits 1 if executed must not break the probe."""
        bindir = tmp_path / "bin"
        _link_deps(bindir, ("python3", "git", "curl"))
        poison = bindir / "claude"
        poison.write_text("#!/bin/sh\necho POISONED >&2\nexit 1\n", encoding="utf-8")
        poison.chmod(0o755)
        script = tmp_path / "harness.sh"
        script.write_text(
            _dep_probe_harness(
                tmp_path,
                path_prefix=str(bindir),
                extra='_probe_dependencies\necho "OK"',
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            ["bash", str(script)], capture_output=True, text=True, timeout=15
        )
        assert "POISONED" not in proc.stderr + proc.stdout
        assert proc.returncode == 0
        assert "OK" in proc.stdout
