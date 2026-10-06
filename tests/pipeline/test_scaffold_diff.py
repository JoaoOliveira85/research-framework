"""Tests for the 3-outcome migrator diff: CREATE, OVERWRITE, LEAVE_ALONE."""

from pathlib import Path

from research_framework.pipeline.scaffold_diff import compute_plan
from research_framework.pipeline.scaffold_models import (
    FileBaseline,
    ManifestEntry,
    OpKind,
    ScaffoldManifest,
    VaultBaseline,
)


def _manifest(*entries):
    return ScaffoldManifest(
        framework_version=2,
        generator_commit="g",
        generated_at="t",
        entries=tuple(entries),
    )


def _entry(path, *, user_owned=False, tv=1):
    return ManifestEntry(
        path=path,
        kind="markdown",
        template_version=tv,
        rendered_sha256="sha-" + path,
        is_user_owned_after_first_write=user_owned,
    )


def _baseline(vault: Path, **files):
    return VaultBaseline(vault_root=vault, from_framework_version=1, files=dict(files))


def test_missing_framework_owned_file_creates(tmp_path):
    m = _manifest(_entry("CLAUDE.md"))
    bl = _baseline(
        tmp_path,
        **{"CLAUDE.md": FileBaseline("CLAUDE.md", "", None, exists=False)},
    )
    plan = compute_plan(bl, m)
    [op] = plan.operations
    assert op.kind == OpKind.CREATE
    assert op.path == "CLAUDE.md"


def test_missing_user_owned_file_creates(tmp_path):
    m = _manifest(_entry("settings.yaml", user_owned=True))
    bl = _baseline(
        tmp_path,
        **{"settings.yaml": FileBaseline("settings.yaml", "", None, exists=False)},
    )
    plan = compute_plan(bl, m)
    [op] = plan.operations
    assert op.kind == OpKind.CREATE


def test_present_framework_owned_overwrites_regardless_of_edits(tmp_path):
    m = _manifest(_entry("CLAUDE.md"))
    bl = _baseline(
        tmp_path,
        **{"CLAUDE.md": FileBaseline("CLAUDE.md", "user-edited", 1, exists=True)},
    )
    plan = compute_plan(bl, m)
    [op] = plan.operations
    assert op.kind == OpKind.OVERWRITE


def test_present_user_owned_left_alone(tmp_path):
    m = _manifest(_entry("settings.yaml", user_owned=True))
    bl = _baseline(
        tmp_path,
        **{"settings.yaml": FileBaseline("settings.yaml", "x", 1, exists=True)},
    )
    plan = compute_plan(bl, m)
    [op] = plan.operations
    assert op.kind == OpKind.LEAVE_ALONE


def test_no_deprecated_op_for_files_outside_manifest(tmp_path):
    m = _manifest(_entry("CLAUDE.md"))
    bl = _baseline(
        tmp_path,
        **{
            "CLAUDE.md": FileBaseline("CLAUDE.md", "x", 1, exists=True),
            # Note: baseline never includes off-manifest paths now, but
            # even if a caller injected one, compute_plan must not emit any
            # report for it.
        },
    )
    plan = compute_plan(bl, m)
    assert all(
        op.kind in (OpKind.CREATE, OpKind.OVERWRITE, OpKind.LEAVE_ALONE)
        for op in plan.operations
    )


def test_plan_ordered_by_kind_then_path(tmp_path):
    m = _manifest(_entry("Z.md"), _entry("A.md", user_owned=True), _entry("M.md"))
    bl = _baseline(
        tmp_path,
        **{
            "Z.md": FileBaseline("Z.md", "x", 1, exists=True),
            "A.md": FileBaseline("A.md", "x", 1, exists=True),
            "M.md": FileBaseline("M.md", "", None, exists=False),
        },
    )
    plan = compute_plan(bl, m)
    kinds = [(op.kind, op.path) for op in plan.operations]
    assert kinds == [
        (OpKind.CREATE, "M.md"),
        (OpKind.OVERWRITE, "Z.md"),
        (OpKind.LEAVE_ALONE, "A.md"),
    ]
