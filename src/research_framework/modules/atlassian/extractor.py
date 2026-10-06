#!/usr/bin/env python3
"""Atlassian module extractor — stdin/stdout JSON contract (spec 020).

One module, two surfaces on the same Atlassian Cloud REST surface:
- **Jira** via ``POST /rest/api/3/search/jql`` (JQL → issues);
- **Confluence** via ``/wiki/rest/api/content/search`` (CQL → pages).

The *family* + *key* are parsed from ``source.url`` (the site lives in the URL,
so one module serves many Atlassian sites):

| URL shape | Family / what is fetched |
|---|---|
| ``<site>.atlassian.net/jira/projects/<KEY>`` (or ``/browse/<KEY>-123``) | Jira: recently-updated issues in project ``<KEY>`` |
| ``…/issues?jql=<encoded>`` (or any Jira URL carrying ``?jql=``) | Jira: the given JQL (takes precedence over the path project) |
| ``<site>.atlassian.net/wiki/spaces/<KEY>`` | Confluence: recently-modified pages in space ``<KEY>`` |
| ``…/wiki/spaces/<KEY>/pages/<id>/…`` | Confluence: that specific page (CQL ``id = <id>``), not the whole space |

Auth: HTTP **Basic** ``base64(ATLASSIAN_EMAIL:ATLASSIAN_API_TOKEN)`` — both env
vars MANDATORY. The token is sent only in the ``Authorization`` header and is
NEVER written to stdout/stderr (key-leak sentinel tests enforce this).

Test override (hermetic — never touches the network):
- ``ATLASSIAN_API_FIXTURE``: JSON file standing in for the API response. Either
  the raw response (Jira ``{"issues": [...]}`` / Confluence ``{"results": [...]}``)
  or a combined ``{"jira": {...}, "confluence": {...}}`` mapping.

Error policy (D9, spec 020): unparseable/unsupported URL, missing creds (no
fixture), HTTP/parse failure, or malformed fixture → ``verdict=error``; zero
items → ``verdict=empty``. ``facts`` is empty in v0.1.0 (mirrors Tier-1 modules).
"""

from __future__ import annotations

import base64
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
USER_AGENT = "research-framework-atlassian/0.1.0 (educational research)"

MAX_ITEMS = 20
_FETCH_LIMIT = MAX_ITEMS + 1

_SITE_RE = re.compile(r"^[a-zA-Z0-9-]+\.atlassian\.net$", re.IGNORECASE)
_ENV_EMAIL = "ATLASSIAN_EMAIL"
_ENV_TOKEN = "ATLASSIAN_API_TOKEN"


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


def _parse_source(url: str) -> tuple[str, str, str] | None:
    """Return ``(family, site, jql_or_cql)`` or ``None``.

    ``family`` is ``"jira"`` or ``"confluence"``; ``site`` is the
    ``<site>.atlassian.net`` host; the third element is the JQL (Jira) or CQL
    (Confluence) query string to execute.

    Routing is **fail-closed and lock-step with the manifest**: a recognised
    surface returns a query that matches what the URL denotes (a *page* URL maps
    to that page, not the whole space; a ``?jql=`` URL maps to that JQL, not the
    enclosing project); anything outside the documented set returns ``None`` so
    ``cmd_extract`` errors loudly instead of silently polling a broader scope.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    site = parsed.netloc
    if not _SITE_RE.match(site):
        return None
    segs = [s for s in parsed.path.split("/") if s]
    lower = [s.lower() for s in segs]

    # --- Confluence (/wiki/...) -------------------------------------------
    if lower[:1] == ["wiki"]:
        if "spaces" in lower:
            si = lower.index("spaces")
            if si + 1 < len(segs):
                space = segs[si + 1]
                # A deep page URL (/wiki/spaces/<KEY>/pages/<id>/...) denotes a
                # SPECIFIC page — watch exactly that page, do not silently widen
                # to the whole space.
                if "pages" in lower:
                    pi = lower.index("pages")
                    if pi + 1 < len(segs) and segs[pi + 1].isdigit():
                        return "confluence", site, f"id = {segs[pi + 1]}"
                    # /pages with no numeric id is a listing view → space-level.
                return (
                    "confluence",
                    site,
                    f'space = "{space}" ORDER BY lastmodified DESC',
                )
        return None

    # --- Jira -------------------------------------------------------------
    # An explicit ?jql= takes precedence over any path-derived project so that
    # issue-navigator / board URLs that carry a JQL (e.g.
    # /jira/software/c/projects/PROJ/issues?jql=… or /jira/issues/?jql=…) use the
    # JQL the user asked for rather than the enclosing project.
    qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
    jql_values = qs.get("jql")
    if jql_values and jql_values[0].strip():
        # parse_qs has already percent-decoded the value; decoding again would
        # turn a literal "+" (C++) into a space.
        return "jira", site, jql_values[0].strip()
    if "browse" in lower:
        i = lower.index("browse")
        if i + 1 < len(segs):
            key = segs[i + 1].split("-")[0]
            return "jira", site, f"project = {key} ORDER BY updated DESC"
    if "projects" in lower:
        i = lower.index("projects")
        if i + 1 < len(segs):
            key = segs[i + 1]
            return "jira", site, f"project = {key} ORDER BY updated DESC"
    return None


def _auth_header() -> str | None:
    email = os.environ.get(_ENV_EMAIL, "").strip()
    token = os.environ.get(_ENV_TOKEN, "").strip()
    if not email or not token:
        return None
    raw = f"{email}:{token}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _api_request(
    url: str, *, method: str = "GET", body: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    auth = _auth_header()
    if auth is None:
        return None
    headers = {
        "Authorization": auth,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _api_get(url: str) -> dict[str, Any] | None:
    return _api_request(url, method="GET")


def _load_fixture(family: str) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(response, error_reason)``. ``(None, None)`` when env unset."""
    fixture = os.environ.get("ATLASSIAN_API_FIXTURE", "").strip()
    if not fixture:
        return None, None
    path = Path(fixture)
    if not path.is_file():
        return None, "ATLASSIAN_API_FIXTURE path missing or unreadable"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, "malformed ATLASSIAN_API_FIXTURE JSON"
    except OSError:
        return None, "ATLASSIAN_API_FIXTURE path missing or unreadable"
    if not isinstance(data, dict):
        return None, "malformed ATLASSIAN_API_FIXTURE JSON"
    if family in data and isinstance(data[family], dict):
        return data[family], None
    return data, None


def _credentials_present() -> bool:
    return _auth_header() is not None


# Jira Cloud retired the GET /rest/api/3/search endpoint (HTTP 410 Gone) in
# 2025; the replacement is POST /rest/api/3/search/jql with a JSON body and
# token-based pagination. The response still nests issues under "issues" with
# the same field shape, so only the request build changes — parsing, identity,
# and notable rendering are untouched. We fetch a single page of _FETCH_LIMIT
# (truncation is detected from len(items) > MAX_ITEMS, as before).
_JIRA_FIELDS = ["summary", "status", "updated", "assignee", "issuetype"]


def _jira_search_request(site: str, jql: str) -> tuple[str, dict[str, Any]]:
    url = f"https://{site}/rest/api/3/search/jql"
    body: dict[str, Any] = {
        "jql": jql,
        "maxResults": _FETCH_LIMIT,
        "fields": _JIRA_FIELDS,
    }
    return url, body


def _confluence_search_url(site: str, cql: str) -> str:
    query = urllib.parse.urlencode(
        {"cql": cql, "limit": _FETCH_LIMIT, "expand": "version,space"}
    )
    return f"https://{site}/wiki/rest/api/content/search?{query}"


def _fetch(family: str, site: str, query: str) -> tuple[list[dict] | None, str | None]:
    """Return ``(items, error_reason)``. ``items is None`` ⇒ fetch/parse failure."""
    fixture_data, fixture_err = _load_fixture(family)
    if os.environ.get("ATLASSIAN_API_FIXTURE", "").strip():
        if fixture_err:
            return None, fixture_err
        response = fixture_data
    else:
        if not _credentials_present():
            return None, (
                f"missing {_ENV_EMAIL} / {_ENV_TOKEN} env vars — export both before "
                "extraction (Basic email:token auth)"
            )
        if family == "jira":
            jira_url, jira_body = _jira_search_request(site, query)
            response = _api_request(jira_url, method="POST", body=jira_body)
        else:
            response = _api_get(_confluence_search_url(site, query))
        if response is None:
            return None, f"{family} API request failed or returned malformed JSON"

    if response is None:
        return None, "no response payload"
    key = "issues" if family == "jira" else "results"
    items = response.get(key)
    if items is None:
        return None, f"{family} response missing {key!r}"
    if not isinstance(items, list):
        return None, f"{family} response {key!r} is not a list"
    return [i for i in items if isinstance(i, dict)], None


def _jira_identity(issue: dict[str, Any]) -> str:
    key = str(issue.get("key") or issue.get("id") or "")
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    updated = str(fields.get("updated") or "")
    return f"{key}|{updated}"


def _confluence_identity(page: dict[str, Any]) -> str:
    pid = str(page.get("id") or "")
    version = page.get("version") if isinstance(page.get("version"), dict) else {}
    when = str(version.get("when") or version.get("number") or "")
    return f"{pid}|{when}"


def _source_version(items: list[dict[str, Any]], family: str) -> str:
    fn = _jira_identity if family == "jira" else _confluence_identity
    ids = sorted(fn(i) for i in items)
    joined = "||".join(ids) if ids else f"empty:{family}"
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _notable_jira(items: list[dict[str, Any]], site: str) -> list[dict[str, Any]]:
    notable: list[dict[str, Any]] = []
    for issue in items[:MAX_ITEMS]:
        key = str(issue.get("key") or "(unknown)")
        fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        summary = str(fields.get("summary") or "(no summary)").strip()
        status = ""
        status_obj = fields.get("status")
        if isinstance(status_obj, dict):
            status = str(status_obj.get("name") or "").strip()
        assignee = ""
        assignee_obj = fields.get("assignee")
        if isinstance(assignee_obj, dict):
            assignee = str(assignee_obj.get("displayName") or "").strip()
        updated = str(fields.get("updated") or "").strip()
        link = f"https://{site}/browse/{key}"
        obs = (
            f"Jira {key} [{status}]: {summary}" if status else f"Jira {key}: {summary}"
        )
        if assignee:
            obs += f" (assignee: {assignee})"
        if updated:
            obs += f" — updated {updated}"
        obs += f" — {link}"
        notable.append({"observation": obs, "confidence": "high", "evidence_ref": link})
    return notable


def _notable_confluence(items: list[dict[str, Any]], site: str) -> list[dict[str, Any]]:
    notable: list[dict[str, Any]] = []
    for page in items[:MAX_ITEMS]:
        title = str(page.get("title") or "(untitled)").strip()
        version = page.get("version") if isinstance(page.get("version"), dict) else {}
        vnum = version.get("number")
        when = str(version.get("when") or "").strip()
        webui = ""
        links = page.get("_links")
        if isinstance(links, dict):
            webui = str(links.get("webui") or "").strip()
        link = f"https://{site}/wiki{webui}" if webui else f"https://{site}/wiki"
        obs = f"Confluence page: {title}"
        if vnum is not None:
            obs += f" (v{vnum})"
        if when:
            obs += f" — modified {when}"
        obs += f" — {link}"
        notable.append({"observation": obs, "confidence": "high", "evidence_ref": link})
    return notable


def _error_payload(source_id: str, reason: str) -> dict[str, Any]:
    return {
        "module": "atlassian",
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


def cmd_get_source_version(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") or {}
    url = str(source.get("url", ""))
    parsed = _parse_source(url) if url else None
    if parsed is None:
        return {"source_version": "unknown"}
    family, site, query = parsed
    items, err = _fetch(family, site, query)
    if err or items is None:
        return {"source_version": "unknown"}
    return {"source_version": _source_version(items, family)}


def cmd_extract(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") or {}
    source_id = str(payload.get("source_id") or source.get("url") or "")
    url = str(source.get("url", ""))

    if not url:
        return _error_payload(source_id, "no source.url provided")
    parsed = _parse_source(url)
    if parsed is None:
        return _error_payload(
            source_id,
            "url is not a supported atlassian source — use "
            "<site>.atlassian.net/jira/projects/<KEY>, /browse/<KEY>-N, "
            "…/issues?jql=…, /wiki/spaces/<KEY> or "
            "/wiki/spaces/<KEY>/pages/<id>/…",
        )
    family, site, query = parsed

    items, err = _fetch(family, site, query)
    if err:
        return _error_payload(source_id, err)
    if items is None:
        return _error_payload(source_id, "malformed API or fixture JSON")

    source_version = _source_version(items, family)

    if not items:
        return {
            "module": "atlassian",
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

    truncated = len(items) > MAX_ITEMS
    if truncated:
        items = items[:MAX_ITEMS]
    notable = (
        _notable_jira(items, site)
        if family == "jira"
        else _notable_confluence(items, site)
    )

    return {
        "module": "atlassian",
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
