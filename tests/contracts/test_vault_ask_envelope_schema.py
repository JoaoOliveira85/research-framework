"""Tier-2 contract test for the spec-036 ``./vault ask --format json`` envelope.

ADR-0013 decided that a cross-repo payload gets its JSON Schema *before* its
producer, carries ``schema_version`` in the payload, and evolves append-only
within a major. ``tests/contracts/vault-ask-1.0.schema.json`` is the first
schema written under that rule, and — deliberately — there is no producer
yet: spec 036 FR-001's ``--format json`` flag is unbuilt (036 T001). So the
fixtures below are hand-written contract fixtures, not real output, and the
module says so rather than pretending otherwise. When the producer lands, a
second test validates what it actually writes, the way #326 did for
``pipeline-state.json`` in ``test_json_schema_validation.py``; this module
stays, because it pins the *policy* (additive within ``1.x``, refuse ``2.x``)
independently of any producer's behaviour.

Constitution Principle XI grades the ``ask`` envelope row **Not met** because
the file this module reads did not exist. The row is not amended here (the
1.6.0 pass owns it); this is the written form, not the mirror or the guard.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "tests" / "contracts" / "vault-ask-1.0.schema.json"


def _schema() -> dict:
    assert SCHEMA_PATH.is_file(), (
        f"{SCHEMA_PATH.relative_to(REPO_ROOT)} does not exist — spec 036 FR-004 "
        "and ADR-0013 §4 require the envelope's schema to be committed before "
        "any producer"
    )
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _minimal_envelope() -> dict:
    """The smallest payload spec 036 FR-003 allows: the four required keys."""
    return {
        "schema_version": "1.0",
        "answer": "Deploy a three-node ring with replication factor 3.",
        "citations": [
            {
                "note_path": "data_vault/concepts/cassandra-cluster.md",
                "snippet": "A three-node ring with RF=3 tolerates one node loss.",
            }
        ],
        "confidence": 0.82,
    }


def _validate(payload: dict) -> None:
    jsonschema.validate(payload, _schema(), cls=Draft202012Validator)


# --- The schema itself -------------------------------------------------------


def test_schema_is_a_valid_2020_12_schema() -> None:
    Draft202012Validator.check_schema(_schema())


def test_schema_declares_its_identity_and_version_family() -> None:
    schema = _schema()
    assert schema["$id"].endswith("/vault-ask-1.0.json")
    assert schema["title"] == "VaultAskEnvelopeV1"
    assert schema["properties"]["schema_version"]["pattern"] == r"^1\.[0-9]+$"


def test_schema_requires_exactly_the_fr_003_required_keys() -> None:
    """Spec 036 FR-003: `schema_version`, `answer`, `citations`, `confidence`
    are required; `source_urls`, `cost_usd`, `low_confidence_reason` are not."""
    schema = _schema()
    assert set(schema["required"]) == {
        "schema_version",
        "answer",
        "citations",
        "confidence",
    }
    for optional in ("source_urls", "cost_usd", "low_confidence_reason"):
        assert optional in schema["properties"]
        assert optional not in schema["required"]


# --- Payloads the contract accepts --------------------------------------------


def test_minimal_envelope_validates() -> None:
    _validate(_minimal_envelope())


def test_full_envelope_with_every_optional_field_validates() -> None:
    payload = _minimal_envelope()
    payload.update(
        {
            "source_urls": ["https://example.invalid/cassandra/docs"],
            "cost_usd": 0.0123,
            "low_confidence_reason": "",
        }
    )
    _validate(payload)


def test_cannot_answer_shape_validates() -> None:
    """Spec 036 FR-006: when nothing relevant exists the envelope is still
    emitted — empty answer, zero confidence, a reason — never omitted."""
    _validate(
        {
            "schema_version": "1.0",
            "answer": "",
            "citations": [],
            "confidence": 0.0,
            "low_confidence_reason": "no relevant notes found",
        }
    )


def test_a_later_minor_with_an_unknown_optional_field_validates() -> None:
    """ADR-0013 §2, pinned: a `1.0` consumer accepts every `1.x` payload,
    unknown fields included. This is the additive rule as a test, so a
    future edit that flips `additionalProperties` to false fails here."""
    payload = _minimal_envelope()
    payload["schema_version"] = "1.3"
    payload["reasoning_trace"] = ["not in 1.0", "ignored by a 1.0 consumer"]
    _validate(payload)


# --- Payloads the contract refuses --------------------------------------------


def test_an_unknown_major_is_refused() -> None:
    """ADR-0013 §3: a consumer refuses a major it does not know; the schema
    for `1.0` must not quietly accept a `2.0` payload."""
    payload = _minimal_envelope()
    payload["schema_version"] = "2.0"
    with pytest.raises(jsonschema.ValidationError):
        _validate(payload)


@pytest.mark.parametrize(
    "missing", ["schema_version", "answer", "citations", "confidence"]
)
def test_each_required_key_is_required(missing: str) -> None:
    payload = _minimal_envelope()
    del payload[missing]
    with pytest.raises(jsonschema.ValidationError):
        _validate(payload)


@pytest.mark.parametrize("confidence", [-0.01, 1.01, "0.5"])
def test_confidence_outside_the_unit_interval_or_not_a_number_is_refused(
    confidence: object,
) -> None:
    payload = _minimal_envelope()
    payload["confidence"] = confidence
    with pytest.raises(jsonschema.ValidationError):
        _validate(payload)


def test_a_citation_without_a_note_path_is_refused() -> None:
    """A citation is a vault note (Principle IX, Tier 1); a snippet with no
    path is a quotation from nowhere."""
    payload = _minimal_envelope()
    payload["citations"] = [{"snippet": "unattributed"}]
    with pytest.raises(jsonschema.ValidationError):
        _validate(payload)


def test_a_citation_with_an_empty_note_path_is_refused() -> None:
    payload = _minimal_envelope()
    payload["citations"] = [{"note_path": "", "snippet": "x"}]
    with pytest.raises(jsonschema.ValidationError):
        _validate(payload)


def test_a_negative_cost_is_refused() -> None:
    payload = _minimal_envelope()
    payload["cost_usd"] = -1.0
    with pytest.raises(jsonschema.ValidationError):
        _validate(payload)
