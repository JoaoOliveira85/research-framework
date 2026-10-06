"""Tier-2 contract test: the claims export validates against its schema (#189).

Same discipline as ``test_json_schema_validation.py``: the document under
test is REAL output of the production writer (``vault.claims_export``) over a
real vault, never a hand-typed literal that merely looks like the shape.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import pytest

from research_framework.vault.claims_export import SCHEMA_VERSION, export_claims
from research_framework.vault.frontmatter import dump_frontmatter
from tests._helpers.vault_factory import build_minimal_vault

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "tests" / "contracts" / "claims-export-1.0.schema.json"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _vault_with_notes(tmp_path: Path) -> Path:
    vault = build_minimal_vault(tmp_path, install_fake_agent=False)
    folder = vault / "data_vault" / "01 - Concepts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "alpha.md").write_text(
        dump_frontmatter(
            {
                "title": "Alpha",
                "type": "concept",
                "summary": "Alpha is first.",
                "tags": ["a"],
                "source_urls": [
                    "https://example.test/plain",
                    {"url": "https://example.test/rich", "credibility": "primary"},
                ],
                "related": [],
                "created": "2026-09-01",
                "updated": "2026-09-01",
                "verifier_status": "verified",
            },
            "# Alpha\n\nbody\n",
        ),
        encoding="utf-8",
    )
    q = vault / "_pipeline" / "quarantine"
    q.mkdir(parents=True)
    (q / "bad.md").write_text(
        dump_frontmatter(
            {"title": "Bad", "type": "concept", "summary": "s", "source_urls": []},
            "# Bad\n",
        ),
        encoding="utf-8",
    )
    return vault


def test_schema_file_names_the_version_the_writer_emits() -> None:
    """ADR-0013 §2: the schema accepts every 1.x, so it pins a pattern, not a
    const — and the writer's version must be one the pattern admits."""
    schema = _schema()
    pattern = schema["properties"]["schema_version"]["pattern"]
    assert re.fullmatch(pattern, SCHEMA_VERSION)
    assert SCHEMA_VERSION.startswith("1.")
    assert SCHEMA_PATH.name == f"claims-export-{SCHEMA_VERSION}.schema.json"


def test_a_later_minor_still_validates(tmp_path: Path) -> None:
    """A 1.0 consumer accepts a 1.7 payload (ADR-0013 §2); a 2.0 is refused."""
    vault = _vault_with_notes(tmp_path)
    doc = export_claims(vault)
    doc["schema_version"] = "1.7"
    jsonschema.validate(doc, _schema())


def test_real_export_validates_against_the_schema(tmp_path: Path) -> None:
    vault = _vault_with_notes(tmp_path)
    doc = export_claims(vault, include_quarantined=True)
    assert doc["counts"]["claims"] == 2  # not vacuous: both records are checked
    jsonschema.validate(doc, _schema())


def test_json_round_trip_validates(tmp_path: Path) -> None:
    """What a subprocess consumer parses off stdout, not the in-memory dict."""
    vault = _vault_with_notes(tmp_path)
    text = json.dumps(export_claims(vault), indent=2, ensure_ascii=False)
    jsonschema.validate(json.loads(text), _schema())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("schema_version"),
        lambda d: d.__setitem__("schema_version", "2.0"),
        lambda d: d["claims"][0].pop("claim"),
        lambda d: d["claims"][0].__setitem__("support_count", "2"),
        lambda d: d["claims"][0]["sources"][0].pop("url"),
        lambda d: d["claims"][0]["sources"][1].__setitem__("credibility", "solid"),
    ],
)
def test_schema_rejects_a_broken_document(tmp_path: Path, mutate) -> None:
    vault = _vault_with_notes(tmp_path)
    doc = export_claims(vault)
    mutate(doc)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, _schema())


def test_schema_is_additive_unknown_fields_are_allowed(tmp_path: Path) -> None:
    """Owner decision D5: append-only within 1.x — a 1.1 producer may add
    fields and a 1.0 consumer must not choke on them."""
    vault = _vault_with_notes(tmp_path)
    doc = export_claims(vault)
    doc["future_field"] = {"anything": 1}
    doc["claims"][0]["future_claim_field"] = "x"
    doc["claims"][0]["sources"][0]["future_source_field"] = 0.5
    jsonschema.validate(doc, _schema())
