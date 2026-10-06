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


def _sanitize_title_for_frontmatter(title: str) -> str:
    """Make a captured title safe to emit as an *unquoted* YAML scalar.

    Downstream note-writers copy ``meta.json``'s ``title`` straight into a
    ``source_urls[].title`` frontmatter field. A colon-followed-by-space
    (``": "``) or ``"::"`` in an unquoted scalar makes PyYAML raise
    "mapping values are not allowed here", corrupting the whole note's
    frontmatter (rc5 reference-vault finding: ``Exceptions :: Spring Framework``,
    ``JMX :: Spring Framework``). HTML ``<title>`` colons are virtually
    always separators, so collapsing ``" :: "`` / ``": "`` to ``" - "``
    keeps the title readable while guaranteeing YAML-safety. A colon NOT
    followed by whitespace (``"10:30"``, ``"https://"``) is left untouched —
    it's already valid in an unquoted scalar.
    """
    return re.sub(r"\s*:{1,}\s+", " - ", title)


def _extract_html_title(text: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    collapsed = re.sub(r"\s+", " ", m.group(1)).strip()
    return _sanitize_title_for_frontmatter(collapsed)[:200]


# ---------------------------------------------------------------------------
# Degenerate-content classifier (spec 050 / post-mortem 2026-05-30)
# ---------------------------------------------------------------------------
#
# When a publisher ships a JavaScript-rendered SPA (Vite/React/Next.js
# shell), a plain HTTP GET returns ~1 KB of bootstrap HTML and zero
# visible text. Codex then has no scrapeable content to ground a note
# on, and — with high reasoning effort — can spend hours reasoning
# itself in circles trying to satisfy the quality bar. The classifier
# below flags those captures so callers (and the LLM reading the CLI
# output) get an actionable signal instead of just ``bytes=1049``.
#
# Classification is conservative — we only flag the obvious case
# (JS-only shell with no visible text) and a generic "thin" bucket for
# payloads with very little body. ``rich`` is the assumed default for
# anything ambiguous; we'd rather under-flag than have codex skip a
# topic whose page happens to be terse but real.


# Vite / React / Next.js empty-root signatures we've actually seen in the wild.
_JS_SHELL_ROOT_RE = re.compile(
    r"""<div\s+id=["']?(?:root|app|__next|__nuxt|svelte)["']?\s*></div>""",
    re.IGNORECASE,
)
_SCRIPT_TAG_RE = re.compile(r"<script\b", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_BODY_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_STYLE_BODY_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")

# Tuning thresholds. ``_JS_SHELL_VISIBLE_MAX`` is intentionally generous
# (200 chars of visible text after stripping) — anything below that with
# the empty-root signature is overwhelmingly likely to be an SPA shell.
# ``_THIN_VISIBLE_MAX`` is the bar below which we record a "thin" tag
# so downstream callers can decide whether to trust the capture.
_JS_SHELL_VISIBLE_MAX = 200
_THIN_VISIBLE_MAX = 500


def _strip_html(text: str) -> str:
    """Stdlib-only HTML→visible-text reducer. Good enough for classification.

    Removes ``<script>`` and ``<style>`` bodies before stripping tags so
    minified JS doesn't inflate the visible-text count of a JS-shell.
    """
    text = _SCRIPT_BODY_RE.sub("", text)
    text = _STYLE_BODY_RE.sub("", text)
    text = _HTML_TAG_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def classify_payload(raw: bytes, content_type: str) -> str:
    """Return one of ``rich`` | ``thin`` | ``js_shell`` | ``binary``.

    Heuristic — see module docstring above for the rationale and tuning.
    """
    ct = (content_type or "").split(";")[0].strip().lower()
    is_html = ct in ("text/html", "application/xhtml+xml") or (
        ct == "" and b"<html" in raw.lower()[:512]
    )
    if not is_html:
        return "binary"
    try:
        text = raw.decode("utf-8", errors="ignore")
    except Exception:
        return "binary"

    visible = _strip_html(text)

    if (
        _JS_SHELL_ROOT_RE.search(text)
        and _SCRIPT_TAG_RE.search(text)
        and len(visible) < _JS_SHELL_VISIBLE_MAX
    ):
        return "js_shell"
    if len(visible) < _THIN_VISIBLE_MAX:
        return "thin"
    return "rich"


def capture(
    url: str, raw_data_dir: Path, source_type: str = "web"
) -> tuple[Path, dict] | None:
    """Download ``url`` into ``raw_data_dir``. Returns (payload_path, meta).

    Returns None on network failure so the caller can decide whether to fall
    back to archive.org or abort. Raises ValueError for a non-http(s) URL:
    ``urlopen`` would read a ``file://`` URL off local disk, and batch callers
    pass URLs taken from agent-written notes.
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"URL must be http(s): {url}")
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

    payload_kind = classify_payload(raw, content_type)

    meta = {
        "url": url,
        "accessed": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_type": source_type,
        "title": title,
        "content_type": content_type,
        "bytes": len(raw),
        "filename": filename,
        # ``payload_kind`` lets downstream code (and the LLM reading the
        # capture log) distinguish a real fetch from a JS-only SPA shell
        # that has no scrapeable content. See spec 050.
        "payload_kind": payload_kind,
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
    kind = meta.get("payload_kind", "rich")
    # Status word: rich = normal capture; js_shell = SPA bootstrap with
    # no usable text (codex should try an alternative source); thin =
    # real but very short body; binary = non-HTML mirror. The status
    # word is the first thing on the line so it's easy to grep for and
    # easy for an LLM reading the log to react to.
    status = {
        "rich": "OK",
        "thin": "THIN",
        "js_shell": "JS_SHELL",
        "binary": "OK",
    }.get(kind, "OK")
    print(f"{status:<8}{args.url}")
    print(f"      mirror={payload}")
    print(f"      title={meta.get('title') or '(none)'}")
    print(f"      bytes={meta.get('bytes')} payload_kind={kind}")
    if kind == "js_shell":
        # Emit a clear, single-line warning to stderr so the LLM's tool
        # output picks it up and the user grep'ing the cycle log sees
        # exactly why this URL didn't yield usable content.
        print(
            f"WARN  {args.url} returned a JavaScript-only SPA shell "
            f"({meta.get('bytes')} bytes, no visible text). The mirror "
            "exists but has no scrapeable content — try an alternative "
            "source (cached copy, archive.org, official PDF).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
