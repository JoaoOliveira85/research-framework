from pathlib import Path
from unittest.mock import patch

from research_framework.generator.scripts import _scripts_src, copy_scripts
from tests._helpers.vault_factory import build_minimal_vault


def test_copy_scripts_merge_retains_unlisted_collect_glob(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    custom = vault / "scripts" / "collect_custom.py"
    payload = b"# custom collector\n"
    custom.write_bytes(payload)
    copy_scripts(vault)
    assert custom.read_bytes() == payload


def test_copy_scripts_merge_retains_reddit_rss_allowlist(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    rss = vault / "scripts" / "reddit_rss.py"
    payload = b"# reddit\n"
    rss.write_bytes(payload)
    copy_scripts(vault)
    assert rss.read_bytes() == payload


def test_copy_scripts_never_rmtree_scripts_directory(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    with patch("research_framework.generator.scripts.shutil.rmtree") as rm:
        copy_scripts(vault)
        for call in rm.call_args_list:
            path = str(call[0][0])
            assert not path.endswith("/scripts") and not path.endswith("scripts")


def test_copy_scripts_adds_framework_script_without_deleting_user_files(
    tmp_path: Path,
) -> None:
    vault = build_minimal_vault(tmp_path)
    user = vault / "scripts" / "collect_custom.py"
    user.write_text("# user\n", encoding="utf-8")
    src_name = next(
        p.name for p in _scripts_src().iterdir() if p.is_file() and p.suffix == ".py"
    )
    copy_scripts(vault)
    assert user.is_file()
    assert (vault / "scripts" / src_name).is_file()


def test_copy_scripts_excludes_maintainer_only_migration_scripts(
    tmp_path: Path,
) -> None:
    """Issue #288: scripts/_migrate_prints_spec048.py is "committed for
    auditability of the migration" (its own docstring) — a completed,
    one-shot maintainer tool that operates on THIS repo's own hot-path
    files, not on vault content. A fresh generated vault never had the
    pre-migration `print()` calls it exists to rewrite, so it has no
    business shipping there (or in the release bundle)."""
    vault = build_minimal_vault(tmp_path)
    copy_scripts(vault)
    assert not (vault / "scripts" / "_migrate_prints_spec048.py").exists()
    # An ordinary top-level framework script is still copied as normal.
    assert (vault / "scripts" / "agent_call.py").is_file()
