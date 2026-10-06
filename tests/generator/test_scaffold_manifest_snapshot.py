import json
from pathlib import Path

from research_framework.generator.scaffold import apply_vault_scaffold_update
from tests._helpers.vault_factory import build_minimal_vault

REPO = Path(__file__).resolve().parents[2]


def test_update_writes_scaffold_manifest_snapshot_json(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    apply_vault_scaffold_update(vault)
    snap = vault / "_pipeline" / "scaffold-manifest-snapshot.json"
    assert snap.is_file()
    doc = json.loads(snap.read_text())
    assert "framework_version" in doc and "captured_at" in doc and "entries" in doc


def test_snapshot_scripts_user_owned_lists_unlisted_scripts(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    (vault / "scripts" / "collect_youtube.py").write_text("# yt\n", encoding="utf-8")
    apply_vault_scaffold_update(vault)
    doc = json.loads((vault / "_pipeline/scaffold-manifest-snapshot.json").read_text())
    assert "scripts/collect_youtube.py" in doc["scripts_user_owned"]


def test_dist_manifest_vault_entry_not_user_owned_after_first_write() -> None:
    manifest = json.loads((REPO / "dist-templates/scaffold-manifest.json").read_text())
    entry = next(e for e in manifest["entries"] if e["path"] == "vault")
    assert entry["is_user_owned_after_first_write"] is False
