#!/usr/bin/env python3
"""Batch raw URL capture for new-note source_urls (spec 038 FR-006/007).

Enumerates in-scope vault notes via ``vault/frontmatter.py``, de-dups URLs by
sha256, and calls the shipped ``raw_capture.capture()`` primitive per unique URL.
Writes an index manifest at ``raw_data/captures/<YYYY-MM-DD>/manifest.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_CAPTURE = None


def _ensure_import_paths() -> None:
    root = Path(__file__).resolve().parents[1]
    src = str(root / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def _load_capture():
    global _CAPTURE
    if _CAPTURE is not None:
        return _CAPTURE
    import importlib.util

    rc_path = Path(__file__).resolve().parent / "raw_capture.py"
    spec = importlib.util.spec_from_file_location("raw_capture", rc_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load raw_capture from {rc_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _CAPTURE = mod.capture
    return _CAPTURE


def url_digest(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _note_paths(vault: Path) -> list[Path]:
    skip = {"_pipeline", "_templates", ".git", "raw_data", "modules"}
    out: list[Path] = []
    for path in vault.rglob("*.md"):
        if any(part in skip for part in path.relative_to(vault).parts):
            continue
        out.append(path)
    return sorted(out)


def _extract_urls(frontmatter: dict[str, Any]) -> list[str]:
    raw = frontmatter.get("source_urls") or []
    urls: list[str] = []
    if not isinstance(raw, list):
        return urls
    for item in raw:
        if isinstance(item, str) and item.strip():
            urls.append(item.strip())
        elif isinstance(item, dict):
            url = item.get("url")
            if url and str(url).strip():
                urls.append(str(url).strip())
    return urls


def collect_urls(
    vault: Path,
    *,
    since: datetime | None = None,
    cycle: int | None = None,
) -> dict[str, list[str]]:
    """Return ``{url: [relative note paths]}`` for in-scope notes."""
    from research_framework.vault.frontmatter import (
        FrontmatterParseError,
        parse_frontmatter,
    )

    vault = vault.resolve()
    if since is not None and since.tzinfo is None:
        # A date-only or offset-less --since parses naive; note mtimes are
        # aware, and comparing the two raises TypeError. Read it as UTC.
        since = since.replace(tzinfo=UTC)
    by_url: dict[str, list[str]] = defaultdict(list)
    for path in _note_paths(vault):
        if since is not None:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            if mtime < since:
                continue
        try:
            fm, _body = parse_frontmatter(path)
        except FrontmatterParseError:
            raise
        if cycle is not None:
            lifecycle = (
                fm.get("lifecycle") if isinstance(fm.get("lifecycle"), dict) else {}
            )
            created = lifecycle.get("created_at_cycle")
            if created is None or int(created) != cycle:
                continue
        rel = str(path.relative_to(vault))
        for url in _extract_urls(fm):
            if rel not in by_url[url]:
                by_url[url].append(rel)
    return dict(by_url)


def manifest_path(vault: Path, *, run_date: datetime | None = None) -> Path:
    when = run_date or datetime.now(UTC)
    day = when.strftime("%Y-%m-%d")
    return vault / "raw_data" / "captures" / day / "manifest.json"


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_manifest(path: Path, data: dict[str, Any]) -> None:
    from research_framework.pipeline.atomic_write import write_json

    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, data)


def run_batch(
    vault: Path,
    *,
    cycle: int | None = None,
    since: datetime | None = None,
    dry_run: bool = False,
    capture_fn: Callable[..., Any] | None = None,
    run_date: datetime | None = None,
) -> tuple[int, dict[str, Any]]:
    """Execute the batch. Returns ``(exit_code, manifest_dict)``."""
    vault = vault.resolve()
    if not vault.is_dir():
        return 2, {}
    when = run_date or datetime.now(UTC)
    mpath = manifest_path(vault, run_date=when)
    existing = _load_manifest(mpath)
    since_effective = since
    if since_effective is None and cycle is None:
        generated = existing.get("generated_at")
        if isinstance(generated, str):
            try:
                since_effective = datetime.fromisoformat(
                    generated.replace("Z", "+00:00")
                )
            except ValueError:
                since_effective = None

    try:
        url_map = collect_urls(vault, since=since_effective, cycle=cycle)
    except Exception as exc:
        print(f"raw_capture_batch: could not collect note URLs: {exc}", file=sys.stderr)
        return 2, {}

    for _digest, entry in (existing.get("captures") or {}).items():
        if not isinstance(entry, dict):
            continue
        if entry.get("status") not in ("FAILED", "PENDING"):
            continue
        url = entry.get("url")
        if not url:
            continue
        notes = [str(n) for n in (entry.get("citing_notes") or []) if n]
        url_map.setdefault(str(url), notes)

    capture = capture_fn or _load_capture()
    raw_data_dir = vault / "raw_data"

    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "cycle": cycle,
        "generated_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "captures": dict(existing.get("captures") or {}),
    }

    if dry_run:
        return 0, manifest

    captures: dict[str, Any] = manifest["captures"]
    for url, citing_notes in sorted(url_map.items()):
        digest = url_digest(url)
        prior = captures.get(digest)
        if isinstance(prior, dict) and prior.get("status") == "OK":
            merged_notes = list(prior.get("citing_notes") or [])
            for note in citing_notes:
                if note not in merged_notes:
                    merged_notes.append(note)
            prior["citing_notes"] = merged_notes
            captures[digest] = prior
            _write_manifest(mpath, manifest)
            continue

        entry: dict[str, Any] = {
            "url": url,
            "status": "PENDING",
            "captured_path": None,
            "captured_at": None,
            "payload_kind": None,
            "citing_notes": list(citing_notes),
        }
        captures[digest] = entry
        _write_manifest(mpath, manifest)

        try:
            result = capture(url, raw_data_dir)
        except Exception as exc:
            entry["status"] = "FAILED"
            entry["error"] = str(exc)
            captures[digest] = entry
            _write_manifest(mpath, manifest)
            continue

        if result is None:
            entry["status"] = "FAILED"
            entry["error"] = "network error"
            captures[digest] = entry
            _write_manifest(mpath, manifest)
            continue

        payload_path, meta = result
        rel_path = str(payload_path.relative_to(vault))
        entry["status"] = "OK"
        entry["captured_path"] = rel_path
        entry["captured_at"] = when.strftime("%Y-%m-%dT%H:%M:%SZ")
        entry["payload_kind"] = meta.get("payload_kind")
        entry.pop("error", None)
        captures[digest] = entry
        _write_manifest(mpath, manifest)

    return 0, manifest


def main(argv: list[str] | None = None) -> int:
    _ensure_import_paths()
    parser = argparse.ArgumentParser(description="Batch-capture note source_urls.")
    parser.add_argument("--vault", type=Path, required=True, help="Vault root path")
    parser.add_argument("--cycle", type=int, default=None, help="Scope to note cycle")
    parser.add_argument(
        "--since",
        default=None,
        help="ISO8601 timestamp — only notes modified at/after this time",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan captures without writing manifest or bytes",
    )
    args = parser.parse_args(argv)

    since_dt: datetime | None = None
    if args.since:
        try:
            since_dt = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
        except ValueError:
            print(
                f"raw_capture_batch: --since {args.since!r} is not ISO 8601",
                file=sys.stderr,
            )
            return 2

    code, _manifest = run_batch(
        args.vault,
        cycle=args.cycle,
        since=since_dt,
        dry_run=args.dry_run,
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
