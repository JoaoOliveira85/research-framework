"""Per-(vault, module) facts schema generation + drift detection (D8)."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from research_framework._assets import asset_path

from .cache import atomic_write_json, module_sources_dir
from .errors import StaleManualSchemaError

logger = logging.getLogger(__name__)

_FALLBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "technologies": {"type": "array"},
        "patterns": {"type": "array"},
        "notable": {"type": "array"},
    },
    "required": ["technologies", "patterns", "notable"],
}


def spec_hash(spec_path: Path) -> str:
    return hashlib.sha256(spec_path.read_bytes()).hexdigest()


def schema_gen_hash_path(vault_dir: Path, module: str) -> Path:
    return module_sources_dir(vault_dir, module) / ".schema-gen-hash"


def facts_schema_path(vault_dir: Path, module: str) -> Path:
    return module_sources_dir(vault_dir, module) / "facts-schema.json"


def load_facts_schema(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Unreadable facts-schema.json at %s", path)
        return {}


def schema_gen_prompt_path() -> Path:
    return (
        asset_path("specs")
        / "020-code-bridge"
        / "contracts"
        / "facts-schema-gen-prompt.md"
    )


def load_schema_gen_prompt() -> str:
    path = schema_gen_prompt_path()
    if path.is_file():
        return path.read_text(encoding="utf-8")
    repo = Path(__file__).resolve().parents[4]
    fallback = repo / "specs/020-code-bridge/contracts/facts-schema-gen-prompt.md"
    return fallback.read_text(encoding="utf-8")


def write_fallback_schema(
    vault_dir: Path, module: str, *, reason: str
) -> dict[str, Any]:
    logger.warning("Schema-gen fallback for %s: %s", module, reason)
    schema = dict(_FALLBACK_SCHEMA)
    schema["manually_edited"] = False
    schema["generated_by"] = "fallback"
    path = facts_schema_path(vault_dir, module)
    atomic_write_json(path, schema)
    return schema


def write_schema_gen_hash(vault_dir: Path, module: str, spec_path: Path) -> None:
    atomic_write_json(
        schema_gen_hash_path(vault_dir, module),
        {"spec_hash": spec_hash(spec_path)},
    )


def run(
    vault_dir: Path,
    module: str,
    spec_path: Path | None = None,
    *,
    agent_response: dict[str, Any] | None = None,
    force_stale_schema: bool = False,
) -> dict[str, Any]:
    """Generate or validate ``facts-schema.json`` for a module."""
    spec_path = spec_path or (vault_dir / "research.spec.md")
    schema_path = facts_schema_path(vault_dir, module)
    module_sources_dir(vault_dir, module).mkdir(parents=True, exist_ok=True)
    current_hash = spec_hash(spec_path)
    hash_path = schema_gen_hash_path(vault_dir, module)
    stored_hash = ""
    if hash_path.is_file():
        try:
            stored_hash = json.loads(hash_path.read_text(encoding="utf-8")).get(
                "spec_hash", ""
            )
        except json.JSONDecodeError:
            stored_hash = ""

    existing = load_facts_schema(schema_path) if schema_path.is_file() else {}
    if existing.get("manually_edited"):
        if stored_hash and stored_hash != current_hash:
            _write_drift_sidecars(vault_dir, module, existing, agent_response)
            if not force_stale_schema:
                raise StaleManualSchemaError(
                    f"Manual schema drift detected for module {module!r}"
                )
        return existing

    if agent_response is None:
        schema = dict(_FALLBACK_SCHEMA)
    else:
        schema = agent_response
    if not _is_valid_json_schema(schema):
        return write_fallback_schema(vault_dir, module, reason="invalid JSON Schema")
    schema.setdefault("manually_edited", False)
    atomic_write_json(schema_path, schema)
    write_schema_gen_hash(vault_dir, module, spec_path)
    return schema


def _is_valid_json_schema(schema: dict[str, Any]) -> bool:
    return isinstance(schema, dict) and (
        "type" in schema or "properties" in schema or "$schema" in schema
    )


def _write_drift_sidecars(
    vault_dir: Path,
    module: str,
    manual: dict[str, Any],
    regenerated: dict[str, Any] | None,
) -> None:
    mod_dir = module_sources_dir(vault_dir, module)
    regen = regenerated or dict(_FALLBACK_SCHEMA)
    atomic_write_json(mod_dir / "facts-schema.regenerated.json", regen)
    drift_md = mod_dir / "facts-schema.drift.md"
    drift_md.write_text(
        f"# Schema Drift Detected: {module}\n\n"
        "Manual schema no longer matches current research.spec.md hash.\n",
        encoding="utf-8",
    )


def acknowledge_drift(
    vault_dir: Path, module: str, spec_path: Path | None = None
) -> None:
    """Merge regenerated schema and clear drift sidecars."""
    spec_path = spec_path or (vault_dir / "research.spec.md")
    mod_dir = module_sources_dir(vault_dir, module)
    regen_path = mod_dir / "facts-schema.regenerated.json"
    if regen_path.is_file():
        atomic_write_json(
            facts_schema_path(vault_dir, module), json.loads(regen_path.read_text())
        )
    for name in ("facts-schema.regenerated.json", "facts-schema.drift.md"):
        (mod_dir / name).unlink(missing_ok=True)
    write_schema_gen_hash(vault_dir, module, spec_path)
