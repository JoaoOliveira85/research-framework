#!/usr/bin/env python3
"""O'Reilly module preflight — stdin/stdout JSON contract (spec 051 FR4).

Validates the module's ``sources.yaml`` ``oreilly_queries`` entries before a
cycle:
- strips stray leading/trailing whitespace from URLs (auto-applied correction);
- verifies each URL is a ``learning.oreilly.com/search/?q=…`` query URL;
- rejects the legacy ``oreilly.com/api/v2/search`` form → corrects toward the
  search-URL shape. When a query param (``q``/``query``) can be lifted out of the
  legacy URL the rewrite is auto-applied (``applied=true``); otherwise it is a
  suggestion only (``applied=false``).

Scope note: API-key / env-var handling is intentionally untouched here — this is
purely the URL-shape preflight (a separate future change moves the key to a
settings file).

Subprocess-isolated exactly like ``extractor.py`` (Principle V): it CANNOT
import from ``src/research_framework`` and emits the ``PreflightResult`` JSON
shape directly. The orchestrator parses stdout via
``pipeline/source_bridge/preflight_types.py``. Contract:
``specs/051-post-revival-hardening/contracts/preflight.contract.md``.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_MODULE = "oreilly"
_MANDATORY_ENV_VARS = ("OREILLY_API_KEY",)
_FAILURE_POLICY = "block_cycle"
_CONNECTIVITY_URL = "https://learning.oreilly.com/api/v1/me"

_SEARCH_PREFIX = "https://learning.oreilly.com/search/?q="
# Legacy content-search API form we want to migrate off of.
_LEGACY_API_MARKER = "oreilly.com/api/v2/search"


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
    """URLs declared under ``oreilly_queries`` as **dict** entries only —
    mirrors ``load_module_sources``, which drops non-dict entries. Bare strings
    are surfaced by :func:`_bare_entries` so preflight and the extractor agree on
    what's usable.
    """
    out: list[str] = []
    for entry in sources.get("oreilly_queries") or []:
        if isinstance(entry, dict) and entry.get("url"):
            out.append(str(entry["url"]))
    return out


def _bare_entries(sources: dict[str, Any]) -> list[str]:
    """Bare-string entries — the extractor's loader drops these, so preflight
    must flag them rather than report them as usable sources."""
    out: list[str] = []
    for entry in sources.get("oreilly_queries") or []:
        if isinstance(entry, str):
            out.append(entry)
    return out


def _load_fake_env() -> dict[str, str] | None:
    fixture = os.environ.get("OREILLY_PREFLIGHT_FAKE_ENV", "").strip()
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


def _connectivity_probe(*, timeout_seconds: int) -> tuple[bool, str | None]:
    """Return (ok, error_message). Fixture-overridable; never raises."""
    fixture = os.environ.get("OREILLY_PREFLIGHT_CONNECTIVITY_FIXTURE", "").strip()
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

    api_key = _env_value("OREILLY_API_KEY", _load_fake_env())
    if not api_key:
        return False, "missing OREILLY_API_KEY for connectivity probe"
    req = urllib.request.Request(
        _CONNECTIVITY_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "research-framework-oreilly-preflight/0.1.0",
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


def _is_search_url(url: str) -> bool:
    """True for ``learning.oreilly.com/search/?q=<non-empty>`` query URLs."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.netloc.lower().lstrip("www.") != "learning.oreilly.com":
        return False
    if parsed.path.rstrip("/").lower() != "/search":
        return False
    qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
    return bool(qs.get("q") or qs.get("query"))


def _query_from_url(url: str) -> str | None:
    """Lift the ``q``/``query`` param (raw form-encoded) from a URL, if any."""
    parsed = urllib.parse.urlparse(url)
    for pair in parsed.query.split("&"):
        if "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        if key in ("q", "query") and value:
            return value
    return None


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
            else "no oreilly_queries declared — nothing to extract"
        )
        return _result("fatal_fail", corrections=corrections, messages=[*messages, msg])

    for raw_url in urls:
        url = raw_url.strip()
        if url != raw_url:
            corrections.append(_corr(raw_url, url, "leading/trailing whitespace", True))

        if _is_search_url(url):
            continue

        if _LEGACY_API_MARKER in url.lower():
            query = _query_from_url(url)
            if query:
                suggested = f"{_SEARCH_PREFIX}{query}"
                corrections.append(
                    _corr(
                        url,
                        suggested,
                        f"legacy {_LEGACY_API_MARKER} form is retired — "
                        "use the learning.oreilly.com/search/?q= URL",
                        True,
                    )
                )
                messages.append(f"oreilly query {url!r} rewritten to {suggested!r}")
            else:
                suggested = f"{_SEARCH_PREFIX}<query>"
                corrections.append(
                    _corr(
                        url,
                        suggested,
                        f"legacy {_LEGACY_API_MARKER} form is retired — "
                        "use the learning.oreilly.com/search/?q= URL "
                        "(no query param found to lift automatically)",
                        False,
                    )
                )
                messages.append(f"oreilly query {url!r} → suggest {suggested!r}")
            continue

        messages.append(
            f"oreilly query {url!r} is not a learning.oreilly.com/search/?q= URL"
        )

    ok, connectivity_error = _connectivity_probe(timeout_seconds=timeout_seconds)
    if not ok and connectivity_error:
        msg = f"module '{_MODULE}': connectivity probe failed — {connectivity_error}"
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
