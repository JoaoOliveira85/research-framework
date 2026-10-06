"""``dist-templates/update.sh`` reads ``settings.yaml`` wherever the bundle lives.

Zero-arg ``./update.sh`` asks Python for ``output_dir:`` in the bundle's own
``settings.yaml``. The path of that file was pasted into the Python source
through an unquoted heredoc (``Path("${DEFAULT_SETTINGS}")``), so the name of
the directory the bundle was unpacked into was code: a double quote in it was
a ``SyntaxError``, a backslash an escape, and a quote followed by an
expression ran.

The script is run with ``/bin/bash`` (3.2 on macOS) from a copy of the bundle
in a hostile directory. Its interpreter is a wrapper that runs the settings
lookup for real and *records* the research run instead of starting one.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_UPDATE_SH = _REPO_ROOT / "dist-templates" / "update.sh"
_SYSTEM_BASH = Path("/bin/bash")

pytestmark = [
    pytest.mark.regression,
    pytest.mark.skipif(not _SYSTEM_BASH.is_file(), reason="/bin/bash not available"),
]

_BUNDLE_DIR_NAMES = {
    "double-quote": 'my "research" bundle',
    "python-expression": (
        'b"+str(open(__import__("os").environ.get("RF_TEST_MARK"),"w"))+"'
    ),
    "backslash-escape": "with\\tab",
}


@pytest.mark.parametrize(
    "dir_name", list(_BUNDLE_DIR_NAMES.values()), ids=list(_BUNDLE_DIR_NAMES)
)
def test_zero_arg_update_resolves_the_vault_from_a_hostile_bundle_path(
    tmp_path: Path, dir_name: str
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "research.spec.md").write_text("---\nname: t\n---\n", encoding="utf-8")

    bundle = tmp_path / dir_name
    bundle.mkdir()
    shutil.copy(_UPDATE_SH, bundle / "update.sh")
    (bundle / "settings.yaml").write_text(f"output_dir: {vault}\n", encoding="utf-8")

    recorded = tmp_path / "research-run.argv"
    marker = tmp_path / "EXECUTED"
    venv_bin = bundle / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    python = venv_bin / "python"
    python.write_text(
        "#!/bin/sh\n"
        # `python - …` is the settings lookup: run it. Anything else is the
        # research run itself: record the argv and stop.
        f'if [ "$1" = "-" ]; then exec {shlex.quote(sys.executable)} "$@"; fi\n'
        f'printf "%s\\n" "$@" > {shlex.quote(str(recorded))}\n',
        encoding="utf-8",
    )
    python.chmod(0o755)

    proc = subprocess.run(
        [str(_SYSTEM_BASH), str(bundle / "update.sh")],
        cwd=tmp_path,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "PYTHONPATH": str(_REPO_ROOT / "src"),
            "RF_TEST_MARK": str(marker),
        },
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
    )
    combined = proc.stdout + proc.stderr

    assert not marker.exists(), f"the bundle path was executed:\n{combined}"
    assert proc.returncode == 0, combined
    assert recorded.read_text(encoding="utf-8").splitlines() == [
        "-m",
        "research_framework.cli",
        "generate",
        "--spec",
        f"{vault}/research.spec.md",
        "--output",
        str(vault),
        "--resume",
    ]
