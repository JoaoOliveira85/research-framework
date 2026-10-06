#!/usr/bin/env python3
"""RSS module preflight — stdin/stdout JSON contract (spec 051 FR4).

Validates the module's ``sources.yaml`` feed entries before a cycle:
- de-dups a doubled path segment ``/feed/feed/`` → ``/feed/`` (auto-applied
  correction);
- rewrites ``arxiv.org/list/cs.AI`` → ``rss.arxiv.org/rss/cs.AI`` (suggestion
  only — not auto-applied; the category is generalized, e.g. ``cs.AI``,
  ``cs.LG``);
- runs a HEAD probe (stdlib ``urllib``) confirming the feed URL emits an
  XML/Atom/RSS content-type, bounded by ``timeout_seconds``. A non-XML
  content-type is a soft ``warning`` message (the feed might still parse), never
  fatal. Network errors during the probe are swallowed (never crash the bridge).

**Offline / hermetic testing (Principle V).** The HEAD probe is
fixture-overridable, mirroring ``RSS_FIXTURE`` / ``YT_DLP_BIN``: when the env var
``RSS_PREFLIGHT_HEAD_FIXTURE`` points at a JSON file, the probe reads its
content-type from that file INSTEAD of the network. The fixture JSON may be:

- a JSON object mapping ``{url: content_type_string}`` — per-URL control; a URL
  absent from the map probes as if it returned no content-type; or
- a bare JSON string — that content-type is applied to every probed URL.

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

USER_AGENT = "research-framework-rss-preflight/0.1.0 (educational; no auth)"

# A doubled trailing feed segment, e.g. ``.../feed/feed/`` or ``.../feed/feed``.
_DOUBLED_FEED = re.compile(r"/feed/feed(?=/|$)", re.IGNORECASE)
# arXiv listing pages → the actual RSS feed host/path. Captures the category
# (e.g. ``cs.AI``, ``cs.LG``, ``math.NA``) so it generalizes.
_ARXIV_LIST = re.compile(
    r"^https?://(?:www\.)?arxiv\.org/list/([A-Za-z][\w.-]*)/?$", re.IGNORECASE
)
# Content-type tokens that indicate a feed payload.
_XML_CT_TOKENS = ("xml", "atom", "rss")


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


def _iter_urls(sources: dict[str, Any]) -> list[str]:
    """Every feed URL declared under ``rss_feeds`` as a **dict** entry — mirrors
    ``load_module_sources``, which drops non-dict entries. Bare strings are
    surfaced by :func:`_bare_entries` so preflight and the extractor agree on
    what's usable."""
    out: list[str] = []
    for entry in sources.get("rss_feeds") or []:
        if isinstance(entry, dict) and entry.get("url"):
            out.append(str(entry["url"]))
    return out


def _bare_entries(sources: dict[str, Any]) -> list[str]:
    """Bare-string entries under ``rss_feeds`` — the extractor's loader drops
    these, so preflight must flag them rather than report them as usable."""
    out: list[str] = []
    for entry in sources.get("rss_feeds") or []:
        if isinstance(entry, str):
            out.append(entry)
    return out


def _probe_head(url: str, *, timeout_seconds: int) -> tuple[str | None, str | None]:
    """Return ``(content_type, error_message)`` — fixture-overridable; never raises."""
    fixture = os.environ.get("RSS_PREFLIGHT_HEAD_FIXTURE", "").strip()
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
            else "no rss_feeds declared — nothing to extract"
        )
        return _result("fatal_fail", corrections=corrections, messages=[*messages, msg])

    for raw_url in urls:
        # The URL that actually gets probed: apply auto-applied corrections.
        probe_url = raw_url

        # 1. De-dup a doubled /feed/feed/ segment (auto-applied).
        deduped = _DOUBLED_FEED.sub("/feed", raw_url)
        if deduped != raw_url:
            corrections.append(
                _corr(raw_url, deduped, "doubled '/feed/feed/' path segment", True)
            )
            probe_url = deduped

        # 2. arXiv /list/<cat> → rss.arxiv.org/rss/<cat> (suggestion only).
        arxiv = _ARXIV_LIST.match(raw_url)
        if arxiv:
            category = arxiv.group(1)
            suggested = f"https://rss.arxiv.org/rss/{category}"
            corrections.append(
                _corr(
                    raw_url,
                    suggested,
                    "arxiv.org/list pages are HTML; use the rss.arxiv.org feed",
                    False,
                )
            )
            messages.append(f"arxiv listing {raw_url!r} → suggest {suggested!r}")

        # 3. HEAD probe: confirm the feed emits an XML/Atom/RSS content-type.
        content_type, probe_error = _probe_head(
            probe_url, timeout_seconds=timeout_seconds
        )
        if probe_error:
            messages.append(
                f"feed {probe_url!r} connectivity probe failed — {probe_error}"
            )
        elif content_type is not None and not any(
            tok in content_type for tok in _XML_CT_TOKENS
        ):
            messages.append(
                f"feed {probe_url!r} returned non-XML content-type "
                f"{content_type!r} — may not be a valid RSS/Atom feed"
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
