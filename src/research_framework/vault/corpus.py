"""Resolve a vault's corpus folder — the one seam every reader shares.

A vault names its corpus folder in the spec (``vault.corpus_dir``, default
``data_vault``). The generator honours it; before this module existed every
downstream reader — indexer, coverage, quarantine, harvest, wikilinks — spelled
``vault / "data_vault"`` instead, so a vault that chose another name got a
second, empty ``data_vault/`` created under it, its indexes written there, and
``met_count`` stuck at 0. A setting accepted and silently ignored.

The name is read from the parsed spec (``_pipeline/spec-parse.json``) through
the one loader, ``spec.parsed.load_parsed_spec``, which re-parses when the spec
file has changed. Readers take a vault root, not a corpus path, so the
resolution has to happen from the vault root; that is what this module is.
"""

from __future__ import annotations

from pathlib import Path

from ..spec.parsed import ParsedSpecError, load_parsed_spec

DEFAULT_CORPUS_DIR = "data_vault"


def corpus_dir_name(vault: Path) -> str:
    """Return the corpus folder name *vault* declares, or the default.

    Never raises: a vault mid-generation has no ``spec-parse.json`` yet, and a
    truncated one must not take down a best-effort reader.
    """
    try:
        data = load_parsed_spec(vault)
    except ParsedSpecError:
        return DEFAULT_CORPUS_DIR
    return str(data.get("vault_corpus_dir") or DEFAULT_CORPUS_DIR)


def corpus_dir(vault: Path) -> Path:
    """Return the corpus directory of *vault*.

    The path is returned whether or not it exists — callers that create the
    corpus (the indexer) must create the DECLARED one, not the default.
    """
    return vault / corpus_dir_name(vault)


def existing_corpus_dir(vault: Path) -> Path | None:
    """Return the corpus directory only if it is on disk, else the default one
    if THAT is on disk, else ``None``.

    For readers that must not invent a folder, and that would rather grade a
    legacy ``data_vault/`` than nothing at all — a vault whose spec was renamed
    before its corpus was moved.
    """
    declared = corpus_dir(vault)
    if declared.is_dir():
        return declared
    fallback = vault / DEFAULT_CORPUS_DIR
    return fallback if fallback.is_dir() else None
