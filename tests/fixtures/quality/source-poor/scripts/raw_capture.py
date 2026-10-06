#!/usr/bin/env python3
"""Download one external URL into the vault's raw_data/ sidecar.

``scripts/raw_capture.py <url> [--vault <path>] [--source-type <type>]``

For each URL the research agents cite, they call this script first so the
payload is mirrored locally *before* the note is written. ``vault_health.py``
then uses the mirror as its first-choice fallback when the upstream URL
breaks — Principle IX (Vault-First Citation) guarantees we can still serve
the citation even after link-rot.

Layout
------

``<vault>/raw_data/{year}/{month}/{slug}-{shorthash}.{ext}`` with a sibling
``meta.json``::

    {
      "url": "<original url>",
      "accessed": "2026-04-23T12:34:56Z",
      "source_type": "article" | "paper" | "video-transcript" | ...,
      "title": "<optional, HTML <title> when available>",
      "content_type": "text/html",
      "bytes": 12345,
      "filename": "my-article-ab12cd.html"
    }

``raw_data/`` lives INSIDE the vault (``<vault>/raw_data/``). Earlier versions
kept it as a sibling of the vault (``<vault>/../raw_data/``) mirroring the
``~/Documents/notes`` convention, but that tree is outside the Codex
``workspace-write`` sandbox when the agent runs against the vault, so every
capture failed with ``PermissionError``. Moving it inside keeps the captures
git-ignored (the vault's ``.gitignore`` still excludes it, so tracked content
is only ``data_vault/``) while making the directory writable to any agent
running with the vault as workdir.

Exit codes
----------
  0 — captured (or idempotent hit on existing mirror)
  1 — network error; note still needs the URL but the mirror failed
  2 — abort (bad args)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

_USER_AGENT = "research-framework-raw-capture/1.0"
_TIMEOUT_SECONDS = 20.0
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB cap per capture — enough for HTML/PDF,
# small enough that bulk misuse is obvious.
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, max_len: int = 60) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-") or "source"
    return slug[:max_len]


def _pick_extension(content_type: str, url: str) -> str:
    """Return a filesystem extension — prefers content-type, falls back to URL."""
    ct = content_type.split(";")[0].strip().lower()
    mapping = {
        "text/html": "html",
        "application/xhtml+xml": "html",
        "application/pdf": "pdf",
        "text/plain": "txt",
        "text/markdown": "md",
        "application/json": "json",
        "application/xml": "xml",
        "text/xml": "xml",
    }
    if ct in mapping:
        return mapping[ct]
    url_ext = Path(urllib_path(url)).suffix.lstrip(".")
    if url_ext and len(url_ext) <= 5:
        return url_ext
    return "bin"


def urllib_path(url: str) -> str:
    """Extract path portion of a URL without importing urlparse at module-top."""
    from urllib.parse import urlparse

    return urlparse(url).path or "/"


def _extract_html_title(text: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()[:200]


def capture(
    url: str, raw_data_dir: Path, source_type: str = "web"
) -> tuple[Path, dict] | None:
    """Download ``url`` into ``raw_data_dir``. Returns (payload_path, meta).

    Returns None on network failure so the caller can decide whether to fall
    back to archive.org or abort.
    """
    now = datetime.now(UTC)
    year = now.strftime("%Y")
    month = now.strftime("%m")
    target_dir = raw_data_dir / year / month
    target_dir.mkdir(parents=True, exist_ok=True)

    url_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    slug_source = urllib_path(url).rstrip("/").split("/")[-1] or "source"
    slug = _slugify(slug_source)

    meta_path = target_dir / f"{slug}-{url_hash}.meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            payload = target_dir / str(meta.get("filename", ""))
            if payload.exists():
                return payload, meta
        except Exception:
            pass

    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read(_MAX_BYTES + 1)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None

    if len(raw) > _MAX_BYTES:
        raw = raw[:_MAX_BYTES]

    ext = _pick_extension(content_type, url)
    filename = f"{slug}-{url_hash}.{ext}"
    payload_path = target_dir / filename
    payload_path.write_bytes(raw)

    title = ""
    if ext == "html":
        try:
            title = _extract_html_title(raw.decode("utf-8", errors="ignore"))
        except Exception:
            title = ""

    meta = {
        "url": url,
        "accessed": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_type": source_type,
        "title": title,
        "content_type": content_type,
        "bytes": len(raw),
        "filename": filename,
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return payload_path, meta


def _resolve_raw_data_dir(vault: Path | None) -> Path:
    """Return the raw_data/ mirror for a given vault path (``vault/raw_data``).

    When no vault is supplied, use the current working directory.

    Kept inside the vault so any agent running with the vault as its workdir
    (e.g. Codex ``--sandbox workspace-write``) can write captures without
    tripping the sandbox. The vault's ``.gitignore`` excludes ``raw_data/``
    so tracked history is still limited to ``data_vault/``.
    """
    base = vault.resolve() if vault else Path.cwd()
    return base / "raw_data"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture one URL into raw_data/.")
    parser.add_argument("url", help="URL to capture")
    parser.add_argument(
        "--vault",
        type=Path,
        default=None,
        help="Vault root (captures land at {vault}/raw_data/). "
        "Defaults to the current working directory.",
    )
    parser.add_argument(
        "--source-type",
        default="web",
        help="Free-form tag recorded in meta.json (article, paper, video, …).",
    )
    args = parser.parse_args(argv)

    if not args.url.startswith(("http://", "https://")):
        print(f"ERROR: URL must be http(s): {args.url}", file=sys.stderr)
        return 2

    raw_data_dir = _resolve_raw_data_dir(args.vault)
    raw_data_dir.mkdir(parents=True, exist_ok=True)

    result = capture(args.url, raw_data_dir, source_type=args.source_type)
    if result is None:
        print(f"FAIL  {args.url} — network error", file=sys.stderr)
        return 1

    payload, meta = result
    print(f"OK    {args.url}")
    print(f"      mirror={payload}")
    print(f"      title={meta.get('title') or '(none)'}")
    print(f"      bytes={meta.get('bytes')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
