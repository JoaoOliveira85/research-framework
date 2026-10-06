#!/usr/bin/env python3
"""Code module extractor — stdin/stdout JSON contract (spec 020)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_stdin() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _git_head(path: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return "unknown"
    return proc.stdout.strip()


def cmd_get_source_version(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") or {}
    repo = source.get("path") or source.get("url", "")
    if not repo:
        return {"source_version": "unknown"}
    return {"source_version": _git_head(Path(repo).expanduser())}


def cmd_extract(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") or {}
    source_id = str(payload.get("source_id", ""))
    repo = source.get("path") or source.get("url", "")
    version = _git_head(Path(repo).expanduser()) if repo else "unknown"
    return {
        "module": "code",
        "source_id": source_id,
        "source_version": version,
        "bridge_version": "0.0.0",
        "extracted_at": _utc_now_iso(),
        "verdict": "ok",
        "truncated": False,
        "partial": False,
        "facts": {"technologies": [], "patterns": []},
        "notable": [],
    }


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "extract"
    payload = _read_stdin()
    if command == "get_source_version":
        out = cmd_get_source_version(payload)
    else:
        out = cmd_extract(payload)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
