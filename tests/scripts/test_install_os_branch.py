"""FR-004/006/007 — OS branch and package-manager probe (spec 039 US2)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
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


def _run_harness(
    tmp_path: Path, *, script_body: str
) -> subprocess.CompletedProcess[str]:
    harness = tmp_path / "harness.sh"
    harness.write_text(
        f"#!/usr/bin/env bash\nset -euo pipefail\n{script_body}\n",
        encoding="utf-8",
    )
    return subprocess.run(
        ["bash", str(harness)], capture_output=True, text=True, timeout=15
    )


@pytest.mark.skipif(not _bash_available(), reason="bash not available")
class TestDetectOs:
    def test_darwin_from_uname(self, tmp_path: Path) -> None:
        fn = _extract_function_block(
            INSTALL_SH.read_text(encoding="utf-8"), "_detect_os"
        )
        proc = _run_harness(
            tmp_path,
            script_body=textwrap.dedent(
                f"""\
                uname() {{ echo "Darwin"; }}
                {fn}
                echo "OS=$(_detect_os)"
                """
            ),
        )
        assert proc.returncode == 0, proc.stderr
        assert "OS=darwin" in proc.stdout

    def test_linux_from_uname(self, tmp_path: Path) -> None:
        fn = _extract_function_block(
            INSTALL_SH.read_text(encoding="utf-8"), "_detect_os"
        )
        proc = _run_harness(
            tmp_path,
            script_body=textwrap.dedent(
                f"""\
                uname() {{ echo "Linux"; }}
                {fn}
                echo "OS=$(_detect_os)"
                """
            ),
        )
        assert proc.returncode == 0, proc.stderr
        assert "OS=linux" in proc.stdout

    def test_unsupported_os_exits_3(self, tmp_path: Path) -> None:
        text = INSTALL_SH.read_text(encoding="utf-8")
        assert "exit 3" in text and "unsupported os" in text.lower()

    def test_unsupported_os_records_a_failed_summary(self, tmp_path: Path) -> None:
        """A run that exits 3 must not leave an audit record that says ``ok``:
        the summary is what a later run, and the operator, read to learn
        whether the install worked."""
        fake_bin = tmp_path / "fake-bin"
        fake_bin.mkdir()
        uname = fake_bin / "uname"
        uname.write_text("#!/bin/sh\necho FreeBSD\n", encoding="utf-8")
        uname.chmod(0o755)
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        summary_path = tmp_path / "install_summary.json"
        env = {
            **os.environ,
            "RV_INSTALL_LOG": "0",
            "RV_NONINTERACTIVE": "1",
            "INSTALL_SUMMARY_PATH": str(summary_path),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        }
        proc = subprocess.run(
            ["bash", str(INSTALL_SH), str(tmp_path / "vault"), "--dry-run"],
            cwd=str(bundle),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 3, proc.stdout + proc.stderr
        assert "unsupported OS: FreeBSD" in proc.stderr
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        assert data["exit_status"] == "failed"


@pytest.mark.skipif(not _bash_available(), reason="bash not available")
class TestPackageManagerProbe:
    def test_linux_apt_before_dnf(self, tmp_path: Path) -> None:
        fn = _extract_function_block(
            INSTALL_SH.read_text(encoding="utf-8"), "_detect_package_manager"
        )
        bindir = tmp_path / "bin"
        bindir.mkdir()
        for name in ("apt", "dnf", "pacman", "apk"):
            (bindir / name).write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
            (bindir / name).chmod(0o755)
        proc = _run_harness(
            tmp_path,
            script_body=textwrap.dedent(
                f"""\
                export PATH="{bindir}:$PATH"
                OS="linux"
                {fn}
                echo "PM=$(_detect_package_manager "$OS")"
                """
            ),
        )
        assert proc.returncode == 0, proc.stderr
        assert "PM=apt" in proc.stdout

    def test_darwin_prefers_brew(self, tmp_path: Path) -> None:
        fn = _extract_function_block(
            INSTALL_SH.read_text(encoding="utf-8"), "_detect_package_manager"
        )
        bindir = tmp_path / "bin"
        bindir.mkdir()
        (bindir / "brew").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
        (bindir / "brew").chmod(0o755)
        proc = _run_harness(
            tmp_path,
            script_body=textwrap.dedent(
                f"""\
                export PATH="{bindir}:$PATH"
                OS="darwin"
                {fn}
                echo "PM=$(_detect_package_manager "$OS")"
                """
            ),
        )
        assert proc.returncode == 0, proc.stderr
        assert "PM=brew" in proc.stdout

    def test_linux_brew_fallback_when_no_native_pm(self, tmp_path: Path) -> None:
        fn = _extract_function_block(
            INSTALL_SH.read_text(encoding="utf-8"), "_detect_package_manager"
        )
        bindir = tmp_path / "bin"
        bindir.mkdir()
        (bindir / "brew").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
        (bindir / "brew").chmod(0o755)
        # ISOLATE PATH to *only* this bindir — `_detect_package_manager` uses
        # nothing but the `command -v` builtin, so it needs no system PATH.
        # Appending `:$PATH` would leak the host's real `apt`/`dnf` on a Linux
        # CI runner and defeat the "no native PM" premise (spec 009).
        proc = _run_harness(
            tmp_path,
            script_body=textwrap.dedent(
                f"""\
                export PATH="{bindir}"
                OS="linux"
                {fn}
                echo "PM=$(_detect_package_manager "$OS")"
                """
            ),
        )
        assert proc.returncode == 0, proc.stderr
        assert "PM=brew" in proc.stdout

    def test_no_manager_returns_none_and_raw_commands(self, tmp_path: Path) -> None:
        fn = _extract_function_block(
            INSTALL_SH.read_text(encoding="utf-8"), "_detect_package_manager"
        )
        cmd_fn = _extract_function_block(
            INSTALL_SH.read_text(encoding="utf-8"), "_install_cmd_for"
        )
        # ISOLATE PATH to an empty dir so NO package manager resolves — both
        # probed functions use only shell builtins. `/usr/bin:/bin` is NOT
        # empty on Linux (it holds the real `apt`), which made this assert
        # host-dependent; an empty dir is deterministic everywhere (spec 009).
        empty_bin = tmp_path / "empty-bin"
        empty_bin.mkdir()
        proc = _run_harness(
            tmp_path,
            script_body=textwrap.dedent(
                f"""\
                export PATH="{empty_bin}"
                OS="linux"
                {fn}
                {cmd_fn}
                PM=$(_detect_package_manager "$OS")
                echo "PM=$PM"
                echo "CMD=$(_install_cmd_for git "$PM")"
                """
            ),
        )
        assert proc.returncode == 0, proc.stderr
        assert "PM=none" in proc.stdout
        assert "CMD=" in proc.stdout
        assert "install git" in proc.stdout or "git" in proc.stdout
