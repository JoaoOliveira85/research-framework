"""Frozen dataclasses for the vault migrator — no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal

__all__ = [
    "ManifestEntry",
    "ScaffoldManifest",
    "FileBaseline",
    "VaultBaseline",
    "OpKind",
    "MigrationOperation",
    "MigrationPlan",
    "ApplyResult",
    "MigrationLogEntry",
]

_KIND = Literal["markdown", "yaml", "json", "shell", "python", "other"]


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    kind: _KIND
    template_version: int
    rendered_sha256: str
    is_user_owned_after_first_write: bool = False


@dataclass(frozen=True)
class ScaffoldManifest:
    framework_version: int
    generator_commit: str
    generated_at: str
    entries: tuple[ManifestEntry, ...]


@dataclass(frozen=True)
class FileBaseline:
    path: str
    content_sha256: str
    template_version: int | None
    exists: bool


@dataclass(frozen=True)
class VaultBaseline:
    vault_root: Path
    from_framework_version: int | None
    files: dict[str, FileBaseline]


class OpKind(StrEnum):
    CREATE = "create"
    OVERWRITE = "overwrite"
    LEAVE_ALONE = "leave_alone"


@dataclass(frozen=True)
class MigrationOperation:
    kind: OpKind
    path: str
    from_version: int | None
    to_version: int | None
    reason: str
    rendered_content: bytes = field(default=b"", compare=False)
    diff_snippet: str | None = None


@dataclass(frozen=True)
class MigrationPlan:
    vault_root: Path
    from_framework_version: int | None
    to_framework_version: int
    generated_at: str
    has_unresolved_conflicts: bool
    operations: tuple[MigrationOperation, ...]


@dataclass(frozen=True)
class ApplyResult:
    applied: tuple[str, ...]
    pre_snapshot_sha: str | None = None
    post_snapshot_sha: str | None = None
    git_skipped_reason: str | None = None


@dataclass(frozen=True)
class MigrationLogEntry:
    timestamp: str
    from_framework_version: int | None
    to_framework_version: int
    operations_applied: tuple[str, ...]
