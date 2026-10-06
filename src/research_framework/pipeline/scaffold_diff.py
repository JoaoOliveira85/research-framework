"""Pure diff: (VaultBaseline, ScaffoldManifest) → MigrationPlan.

Decision matrix (3 outcomes):
  manifest entry        |  on disk?   |  operation
  ----------------------+-------------+-------------
  any                   |  no         |  CREATE
  user_owned=True       |  yes        |  LEAVE_ALONE
  user_owned=False      |  yes        |  OVERWRITE
"""

from __future__ import annotations

import datetime

from .scaffold_models import (
    FileBaseline,
    ManifestEntry,
    MigrationOperation,
    MigrationPlan,
    OpKind,
    ScaffoldManifest,
    VaultBaseline,
)

__all__ = ["compute_plan"]


def _diff_entry(
    entry: ManifestEntry, file_bl: FileBaseline | None
) -> MigrationOperation:
    if file_bl is None or not file_bl.exists:
        return MigrationOperation(
            kind=OpKind.CREATE,
            path=entry.path,
            from_version=None,
            to_version=entry.template_version,
            reason="file absent from vault",
        )
    if entry.is_user_owned_after_first_write:
        return MigrationOperation(
            kind=OpKind.LEAVE_ALONE,
            path=entry.path,
            from_version=file_bl.template_version,
            to_version=entry.template_version,
            reason="user-owned file; not managed after creation",
        )
    return MigrationOperation(
        kind=OpKind.OVERWRITE,
        path=entry.path,
        from_version=file_bl.template_version,
        to_version=entry.template_version,
        reason="framework-owned file; refresh to current template",
    )


_ORDER = {OpKind.CREATE: 0, OpKind.OVERWRITE: 1, OpKind.LEAVE_ALONE: 2}


def compute_plan(baseline: VaultBaseline, manifest: ScaffoldManifest) -> MigrationPlan:
    ops = [_diff_entry(e, baseline.files.get(e.path)) for e in manifest.entries]
    ops.sort(key=lambda op: (_ORDER[op.kind], op.path))
    return MigrationPlan(
        vault_root=baseline.vault_root,
        from_framework_version=baseline.from_framework_version,
        to_framework_version=manifest.framework_version,
        generated_at=datetime.datetime.now(datetime.UTC).isoformat(),
        has_unresolved_conflicts=False,
        operations=tuple(ops),
    )
