#!/usr/bin/env python3
"""Atlassian module preflight — stdin/stdout JSON contract (spec 051 FR4).

Validates before a cycle:
- ``ATLASSIAN_EMAIL`` + ``ATLASSIAN_API_TOKEN`` are BOTH set (mandatory) —
  **fail-closed** (``fatal_fail``) when either is missing;
- ``sources.yaml`` declares usable ``jira_projects`` / ``confluence_spaces``
  entries whose ``url`` is a ``<site>.atlassian.net`` URL (auto-strips
  whitespace; flags bare-string entries the loader would drop);
- optional connectivity probe (fixture-overridable).

Credentials are read for the connectivity probe but **never** written to
stdout/stderr (key-leak sentinel tests enforce this).

Subprocess-isolated like ``extractor.py`` (Principle V): cannot import from
``src/research_framework``. Contract:
``specs/051-post-revival-hardening/contracts/preflight.contract.md``.

Test overrides (hermetic):
- ``ATLASSIAN_PREFLIGHT_FAKE_ENV``: JSON mapping of env vars.
- ``ATLASSIAN_PREFLIGHT_CONNECTIVITY_FIXTURE``: JSON ``{"ok": bool, "error": str}``.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_MODULE = "atlassian"
_MANDATORY_ENV_VARS = ("ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN")
_FAILURE_POLICY = "block_cycle"
_SOURCE_KINDS = ("jira_projects", "confluence_spaces")
_SITE_RE = re.compile(r"^[a-zA-Z0-9-]+\.atlassian\.net$", re.IGNORECASE)


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


def _load_fake_env() -> dict[str, str] | None:
    fixture = os.environ.get("ATLASSIAN_PREFLIGHT_FAKE_ENV", "").strip()
    if not fixture:
        return None
    try:
        with open(fixture, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _env_value(var: str, fake_env: dict[str, str] | None) -> str | None:
    if fake_env is not None:
        value = fake_env.get(var)
        return str(value).strip() if value else None
    value = os.environ.get(var)
    return value.strip() if value else None


def _auth_probe_messages() -> tuple[list[str], bool]:
    fake_env = _load_fake_env()
    messages: list[str] = []
    missing = False
    for var in _MANDATORY_ENV_VARS:
        if not _env_value(var, fake_env):
            messages.append(f"module '{_MODULE}': missing env var {var}")
            missing = True
    return messages, missing


def _iter_urls(sources: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for kind in _SOURCE_KINDS:
        for entry in sources.get(kind) or []:
            if isinstance(entry, dict) and entry.get("url"):
                out.append(str(entry["url"]))
    return out


def _bare_entries(sources: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for kind in _SOURCE_KINDS:
        for entry in sources.get(kind) or []:
            if isinstance(entry, str):
                out.append(entry)
    return out


def _is_atlassian_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    return bool(_SITE_RE.match(parsed.netloc))


def _first_site(urls: list[str]) -> str | None:
    for url in urls:
        parsed = urllib.parse.urlparse(url.strip())
        if _SITE_RE.match(parsed.netloc):
            return parsed.netloc
    return None


def _connectivity_probe(
    site: str | None, *, timeout_seconds: int
) -> tuple[bool, str | None]:
    """Return ``(ok, error)``. Fixture-overridable; never raises; never leaks creds."""
    fixture = os.environ.get("ATLASSIAN_PREFLIGHT_CONNECTIVITY_FIXTURE", "").strip()
    if fixture:
        try:
            with open(fixture, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return False, "connectivity probe fixture unreadable"
        if isinstance(data, dict) and data.get("ok"):
            return True, None
        if isinstance(data, dict):
            return False, str(data.get("error") or "connectivity probe failed")
        return False, "connectivity probe failed"

    if site is None:
        return False, "no atlassian.net site URL to probe"
    fake_env = _load_fake_env()
    email = _env_value("ATLASSIAN_EMAIL", fake_env)
    token = _env_value("ATLASSIAN_API_TOKEN", fake_env)
    if not email or not token:
        return False, "missing credentials for connectivity probe"
    auth = "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode("ascii")
    req = urllib.request.Request(
        f"https://{site}/rest/api/3/myself",
        headers={
            "Authorization": auth,
            "Accept": "application/json",
            "User-Agent": "research-framework-atlassian-preflight/0.1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            if 200 <= resp.status < 400:
                return True, None
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code} {exc.reason}"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return False, str(exc)


def check(
    sources: dict[str, Any],
    watermarks: dict[str, Any],
    *,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    del watermarks
    if not isinstance(sources, dict):
        return _result("fatal_fail", messages=["sources.yaml block is not a mapping"])

    auth_messages, auth_missing = _auth_probe_messages()
    if auth_missing:
        return _result("fatal_fail", messages=auth_messages)

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
            else "no jira_projects / confluence_spaces declared — nothing to extract"
        )
        return _result("fatal_fail", corrections=corrections, messages=[*messages, msg])

    for raw_url in urls:
        url = raw_url.strip()
        if url != raw_url:
            corrections.append(_corr(raw_url, url, "leading/trailing whitespace", True))
        if not _is_atlassian_url(url):
            messages.append(
                f"atlassian source {url!r} is not a <site>.atlassian.net URL"
            )

    # Only probe when a real <site>.atlassian.net host is derivable. Probing a
    # missing site would return "no atlassian.net site URL to probe" and, under
    # block_cycle, turn a *URL-shape* warning (already in `messages`) into a
    # misleading connectivity FATAL. A bad URL shape is correctable → warning;
    # fail-closed stays reserved for missing creds and an unreachable site.
    site = _first_site(urls)
    if site is not None:
        ok, connectivity_error = _connectivity_probe(
            site, timeout_seconds=timeout_seconds
        )
        if not ok and connectivity_error:
            msg = (
                f"module '{_MODULE}': connectivity probe failed — {connectivity_error}"
            )
            if _FAILURE_POLICY == "block_cycle":
                return _result(
                    "fatal_fail", corrections=corrections, messages=[*messages, msg]
                )
            messages.append(msg)

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
