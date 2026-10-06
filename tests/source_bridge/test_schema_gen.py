"""Schema generation tests (spec 020 US4)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_framework.pipeline.source_bridge.schema_gen import (
    facts_schema_path,
    load_schema_gen_prompt,
    schema_gen_hash_path,
)
from research_framework.pipeline.source_bridge.schema_gen import (
    run as schema_gen_run,
)


def test_schema_gen_happy_path_writes_facts_schema(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    spec = vault / "research.spec.md"
    spec.write_text("# Spec\n", encoding="utf-8")
    schema = schema_gen_run(
        vault,
        "code",
        spec,
        agent_response={"type": "object", "properties": {"foo": {"type": "string"}}},
    )
    assert schema
    assert facts_schema_path(vault, "code").is_file()


def test_schema_gen_invalid_json_schema_falls_back_three_buckets(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    spec = vault / "research.spec.md"
    spec.write_text("# Spec\n", encoding="utf-8")
    schema_gen_run(vault, "code", spec, agent_response={"not": "a schema"})
    schema = json.loads(facts_schema_path(vault, "code").read_text(encoding="utf-8"))
    assert set(schema["properties"]) == {"technologies", "patterns", "notable"}


def test_manually_edited_skips_overwrite(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    spec = vault / "research.spec.md"
    spec.write_text("# Spec\n", encoding="utf-8")
    path = facts_schema_path(vault, "code")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"manually_edited": True, "type": "object"}) + "\n",
        encoding="utf-8",
    )
    schema_gen_run(vault, "code", spec, agent_response={"type": "object"})
    assert "manually_edited" in path.read_text(encoding="utf-8")


def test_schema_gen_prompt_loaded_from_contract() -> None:
    prompt = load_schema_gen_prompt()
    assert "facts-schema" in prompt.lower() or "schema" in prompt.lower()


def test_schema_gen_dispatches_via_agent_call_stub(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    spec = vault / "research.spec.md"
    spec.write_text("# Spec\n", encoding="utf-8")
    schema_gen_run(
        vault,
        "code",
        spec,
        agent_response={"type": "object", "properties": {}},
    )
    assert facts_schema_path(vault, "code").is_file()


def test_three_bucket_fallback_on_invalid_schema(tmp_path: Path) -> None:
    test_schema_gen_invalid_json_schema_falls_back_three_buckets(tmp_path)


def test_schema_gen_hash_written_from_spec_bytes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    spec = vault / "research.spec.md"
    body = b"# Spec bytes\n"
    spec.write_bytes(body)
    schema_gen_run(
        vault,
        "code",
        spec,
        agent_response={"type": "object", "properties": {"x": {"type": "string"}}},
    )
    stored = json.loads(schema_gen_hash_path(vault, "code").read_text(encoding="utf-8"))
    assert stored["spec_hash"] == hashlib.sha256(body).hexdigest()


def test_manually_edited_true_preserves_facts_schema_json(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    spec = vault / "research.spec.md"
    spec.write_text("# Spec\n", encoding="utf-8")
    path = facts_schema_path(vault, "code")
    path.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"manually_edited": True, "custom": 1})
    path.write_text(original + "\n", encoding="utf-8")
    schema_gen_run(vault, "code", spec, agent_response={"type": "object"})
    assert path.read_text(encoding="utf-8").strip() == original


def test_sc006_schemas_differ_across_fixture_vaults(tmp_path: Path) -> None:
    web = tmp_path / "web"
    emb = tmp_path / "emb"
    for vault, body in (
        (web, "web microservices kubernetes\n"),
        (emb, "embedded firmware RTOS MCU\n"),
    ):
        vault.mkdir()
        (vault / "research.spec.md").write_text(body, encoding="utf-8")
        schema_gen_run(
            vault,
            "code",
            vault / "research.spec.md",
            agent_response={
                "type": "object",
                "properties": {"domain": {"const": body.split()[0]}},
            },
        )
    web_schema = json.loads(facts_schema_path(web, "code").read_text(encoding="utf-8"))
    emb_schema = json.loads(facts_schema_path(emb, "code").read_text(encoding="utf-8"))
    assert web_schema != emb_schema
