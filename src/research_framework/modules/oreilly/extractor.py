#!/usr/bin/env python3
"""O'Reilly module extractor — stdin/stdout JSON contract (spec 020).

Lifecycle:
1. Read JSON request from stdin.
2. Resolve a search query from ``source.url`` (``learning.oreilly.com/search/?q=…``).
3. Call the content-discovery API (or ``OREILLY_API_FIXTURE`` for hermetic tests).
4. Emit a ``SignalPayload`` on stdout with one ``notable[]`` entry per hit.

Handles ONE query per invocation — the framework drives the loop across
``sources.yaml`` ``oreilly_queries`` entries.

Error policy (D9, spec 020):
- Missing ``OREILLY_API_KEY`` (and no fixture) → ``verdict=error``.
- Missing / unreadable ``OREILLY_API_FIXTURE`` when override is set → ``verdict=error``.
- URL not matching ``learning.oreilly.com`` search shape → ``verdict=error``.
- Malformed JSON → ``verdict=error``.
- Zero hits → ``verdict=empty``.

``facts`` is intentionally empty in v0.1.0 (mirrors ``youtube`` / ``reddit`` / ``rss``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BRIDGE_VERSION = "0.0.0"
USER_AGENT = "research-framework-oreilly/0.1.0 (educational research)"
API_BASE = "https://api.oreilly.com/api/content-discovery/v1/mcp/"

MAX_HITS = 20
MAX_NOTABLE_HITS = 20
# We fetch ONE extra hit beyond MAX_HITS so the boundary case (source has
# exactly MAX_HITS results) doesn't get falsely reported as `truncated=True`.
# See cmd_extract: truncated = len(hits) > MAX_HITS, then hits[:MAX_HITS].
_FETCH_LIMIT = MAX_HITS + 1

_OREILLY_URL_PATTERN = re.compile(
    r"^https?://learning\.oreilly\.com/(?:search|library|api)/",
    re.IGNORECASE,
)


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


def _looks_like_oreilly_url(url: str) -> bool:
    return bool(_OREILLY_URL_PATTERN.search(url))


def _extract_query_from_url(url: str) -> str | None:
    """Parse search query from ``learning.oreilly.com/search/?q=…`` URLs."""
    parsed = urllib.parse.urlparse(url)
    path_lower = parsed.path.lower().rstrip("/")
    if path_lower.endswith("/search") or "/search/" in path_lower:
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
        q_values = qs.get("q") or qs.get("query")
        if q_values and q_values[0].strip():
            # parse_qs has already decoded it; a second unquote_plus turned the
            # "+" of "C++" into spaces.
            return q_values[0].strip()
    return None


def _api_key_present() -> bool:
    return bool(os.environ.get("OREILLY_API_KEY", "").strip())


def _load_fixture_json() -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(data, error_reason)``. When env is unset, ``(None, None)``."""
    fixture = os.environ.get("OREILLY_API_FIXTURE", "").strip()
    if not fixture:
        return None, None
    path = Path(fixture)
    if not path.is_file():
        return None, "OREILLY_API_FIXTURE path missing or unreadable"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, "malformed OREILLY_API_FIXTURE JSON"
    except OSError:
        return None, "OREILLY_API_FIXTURE path missing or unreadable"
    if not isinstance(data, dict):
        return None, "malformed OREILLY_API_FIXTURE JSON"
    return data, None


def _search_results_from_payload(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract ``search_results`` from MCP envelope or direct fixture shape."""
    if "search_results" in data and isinstance(data["search_results"], dict):
        return data["search_results"]

    rpc_result = data.get("result")
    if isinstance(rpc_result, dict):
        content_blocks = rpc_result.get("content", [])
        if content_blocks and isinstance(content_blocks[0], dict):
            try:
                inner = json.loads(str(content_blocks[0].get("text", "")))
            except json.JSONDecodeError:
                return None
            if isinstance(inner, dict):
                raw = inner.get("search_results")
                if isinstance(raw, dict):
                    return raw
    return None


def _call_api(
    query: str, api_key: str, *, n: int = _FETCH_LIMIT
) -> dict[str, Any] | None:
    """POST to content-discovery API; return parsed JSON or None on failure."""
    params: dict[str, Any] = {"query": query, "n_items": n}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "search_oreilly_content",
            "arguments": params,
        },
    }

    req = urllib.request.Request(
        API_BASE,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _hits_from_search_results(raw_items: dict[str, Any]) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for _urn, item in raw_items.items():
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        authors_raw = item.get("authors") or []
        if isinstance(authors_raw, list):
            authors = ", ".join(str(a).strip() for a in authors_raw if str(a).strip())
        else:
            authors = str(authors_raw).strip()
        description = str(item.get("description") or "").strip()
        content_type = str(
            item.get("display_format") or item.get("marketing_type") or "content"
        ).strip()
        date_published = str(
            item.get("publication_date") or item.get("date_published") or ""
        ).strip()
        if not title and not url:
            continue
        hits.append(
            {
                "title": title or url,
                "url": url,
                "authors": authors,
                "description": description,
                "content_type": content_type or "content",
                "date_published": date_published,
            }
        )
        if len(hits) >= _FETCH_LIMIT:
            break
    return hits


def _fetch_hits(query: str) -> tuple[list[dict[str, str]] | None, str | None]:
    """Return (hits, error_reason). ``hits is None`` means parse/fetch failure."""
    fixture_data, fixture_err = _load_fixture_json()
    if os.environ.get("OREILLY_API_FIXTURE", "").strip():
        if fixture_err:
            return None, fixture_err
        if fixture_data is None:
            return None, "OREILLY_API_FIXTURE path missing or unreadable"
        raw_items = _search_results_from_payload(fixture_data)
        if raw_items is None:
            return None, "malformed OREILLY_API_FIXTURE JSON (no search_results)"
        return _hits_from_search_results(raw_items), None

    if not _api_key_present():
        return None, (
            "OREILLY_API_KEY env var not set — export a bearer token before extraction"
        )

    api_key = os.environ.get("OREILLY_API_KEY", "").strip()
    response = _call_api(query, api_key)
    if response is None:
        return None, "API request failed or returned malformed JSON"

    raw_items = _search_results_from_payload(response)
    if raw_items is None:
        return None, "could not parse API search_results"
    return _hits_from_search_results(raw_items), None


def _source_version_from_hits(hits: list[dict[str, str]], query: str) -> str:
    urls = sorted({h["url"] for h in hits if h.get("url")})
    if urls:
        joined = "|".join(urls)
        digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
        return f"sha256:{digest}"

    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _error_payload(source_id: str, reason: str) -> dict[str, Any]:
    return {
        "module": "oreilly",
        "source_id": source_id or "unknown",
        "source_version": "unknown",
        "bridge_version": BRIDGE_VERSION,
        "extracted_at": _utc_now_iso(),
        "verdict": "error",
        "truncated": False,
        "partial": False,
        "facts": {},
        "notable": [
            {
                "observation": reason,
                "confidence": "high",
                "evidence_ref": "extractor:precondition",
            }
        ],
    }


def _format_content_label(content_type: str) -> str:
    ct = content_type.lower().replace("_", " ")
    if ct in {"book", "books"}:
        return "book"
    if ct in {"video", "videos"}:
        return "video"
    if ct in {"course", "courses"}:
        return "course"
    if ct in {"article", "articles"}:
        return "article"
    return content_type or "content"


def _notable_from_hits(hits: list[dict[str, str]]) -> list[dict[str, Any]]:
    notable: list[dict[str, Any]] = []
    for hit in hits[:MAX_NOTABLE_HITS]:
        label = _format_content_label(hit.get("content_type", "content"))
        title = hit.get("title") or "(untitled)"
        authors = hit.get("authors") or ""
        obs = f"O'Reilly {label}: {title}"
        if authors:
            obs += f" by {authors}"
        date_str = hit.get("date_published") or ""
        if date_str:
            obs += f" ({date_str})"
        link = hit.get("url") or ""
        if link:
            obs += f" — {link}"
        notable.append(
            {
                "observation": obs,
                "confidence": "high",
                "evidence_ref": link or "oreilly:search-hit",
            }
        )
        desc = hit.get("description") or ""
        if desc:
            preview = desc[:200] + ("..." if len(desc) > 200 else "")
            notable.append(
                {
                    "observation": f"Description: {preview}",
                    "confidence": "medium",
                    "evidence_ref": link or "oreilly:search-hit",
                }
            )
    return notable


def cmd_get_source_version(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") or {}
    url = str(source.get("url", ""))
    if not url or not _looks_like_oreilly_url(url):
        return {"source_version": "unknown"}

    query = _extract_query_from_url(url)
    if not query:
        return {"source_version": "unknown"}

    hits, err = _fetch_hits(query)
    if err or hits is None:
        return {"source_version": "unknown"}
    return {"source_version": _source_version_from_hits(hits, query)}


def cmd_extract(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") or {}
    source_id = str(payload.get("source_id") or source.get("url") or "")
    url = str(source.get("url", ""))

    if not url:
        return _error_payload(source_id, "no source.url provided")

    if not _looks_like_oreilly_url(url):
        return _error_payload(
            source_id,
            "url does not match learning.oreilly.com search/library/api shape",
        )

    query = _extract_query_from_url(url)
    if not query:
        return _error_payload(
            source_id,
            "could not extract search query from learning.oreilly.com/search/?q= URL",
        )

    hits, err = _fetch_hits(query)
    if err:
        return _error_payload(source_id, err)
    if hits is None:
        return _error_payload(source_id, "malformed API or fixture JSON")

    source_version = _source_version_from_hits(hits, query)

    if not hits:
        return {
            "module": "oreilly",
            "source_id": source_id,
            "source_version": source_version,
            "bridge_version": BRIDGE_VERSION,
            "extracted_at": _utc_now_iso(),
            "verdict": "empty",
            "truncated": False,
            "partial": False,
            "facts": {},
            "notable": [],
        }

    truncated = len(hits) > MAX_HITS
    if truncated:
        hits = hits[:MAX_HITS]
    notable = _notable_from_hits(hits)

    return {
        "module": "oreilly",
        "source_id": source_id,
        "source_version": source_version,
        "bridge_version": BRIDGE_VERSION,
        "extracted_at": _utc_now_iso(),
        "verdict": "ok",
        "truncated": truncated,
        "partial": False,
        "facts": {},
        "notable": notable,
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
