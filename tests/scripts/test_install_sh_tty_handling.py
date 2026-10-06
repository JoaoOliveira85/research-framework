"""Regression test for the v0.2.24 fix to ``dist-templates/install.sh``.

Background: v0.2.23 added an ``exec > >(tee -a install.log) 2>&1`` redirect
near the top of the install script so every line of output is mirrored to
``install.log`` for post-mortem use. The redirect makes ``-t 1`` return
false even when the user is sitting at a real terminal, so the
``is_interactive()`` check below the redirect short-circuited every install
to non-interactive mode and the wizard never offered to run ``generate.sh``.

The v0.2.24 fix captures ``-t 0`` / ``-t 1`` / ``-t 2`` into
``RV_STDIN_IS_TTY`` / ``RV_STDOUT_IS_TTY`` / ``RV_STDERR_IS_TTY`` BEFORE
the redirect, then ``is_interactive()`` consults those cached values
instead of the live FD state. This test exercises both code paths against
the bundled ``install.sh`` directly so any future redirect that re-breaks
TTY detection fails the test before it can ship.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parents[2] / "dist-templates" / "install.sh"


def _extract_tty_capture_block(install_sh_text: str) -> str:
    """Return the install.sh block that captures TTY state — the exact
    lines we depend on. Tests assert on this snippet's behavior in
    isolation rather than re-running the full install pipeline.
    """
    lines = install_sh_text.splitlines()
    capture: list[str] = []
    in_block = False
    for line in lines:
        if "RV_STDIN_IS_TTY=0" in line:
            in_block = True
        if in_block:
            capture.append(line)
            if line.startswith("export RV_STDIN_IS_TTY"):
                break
    assert capture, "TTY-capture block not found in install.sh"
    return "\n".join(capture)


def _is_interactive_block(install_sh_text: str) -> str:
    """Return the is_interactive() function body so tests can verify
    it consults the cached values, not live ``-t`` checks."""
    lines = install_sh_text.splitlines()
    out: list[str] = []
    in_fn = False
    for line in lines:
        if line.startswith("is_interactive()"):
            in_fn = True
        if in_fn:
            out.append(line)
            if line.rstrip() == "}":
                break
    assert out, "is_interactive() function not found in install.sh"
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Structural checks — guard against accidental regressions to the source
# ---------------------------------------------------------------------------


def test_install_sh_captures_tty_state_before_log_redirect() -> None:
    """The TTY-state capture MUST appear BEFORE the ``exec >`` log redirect.
    Anywhere after the redirect, ``-t 1`` is false on real terminals too,
    so the cache would always record 0 and the bug would silently come back.
    """
    text = INSTALL_SH.read_text(encoding="utf-8")
    idx_capture = text.find("RV_STDIN_IS_TTY=0")
    idx_redirect = text.find("exec > >(tee -a")
    assert idx_capture > 0, "TTY-capture block missing"
    assert idx_redirect > 0, "log-redirect line missing"
    assert idx_capture < idx_redirect, (
        "TTY-state capture MUST happen BEFORE the log redirect; "
        f"capture at offset {idx_capture}, redirect at offset {idx_redirect}"
    )


def test_is_interactive_uses_cached_tty_state_not_live_checks() -> None:
    """``is_interactive()`` MUST consult ``RV_STDIN_IS_TTY`` and
    ``RV_STDOUT_IS_TTY`` instead of ``-t 0`` / ``-t 1``. The latter
    silently break under the log redirect."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    body = _is_interactive_block(text)
    assert "RV_STDIN_IS_TTY" in body, (
        "is_interactive() must check the cached TTY state for stdin"
    )
    assert "RV_STDOUT_IS_TTY" in body, (
        "is_interactive() must check the cached TTY state for stdout"
    )
    # The buggy form is "-t 0" or "-t 1" inside the function body.
    assert " -t 0" not in body, (
        "is_interactive() must NOT use live -t 0 — it's false under the log redirect"
    )
    assert " -t 1" not in body, (
        "is_interactive() must NOT use live -t 1 — it's false under the log redirect"
    )


def test_tty_capture_block_handles_all_three_streams() -> None:
    """Capture stdin (-t 0), stdout (-t 1), and stderr (-t 2) so the
    Python CLI (which reads ``RV_STDERR_IS_TTY`` in future to drive
    color decisions) sees pre-redirect truth."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    block = _extract_tty_capture_block(text)
    assert "-t 0" in block
    assert "-t 1" in block
    assert "-t 2" in block
    assert "RV_STDIN_IS_TTY=1" in block
    assert "RV_STDOUT_IS_TTY=1" in block
    assert "RV_STDERR_IS_TTY=1" in block


# ---------------------------------------------------------------------------
# Behavioural checks — execute the install.sh logic in a sandboxed shell
# ---------------------------------------------------------------------------


@pytest.fixture
def sandbox_install_sh(tmp_path: Path) -> Path:
    """Build a minimal shell script that exercises ONLY the TTY-capture
    and ``is_interactive()`` logic from ``dist-templates/install.sh``.

    The full install script does heavy work (venv creation, wheel
    install) that we don't want to run in a unit test — but its TTY
    handling is self-contained, so we lift the two blocks verbatim and
    short-circuit immediately after with a sentinel ``RV_DECISION``
    line the test parses. If either block is rewritten in install.sh in
    a way that breaks TTY detection, this fixture's tests will fail
    even though the install.sh prelude is never executed.
    """
    src_text = INSTALL_SH.read_text(encoding="utf-8")

    tty_capture = _extract_tty_capture_block(src_text)
    is_interactive = _is_interactive_block(src_text)

    # Use a placeholder-based template (not str.format) because shell
    # scripts are full of ``${VAR}`` which collides with Python format
    # syntax.
    sandboxed = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "\n"
        'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        'cd "${ROOT_DIR}"\n'
        "\n"
        "# === TTY-capture block (verbatim from dist-templates/install.sh) ===\n"
        + tty_capture
        + "\n\n"
        "# === Log redirect (verbatim — this is what historically broke -t 1) ===\n"
        'INSTALL_LOG="${ROOT_DIR}/install.log"\n'
        ': > "${INSTALL_LOG}"\n'
        'exec > >(tee -a "${INSTALL_LOG}") 2>&1\n'
        "\n"
        "# === Defaults that install.sh sets before is_interactive is called ===\n"
        'NON_INTERACTIVE="${RV_NONINTERACTIVE:-}"\n'
        "\n"
        "# === is_interactive() (verbatim from dist-templates/install.sh) ===\n"
        + is_interactive
        + "\n\n"
        "if is_interactive; then\n"
        '    echo "RV_DECISION: interactive"\n'
        '    echo "interactive" > "${ROOT_DIR}/decision"\n'
        "else\n"
        '    echo "RV_DECISION: non-interactive"\n'
        '    echo "non-interactive" > "${ROOT_DIR}/decision"\n'
        "fi\n"
        # Wait briefly so the tee process substitution can flush before
        # the shell exits — without this, the pty consumer occasionally
        # reads EOF before any data arrives on macOS.
        "sleep 0.1\n"
        "exit 0\n"
    )
    dest = tmp_path / "install.sh"
    dest.write_text(sandboxed, encoding="utf-8")
    dest.chmod(0o755)
    return dest


def _bash_available() -> bool:
    return shutil.which("bash") is not None


@pytest.mark.skipif(not _bash_available(), reason="bash not available")
def test_install_sh_is_interactive_when_run_under_a_pty(
    sandbox_install_sh: Path, tmp_path: Path
) -> None:
    """When ``install.sh`` runs under a pseudo-terminal (i.e. the user's
    real terminal) the wizard MUST be reachable. Without the v0.2.24 fix
    the log redirect made this false even under a pty.

    We allocate a pty using ``script(1)`` (BSD/macOS) or stdlib ``pty``
    and assert the sentinel reports ``interactive``.
    """
    import os
    import pty

    # Fork a child that runs the sandbox script under a controlling pty.
    pid, master_fd = pty.fork()
    if pid == 0:
        os.execvp("bash", ["bash", str(sandbox_install_sh)])

    # Drain the pty so the child doesn't block on a full output buffer,
    # but DON'T rely on what we read for the assertion — process
    # substitution + pty interact badly enough on macOS that occasional
    # zero-byte reads happen even when the child writes the file. We
    # read the ``decision`` sidecar the sandbox wrote instead.
    try:
        while True:
            try:
                if not os.read(master_fd, 4096):
                    break
            except OSError:
                break
    finally:
        os.close(master_fd)
        os.waitpid(pid, 0)

    decision_path = sandbox_install_sh.parent / "decision"
    assert decision_path.is_file(), "sandbox did not write decision sidecar"
    decision = decision_path.read_text(encoding="utf-8").strip()
    assert decision == "interactive", (
        f"install.sh should report interactive under a real pty; got {decision!r}"
    )


@pytest.mark.skipif(not _bash_available(), reason="bash not available")
def test_install_sh_is_non_interactive_when_stdin_is_not_a_tty(
    sandbox_install_sh: Path,
) -> None:
    """When stdin is a pipe (CI, ``cat | install.sh``, etc.) the script
    MUST correctly degrade to non-interactive mode — that's the whole
    point of the check; we must not over-correct in the v0.2.24 fix."""
    subprocess.run(
        ["bash", str(sandbox_install_sh)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=15,
        check=False,
    )
    decision_path = sandbox_install_sh.parent / "decision"
    assert decision_path.is_file(), "sandbox did not write decision sidecar"
    decision = decision_path.read_text(encoding="utf-8").strip()
    assert decision == "non-interactive", (
        f"install.sh should report non-interactive when stdin is /dev/null; "
        f"got {decision!r}"
    )


@pytest.mark.skipif(not _bash_available(), reason="bash not available")
def test_install_sh_respects_rv_noninteractive_env(
    sandbox_install_sh: Path,
) -> None:
    """``RV_NONINTERACTIVE=1`` MUST force non-interactive mode regardless
    of TTY state — preserved from the v0.2.22 behaviour. We run under a
    pty (real TTY) and confirm the env var still wins.
    """
    import os
    import pty

    pid, master_fd = pty.fork()
    if pid == 0:
        env = os.environ.copy()
        env["RV_NONINTERACTIVE"] = "1"
        os.execvpe("bash", ["bash", str(sandbox_install_sh)], env)
    try:
        while True:
            try:
                if not os.read(master_fd, 4096):
                    break
            except OSError:
                break
    finally:
        os.close(master_fd)
        os.waitpid(pid, 0)
    decision_path = sandbox_install_sh.parent / "decision"
    assert decision_path.is_file(), "sandbox did not write decision sidecar"
    decision = decision_path.read_text(encoding="utf-8").strip()
    assert decision == "non-interactive", (
        f"RV_NONINTERACTIVE=1 must force non-interactive; got {decision!r}"
    )


def test_install_sh_contains_path_confirm_and_accept_path_flag() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "Installing into:" in text
    assert "--accept-path" in text
    assert "confirm_install_path" in text


@pytest.mark.skipif(not _bash_available(), reason="bash not available")
def test_headless_refuses_without_accept_path(tmp_path: Path) -> None:
    """Non-interactive install must refuse without --accept-path (FR-009)."""
    src = INSTALL_SH.read_text(encoding="utf-8")
    start = src.find("confirm_install_path()")
    end = src.find("_detect_stale_venv()", start)
    assert start > 0 and end > start
    block = src[start:end]
    script = tmp_path / "confirm.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        'TARGET="${ROOT_DIR}"\n'
        "NON_INTERACTIVE=1\n"
        'ACCEPT_PATH=""\n'
        "RV_STDIN_IS_TTY=0\n"
        "RV_STDOUT_IS_TTY=0\n"
        'is_interactive() { [[ -z "${NON_INTERACTIVE}" && "${RV_STDIN_IS_TTY}" == "1" && "${RV_STDOUT_IS_TTY}" == "1" ]]; }\n'
        "ask_yn() { return 0; }\n" + block + "\nconfirm_install_path\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    proc = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "requires --accept-path" in proc.stderr
