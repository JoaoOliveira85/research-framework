from pathlib import Path

from research_framework.generator.scaffold import apply_vault_scaffold_update
from tests._helpers.vault_factory import build_minimal_vault


def test_vault_update_preserves_custom_collector_script_bytes(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    custom = vault / "scripts" / "custom_collector.py"
    payload = b"# bespoke\n"
    custom.write_bytes(payload)
    apply_vault_scaffold_update(vault)
    assert custom.read_bytes() == payload


def test_vault_update_preserves_collect_star_and_reddit_rss(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    yt = vault / "scripts" / "collect_youtube.py"
    rss = vault / "scripts" / "reddit_rss.py"
    yt.write_bytes(b"yt-bytes\n")
    rss.write_bytes(b"rss-bytes\n")
    apply_vault_scaffold_update(vault)
    assert yt.read_bytes() == b"yt-bytes\n"
    assert rss.read_bytes() == b"rss-bytes\n"
