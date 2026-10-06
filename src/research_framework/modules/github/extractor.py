#!/usr/bin/env python3
"""GitHub module extractor — stdin/stdout JSON contract (spec 020).

Lifecycle:
1. Read JSON request from stdin.
2. Resolve ``org/repo`` + a *surface* (pulls / issues / releases) from
   ``source.url`` (``github.com/<org>/<repo>[/<surface>]``).
3. Fetch recent items via the ``gh`` CLI (``gh api repos/<org>/<repo>/...``),
   or from ``GH_FIXTURE`` for hermetic tests.
4. Emit a ``SignalPayload`` on stdout with one ``notable[]`` entry per item.

Handles ONE source URL per invocation — the framework drives the loop across
``sources.yaml`` ``github_sources`` entries.

Auth model: the host ``gh`` CLI **session** (``gh auth login``). There is NO
env API key (contrast ``oreilly``); ``preflight.py`` runs ``gh auth status``
and fails the cycle closed when unauthenticated. This module is deliberately
distinct from ``code`` — ``code`` reads *local working copies* (filesystem
paths), ``github`` reads *remote GitHub surfaces* (URLs). See the spec-020
amendment (Session 2026-06-08).

Test overrides (hermetic — never touch the network):
- ``GH_BIN``: path to the ``gh`` binary (default ``gh``).
- ``GH_FIXTURE``: path to a JSON file standing in for the ``gh api`` response.
  Shape: either a bare list of items, or a mapping ``{surface: [items]}``.

Error policy (D9, spec 020):
- URL not matching ``github.com/<org>/<repo>`` → ``verdict=error``.
- ``gh`` missing / not authenticated / non-zero exit (no fixture) → ``verdict=error``.
- Missing / unreadable / malformed ``GH_FIXTURE`` → ``verdict=error``.
- Zero items → ``verdict=empty``.

``facts`` is intentionally empty in v0.1.0 (mirrors the Tier-1 modules).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BRIDGE_VERSION = "0.0.0"

MAX_ITEMS = 20
MAX_NOTABLE_ITEMS = 20
# Fetch ONE extra item beyond MAX_ITEMS so the boundary case (source has
# exactly MAX_ITEMS results) is not falsely reported as ``truncated=True``.
_FETCH_LIMIT = MAX_ITEMS + 1

_DEFAULT_SURFACE = "releases"

_GITHUB_HOST_RE = re.compile(r"^(www\.)?github\.com$", re.IGNORECASE)


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


def _parse_repo(url: str) -> tuple[str, str, str] | None:
    """Return ``(org, repo, surface)`` for a github.com URL, else ``None``."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    if not _GITHUB_HOST_RE.match(parsed.netloc):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None
    org = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    surface = _DEFAULT_SURFACE
    if len(parts) >= 3:
        seg = parts[2].lower()
        if seg in ("pull", "pulls"):
            surface = "pulls"
        elif seg in ("issue", "issues"):
            surface = "issues"
        elif seg in ("release", "releases", "tags"):
            surface = "releases"
        else:
            # Unknown surface segment (e.g. /blob, /tree, /commit) — NOT a
            # supported source. Returning None keeps the extractor in lock-step
            # with the (tightened) manifest trigger so a mis-pasted file URL
            # errors loudly instead of silently polling releases.
            return None
    return org, repo, surface


def _api_endpoint(org: str, repo: str, surface: str) -> str:
    base = f"repos/{org}/{repo}/{surface}"
    if surface == "releases":
        return f"{base}?per_page={_FETCH_LIMIT}"
    return f"{base}?state=all&sort=updated&direction=desc&per_page={_FETCH_LIMIT}"


def _gh_bin() -> str:
    return os.environ.get("GH_BIN", "").strip() or "gh"


def _call_gh_api(endpoint: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Run ``gh api <endpoint>``; return ``(items, error_reason)``."""
    try:
        proc = subprocess.run(
            [_gh_bin(), "api", "-H", "Accept: application/vnd.github+json", endpoint],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError:
        return None, "gh CLI not found on PATH — install GitHub CLI and `gh auth login`"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"gh invocation failed: {exc}"
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        hint = ""
        if "auth" in stderr.lower() or "logged" in stderr.lower():
            hint = " — run `gh auth login`"
        return None, f"gh api exited {proc.returncode}{hint}"
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, "gh api returned malformed JSON"
    if not isinstance(data, list):
        return None, "gh api response was not a JSON array"
    return data, None


def _load_fixture(surface: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Return ``(items, error_reason)``. ``(None, None)`` when env unset."""
    fixture = os.environ.get("GH_FIXTURE", "").strip()
    if not fixture:
        return None, None
    path = Path(fixture)
    if not path.is_file():
        return None, "GH_FIXTURE path missing or unreadable"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, "malformed GH_FIXTURE JSON"
    except OSError:
        return None, "GH_FIXTURE path missing or unreadable"
    if isinstance(data, dict):
        if surface not in data:
            # Fail closed: a typo'd surface key (e.g. "issue" vs "issues")
            # must not silently degrade to an empty verdict.
            return None, f"GH_FIXTURE has no '{surface}' surface key"
        items = data.get(surface)
        if not isinstance(items, list):
            return None, f"GH_FIXTURE[{surface!r}] is not a list"
        return [i for i in items if isinstance(i, dict)], None
    if isinstance(data, list):
        return [i for i in data if isinstance(i, dict)], None
    return None, "malformed GH_FIXTURE JSON (expected list or mapping)"


def _fetch_items(
    org: str, repo: str, surface: str
) -> tuple[list[dict[str, Any]] | None, str | None]:
    items, err = _load_fixture(surface)
    if os.environ.get("GH_FIXTURE", "").strip():
        return items, err
    return _call_gh_api(_api_endpoint(org, repo, surface))


def _normalize_items(items: list[dict[str, Any]], surface: str) -> list[dict[str, Any]]:
    """Surface-specific normalization applied BEFORE hashing or rendering.

    The ``/issues`` endpoint also returns pull requests (they carry a
    ``pull_request`` key); drop those so the ``issues`` surface is genuinely
    issues-only. Applied in BOTH ``cmd_extract`` and ``cmd_get_source_version``
    so the cache-probe version always predicts the version ``extract`` emits.
    """
    if surface == "issues":
        return [i for i in items if "pull_request" not in i]
    return items


def _item_identity(item: dict[str, Any], surface: str) -> str:
    if surface == "releases":
        key = item.get("tag_name") or item.get("id") or item.get("name") or ""
        stamp = item.get("published_at") or item.get("created_at") or ""
    else:
        key = item.get("number") or item.get("id") or ""
        stamp = item.get("updated_at") or item.get("created_at") or ""
    return f"{key}|{stamp}"


def _source_version_from_items(items: list[dict[str, Any]], surface: str) -> str:
    ids = sorted(_item_identity(i, surface) for i in items)
    joined = "||".join(ids) if ids else f"empty:{surface}"
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _notable_from_items(
    items: list[dict[str, Any]], surface: str
) -> list[dict[str, Any]]:
    notable: list[dict[str, Any]] = []
    for item in items[:MAX_NOTABLE_ITEMS]:
        url = str(item.get("html_url") or item.get("url") or "").strip()
        evidence = url or f"github:{surface}"
        if surface == "releases":
            tag = str(item.get("tag_name") or "").strip()
            name = str(item.get("name") or tag or "(untitled release)").strip()
            when = str(item.get("published_at") or item.get("created_at") or "").strip()
            obs = f"GitHub release {tag}: {name}".strip()
            if when:
                obs += f" ({when})"
        else:
            label = "PR" if surface == "pulls" else "Issue"
            number = item.get("number")
            title = str(item.get("title") or "(untitled)").strip()
            state = str(item.get("state") or "").strip()
            author = ""
            user = item.get("user")
            if isinstance(user, dict):
                author = str(user.get("login") or "").strip()
            when = str(item.get("updated_at") or item.get("created_at") or "").strip()
            head = (
                f"GitHub {label} #{number}" if number is not None else f"GitHub {label}"
            )
            obs = f"{head} [{state}]: {title}" if state else f"{head}: {title}"
            if author:
                obs += f" by {author}"
            if when:
                obs += f" ({when})"
        if url:
            obs += f" — {url}"
        notable.append(
            {
                "observation": obs,
                "confidence": "high",
                "evidence_ref": evidence,
            }
        )
    return notable


def _error_payload(source_id: str, reason: str) -> dict[str, Any]:
    return {
        "module": "github",
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
    parsed = _parse_repo(url) if url else None
    if parsed is None:
        return {"source_version": "unknown"}
    org, repo, surface = parsed
    items, err = _fetch_items(org, repo, surface)
    if err or items is None:
        return {"source_version": "unknown"}
    items = _normalize_items(items, surface)
    return {"source_version": _source_version_from_items(items, surface)}


def cmd_extract(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") or {}
    source_id = str(payload.get("source_id") or source.get("url") or "")
    url = str(source.get("url", ""))

    if not url:
        return _error_payload(source_id, "no source.url provided")

    parsed = _parse_repo(url)
    if parsed is None:
        return _error_payload(
            source_id,
            "url is not a supported github.com source — use the repo root or "
            "a /pulls, /issues or /releases path",
        )
    org, repo, surface = parsed

    items, err = _fetch_items(org, repo, surface)
    if err:
        return _error_payload(source_id, err)
    if items is None:
        return _error_payload(source_id, "malformed gh response or fixture JSON")

    items = _normalize_items(items, surface)
    source_version = _source_version_from_items(items, surface)

    if not items:
        return {
            "module": "github",
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
    notable = _notable_from_items(items, surface)

    return {
        "module": "github",
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
