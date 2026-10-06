"""Map of vault-local script paths superseded by framework modules.

A path appears here ONLY after the superseding framework module is
well-tested against at least one real vault. False positives are
worse than missing entries — they cause data loss.
"""

from __future__ import annotations

from pathlib import Path

_SUPERSEDED_BY: dict[str, str] = {
    # Collectors (014 — RSS slice landed)
    "scripts/collect_rss.py": "research_framework.collectors.rss",
    # Processors (015f — all four landed)
    "scripts/extract.py": "research_framework.processors.extract",
    "scripts/preprocess.py": "research_framework.processors.preprocess",
    "scripts/verify.py": "research_framework.processors.verify",
    "scripts/archive.py": "research_framework.processors.archive",
    # NOTE: YouTube/Reddit/O'Reilly collectors are NOT listed yet —
    # 014 only shipped the RSS collector.
}


def superseded_paths_present(vault: Path) -> list[tuple[str, str]]:
    """Return [(rel_path, superseded_by), ...] for map entries that exist on disk."""
    result: list[tuple[str, str]] = []
    for rel_path, module in _SUPERSEDED_BY.items():
        if (vault / rel_path).exists():
            result.append((rel_path, module))
    return result
