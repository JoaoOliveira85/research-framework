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
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

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
    with no spec file to rebuild it from; a spec that fails to parse. The
    underlying error, when there is one, is chained as ``__cause__``.
    """


def spec_parse_path(vault: Path) -> Path:
    """Path of the vault's ``spec-parse.json`` (it may not exist)."""
    return vault / SPEC_PARSE_RELPATH


def find_spec_file(vault: Path) -> Path | None:
    """Return the vault's spec file, or ``None``.

    Order: ``<vault-name>-spec.md``, the first ``*-spec.md``, then
    ``research.spec.md``.
    """
    canonical = vault / f"{vault.name}-spec.md"
    if canonical.exists():
        return canonical
    for p in sorted(vault.glob("*-spec.md")):
        return p
    research = vault / "research.spec.md"
    if research.exists():
        return research
    return None


def spec_file_sha256(spec_file: Path) -> str:
    """SHA-256 hex digest of the spec file's bytes."""
    return hashlib.sha256(spec_file.read_bytes()).hexdigest()


def stamp_parsed_spec(
    doc: dict[str, Any], spec_file: Path, vault: Path
) -> dict[str, Any]:
    """Return *doc* plus the metadata keys that tie it to *spec_file*.

    ``spec_file`` is recorded relative to *vault* when it lives inside it
    (absolute otherwise), so an explicit ``parse-spec <vault> <other.md>`` is
    not silently replaced by the vault's default spec on the next load.
    """
    try:
        recorded = spec_file.resolve().relative_to(vault.resolve()).as_posix()
    except ValueError:
        recorded = str(spec_file.resolve())
    return {
        **json.loads(json.dumps(doc, default=str)),  # JSON-safe: Path -> str
        SPEC_SHA256_KEY: spec_file_sha256(spec_file),
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


def _is_fresh(cache: dict[str, Any], spec_file: Path) -> bool:
    if cache.get(PARSER_VERSION_KEY) != PARSER_VERSION:
        return False
    recorded = cache.get(SPEC_SHA256_KEY)
    if not isinstance(recorded, str) or not recorded:
        return False
    return recorded == spec_file_sha256(spec_file)


def load_parsed_spec(vault: Path, *, write_cache: bool = True) -> dict[str, Any]:
    """Return the vault's parsed spec, re-parsing if the cache is not current.

    The cache is current iff it is a JSON object whose ``parser_version`` is
    :data:`PARSER_VERSION` and whose ``spec_sha256`` equals the SHA-256 of the
    spec file now. File modification times are never consulted.

    A stale or missing cache is rebuilt from the spec file and, unless
    *write_cache* is false, written back atomically. Pass ``write_cache=False``
    from read-only diagnostics.

    When the vault has no spec file there is nothing to compare against or
    rebuild from (a vault built straight from a parsed dict, or one whose spec
    was removed): the cache is returned as it is.

    A failure to write the cache back (a read-only vault) is logged, not raised.

    Raises :class:`ParsedSpecError` if there is neither a usable cache nor a
    spec file, or the spec file fails to parse. A spec that fails to parse is
    an error even when a stale cache exists — serving the stale cache is the
    behaviour this loader exists to prevent.
    """
    path = spec_parse_path(vault)
    cache = _read_cache(path) if path.exists() else None
    spec_file = _resolve_spec_file(vault, cache)

    if spec_file is None:
        if cache is not None:
            return cache
        raise ParsedSpecError(
            f"no usable {SPEC_PARSE_RELPATH.as_posix()} and no spec file in {vault}"
        )

    if cache is not None and _is_fresh(cache, spec_file):
        return cache

    from .simple import load as load_spec

    try:
        spec = load_spec(spec_file, location=vault.resolve())
    except SpecValidationError as exc:
        raise ParsedSpecError(
            f"cannot rebuild {SPEC_PARSE_RELPATH.as_posix()}: "
            f"{spec_file.name} failed validation: {exc}"
        ) from exc
    except OSError as exc:
        raise ParsedSpecError(f"cannot read {spec_file}: {exc}") from exc

    doc = stamp_parsed_spec(spec.to_dict(), spec_file, vault)
    if write_cache:
        try:
            write_parsed_spec(vault, doc)
        except OSError as exc:  # read-only vault: serve the fresh parse anyway
            _LOG.warning("could not refresh %s: %s", SPEC_PARSE_RELPATH, exc)
    return doc
