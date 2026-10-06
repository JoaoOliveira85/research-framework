"""research_framework.processors — post-collection pipeline processors.

Four modules promoted from the feeds-vault's scripts/:

  extract    — Haiku per-source extraction + Sonnet context tree synthesis
  preprocess — boilerplate stripping, deduplication, language detection
  verify     — structural vault checks (wikilinks, frontmatter, orphans, MOC)
  archive    — move aged raw items to _pipeline/archive/<YYYY-MM>/

Each exposes a ``<verb>(vault: Path, ...) -> <Verb>Result`` Python API and a
``python -m research_framework.processors.<name> <vault>`` CLI.
"""

from .archive import ArchiveResult, archive
from .extract import ExtractResult, extract
from .preprocess import PreprocessResult, preprocess
from .verify import VerifyResult, verify

__all__ = [
    "archive",
    "ArchiveResult",
    "extract",
    "ExtractResult",
    "preprocess",
    "PreprocessResult",
    "verify",
    "VerifyResult",
]
