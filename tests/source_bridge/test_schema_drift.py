"""Schema drift detection tests (spec 020 D8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.source_bridge.errors import StaleManualSchemaError
from research_framework.pipeline.source_bridge.schema_gen import (
    facts_schema_path,
    schema_gen_hash_path,
)
from research_framework.pipeline.source_bridge.schema_gen import (
    run as schema_gen_run,
)


def _seed_manual(vault: Path, spec_hash: str) -> None:
    mod_dir = vault / "_pipeline" / "sources" / "code"
    mod_dir.mkdir(parents=True, exist_ok=True)
    facts_schema_path(vault, "code").write_text(
        json.dumps({"manually_edited": True, "type": "object"}) + "\n",
        encoding="utf-8",
    )
    schema_gen_hash_path(vault, "code").write_text(
        json.dumps({"spec_hash": spec_hash}) + "\n",
        encoding="utf-8",
    )


def test_drift_writes_sidecar_and_drift_md(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    spec = vault / "research.spec.md"
    spec.write_text("version one\n", encoding="utf-8")
    _seed_manual(vault, "oldhash")
    spec.write_text("version two\n", encoding="utf-8")
    with pytest.raises(StaleManualSchemaError):
        schema_gen_run(vault, "code", spec, agent_response={"type": "object"})
    mod_dir = vault / "_pipeline" / "sources" / "code"
    assert (mod_dir / "facts-schema.regenerated.json").is_file()
    assert (mod_dir / "facts-schema.drift.md").is_file()


def test_drift_fail_closed_raises_stale_manual_schema_error(tmp_path: Path) -> None:
    test_drift_writes_sidecar_and_drift_md(tmp_path)


def test_force_stale_schema_allows_proceed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    spec = vault / "research.spec.md"
    spec.write_text("v1\n", encoding="utf-8")
    _seed_manual(vault, "old")
    spec.write_text("v2\n", encoding="utf-8")
    out = schema_gen_run(
        vault,
        "code",
        spec,
        agent_response={"type": "object"},
        force_stale_schema=True,
    )
    assert out.get("manually_edited") is True


def test_stale_manual_schema_error_on_hash_mismatch(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    spec = vault / "research.spec.md"
    spec.write_text("a\n", encoding="utf-8")
    _seed_manual(vault, "mismatch")
    spec.write_text("b\n", encoding="utf-8")
    with pytest.raises(StaleManualSchemaError):
        schema_gen_run(vault, "code", spec)
