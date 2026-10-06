"""CLI acknowledge-drift command tests."""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.cli.schema import main as schema_main
from research_framework.pipeline.source_bridge.schema_gen import facts_schema_path


def test_schema_acknowledge_drift_merges_and_clears_sidecars(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    mod_dir = vault / "_pipeline" / "sources" / "code"
    mod_dir.mkdir(parents=True)
    (vault / "research.spec.md").write_text("# Spec\n", encoding="utf-8")
    regen = {"type": "object", "properties": {"merged": {"type": "string"}}}
    (mod_dir / "facts-schema.regenerated.json").write_text(
        json.dumps(regen) + "\n",
        encoding="utf-8",
    )
    (mod_dir / "facts-schema.drift.md").write_text("# drift\n", encoding="utf-8")
    schema_main(["acknowledge-drift", "code", "--vault", str(vault)])
    assert not (mod_dir / "facts-schema.drift.md").exists()
    schema = json.loads(facts_schema_path(vault, "code").read_text(encoding="utf-8"))
    assert "merged" in schema.get("properties", {})
