"""Per-module YAML + Python validators (FR validator surface)."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

import yaml

from .discovery import ModuleManifest
from .isolation import isolated_call
from .signal import SignalPayload

logger = logging.getLogger(__name__)


def validators_yaml_path(vault_dir: Path, module: str) -> Path:
    return vault_dir / f"{module}.validators.yaml"


def validators_py_path(vault_dir: Path, module: str) -> Path:
    return vault_dir / f"{module}.validators.py"


def validate_yaml_rules(payload: SignalPayload, rules: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    facts_rules = rules.get("facts") or {}
    if not isinstance(facts_rules, dict):
        return errors
    for bucket, constraints in facts_rules.items():
        if not isinstance(constraints, dict):
            continue
        value = payload.facts.get(bucket)
        if constraints.get("required") and value is None:
            errors.append(f"facts.{bucket} is required")
        if isinstance(value, list) and "min_items" in constraints:
            min_items = int(constraints["min_items"])
            if len(value) < min_items:
                errors.append(f"facts.{bucket} needs at least {min_items} items")
    return errors


def load_yaml_validator(vault_dir: Path, module: str) -> dict[str, Any] | None:
    path = validators_yaml_path(vault_dir, module)
    if not path.is_file():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None


def _load_python_validator(vault_dir: Path, module: str):
    path = validators_py_path(vault_dir, module)
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"{module}_validators", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "validate", None)


def validate_payload(
    vault_dir: Path,
    manifest: ModuleManifest,
    payload: SignalPayload,
) -> list[str]:
    """Run vault validators; default is JSON-schema conformance only (no files)."""
    errors: list[str] = []
    yaml_rules = load_yaml_validator(vault_dir, manifest.name)
    if yaml_rules is not None:
        errors.extend(validate_yaml_rules(payload, yaml_rules))
    py_validate = _load_python_validator(vault_dir, manifest.name)
    if py_validate is not None:

        def _run() -> list[str]:
            result = py_validate(payload.to_dict())
            if not isinstance(result, list):
                raise TypeError("validate() must return list[str]")
            return [str(x) for x in result]

        py_errors = isolated_call(
            _run,
            vault_dir=vault_dir,
            module=manifest.name,
            source_id=payload.source_id,
            kind="validator",
        )
        if py_errors is None:
            errors.append("validator raised after retry")
        else:
            errors.extend(py_errors)
    if yaml_rules is None and py_validate is None:
        # An ``ok`` verdict must carry SOME signal, but notable-only modules
        # (all Tier-1 ports + github/atlassian) legitimately emit ``facts: {}``
        # with observations in ``notable``. Only a wholly-empty ``ok`` — no
        # facts AND no notable — is a contract violation. (Spec 047 validation
        # run, 2026-06-08: the prior facts-only rule marked every successful
        # notable-module extraction source-health FAILED.)
        if payload.verdict == "ok" and not payload.facts and not payload.notable:
            errors.append(
                "an 'ok' verdict requires non-empty 'facts' or a non-empty "
                "'notable' list"
            )
    return errors
