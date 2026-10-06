"""Runtime asset resolver for research-framework.

Runtime assets (``templates/``, ``scripts/``, ``.agents/``, ``settings.yaml``)
are bundled into the wheel under ``research_framework/_data/`` via hatchling
``force-include``. When running from the source tree in development, they live
at the repo root instead.

This module provides a single lookup that prefers the packaged copy and falls
back to the source-tree copy so the CLI behaves identically in both modes.

Use :func:`asset_path` for directory or file assets and
:func:`default_settings_path` as a convenience for the bundled
``settings.yaml``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from research_framework.pipeline.settings import SettingsError, load_vault_settings

_LOG = logging.getLogger(__name__)

_PKG_DIR = Path(__file__).resolve().parent


def _legacy_settings_dict(settings_path: Path) -> dict | None:
    """Parse a profile ``settings.yaml`` without B7 required-key validation."""
    try:
        raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return raw if isinstance(raw, dict) else None


def _settings_top_level(settings_path: Path, key: str) -> object:
    """Return top-level *key* of the settings file at *settings_path*.

    ``load_vault_settings`` takes a directory and reads the ``settings.yaml``
    in it, so it answers for *settings_path* only when that is the file's
    name. Asked about a profile such as ``settings.codex.yaml`` it used to
    answer from the ``settings.yaml`` beside it.
    """
    if settings_path.name == "settings.yaml":
        try:
            return load_vault_settings(settings_path.parent).extras.get(key)
        except SettingsError:
            pass
    data = _legacy_settings_dict(settings_path)
    return data.get(key) if data else None


_PACKAGED_DATA = _PKG_DIR / "_data"
_SOURCE_ROOT = _PKG_DIR.parents[1]


def _source_tree_candidate(name: str) -> Path:
    return _SOURCE_ROOT / name


def _packaged_candidate(name: str) -> Path:
    return _PACKAGED_DATA / name


def asset_path(name: str) -> Path:
    """Return the path to a bundled runtime asset.

    Lookup order:

    1. ``research_framework/_data/<name>`` inside the installed package (production).
    2. ``<repo-root>/<name>`` in the source tree (dev mode).

    Raises :class:`FileNotFoundError` if neither location exists so callers get
    a single, actionable error instead of generic path failures downstream.
    """
    packaged = _packaged_candidate(name)
    if packaged.exists():
        return packaged
    source = _source_tree_candidate(name)
    if source.exists():
        return source
    raise FileNotFoundError(
        f"research-framework asset '{name}' not found in packaged location "
        f"({packaged}) or source tree ({source}). This usually means the "
        f"wheel was built without force-include or the source checkout is "
        f"incomplete."
    )


def default_settings_path() -> Path:
    """Return the path to the bundled ``settings.yaml``."""
    return asset_path("settings.yaml")


# Legacy alias map retained for a single purpose: producing a helpful error
# message when someone passes ``--settings claude`` or ``--settings codex``
# from memory or from old docs. Resolution itself is filepath-only now —
# ``settings_profile_path`` treats every input as a filesystem path.
_LEGACY_ALIAS_FILENAMES: dict[str, str] = {
    "claude": "settings.yaml",
    "codex": "settings.codex.yaml",
}


def settings_profile_path(path_arg: str) -> Path:
    """Resolve ``path_arg`` (a filesystem path) to an on-disk settings file.

    Accepts absolute paths, relative paths, and ``~``/``$VAR`` expansion.
    Relative paths are resolved against the caller's current working
    directory — consistent with how every other CLI tool handles path args.

    Raises :class:`FileNotFoundError` with an actionable message when the
    path does not exist. If the input looks like one of the legacy alias
    names (``claude`` / ``codex``), the error nudges the user toward the
    replacement filename so the upgrade path is obvious.
    """
    expanded = os.path.expandvars(os.path.expanduser(path_arg))
    candidate = Path(expanded)
    if candidate.is_file():
        return candidate

    if path_arg in _LEGACY_ALIAS_FILENAMES:
        replacement = _LEGACY_ALIAS_FILENAMES[path_arg]
        raise FileNotFoundError(
            f"--settings no longer accepts the alias '{path_arg}'. "
            f"Pass a file path instead, e.g. --settings {replacement} "
            f"(bundled next to install.sh)."
        )
    raise FileNotFoundError(f"--settings '{path_arg}' is not a readable file path.")


def load_output_dir_from_settings(settings_path: Path) -> Path | None:
    """Return the ``output_dir`` field from ``settings_path``, or ``None``.

    Expansion rules mirror the YAML-level documentation:

    - ``~`` / ``$VAR`` / ``${VAR}`` expand.
    - Absolute paths return verbatim (after expansion).
    - Relative paths resolve against ``settings_path.parent``, so a
      ``settings.yaml`` sitting next to a spec stays portable across
      clones.

    A missing file, a missing key, a ``null`` value, or a non-string value
    all return ``None`` rather than raising — the setting is optional and
    the caller will fall through to the next resolution tier.
    """
    if not settings_path.is_file():
        return None
    raw = _settings_top_level(settings_path, "output_dir")
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        return None
    expanded = os.path.expandvars(os.path.expanduser(raw.strip()))
    p = Path(expanded)
    if not p.is_absolute():
        p = (settings_path.parent / p).resolve()
    return p


def load_cycle_limits_from_settings(
    settings_path: Path,
) -> tuple[int | None, int | None]:
    """Return ``(initial_max, update_max)`` from the settings file's ``cycles``
    block, each entry ``None`` when absent or malformed.

    **DEPRECATED (spec 061).** The ``cycles:`` block is superseded by the single
    canonical ``pipeline.max_cycles`` key. The live budget path no longer calls
    this helper — generate / resume / phase3 all resolve through
    :func:`research_framework.cli._budget_resolve.resolve_cycle_budget`, which
    reads (and warns on) the deprecated ``cycles.*`` keys directly. This helper
    is retained for back-compat parsing of the legacy block and is exercised by
    ``tests/test_assets.py``; when either deprecated key is present it emits a
    single loud ``logging.WARNING`` naming the canonical key (it never silently
    wins — that was the rc1 truncation bug).
    """
    if not settings_path.is_file():
        return None, None
    cycles = _settings_top_level(settings_path, "cycles")
    if cycles is None:
        return None, None
    if not isinstance(cycles, dict):
        return None, None

    def _positive_int(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int) and value > 0:
            return value
        return None

    initial_max = _positive_int(cycles.get("initial_max"))
    update_max = _positive_int(cycles.get("update_max"))

    seen = [
        f"cycles.{key}"
        for key, value in (("initial_max", initial_max), ("update_max", update_max))
        if value is not None
    ]
    if seen:
        _LOG.warning(
            "settings: %s is deprecated — use the canonical pipeline.max_cycles "
            "instead (see spec 061). Honouring it for now.",
            ", ".join(seen),
        )

    return initial_max, update_max
