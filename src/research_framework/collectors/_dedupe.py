"""Content-hash-based deduplication for collected items.

Replaces scattered ``if url in seen`` / ``get_existing_video_ids`` logic from
feeds-vault scripts.

A collected item is "seen" if a file named ``<source_id>.md`` already exists
under ``<vault>/_pipeline/raw/<source_kind>/``.  The check is purely
filesystem-based — no database, no separate index file.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def seen(vault: Path, source_kind: str, source_id: str) -> bool:
    """Return ``True`` if *source_id* has already been written to the vault.

    Checks whether ``<vault>/_pipeline/raw/<source_kind>/<source_id>.md``
    exists.
    """
    target = vault / "_pipeline" / "raw" / source_kind / f"{source_id}.md"
    return target.exists()


def content_hash(text: str) -> str:
    """Return a hex SHA-256 digest of *text* (UTF-8 encoded)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
