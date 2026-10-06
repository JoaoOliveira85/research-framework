"""Regression test for B.4 — path-prefixed wikilinks resolve in `validate_vault.py`.

Pre-0.7.0, `_vault_note_stems` returned only bare filename stems, so a
related-link of the form `[[Folder/Note]]` always tripped the "file not
found" violation even when `Folder/Note.md` existed. On the feeds-vault
revival this generated 2,120+ false SG-004 WARNs per cycle and made the
gate report unreadable.

This test pins both halves of the fix:
  - Stem set now includes relative paths (`folder/note`).
  - Related-link lookup accepts bare stem, full path, and case-folded
    variants.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# `scripts/validate_vault.py` isn't a package module — load it by file path.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "validate_vault", _PROJECT_ROOT / "scripts" / "validate_vault.py"
)
assert _SPEC is not None and _SPEC.loader is not None
validate_vault = importlib.util.module_from_spec(_SPEC)
sys.modules["validate_vault"] = validate_vault
_SPEC.loader.exec_module(validate_vault)


def _write_note(path: Path, frontmatter: str, body: str = "x " * 250) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n{body}\n", encoding="utf-8")


def test_stem_set_includes_relative_paths(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "data_vault" / "04 - Concepts").mkdir(parents=True)
    (vault / "data_vault" / "04 - Concepts" / "Sample.md").write_text(
        "---\ntitle: Sample\ntype: concept\n---\nbody\n", encoding="utf-8"
    )
    stems = validate_vault._vault_note_stems(vault)
    assert "sample" in stems
    assert "04 - concepts/sample" in stems


def _link_violations(violations) -> list:
    """Filter to the `field=='related' AND 'file not found' in message` ones —
    excludes the unrelated "required field missing" violation on bare notes."""
    return [v for v in violations if v.field == "related" and "not found" in v.message]


def test_path_prefixed_related_link_resolves(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    target = vault / "data_vault" / "04 - Concepts" / "Sample.md"
    referrer = vault / "data_vault" / "05 - Issues" / "Referrer.md"
    _write_note(
        target,
        "title: Sample\ntype: concept\nsource_urls:\n  - 'https://x'\n"
        "related:\n  - '05 - Issues/Referrer'\n",
    )
    _write_note(
        referrer,
        'title: Referrer\ntype: issue\nsource_urls:\n  - "https://y"\n'
        "related:\n  - '04 - Concepts/Sample'\n",
    )
    violations, _warnings = validate_vault.validate(vault)
    assert not _link_violations(violations), (
        "path-prefixed related link should resolve when the file exists; "
        f"got: {_link_violations(violations)}"
    )


def test_case_mismatch_in_path_prefixed_link_resolves(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    target = vault / "data_vault" / "04 - Concepts" / "Sample.md"
    referrer = vault / "data_vault" / "05 - Issues" / "Referrer.md"
    _write_note(
        target,
        "title: Sample\ntype: concept\nsource_urls:\n  - 'https://x'\n"
        "related:\n  - '05 - Issues/Referrer'\n",
    )
    _write_note(
        referrer,
        'title: Referrer\ntype: issue\nsource_urls:\n  - "https://y"\n'
        "related:\n  - '04 - concepts/sample'\n",  # lowercased!
    )
    violations, _warnings = validate_vault.validate(vault)
    assert not _link_violations(violations)


def test_genuinely_missing_target_still_flags(tmp_path: Path) -> None:
    """Guard rail: a related link to a file that truly doesn't exist must still fail."""
    vault = tmp_path / "vault"
    referrer = vault / "data_vault" / "05 - Issues" / "Referrer.md"
    _write_note(
        referrer,
        'title: Referrer\ntype: issue\nsource_urls:\n  - "https://y"\n'
        "related:\n  - '04 - Concepts/Does Not Exist'\n",
    )
    violations, _warnings = validate_vault.validate(vault)
    assert any("Does Not Exist" in v.message for v in _link_violations(violations)), (
        "missing file should still raise the related-link violation"
    )


def test_titlecase_related_link_resolves_to_snake_case_file(tmp_path: Path) -> None:
    """rc5 reference-vault finding (#4): a natural-language ``related`` link with
    spaces must resolve to the snake_case file on disk. Previously
    ``[[Outcome Matrix Order Vector Calculation]]`` never matched
    ``outcome_matrix_order_vector_calculation.md`` → bulk "file not found"
    violations that drove note quarantines."""
    vault = tmp_path / "vault"
    target = (
        vault
        / "data_vault"
        / "06 - Algorithms"
        / "outcome_matrix_order_vector_calculation.md"
    )
    referrer = vault / "data_vault" / "07 - APIs" / "order_validation_api_surface.md"
    _write_note(
        target,
        "title: OMLVC\ntype: algorithm-ds\nsource_urls:\n  - 'https://x'\nrelated: []\n",
    )
    _write_note(
        referrer,
        "title: PBRCAS\ntype: api-protocol\nsource_urls:\n  - 'https://y'\n"
        "related:\n  - '[[Outcome Matrix Order Vector Calculation]]'\n",
    )
    violations, _warnings = validate_vault.validate(vault)
    assert not _link_violations(violations), (
        "title-style related link should resolve to its snake_case file; "
        f"got: {_link_violations(violations)}"
    )


def test_titlecase_related_link_to_missing_file_still_flags(tmp_path: Path) -> None:
    """Guard rail: space-normalization must NOT invent targets — a title-style
    link to a file that doesn't exist still fails."""
    vault = tmp_path / "vault"
    referrer = vault / "data_vault" / "07 - APIs" / "referrer.md"
    _write_note(
        referrer,
        "title: R\ntype: api-protocol\nsource_urls:\n  - 'https://y'\n"
        "related:\n  - '[[No Such Note At All]]'\n",
    )
    violations, _warnings = validate_vault.validate(vault)
    assert any("No Such Note At All" in v.message for v in _link_violations(violations))


def test_alias_redirect_stub_is_exempt_from_full_schema(tmp_path: Path) -> None:
    """rc5 reference-vault finding (#3): acronym redirect stubs (``note_type: alias``,
    written verbatim by ``pipeline/wikilinks.resolve_acronym_links``) are
    intentionally minimal — title + note_type + redirect_to + verifier_status
    and a one-line body. The validator must EXEMPT them from the full-note
    schema (required fields + word-count floor); otherwise every generated stub
    reports a fistful of spurious violations — the dominant driver of the rc5
    reference-vault 113->246 violation growth (the framework failing notes it
    generates itself)."""
    vault = tmp_path / "vault"
    stub = vault / "data_vault" / "oecdh.md"
    stub.parent.mkdir(parents=True, exist_ok=True)
    # Exact shape resolve_acronym_links emits (see pipeline/wikilinks.py): no
    # source_urls, no summary, no type, two-word body — all of which the
    # full-note schema would otherwise flag.
    stub.write_text(
        "---\n"
        "title: OECDH\n"
        "note_type: alias\n"
        "redirect_to: order-engine-customer-data-handler\n"
        "verifier_status: exempt\n"
        "---\n"
        "See [[order-engine-customer-data-handler]].\n",
        encoding="utf-8",
    )
    violations, _warnings = validate_vault.validate(vault)
    stub_violations = [v for v in violations if v.file == stub]
    assert not stub_violations, (
        "alias redirect stub must be exempt from the full-note schema; "
        f"got: {stub_violations}"
    )
