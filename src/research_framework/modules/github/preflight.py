#!/usr/bin/env python3
"""GitHub module preflight — stdin/stdout JSON contract (spec 051 FR4).

Validates the module before a cycle:
- confirms the host ``gh`` CLI is installed AND authenticated
  (``gh auth status``) — **fail-closed** when not (``fatal_fail``), because
  every extraction depends on the session token;
- confirms ``sources.yaml`` declares usable ``github_sources`` entries and
  that each ``url`` looks like a ``github.com/<org>/<repo>`` URL (auto-strips
  stray whitespace);
- flags bare-string entries (the extractor's loader drops non-dict records).

Auth is the ``gh`` **session**, not an env API key — there is intentionally
no ``authentication.env_vars`` to probe (contrast ``oreilly``).

Subprocess-isolated like ``extractor.py`` (Principle V): cannot import from
``src/research_framework``; emits the ``PreflightResult`` JSON shape directly.
Contract: ``specs/051-post-revival-hardening/contracts/preflight.contract.md``.

Test override (hermetic):
- ``GH_BIN``: path to the ``gh`` binary (default ``gh``).
- ``GITHUB_PREFLIGHT_AUTH_FIXTURE``: JSON file ``{"ok": bool, "error": str}``
  standing in for ``gh auth status`` so tests never touch the real session.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.parse
from typing import Any

_MODULE = "github"
_FAILURE_POLICY = "block_cycle"
_GITHUB_HOST_RE = re.compile(r"^(www\.)?github\.com$", re.IGNORECASE)


def _corr(original: str, suggested: str, reason: str, applied: bool) -> dict[str, Any]:
    return {
        "original": original,
        "suggested": suggested,
        "reason": reason,
        "applied": applied,
    }


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


def _gh_bin() -> str:
    return os.environ.get("GH_BIN", "").strip() or "gh"


def _iter_urls(sources: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for entry in sources.get("github_sources") or []:
        if isinstance(entry, dict) and entry.get("url"):
            out.append(str(entry["url"]))
    return out


def _bare_entries(sources: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for entry in sources.get("github_sources") or []:
        if isinstance(entry, str):
            out.append(entry)
    return out


def _is_github_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    if not _GITHUB_HOST_RE.match(parsed.netloc):
        return False
    parts = [p for p in parsed.path.split("/") if p]
    return len(parts) >= 2


def _auth_probe(*, timeout_seconds: int) -> tuple[bool, str | None]:
    """Return ``(authenticated, error_message)``. Fixture-overridable; never raises."""
    fixture = os.environ.get("GITHUB_PREFLIGHT_AUTH_FIXTURE", "").strip()
    if fixture:
        try:
            with open(fixture, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return False, "gh auth status fixture unreadable"
        if isinstance(data, dict) and data.get("ok"):
            return True, None
        if isinstance(data, dict):
            return False, str(
                data.get("error") or "gh auth status reported not logged in"
            )
        return False, "gh auth status fixture malformed"

    try:
        proc = subprocess.run(
            [_gh_bin(), "auth", "status"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return False, "gh CLI not found on PATH — install GitHub CLI"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"gh auth status failed: {exc}"
    if proc.returncode == 0:
        return True, None
    return False, "gh auth status reported not logged in — run `gh auth login`"


def check(
    sources: dict[str, Any],
    watermarks: dict[str, Any],
    *,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    del watermarks  # reserved for contract parity
    if not isinstance(sources, dict):
        return _result("fatal_fail", messages=["sources.yaml block is not a mapping"])

    authed, auth_error = _auth_probe(timeout_seconds=timeout_seconds)
    if not authed:
        msg = f"module '{_MODULE}': {auth_error}"
        if _FAILURE_POLICY == "block_cycle":
            return _result("fatal_fail", messages=[msg])

    urls = _iter_urls(sources)
    bare = _bare_entries(sources)

    corrections: list[dict[str, Any]] = []
    messages: list[str] = []
    for raw in bare:
        corrections.append(
            _corr(
                raw,
                f'{{"url": "{raw}"}}',
                "bare-string source is ignored by the extractor — wrap as a "
                "{url: ...} mapping",
                False,
            )
        )
        messages.append(f"bare-string source {raw!r} → wrap as {{url: {raw!r}}}")

    if not urls:
        msg = (
            "all source entries are bare strings — wrap each as {url: ...}"
            if bare
            else "no github_sources declared — nothing to extract"
        )
        return _result("fatal_fail", corrections=corrections, messages=[*messages, msg])

    for raw_url in urls:
        url = raw_url.strip()
        if url != raw_url:
            corrections.append(_corr(raw_url, url, "leading/trailing whitespace", True))
        if not _is_github_url(url):
            messages.append(
                f"github source {url!r} is not a github.com/<org>/<repo> URL"
            )

    verdict = "warning" if (corrections or messages) else "success"
    return _result(verdict, corrections=corrections, messages=messages)


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
