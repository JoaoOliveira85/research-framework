"""Archive processor — move aged raw items to <vault>/_pipeline/archive/<YYYY-MM>/.

Ported from feeds-vault/scripts/archive.py with the path conventions adapted to the
framework's shared I/O contract:

  <vault>/_pipeline/raw/<source_kind>/<id>.md   →  input
  <vault>/_pipeline/archive/<YYYY-MM>/<source_kind>/<id>.md  →  output

The original feeds-vault script archived URLs fetched from the network.  This
framework version archives *raw pipeline items* that have aged past
``after_days``.  The URL-fetching utility (``archive_url``) is preserved as a
standalone helper for callers that need it.

Python API:
    from research_framework.processors.archive import archive, ArchiveResult
    result = archive(vault_path, after_days=90)

CLI:
    python -m research_framework.processors.archive <vault> [--after-days N] [--dry-run]
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ._common import (
    archive_dir,
    parse_frontmatter,
    processor_config,
    raw_dir,
    validate_raw_item,
)

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArchiveResult:
    files_processed: int
    files_archived: int
    files_skipped: int
    errors: tuple[str, ...]


# ---------------------------------------------------------------------------
# URL archiving helpers (preserved from feeds-vault/scripts/archive.py)
# ---------------------------------------------------------------------------

USER_AGENT = "research-framework-archiver/1.0 (educational research; archival)"


def _slug_from_url(url: str, maxlen: int = 80) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        path = "index"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", path)
    slug = slug.strip("-")
    return slug[:maxlen] if slug else "index"


def _domain_from_url(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _strip_html(content: str) -> str:
    """Strip HTML tags and decode entities (stdlib-only)."""
    text = html.unescape(content)
    text = re.sub(
        r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(
        r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]*\n", "\n\n", text)
    lines = [line.strip() for line in text.splitlines()]
    result = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                result.append("")
            prev_blank = True
        else:
            result.append(line)
            prev_blank = False
    return "\n".join(result).strip()


def _extract_title(html_content: str) -> str:
    match = re.search(
        r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL
    )
    if match:
        return html.unescape(match.group(1)).strip()
    return ""


def archive_url(url: str, base_dir: Path) -> Path | None:
    """Archive raw text from a URL to _pipeline/archive/web/<YYYY-MM>/.

    Idempotent: if the file already exists, returns its path without re-fetching.
    Never raises — failures are logged to stderr.
    """
    try:
        domain = _domain_from_url(url)
        slug = _slug_from_url(url)
        today = datetime.now()
        date_str = today.strftime("%Y-%m-%d")
        month_dir = today.strftime("%Y-%m")

        dest_dir = base_dir / "_pipeline" / "archive" / "web" / month_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{domain}--{slug}--{date_str}.txt"
        archive_path = dest_dir / filename

        if archive_path.exists():
            return archive_path

        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            try:
                content = raw.decode(charset)
            except (UnicodeDecodeError, LookupError):
                content = raw.decode("utf-8", errors="replace")

        title = _extract_title(content)
        plain_text = _strip_html(content)
        fetched_str = today.strftime("%Y-%m-%d %H:%M")
        header = f"URL: {url}\nTitle: {title}\nFetched: {fetched_str}\n---\n\n"
        archive_path.write_text(header + plain_text, encoding="utf-8")
        return archive_path

    except Exception as exc:
        print(f"[archive] Failed to archive {url}: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Raw-item age check
# ---------------------------------------------------------------------------


_MONTH_RE = re.compile(r"\d{4}-\d{2}")


def _item_age_days(fm: dict[str, str], path: Path) -> float:
    """Return age in days from collected_at frontmatter or file mtime."""
    collected_at = fm.get("collected_at", "")
    if collected_at:
        try:
            # Accept "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
            dt_str = collected_at[:10]
            collected_dt = datetime.strptime(dt_str, "%Y-%m-%d").replace(tzinfo=UTC)
            now = datetime.now(tz=UTC)
            return (now - collected_dt).total_seconds() / 86400
        except ValueError:
            pass
    # Fallback: file modification time
    mtime = path.stat().st_mtime
    age = datetime.now().timestamp() - mtime
    return age / 86400


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def archive(
    vault: Path,
    *,
    after_days: int | None = None,
    dry_run: bool = False,
    source_types: list[str] | None = None,
    spec_processors: dict[str, Any] | None = None,
) -> ArchiveResult:
    """Move raw items older than ``after_days`` to the archive directory.

    Source:  <vault>/_pipeline/raw/<source_kind>/<id>.md
    Dest:    <vault>/_pipeline/archive/<YYYY-MM>/<source_kind>/<id>.md

    Idempotent — items already present in the archive are not double-moved.

    Args:
        vault: Root directory of the vault.
        after_days: Age threshold in days. ``None`` defers to spec config,
            then to 90.
        dry_run: Discover candidates but move nothing.
        source_types: Source sub-directories to scan. Defaults to all found.
        spec_processors: Optional processors section from SpecConfig.

    Returns:
        ArchiveResult with counts and any errors.
    """
    cfg = processor_config(spec_processors, "archive")
    # Explicit argument > spec config > default. ``cfg`` always carries the
    # PROCESSOR_DEFAULTS key, so ``cfg.get(key, param)`` discarded the argument.
    if after_days is None:
        after_days = cfg.get("after_days", 90)
    after_days = int(after_days)

    raw_root = raw_dir(vault)
    if not raw_root.exists():
        return ArchiveResult(
            files_processed=0,
            files_archived=0,
            files_skipped=0,
            errors=(),
        )

    if source_types is None:
        source_types = [d.name for d in sorted(raw_root.iterdir()) if d.is_dir()]

    errors: list[str] = []
    files_processed = 0
    files_archived = 0
    files_skipped = 0

    for source_kind in source_types:
        sub = raw_root / source_kind
        if not sub.exists():
            continue
        for raw_path in sorted(sub.glob("*.md")):
            files_processed += 1
            try:
                text = raw_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                errors.append(f"{raw_path}: read error: {exc}")
                continue

            fm, _body = parse_frontmatter(text)

            # Validate input boundary.
            errs = validate_raw_item(fm, raw_path)
            errors.extend(errs)

            age = _item_age_days(fm, raw_path)
            if age < after_days:
                files_skipped += 1
                continue

            # Determine archive destination.
            # Only a real "YYYY-MM" may name the directory: the value comes from
            # item frontmatter, and "../../x" or "/tmp/x" would move the item
            # outside the archive.
            month = str(fm.get("collected_at", "") or "")[:7]
            if not _MONTH_RE.fullmatch(month):
                month = datetime.now().strftime("%Y-%m")

            dest_dir = archive_dir(vault) / month / source_kind
            dest_path = dest_dir / raw_path.name

            if dest_path.exists():
                # Already archived — remove the raw copy to keep things tidy.
                if not dry_run:
                    raw_path.unlink()
                files_archived += 1
                continue

            if not dry_run:
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(raw_path), str(dest_path))
            files_archived += 1

    return ArchiveResult(
        files_processed=files_processed,
        files_archived=files_archived,
        files_skipped=files_skipped,
        errors=tuple(errors),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli_main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Archive aged raw pipeline items")
    ap.add_argument("vault", type=Path, help="Vault root directory")
    ap.add_argument(
        "--after-days",
        type=int,
        default=None,
        help="Archive items older than this many days (default: spec config, else 90)",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Report targets without moving"
    )
    ap.add_argument("--source-type", help="Process only one source type")
    args = ap.parse_args(argv)

    source_types = [args.source_type] if args.source_type else None
    result = archive(
        args.vault,
        after_days=args.after_days,
        dry_run=args.dry_run,
        source_types=source_types,
    )

    print(f"Scanned:  {result.files_processed}")
    print(f"Archived: {result.files_archived}")
    print(f"Skipped (too recent): {result.files_skipped}")
    if result.errors:
        print(f"Errors ({len(result.errors)}):", file=sys.stderr)
        for e in result.errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
