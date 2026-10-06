"""CLI contract tests for scripts/source_bridge.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "source_bridge.py"


def test_cli_parses_vault_cycle_and_flags(tmp_path: Path) -> None:
    help_proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--vault" in help_proc.stdout
    assert "--cycle" in help_proc.stdout
    assert "--debug-triggers" in help_proc.stdout
    assert "--force-stale-schema" in help_proc.stdout

    vault = tmp_path / "v"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 1\n  budget_usd: 0\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--vault",
            str(vault),
            "--cycle",
            "2",
            "--force-stale-schema",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0


def test_stderr_json_log_per_source_status(bridge_vault) -> None:
    """Per-source telemetry lands on stderr (spec 048: now via logger.info).

    Was `print(..., file=sys.stderr)` pre-spec-048. After migration it's
    `logger.info(json.dumps(record))` and the standalone script in
    `scripts/source_bridge.py` wires its own `logging.basicConfig(level=INFO)`
    so the JSON tail still reaches stderr. The format prefix is
    `<asctime> [INFO] <name>: ` — match the JSON tail of each line.
    """
    import json

    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--vault", str(bridge_vault), "--cycle", "1"],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [
        ln
        for ln in proc.stderr.splitlines()
        if (idx := ln.find("{")) != -1 and ln[idx:].strip().startswith("{")
    ]
    assert lines, f"no JSON-bearing line found in stderr; got: {proc.stderr!r}"
    first = lines[0]
    json.loads(first[first.find("{") :])


def test_debug_triggers_prints_markdown_table(bridge_vault) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--vault",
            str(bridge_vault),
            "--debug-triggers",
            "https://github.com/org/repo",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Trigger Registry" in proc.stdout
