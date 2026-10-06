#!/usr/bin/env python3
"""YouTube module preflight — stdin/stdout JSON contract (spec 051 FR4).

Validates the module's ``sources.yaml`` entries before a cycle:
- strips stray leading/trailing whitespace from URLs (auto-applied correction);
- validates channel-URL shape;
- flags a plain handle written without the ``@`` prefix → suggests ``@handle``.

Subprocess-isolated exactly like ``extractor.py`` (Principle V): it CANNOT
import from ``src/research_framework`` and emits the ``PreflightResult`` JSON
shape directly. The orchestrator parses stdout via
``pipeline/source_bridge/preflight_types.py``. Contract:
``specs/051-post-revival-hardening/contracts/preflight.contract.md``.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

_MODULE = "youtube"
_MANDATORY_ENV_VARS = ("YOUTUBE_API_KEY",)

_CHANNEL_OK = re.compile(
    r"^https?://(?:www\.)?youtube\.com/"
    r"(?:@[\w.-]+|channel/UC[\w-]+|c/[\w.-]+|user/[\w.-]+)/?$"
)
_VIDEO_OK = re.compile(
    r"^https?://(?:(?:www\.)?youtube\.com/watch\?v=|youtu\.be/)[\w-]+"
)


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


_KEYS = ("youtube_videos", "youtube_channels")


def _iter_urls(sources: dict[str, Any]) -> list[tuple[str, str]]:
    """(key, url) for **dict** entries only — mirrors ``load_module_sources``,
    which drops non-dict entries. Bare strings are surfaced by
    :func:`_bare_entries` so preflight and the extractor agree on what's usable.
    """
    out: list[tuple[str, str]] = []
    for key in _KEYS:
        for entry in sources.get(key) or []:
            if isinstance(entry, dict) and entry.get("url"):
                out.append((key, str(entry["url"])))
    return out


def _bare_entries(sources: dict[str, Any]) -> list[str]:
    """Bare-string entries — the extractor's loader drops these, so preflight
    must flag them rather than report them as usable sources."""
    out: list[str] = []
    for key in _KEYS:
        for entry in sources.get(key) or []:
            if isinstance(entry, str):
                out.append(entry)
    return out


def _load_fake_env() -> dict[str, str] | None:
    fixture = os.environ.get("YOUTUBE_PREFLIGHT_FAKE_ENV", "").strip()
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


def check(
    sources: dict[str, Any],
    watermarks: dict[str, Any],
    *,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
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
        # The extractor's loader drops bare strings; flag (don't auto-apply) so
        # preflight and extraction agree on what's usable.
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
        # No usable (dict) sources → the extractor would produce nothing.
        msg = (
            "all source entries are bare strings — wrap each as {url: ...}"
            if bare
            else "no youtube_videos or youtube_channels declared — nothing to extract"
        )
        return _result("fatal_fail", corrections=corrections, messages=[*messages, msg])
    for key, raw_url in urls:
        url = raw_url.strip()
        if url != raw_url:
            corrections.append(_corr(raw_url, url, "leading/trailing whitespace", True))
        if key == "youtube_channels":
            if url.startswith("@") or _CHANNEL_OK.match(url):
                continue
            token = url.rstrip("/").split("/")[-1]
            suggested = token if token.startswith("@") else f"@{token}"
            corrections.append(
                _corr(
                    url,
                    suggested,
                    "channel ref should be an @handle or a /channel|/c|/user URL",
                    False,
                )
            )
            messages.append(f"youtube channel {url!r} → suggest {suggested!r}")
        elif not _VIDEO_OK.match(url):
            messages.append(
                f"youtube video URL {url!r} is not a watch?v= / youtu.be link"
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
