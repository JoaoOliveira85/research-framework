"""Spec 027 (FR-010 / SC-005): the ``./vault update`` CLI test MUST be
registered in ``build.sh::SMOKE_TESTS`` so a release can never ship an
update path that silently breaks vault upgrades.

Distinct from ``test_smoke_gate_enforces_contract_tier.py`` (which pins the
spec-019 contract-tier set and on-disk existence): this guard additionally
asserts the vault-update entry carries a *provenance comment* citing spec
027 / FR-010 / SC-005, so a future trim is a deliberate, reviewable change.

Companion: ``specs/027-vault-update-hardening/spec.md`` US1 + FR-010.
"""

from __future__ import annotations

import re
from pathlib import Path

BUILD_SH = Path(__file__).resolve().parents[2] / "build.sh"

_VAULT_UPDATE_ENTRY = "tests/cli/test_vault_update.py"


def _smoke_tests_block() -> str:
    text = BUILD_SH.read_text(encoding="utf-8")
    match = re.search(r"SMOKE_TESTS=\(\n(.*?)\n\)", text, re.DOTALL)
    assert match, "could not locate SMOKE_TESTS=(...) block in build.sh"
    return match.group(1)


def test_vault_update_registered_in_smoke_tests() -> None:
    """FR-010: ``tests/cli/test_vault_update.py`` is in SMOKE_TESTS, carrying
    a comment that cites spec 027 / FR-010 / SC-005 for provenance."""
    block = _smoke_tests_block()
    quoted = [
        m.group(1)
        for line in block.splitlines()
        if (m := re.match(r'"([^"]+)"', line.strip()))
    ]
    assert _VAULT_UPDATE_ENTRY in quoted, (
        f"{_VAULT_UPDATE_ENTRY} must be registered in build.sh::SMOKE_TESTS "
        "(spec 027 FR-010 release gate)."
    )

    text = BUILD_SH.read_text(encoding="utf-8")
    assert re.search(r"#.*spec 027", text, re.IGNORECASE), (
        "the vault-update smoke entry must carry a comment citing spec 027."
    )
    assert "FR-010" in text and "SC-005" in text, (
        "the vault-update smoke entry comment must cite FR-010 / SC-005."
    )
