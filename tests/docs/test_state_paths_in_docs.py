"""Spec 083 T014: no tracked prose names a legacy state path as a current one."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The four paths FR-017's prose surfaces used to name. Each now lives under
# `_pipeline/state/`; `_pipeline/state/sources.db` does not match because the
# pattern requires `_pipeline/` to be followed directly by the legacy name.
LEGACY = re.compile(
    r"_pipeline/(coverage-targets\.json|sources\.db|propose-rejects\.md|quarantine)"
)

# Specs record history; the changelog describes the move; `_archive/` is
# frozen; fixtures under `tests/fixtures/` are deliberately pre-083 vaults.
EXEMPT_PREFIXES = ("specs/", "_archive/", "tests/fixtures/")
EXEMPT_FILES = {"CHANGELOG.md"}


def _tracked_markdown() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "*.md"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [p for p in out.splitlines() if (REPO / p).exists()]


def test_no_doc_names_a_legacy_state_path_as_current() -> None:
    files = _tracked_markdown()
    assert len(files) > 50, "the scan root went empty"
    offenders: list[str] = []
    for rel in files:
        if rel in EXEMPT_FILES or rel.startswith(EXEMPT_PREFIXES):
            continue
        for lineno, line in enumerate(
            (REPO / rel).read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if LEGACY.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()[:100]}")
    assert offenders == [], "legacy state paths named as current:\n" + "\n".join(
        offenders
    )
