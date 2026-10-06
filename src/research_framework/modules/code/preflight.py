#!/usr/bin/env python3
"""Code module preflight — stdin/stdout JSON contract (spec 051 FR4).

Validates the module's ``sources.yaml`` before a cycle:
- confirms at least one source is declared;
- checks ``github_repos`` local ``path`` entries exist on disk (WARN when missing).

Subprocess-isolated like ``extractor.py`` (Principle V) — it cannot import from
``src/`` and emits the ``PreflightResult`` JSON shape directly. Contract:
``specs/051-post-revival-hardening/contracts/preflight.contract.md``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _result(
    verdict: str,
    *,
    corrections: list[dict[str, Any]] | None = None,
    messages: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "verdict": verdict,
        "corrections": corrections or [],
        "messages": messages or [],
    }


def _iter_repo_paths(sources: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for entry in sources.get("github_repos") or []:
        if isinstance(entry, dict) and entry.get("path"):
            out.append(str(entry["path"]))
    return out


def _remote_only_entries(sources: dict[str, Any]) -> list[str]:
    """github_repos entries that declare a remote ``url`` but no local ``path``.

    The ``code`` module is local-only (spec-020 amendment 2026-06-08); a
    remote-only entry would be silently ignored by the extractor, so flag it
    and steer the author to the ``github`` module.
    """
    out: list[str] = []
    for entry in sources.get("github_repos") or []:
        if isinstance(entry, dict) and entry.get("url") and not entry.get("path"):
            out.append(str(entry["url"]))
    return out


def check(
    sources: dict[str, Any],
    watermarks: dict[str, Any],
    *,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    del watermarks, timeout_seconds  # reserved for contract parity
    if not isinstance(sources, dict):
        return _result("fatal_fail", messages=["sources.yaml block is not a mapping"])
    if not any(sources.get(key) for key in sources):
        return _result(
            "fatal_fail", messages=["no code sources declared — nothing to extract"]
        )

    messages: list[str] = []
    for path_str in _iter_repo_paths(sources):
        path = Path(path_str).expanduser()
        if not path.exists():
            messages.append(f"code repo path {path_str!r} does not exist on disk")
        elif not path.is_dir():
            messages.append(f"code repo path {path_str!r} is not a directory")

    for url in _remote_only_entries(sources):
        messages.append(
            f"code source {url!r} has a remote url but no local path — `code` is "
            "local-only; use the `github` module for remote GitHub surfaces"
        )

    if messages:
        return _result("warning", messages=messages)
    return _result("success")


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "preflight"
    payload = json.loads(sys.stdin.read() or "{}")
    if command == "preflight":
        out = check(
            payload.get("sources") or {},
            payload.get("watermarks") or {},
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
        )
    else:
        out = _result("fatal_fail", messages=[f"unknown command: {command}"])
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
