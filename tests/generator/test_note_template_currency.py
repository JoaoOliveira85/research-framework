"""Tier 3: the rendered note template stamps the currency fields (spec 087)."""

from __future__ import annotations

from pathlib import Path

from research_framework.generator.templates import render_all
from research_framework.processors.verify import _declared_note_format
from research_framework.spec.simple import expand, parse_simple
from research_framework.vault import note_currency
from research_framework.vault.frontmatter import parse_frontmatter

_SPEC = """\
---
name: "Currency Vault"
owner: "tester"
topic: "A small topic for currency tests"
note_types:
  - case
---

Body.
"""


def test_template_stamps_both_keys_empty_and_verify_requires_them(
    tmp_path: Path,
) -> None:
    spec_path = tmp_path / "research.spec.md"
    spec_path.write_text(_SPEC, encoding="utf-8")
    vault = tmp_path / "vault"
    (vault / "_templates").mkdir(parents=True)
    (vault / "_pipeline" / "prompts").mkdir(parents=True)
    (vault / ".claude" / "commands").mkdir(parents=True)
    render_all(expand(parse_simple(spec_path), location=vault), vault)

    template = vault / "_templates" / "case.md"
    fm, _ = parse_frontmatter(template)
    assert fm[note_currency.AS_OF_FIELD] == ""
    assert fm[note_currency.CURRENCY_FIELD] == ""
    assert f'{note_currency.AS_OF_FIELD}: ""' in template.read_text("utf-8")
    assert f'{note_currency.CURRENCY_FIELD}: ""' in template.read_text("utf-8")

    required = _declared_note_format(vault / "_templates")
    assert note_currency.AS_OF_FIELD in required
    assert note_currency.CURRENCY_FIELD in required
