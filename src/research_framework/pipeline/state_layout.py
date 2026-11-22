"""Where a vault's durable state lives (spec 083).

State is what a later command reads and cannot recompute without spending
again or asking the operator again (spec 083 FR-001). It lives under
``_pipeline/state/`` and nowhere else, and that directory is the one part of
``_pipeline/`` git tracks.

This module is the only place a state path is spelled (FR-004). Writers and
readers call the accessors; the migration, the guard, the health check and the
scaffold manifest read :data:`STATE_ARTEFACTS`. ``scripts/guards/state_paths.py``
fails the battery when a state file's name appears anywhere else under ``src/``
or ``scripts/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PIPELINE_DIR = "_pipeline"
STATE_DIR = "_pipeline/state"

MIGRATION_COMMAND = "./vault migrate-layout"

Kind = Literal["file", "dir", "per_module_file"]

_MODULE = "<module>"


@dataclass(frozen=True)
class StateArtefact:
    """One row of spec 083's FR-002 table.

    ``new_rel`` and ``legacy_rel`` are vault-relative POSIX paths, written as
    the spec writes them: a directory ends in ``/`` and a per-module file
    carries the literal ``<module>`` segment. ``legacy_rel`` is empty for an
    artefact that had no file before this layout (the cycle ledger).
    ``moved_by_083`` is False for a row the layout migration must leave alone.
    """

    name: str
    new_rel: str
    legacy_rel: str
    kind: Kind
    moved_by_083: bool = True


STATE_ARTEFACTS: tuple[StateArtefact, ...] = (
    # Spec 084 converts the Markdown backlog into this file and keeps the
    # ``.md`` as an ignored view; until then the legacy path is the live one
    # and the migration does not touch it (D-3).
    StateArtefact(
        "research_backlog",
        f"{STATE_DIR}/research-backlog.json",
        f"{PIPELINE_DIR}/research-backlog.md",
        "file",
        moved_by_083=False,
    ),
    StateArtefact(
        "coverage_targets",
        f"{STATE_DIR}/coverage-targets.json",
        f"{PIPELINE_DIR}/coverage-targets.json",
        "file",
    ),
    StateArtefact(
        "propose_rejects",
        f"{STATE_DIR}/propose-rejects.md",
        f"{PIPELINE_DIR}/propose-rejects.md",
        "file",
    ),
    StateArtefact(
        "sources_db",
        f"{STATE_DIR}/sources.db",
        f"{PIPELINE_DIR}/sources.db",
        "file",
    ),
    StateArtefact(
        "quarantine",
        f"{STATE_DIR}/quarantine/",
        f"{PIPELINE_DIR}/quarantine/",
        "dir",
    ),
    StateArtefact(
        "facts_schema",
        f"{STATE_DIR}/sources/{_MODULE}/facts-schema.json",
        f"{PIPELINE_DIR}/sources/{_MODULE}/facts-schema.json",
        "per_module_file",
    ),
    StateArtefact(
        "archive_snapshots",
        f"{STATE_DIR}/archive-snapshots.json",
        f"{PIPELINE_DIR}/archive-snapshots.json",
        "file",
    ),
    StateArtefact(
        "approval_decisions",
        f"{STATE_DIR}/approval-decisions.json",
        f"{PIPELINE_DIR}/approval-decisions.json",
        "file",
    ),
    # New with this layout (D-1): the facts resume numbering, the lifetime
    # spend cap and the yield cadence used to derive from the ignored
    # ``cycles/`` tree.
    StateArtefact(
        "cycle_ledger",
        f"{STATE_DIR}/cycle-ledger.json",
        "",
        "file",
        moved_by_083=False,
    ),
)

_BY_NAME = {artefact.name: artefact for artefact in STATE_ARTEFACTS}

# SQLite sidecars that sit beside a tracked database and are never tracked.
SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm")


class LegacyLayoutError(RuntimeError):
    """A state-writing command met state at a pre-083 path.

    The command must stop (exit 2) rather than write new state beside old
    state it is not reading (FR-015).
    """

    def __init__(self, vault_dir: Path, present: list[Path]) -> None:
        self.vault_dir = vault_dir
        self.present = present
        shown = ", ".join(_rel(vault_dir, path) for path in present[:5])
        more = f" (and {len(present) - 5} more)" if len(present) > 5 else ""
        super().__init__(
            f"legacy _pipeline/ layout: durable state is still at {shown}{more}. "
            f"Run `{MIGRATION_COMMAND}` (or `./vault update`) to move it under "
            f"{STATE_DIR}/, then run this command again."
        )


def _rel(vault_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(vault_dir).as_posix()
    except ValueError:
        return path.as_posix()


def _new(vault_dir: Path, name: str) -> Path:
    return vault_dir / _BY_NAME[name].new_rel


def state_dir(vault_dir: Path) -> Path:
    return vault_dir / STATE_DIR


def research_backlog_path(vault_dir: Path) -> Path:
    """Spec 084's store. Nothing writes it until 084 ships."""
    return _new(vault_dir, "research_backlog")


def coverage_targets_path(vault_dir: Path) -> Path:
    return _new(vault_dir, "coverage_targets")


def propose_rejects_path(vault_dir: Path) -> Path:
    return _new(vault_dir, "propose_rejects")


def sources_db_path(vault_dir: Path) -> Path:
    return _new(vault_dir, "sources_db")


def quarantine_dir(vault_dir: Path) -> Path:
    return _new(vault_dir, "quarantine")


def facts_schema_path(vault_dir: Path, module: str) -> Path:
    return vault_dir / _BY_NAME["facts_schema"].new_rel.replace(_MODULE, module)


def archive_snapshots_path(vault_dir: Path) -> Path:
    return _new(vault_dir, "archive_snapshots")


def approval_decisions_path(vault_dir: Path) -> Path:
    return _new(vault_dir, "approval_decisions")


def cycle_ledger_path(vault_dir: Path) -> Path:
    return _new(vault_dir, "cycle_ledger")


def legacy_paths_present(vault_dir: Path) -> list[Path]:
    """Every pre-083 state path that exists, in registry order.

    Only rows the layout migration moves are considered: the Markdown backlog
    is still the live backlog until spec 084, and the ledger never had a file.
    """
    found: list[Path] = []
    for artefact in STATE_ARTEFACTS:
        if not artefact.moved_by_083 or not artefact.legacy_rel:
            continue
        if artefact.kind == "per_module_file":
            prefix, suffix = artefact.legacy_rel.split(f"{_MODULE}/", 1)
            parent = vault_dir / prefix
            if parent.is_dir():
                found.extend(
                    module / suffix
                    for module in sorted(parent.iterdir())
                    if (module / suffix).is_file()
                )
            continue
        path = vault_dir / artefact.legacy_rel
        if path.exists():
            found.append(path)
    return found


def is_legacy_layout(vault_dir: Path) -> bool:
    return bool(legacy_paths_present(vault_dir))


def require_migrated(vault_dir: Path) -> None:
    """Raise :class:`LegacyLayoutError` when the vault still holds legacy state."""
    present = legacy_paths_present(vault_dir)
    if present:
        raise LegacyLayoutError(vault_dir, present)
