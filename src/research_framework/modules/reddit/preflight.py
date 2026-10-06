#!/usr/bin/env python3
"""Reddit module preflight — stdin/stdout JSON contract (spec 051 FR4).

Validates the module's ``sources.yaml`` entries before a cycle:
- accepts a full ``https://www.reddit.com/r/<name>...`` URL (in a
  ``{url: ...}`` mapping) as-is;
- normalizes a bare ``<name>`` or ``/r/<name>`` mapping value to the
  canonical ``https://www.reddit.com/r/<name>/.rss`` URL (auto-applied
  correction) — this is the shape the extractor consumes (``_SUBREDDIT_RX``
  / ``_rss_url_for_source`` resolve every source to ``/r/<name>/.rss``);
- rejects obvious typos (spaces, invalid characters, empty) as
  suggestion-only corrections (``applied=false``);
- flags bare-string entries (a YAML scalar, not a ``{url: ...}`` mapping)
  as NOT usable — the extractor's loader drops them — with a wrap
  correction (``applied=false``).

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
import urllib.error
import urllib.request
from typing import Any

USER_AGENT = "research-framework-reddit-preflight/0.1.0 (educational; no auth)"

# A valid full Reddit subreddit/post URL the extractor recognises.
_FULL_URL_OK = re.compile(
    r"^https?://(?:www\.)?reddit\.com/r/[A-Za-z0-9_]+(?:/[^\s]*)?$"
)
# A subreddit name is 1-21 chars of [A-Za-z0-9_] (Reddit's own naming rule).
_NAME_OK = re.compile(r"^[A-Za-z0-9_]{1,21}$")


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


_KEYS = ("reddit_subreddits", "reddit_posts")


def _iter_urls(sources: dict[str, Any]) -> list[tuple[str, str]]:
    """(key, url) for **dict** entries only — mirrors ``load_module_sources``,
    which drops non-dict entries. Bare strings are surfaced by
    :func:`_bare_entries` so preflight and the extractor agree on what's usable.
    """
    out: list[tuple[str, str]] = []
    for key in _KEYS:
        for entry in sources.get(key) or []:
            if isinstance(entry, dict) and "url" in entry:
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


def _canonical_url(name: str) -> str:
    return f"https://www.reddit.com/r/{name}/.rss"


def _probe_head(url: str, *, timeout_seconds: int) -> tuple[str | None, str | None]:
    """Return ``(content_type, error_message)`` — fixture-overridable; never raises."""
    fixture = os.environ.get("REDDIT_PREFLIGHT_HEAD_FIXTURE", "").strip()
    if fixture:
        try:
            with open(fixture, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None, "connectivity probe fixture unreadable"
        if isinstance(data, str):
            return data.lower(), None
        if isinstance(data, dict):
            value = data.get(url)
            if isinstance(value, dict) and "error" in value:
                return None, str(value["error"])
            if value is not None:
                return str(value).lower(), None
            return None, None
        return None, None

    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            ct = resp.headers.get("Content-Type")
            return (ct.lower() if ct else None), None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return None, str(exc)


def check(
    sources: dict[str, Any],
    watermarks: dict[str, Any],
    *,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    if not isinstance(sources, dict):
        return _result("fatal_fail", messages=["sources.yaml block is not a mapping"])
    entries = _iter_urls(sources)
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

    if not entries:
        # No usable (dict) sources → the extractor would produce nothing.
        msg = (
            "all source entries are bare strings — wrap each as {url: ...}"
            if bare
            else "no reddit_subreddits or reddit_posts declared — nothing to extract"
        )
        return _result("fatal_fail", corrections=corrections, messages=[*messages, msg])

    usable = 0
    probe_urls: list[str] = []
    for _key, raw_url in entries:
        url = raw_url.strip()
        probe_url = url
        # Full, recognised Reddit URL — used as-is.
        if _FULL_URL_OK.match(url):
            usable += 1
            probe_urls.append(probe_url)
            continue

        # Strip an optional leading "/r/" or "r/" to get the bare name.
        name = re.sub(r"^/?r/", "", url, count=1, flags=re.IGNORECASE)
        if _NAME_OK.match(name):
            suggested = _canonical_url(name)
            corrections.append(
                _corr(
                    raw_url,
                    suggested,
                    "bare subreddit normalized to canonical /r/<name>/.rss URL",
                    True,
                )
            )
            usable += 1
            probe_urls.append(suggested)
            continue

        # Obvious typo: spaces, invalid characters, or empty — suggestion only.
        cleaned = re.sub(r"[^A-Za-z0-9_]", "", name)
        if _NAME_OK.match(cleaned):
            corrections.append(
                _corr(
                    raw_url,
                    _canonical_url(cleaned),
                    "subreddit ref has invalid characters — verify the intended name",
                    False,
                )
            )
            messages.append(
                f"reddit subreddit {raw_url!r} has invalid characters "
                f"→ suggest {_canonical_url(cleaned)!r}"
            )
        else:
            messages.append(
                f"reddit subreddit {raw_url!r} is empty or unrecognisable — skipped"
            )

    if usable == 0:
        return _result(
            "fatal_fail",
            corrections=corrections,
            messages=messages
            + ["no usable subreddits after normalization — nothing to extract"],
        )

    for probe_url in probe_urls:
        _content_type, probe_error = _probe_head(
            probe_url, timeout_seconds=timeout_seconds
        )
        if probe_error:
            messages.append(
                f"reddit feed {probe_url!r} connectivity probe failed — {probe_error}"
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
