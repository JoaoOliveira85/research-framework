"""Pre-processor for the extract pipeline (Tier 0 — no AI).

Reads raw files from <vault>/_pipeline/raw/, strips boilerplate, deduplicates,
detects non-English content, and saves cleaned excerpts to
<vault>/_pipeline/extracted/excerpts/<source-type>/<filename>.txt.

Ported faithfully from feeds-vault/scripts/preprocess.py; path conventions adapted
to accept a vault root instead of assuming a hard-coded BASE directory.

Python API:
    from research_framework.processors.preprocess import preprocess, PreprocessResult
    result = preprocess(vault_path, dedupe_strategy="content_hash")

CLI:
    python -m research_framework.processors.preprocess <vault> [options]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._common import (
    content_hash,
    excerpts_dir,
    processor_config,
    raw_dir,
    validate_raw_item,
)

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreprocessResult:
    files_processed: int
    files_skipped: int
    non_english: int
    duplicates_removed: int
    errors: tuple[str, ...]


# ---------------------------------------------------------------------------
# Content cleaning helpers (ported verbatim from feeds-vault/scripts/preprocess.py)
# ---------------------------------------------------------------------------


def _strip_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Remove YAML frontmatter and return (metadata_dict, body)."""
    metadata: dict[str, str] = {}
    if not text.startswith("---"):
        return metadata, text
    end = text.find("\n---", 3)
    if end == -1:
        return metadata, text
    fm_block = text[3:end].strip()
    body = text[end + 4 :].strip()
    for line in fm_block.splitlines():
        line = line.strip()
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            metadata[key] = val
    return metadata, body


def _strip_reddit_metadata(text: str) -> str:
    """Strip Reddit per-comment metadata lines."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^\*\*u/\S+\*\*", stripped):
            continue
        if re.match(r"^\*\*Score:\*\*\s", stripped):
            continue
        if re.match(r"^\*\*(Score|Comments|By|Date|Link|External):\*\*", stripped):
            continue
        lines.append(line)
    return "\n".join(lines)


def _strip_srt_artifacts(text: str) -> str:
    """Strip any remaining SRT timestamps, sequence numbers, and HTML tags."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if re.match(r"^\d+$", stripped):
            continue
        if re.match(r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->", stripped):
            continue
        cleaned = re.sub(r"<[^>]+>", "", line)
        lines.append(cleaned)
    return "\n".join(lines)


def _deduplicate_consecutive(text: str) -> str:
    """Remove consecutive identical lines."""
    lines = text.splitlines()
    deduped = []
    for line in lines:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return "\n".join(deduped)


def _is_english(text: str, sample_size: int = 500) -> bool:
    """Check if text is likely English by Latin script ratio in first N chars."""
    sample = text[:sample_size]
    alpha_chars = [c for c in sample if c.isalpha()]
    if len(alpha_chars) < 20:
        return True
    latin = sum(1 for c in alpha_chars if c.isascii())
    return (latin / len(alpha_chars)) >= 0.70


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------


def _preprocess_file(raw_file: Path, vault: Path) -> tuple[Path, int, bool]:
    """Pre-process a single raw file. Returns (excerpt_path, token_estimate, is_english)."""
    source_type = raw_file.parent.name
    raw_text = raw_file.read_text(encoding="utf-8", errors="replace")

    metadata, body = _strip_frontmatter(raw_text)
    title = metadata.get("title", raw_file.stem)
    source_url = metadata.get("source_url", metadata.get("original_url", ""))

    if source_type == "reddit":
        body = _strip_reddit_metadata(body)
    body = _strip_srt_artifacts(body)
    body = _deduplicate_consecutive(body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    english = _is_english(body)

    header_lines: list[str] = []
    if source_url:
        header_lines.append(f"URL: {source_url}")
    header_lines.append(f"Title: {title}")
    header_lines.append("---")
    header_lines.append("")
    if not english:
        header_lines.append("(Non-English content — skipped for AI processing)")
        header_lines.append("")

    excerpt_text = "\n".join(header_lines) + body
    exc_dir = excerpts_dir(vault) / source_type
    exc_dir.mkdir(parents=True, exist_ok=True)
    excerpt_path = exc_dir / f"{raw_file.stem}.txt"
    excerpt_path.write_text(excerpt_text, encoding="utf-8")

    tokens = _estimate_tokens(body)
    return excerpt_path, tokens, english


def _is_already_processed(raw_file: Path, vault: Path, force: bool = False) -> bool:
    if force:
        return False
    source_type = raw_file.parent.name
    excerpt_path = excerpts_dir(vault) / source_type / f"{raw_file.stem}.txt"
    return excerpt_path.exists()


def _discover_raw_files(vault: Path, source_types: list[str]) -> list[Path]:
    files = []
    for st in source_types:
        sub = raw_dir(vault) / st
        if sub.exists():
            files.extend(sorted(sub.glob("*.md")))
    return files


def _dedupe_by_content_hash(raw_files: list[Path]) -> tuple[list[Path], int]:
    """Filter duplicate raw files by content hash. Keeps first seen."""
    seen: set[str] = set()
    kept: list[Path] = []
    dupes = 0
    for f in raw_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            kept.append(f)
            continue
        _, body = _strip_frontmatter(text)
        h = content_hash(body)
        if h in seen:
            dupes += 1
        else:
            seen.add(h)
            kept.append(f)
    return kept, dupes


def _dedupe_by_url(raw_files: list[Path]) -> tuple[list[Path], int]:
    """Filter duplicate raw files by original_url / source_url. Keeps first seen."""
    seen: set[str] = set()
    kept: list[Path] = []
    dupes = 0
    for f in raw_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            kept.append(f)
            continue
        fm, _ = _strip_frontmatter(text)
        url = fm.get("original_url", fm.get("source_url", ""))
        if not url:
            kept.append(f)
            continue
        if url in seen:
            dupes += 1
        else:
            seen.add(url)
            kept.append(f)
    return kept, dupes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def preprocess(
    vault: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    source_types: list[str] | None = None,
    dedupe_strategy: str | None = None,
    spec_processors: dict[str, Any] | None = None,
) -> PreprocessResult:
    """Pre-process raw pipeline items for a vault.

    Reads from <vault>/_pipeline/raw/<source_kind>/*.md, writes cleaned
    excerpts to <vault>/_pipeline/extracted/excerpts/<source_kind>/*.txt.

    Args:
        vault: Root directory of the vault.
        force: Re-process files that already have excerpts.
        dry_run: Discover targets but write nothing.
        source_types: Source sub-directories to scan. Defaults to all found.
        dedupe_strategy: "content_hash" or "url". ``None`` defers to spec
            config, then to "content_hash".
        spec_processors: Optional processors section from SpecConfig.

    Returns:
        PreprocessResult with counts and any errors.
    """
    cfg = processor_config(spec_processors, "preprocess")
    if source_types is None:
        source_types = cfg.get("source_types", ["youtube", "reddit", "web"])
        # Fall back to dynamically discovering whatever source_kinds exist on disk.
        raw_root = raw_dir(vault)
        if raw_root.exists():
            found = [d.name for d in sorted(raw_root.iterdir()) if d.is_dir()]
            if found:
                source_types = found
    # Explicit argument > spec config > default (``cfg`` always carries the
    # PROCESSOR_DEFAULTS key, so ``cfg.get(key, param)`` discarded the argument).
    if dedupe_strategy is None:
        dedupe_strategy = cfg.get("dedupe_strategy", "content_hash")

    all_raw = _discover_raw_files(vault, source_types)

    # Validate each raw item's frontmatter (input boundary).
    errors: list[str] = []
    for f in all_raw:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{f}: read error: {exc}")
            continue
        fm, _ = _strip_frontmatter(text)
        errs = validate_raw_item(fm, f)
        errors.extend(errs)

    # Deduplication.
    if dedupe_strategy == "url":
        unique_raw, dupes_removed = _dedupe_by_url(all_raw)
    else:
        unique_raw, dupes_removed = _dedupe_by_content_hash(all_raw)

    to_process = [f for f in unique_raw if not _is_already_processed(f, vault, force)]
    to_skip = len(unique_raw) - len(to_process)

    if dry_run or not to_process:
        return PreprocessResult(
            files_processed=0,
            files_skipped=to_skip,
            non_english=0,
            duplicates_removed=dupes_removed,
            errors=tuple(errors),
        )

    processed = 0
    non_english = 0
    for f in to_process:
        try:
            _, _tokens, english = _preprocess_file(f, vault)
            processed += 1
            if not english:
                non_english += 1
        except Exception as exc:
            errors.append(f"{f}: {exc}")

    return PreprocessResult(
        files_processed=processed,
        files_skipped=to_skip,
        non_english=non_english,
        duplicates_removed=dupes_removed,
        errors=tuple(errors),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli_main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Pre-process raw pipeline files (Tier 0 — no AI)"
    )
    ap.add_argument("vault", type=Path, help="Vault root directory")
    ap.add_argument("--force", action="store_true", help="Re-process all files")
    ap.add_argument(
        "--dry-run", action="store_true", help="List targets without writing"
    )
    ap.add_argument("--source-type", help="Process only one source type")
    ap.add_argument(
        "--dedupe-strategy",
        choices=["content_hash", "url"],
        default=None,
        help="Deduplication strategy (default: spec config, else content_hash)",
    )
    args = ap.parse_args(argv)

    source_types = [args.source_type] if args.source_type else None
    result = preprocess(
        args.vault,
        force=args.force,
        dry_run=args.dry_run,
        source_types=source_types,
        dedupe_strategy=args.dedupe_strategy,
    )

    print(f"Processed:         {result.files_processed}")
    print(f"Skipped (cached):  {result.files_skipped}")
    print(f"Non-English:       {result.non_english}")
    print(f"Duplicates removed:{result.duplicates_removed}")
    if result.errors:
        print(f"Errors ({len(result.errors)}):", file=sys.stderr)
        for e in result.errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
