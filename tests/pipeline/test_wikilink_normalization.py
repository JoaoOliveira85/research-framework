"""spec-019 / 0.2.31 \u2014 auto-normalize wikilinks after note-writer.

Background \u2014 user trial-run audit 2026-05-18:

`vault_health.py` reported **207 case-broken wikilinks** in
reference-vault-0.2.30. The note-writer agent emits natural-language
wikilinks (`[[Cassandra]]`, `[[OMS]]`, `[[Kafka]]`) while the
filename convention is lowercase-snake (`cassandra.md`, `oms.md`,
`kafka.md`). Obsidian + the framework's wikilink resolver treat these
as different references \u2014 the entire vault graph fragments.

`vault_health.py` already has the `apply_wikilink_fixes()` function
that handles the `moved` classification (case mismatch where a
lowercase target exists). 0.2.31 wires this into the cycle_runner as
an automatic post-cycle step so each cycle leaves the graph clean
instead of accumulating broken links.

These tests lock the contract for the new `auto_fix_moved_wikilinks`
helper. Integration with cycle_runner is covered separately in
`test_cycle_runner.py` once the helper exists.
"""

from __future__ import annotations

from pathlib import Path


def _import_helper():
    """Defer import so the test can run before the helper is added."""
    from research_framework.pipeline.wikilinks import auto_fix_moved_wikilinks

    return auto_fix_moved_wikilinks


def _make_minimal_vault(tmp_path: Path) -> Path:
    """Build the smallest vault layout that exercises the wikilink scan.

    Mirrors the user's reference-vault shape: lowercase-snake filenames in a
    category folder, frontmatter with `related` list, body with inline
    ``[[Target]]`` references.
    """
    vault = tmp_path / "vault"
    (vault / "data_vault" / "01 - Concepts").mkdir(parents=True)
    return vault


def _write_note(
    vault: Path, rel: str, *, related: list[str] | None = None, body: str = ""
) -> Path:
    """Write a minimal note with frontmatter + body."""
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_lines = ["---", "title: T", "summary: s"]
    if related:
        fm_lines.append("related:")
        for r in related:
            fm_lines.append(f"  - '[[{r}]]'")
    fm_lines.append("---")
    fm_lines.append("")
    path.write_text("\n".join(fm_lines) + body, encoding="utf-8")
    return path


# ---- core normalization cases ---------------------------------------------


def test_normalizes_pascalcase_related_to_lowercase_when_target_exists(
    tmp_path: Path,
) -> None:
    """``related: [[Cassandra]]`` becomes ``related: [[cassandra]]`` when
    ``cassandra.md`` exists. The user's #1 wikilink complaint.
    """
    fix = _import_helper()
    vault = _make_minimal_vault(tmp_path)
    _write_note(vault, "data_vault/01 - Concepts/cassandra.md")
    note = _write_note(
        vault,
        "data_vault/01 - Concepts/pim.md",
        related=["Cassandra"],
        body="See [[Cassandra]] for details.",
    )

    fixes = fix(vault)

    text = note.read_text(encoding="utf-8")
    assert fixes >= 1, f"expected \u22651 fix, got {fixes}"
    assert "[[cassandra]]" in text, f"body wikilink not normalized:\n{text}"
    assert "[[Cassandra]]" not in text, "PascalCase wikilink should have been replaced"


def test_normalizes_acronym_wikilinks(tmp_path: Path) -> None:
    """Acronyms like ``[[OMS]]`` \u2192 ``[[oms]]`` when target is lowercase.

    The user's reference-vault had a lot of these (OMS, PIM, WMS, OEHK).
    """
    fix = _import_helper()
    vault = _make_minimal_vault(tmp_path)
    _write_note(vault, "data_vault/01 - Concepts/oms.md")
    note = _write_note(
        vault,
        "data_vault/01 - Concepts/pim.md",
        body="The [[OMS]] aggregates risk events.",
    )

    fix(vault)
    assert "[[oms]]" in note.read_text(encoding="utf-8")


def test_idempotent_when_already_normalized(tmp_path: Path) -> None:
    """Re-running on a clean graph reports 0 fixes and changes nothing.

    Critical for cycle_runner integration \u2014 every cycle calls the helper,
    so it MUST be a no-op after the first pass cleans the vault.
    """
    fix = _import_helper()
    vault = _make_minimal_vault(tmp_path)
    _write_note(vault, "data_vault/01 - Concepts/kafka.md")
    note = _write_note(
        vault,
        "data_vault/01 - Concepts/topics.md",
        related=["kafka"],
        body="See [[kafka]].",
    )
    text_before = note.read_text(encoding="utf-8")

    fixes = fix(vault)

    assert fixes == 0, f"clean vault should report 0 fixes, got {fixes}"
    assert note.read_text(encoding="utf-8") == text_before


# ---- guard cases (must NOT change anything) -------------------------------


def test_does_not_create_stubs_or_touch_orphans(tmp_path: Path) -> None:
    """The cycle-time helper is the LIGHT touch: it ONLY fixes ``moved``
    (case mismatch where a lowercase target exists). It does NOT:

    - create draft notes for unknown wikilinks (the ``stub`` class),
    - delete orphan ``related`` entries (the ``orphan`` class).

    Those are heavier mutations and remain opt-in via
    ``vault_health.py --apply``. Auto-applying them every cycle would
    silently expand or prune the vault.
    """
    fix = _import_helper()
    vault = _make_minimal_vault(tmp_path)
    _write_note(
        vault,
        "data_vault/01 - Concepts/note_a.md",
        related=["TotallyUnknownNote"],
        body="Reference to [[NonExistentThing]].",
    )

    fix(vault)

    # No new files created.
    files = sorted(p.name for p in (vault / "data_vault" / "01 - Concepts").iterdir())
    assert files == ["note_a.md"], f"unexpected files created: {files}"
    # Note unchanged.
    text = (vault / "data_vault" / "01 - Concepts/note_a.md").read_text()
    assert "[[NonExistentThing]]" in text, "orphan body link should be untouched"


def test_preserves_pipe_aliases(tmp_path: Path) -> None:
    """Wikilinks with alias syntax (``[[Target|display text]]``) MUST
    preserve the alias when the target is normalized.

    Otherwise we silently lose the human-readable rendering.
    """
    fix = _import_helper()
    vault = _make_minimal_vault(tmp_path)
    _write_note(vault, "data_vault/01 - Concepts/cassandra.md")
    note = _write_note(
        vault,
        "data_vault/01 - Concepts/pim.md",
        body="See [[Cassandra|the distributed store]] for details.",
    )

    fix(vault)
    text = note.read_text(encoding="utf-8")
    assert "[[cassandra|the distributed store]]" in text, (
        f"alias not preserved:\n{text}"
    )


def test_preserves_display_text_when_title_style_body_link_maps_to_snake_case(
    tmp_path: Path,
) -> None:
    """A title-style body link should resolve to the snake_case stem while
    keeping the original human-readable text as the display alias."""
    fix = _import_helper()
    vault = _make_minimal_vault(tmp_path)
    _write_note(
        vault,
        "data_vault/01 - Concepts/outcome_matrix_order_vector_calculation.md",
    )
    note = _write_note(
        vault,
        "data_vault/01 - Concepts/order_validation_api_surface.md",
        body="See [[Outcome Matrix Order Vector Calculation]] for details.",
    )

    fix(vault)
    text = note.read_text(encoding="utf-8")
    assert (
        "[[outcome_matrix_order_vector_calculation|"
        "Outcome Matrix Order Vector Calculation]]" in text
    ), f"title-style body wikilink not normalized with preserved display text:\n{text}"


def test_does_not_touch_code_fenced_brackets(tmp_path: Path) -> None:
    """``[[Foo]]`` inside a fenced code block must NOT be rewritten \u2014
    it's likely showing the WRONG form as a counterexample, or it's
    actual code that happens to use double-bracket syntax.

    This guards against the normalizer corrupting documentation that
    teaches users about wikilinks.
    """
    fix = _import_helper()
    vault = _make_minimal_vault(tmp_path)
    _write_note(vault, "data_vault/01 - Concepts/cassandra.md")
    note = _write_note(
        vault,
        "data_vault/01 - Concepts/howto.md",
        body=(
            "Bad form:\n\n```\n"
            "See [[Cassandra]] in the body.\n"
            "```\n\n"
            "Good form: [[Cassandra]].\n"
        ),
    )

    fix(vault)
    text = note.read_text(encoding="utf-8")
    # The OUTSIDE-fence reference should normalize.
    assert "Good form: [[cassandra]]" in text
    # The INSIDE-fence reference should be preserved verbatim.
    assert "See [[Cassandra]] in the body." in text, (
        f"in-fence wikilink was modified:\n{text}"
    )


# ---- return-value contract -------------------------------------------------


def test_returns_count_of_files_modified(tmp_path: Path) -> None:
    """Helper returns the count of FILES touched (not the count of
    individual wikilink fixes). Cycle_runner uses this for a one-line
    log entry: ``normalized wikilinks in N file(s)``.
    """
    fix = _import_helper()
    vault = _make_minimal_vault(tmp_path)
    _write_note(vault, "data_vault/01 - Concepts/cassandra.md")
    _write_note(vault, "data_vault/01 - Concepts/kafka.md")
    # Note A: 2 broken links in body
    _write_note(
        vault,
        "data_vault/01 - Concepts/note_a.md",
        body="[[Cassandra]] and [[Kafka]] together.",
    )
    # Note B: 1 broken link in related, 1 in body
    _write_note(
        vault,
        "data_vault/01 - Concepts/note_b.md",
        related=["Cassandra"],
        body="See [[Cassandra]].",
    )
    # Note C: already clean
    _write_note(
        vault,
        "data_vault/01 - Concepts/note_c.md",
        body="[[cassandra]] only.",
    )

    fixes = fix(vault)

    # Two files touched. Note C didn't need changes.
    assert fixes == 2, f"expected 2 files modified, got {fixes}"


def test_handles_empty_vault_gracefully(tmp_path: Path) -> None:
    """Edge case: helper called on a vault with no notes yet. Must not
    raise; returns 0.
    """
    fix = _import_helper()
    vault = _make_minimal_vault(tmp_path)
    assert fix(vault) == 0


def test_handles_missing_data_vault_dir(tmp_path: Path) -> None:
    """Edge case: helper called before ``data_vault/`` is created.
    Must not raise; returns 0.
    """
    fix = _import_helper()
    vault = tmp_path / "vault"
    vault.mkdir()
    assert fix(vault) == 0
