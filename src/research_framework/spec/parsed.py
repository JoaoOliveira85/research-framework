"""The one loader for a vault's parsed spec (``_pipeline/spec-parse.json``).

``spec-parse.json`` is a cache of the vault's spec file after parsing and
expansion. A cache is only worth reading if it still matches what produced
it, so the file records two things alongside the parsed spec:

``spec_sha256``
    SHA-256 of the spec file's bytes at parse time. The content, never the
    modification time: a checkout, copy, restore or clock skew leaves mtimes
    that say nothing about whether the spec changed.

``parser_version``
    :data:`PARSER_VERSION` at parse time, so a cache written by a parser whose
    output differs is rebuilt rather than trusted.

Every reader of the parsed content goes through :func:`load_parsed_spec`.
It re-parses when the cache is missing, was written without a hash or a
version, was written by a different parser version, or no longer matches the
spec file, and otherwise returns the cache. Spec-file freshness is therefore
decided in exactly one place.

Strict and lenient reads
------------------------
When the spec no longer parses (mid-edit, or invalid), a *reader* should keep
working from the last good parse rather than resolve a different corpus folder
or silently see nothing. So the default is **lenient**: if a cache exists it is
served and a WARNING names the spec file and the parse error. The verbs that
exist to (re)build from the spec — ``parse-spec``, ``regenerate-agents``,
``regenerate-shim``, ``onboard``, ``scaffold`` — pass ``strict=True`` and get a
:class:`ParsedSpecError` instead. Only those verbs and the cycle runner pass
``write_cache=True``; every other reader leaves the vault untouched.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import yaml

from .schema import SpecValidationError

_LOG = logging.getLogger(__name__)

#: Version of the ``spec-parse.json`` producer. **Bump it whenever the parsed
#: output changes in a way a cache written earlier would be wrong about** —
#: a key added to / removed from / renamed in ``SpecConfig.to_dict()`` (or a
#: nested ``to_dict``), a changed default, or a changed expansion rule in
#: ``spec/simple.py`` / ``spec/parser.py``. A cache whose ``parser_version``
#: is absent or different from this value is treated as stale and rebuilt.
#: ``tests/spec/test_parsed_spec_cache.py`` pins the top-level key set so a
#: shape change without a bump fails the suite.
PARSER_VERSION = 1

#: Where the cache lives, relative to the vault root.
SPEC_PARSE_RELPATH = Path("_pipeline") / "spec-parse.json"

#: Metadata keys the loader adds to the parsed spec. Not part of ``SpecConfig``.
SPEC_SHA256_KEY = "spec_sha256"
PARSER_VERSION_KEY = "parser_version"
SPEC_FILE_KEY = "spec_file"


class ParsedSpecError(Exception):
    """The parsed spec could not be produced or read.

    Raised for: no cache and no spec file; an unreadable or non-object cache
    with no spec file to rebuild it from; a spec that fails to parse and either
    ``strict=True`` was asked for or there is no earlier cache to fall back to.
    The underlying error, when there is one, is chained as ``__cause__``.
    """


def spec_parse_path(vault: Path) -> Path:
    """Path of the vault's ``spec-parse.json`` (it may not exist)."""
    return vault / SPEC_PARSE_RELPATH


def find_spec_file(vault: Path) -> Path | None:
    """Return the vault's spec file, or ``None``.

    Probe order: ``<vault-name>-spec.md``, then ``research.spec.md``. There is
    deliberately no ``*-spec.md`` glob: a stray file must not be able to take
    over a vault's cache. ``onboard``, which may meet a hand-named spec, finds
    it itself and passes it as ``spec_file=``; the loader then records it.
    """
    for name in (f"{vault.resolve().name}-spec.md", "research.spec.md"):
        candidate = vault / name
        if candidate.exists():
            return candidate
    return None


def spec_file_sha256(spec_file: Path) -> str:
    """SHA-256 hex digest of the spec file's bytes."""
    return hashlib.sha256(spec_file.read_bytes()).hexdigest()


def stamp_parsed_spec(
    doc: dict[str, Any],
    spec_file: Path,
    vault: Path,
    *,
    sha256: str | None = None,
) -> dict[str, Any]:
    """Return *doc* plus the metadata keys that tie it to *spec_file*.

    ``spec_file`` is recorded relative to *vault* when it lives inside it
    (absolute otherwise), so an explicit ``parse-spec <vault> <other.md>`` is
    not silently replaced by the vault's default spec on the next load.

    ``sha256`` is the digest of the bytes the caller parsed. Pass it whenever
    the file was hashed before it was parsed, so the stamp can never describe
    newer content than the parse saw; by default the file is hashed here.
    """
    try:
        recorded = spec_file.resolve().relative_to(vault.resolve()).as_posix()
    except ValueError:
        recorded = str(spec_file.resolve())
    return {
        **json.loads(json.dumps(doc, default=str)),  # JSON-safe: Path -> str
        SPEC_SHA256_KEY: sha256 if sha256 is not None else spec_file_sha256(spec_file),
        PARSER_VERSION_KEY: PARSER_VERSION,
        SPEC_FILE_KEY: recorded,
    }


def write_parsed_spec(vault: Path, doc: dict[str, Any]) -> Path:
    """Atomically write *doc* as the vault's ``spec-parse.json``."""
    from ..pipeline.atomic_write import write_text

    path = spec_parse_path(vault)
    write_text(path, json.dumps(doc, indent=2, default=str) + "\n")
    return path


def _read_cache(path: Path) -> dict[str, Any] | None:
    """The cache as a dict, or ``None`` if absent, unreadable or not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _resolve_spec_file(vault: Path, cache: dict[str, Any] | None) -> Path | None:
    if cache is not None:
        stored = cache.get(SPEC_FILE_KEY)
        if isinstance(stored, str) and stored:
            candidate = Path(stored)
            if not candidate.is_absolute():
                candidate = vault / candidate
            if candidate.is_file():
                return candidate
    return find_spec_file(vault)


def _is_fresh(cache: dict[str, Any], sha256: str) -> bool:
    if cache.get(PARSER_VERSION_KEY) != PARSER_VERSION:
        return False
    recorded = cache.get(SPEC_SHA256_KEY)
    return isinstance(recorded, str) and bool(recorded) and recorded == sha256


def load_parsed_spec(
    vault: Path,
    *,
    write_cache: bool = False,
    strict: bool = False,
    spec_file: Path | None = None,
) -> dict[str, Any]:
    """Return the vault's parsed spec, re-parsing if the cache is not current.

    The cache is current iff it is a JSON object whose ``parser_version`` is
    :data:`PARSER_VERSION` and whose ``spec_sha256`` equals the SHA-256 of the
    spec file now. File modification times are never consulted.

    A stale or missing cache is rebuilt from the spec file. The rebuild is
    returned either way; it is written back (atomically) only when
    *write_cache* is true, and a failure to write is logged, not raised.

    *spec_file* names the spec explicitly (``onboard`` uses this for a
    hand-named spec). Otherwise the file the cache was stamped from is used,
    then :func:`find_spec_file`. With no spec file at all there is nothing to
    compare against or rebuild from, and the cache is returned as it is.

    If the spec cannot be read or parsed: with ``strict=True`` this raises
    :class:`ParsedSpecError`. Otherwise, if any cache exists it is returned
    (the last good parse) and a WARNING names the spec file and the error; with
    no cache at all it raises.

    Raises :class:`ParsedSpecError` and nothing else.
    """
    path = spec_parse_path(vault)
    cache = _read_cache(path) if path.exists() else None
    if spec_file is None:
        spec_file = _resolve_spec_file(vault, cache)

    if spec_file is None:
        if cache is not None:
            return cache
        raise ParsedSpecError(
            f"no usable {SPEC_PARSE_RELPATH.as_posix()} and no spec file in {vault}"
        )

    # Hash once, up front. The stamp below uses this digest, so a spec edited
    # while it is being parsed is stamped with the older content and simply
    # re-parsed on the next load, never trusted.
    try:
        sha256 = spec_file_sha256(spec_file)
    except OSError as exc:
        return _unparseable(cache, spec_file, exc, strict)

    if cache is not None and _is_fresh(cache, sha256):
        return cache

    from .simple import load as load_spec

    try:
        spec = load_spec(spec_file, location=vault.resolve())
    except (SpecValidationError, OSError, ValueError, yaml.YAMLError) as exc:
        return _unparseable(cache, spec_file, exc, strict)

    doc = stamp_parsed_spec(spec.to_dict(), spec_file, vault, sha256=sha256)
    if write_cache:
        try:
            write_parsed_spec(vault, doc)
        except OSError as exc:  # read-only vault: serve the fresh parse anyway
            _LOG.warning("could not refresh %s: %s", SPEC_PARSE_RELPATH, exc)
    return doc


def _unparseable(
    cache: dict[str, Any] | None, spec_file: Path, exc: Exception, strict: bool
) -> dict[str, Any]:
    """Serve the last good parse (lenient) or raise ``ParsedSpecError``."""
    detail = f"{spec_file.name} could not be parsed: {exc}"
    if strict or cache is None:
        raise ParsedSpecError(
            f"cannot rebuild {SPEC_PARSE_RELPATH.as_posix()}: {detail}"
        ) from exc
    _LOG.warning(
        "%s: using the last good parse of %s (%s)",
        spec_file.name,
        SPEC_PARSE_RELPATH.as_posix(),
        detail,
    )
    return cache
