"""Verify grades against the vault's declared note format, not one vault's
(issue #226).

``processors/verify.py`` was ported from one specific vault's
``scripts/verify.py`` and kept that vault's schema and taxonomy as module
constants: ``summary`` / ``status`` / ``related`` as the required frontmatter,
and ``MOC_TO_FOLDERS`` naming folders like ``"13 - AI Tools"`` and
``"Society Culture Technology MOC"``.

The consequence a reviewer measured across three quality fixtures,
``tests/fixtures/vault`` and the real 840-note feeds-vault: **all FAIL**, and the
root cause of every ``missing_summary`` flag was that the framework's OWN
shipped note template has no ``summary`` key. The weekly pipeline's verify
phase was a guaranteed FAIL on every vault the framework itself produced.

Two halves are pinned here:

1. The required frontmatter is **resolved**, not hardcoded — explicit argument
   > spec config > the vault's own ``_templates/`` > the historical default.
2. The shipped template and the checker cannot disagree, because the checker
   reads the template. The template's EMPTY slots are exactly the keys the
   framework's own step gate ``SG-005`` requires a written note to fill.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.pipeline.gates_step import _SG005_REQUIRED_KEYS
from research_framework.processors.verify import (
    MOC_TO_FOLDERS,
    _declared_note_format,
    verify,
)
from research_framework.vault.frontmatter import parse_frontmatter_str
from tests._helpers.vault_factory import build_minimal_vault

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _note(vault: Path, rel: str, text: str) -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _checks(result, check: str) -> list[dict]:
    return [r for r in result.report["results"] if r.get("check") == check]


def _content_checks(result) -> set[str]:
    return {
        r["check"]
        for r in result.report["results"]
        if r["type"] == "structural_flag" and r["class"] == "content"
    }


def _fill_template(template_text: str, title: str, body: str) -> str:
    """Turn a rendered note-type template into a written note, the way the
    note-writer agent does: fill the empty frontmatter slots, write a body."""
    fm, _ = parse_frontmatter_str(template_text)
    fm["summary"] = f"What {title} is."
    fm["coverage_category"] = "cat_a"
    fm["source_urls"] = ["https://synthetic.invalid/source"]
    lines = ["---"]
    for key, value in fm.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + f"\n\n# {title}\n\n{body}\n"


# ---------------------------------------------------------------------------
# The shipped template must satisfy the shipped checker
# ---------------------------------------------------------------------------


class TestTheShippedTemplateSatisfiesItsOwnChecker:
    def test_the_template_declares_a_summary_slot(self, tmp_path: Path) -> None:
        """The confirmed root cause: it did not, so every generated note
        flagged ``missing_summary`` the moment it was written."""
        vault = build_minimal_vault(tmp_path)

        fm, _ = parse_frontmatter_str(
            (vault / "_templates" / "concept.md").read_text(encoding="utf-8")
        )

        assert "summary" in fm

    def test_the_template_slots_are_exactly_the_sg005_contract(
        self, tmp_path: Path
    ) -> None:
        """The framework already had a note-format contract — SG-005's
        ``coverage_category`` / ``source_urls`` / ``summary``. Verify invented
        a second, different one. One template, one contract, both readers."""
        vault = build_minimal_vault(tmp_path)

        declared = _declared_note_format(vault / "_templates")

        assert set(declared) == set(_SG005_REQUIRED_KEYS)

    def test_a_note_written_from_the_template_passes_verify(
        self, tmp_path: Path
    ) -> None:
        vault = build_minimal_vault(tmp_path)
        template = (vault / "_templates" / "concept.md").read_text(encoding="utf-8")
        corpus = vault / "data_vault"
        _note(
            corpus,
            "01 - Concepts/alpha.md",
            _fill_template(template, "alpha", "Alpha relates to [[beta]]."),
        )
        _note(
            corpus,
            "01 - Concepts/beta.md",
            _fill_template(template, "beta", "Beta relates to [[alpha]]."),
        )

        result = verify(corpus, auto_fix=False)

        assert result.notes_checked == 2
        assert result.content_flags == 0
        assert result.verdict == "PASS"

    def test_an_unfilled_note_flags_the_templates_own_slots(
        self, tmp_path: Path
    ) -> None:
        """A note that stopped at the template flags what it did not fill —
        and nothing the template never asked for."""
        vault = build_minimal_vault(tmp_path)
        template = (vault / "_templates" / "concept.md").read_text(encoding="utf-8")
        corpus = vault / "data_vault"
        _note(corpus, "01 - Concepts/stub.md", template)

        result = verify(corpus, auto_fix=False)

        assert _content_checks(result) == {
            f"missing_{key}" for key in _SG005_REQUIRED_KEYS
        }


# ---------------------------------------------------------------------------
# Required frontmatter is resolved, not hardcoded
# ---------------------------------------------------------------------------


class TestRequiredFrontmatterPrecedence:
    BARE = "---\ntitle: Bare\n---\n\nBody.\n"

    def test_the_default_stands_when_the_vault_declares_nothing(
        self, tmp_path: Path
    ) -> None:
        _note(tmp_path, "04 - Concepts/Bare.md", self.BARE)

        result = verify(tmp_path, auto_fix=False)

        assert _content_checks(result) == {"missing_summary"}

    def test_spec_config_declares_the_note_format(self, tmp_path: Path) -> None:
        _note(tmp_path, "04 - Concepts/Bare.md", self.BARE)

        result = verify(
            tmp_path,
            auto_fix=False,
            spec_processors={"verify": {"required_frontmatter": ["headline", "owner"]}},
        )

        assert _content_checks(result) == {"missing_headline", "missing_owner"}

    def test_an_explicit_argument_beats_spec_config(self, tmp_path: Path) -> None:
        _note(tmp_path, "04 - Concepts/Bare.md", self.BARE)

        result = verify(
            tmp_path,
            auto_fix=False,
            required_frontmatter=["headline"],
            spec_processors={"verify": {"required_frontmatter": ["owner"]}},
        )

        assert _content_checks(result) == {"missing_headline"}

    def test_the_vaults_templates_beat_the_default(self, tmp_path: Path) -> None:
        vault = build_minimal_vault(tmp_path)
        _note(vault / "data_vault", "01 - Concepts/Bare.md", self.BARE)

        result = verify(vault / "data_vault", auto_fix=False)

        assert _content_checks(result) == {
            f"missing_{key}" for key in _SG005_REQUIRED_KEYS
        }

    def test_the_report_records_what_was_required(self, tmp_path: Path) -> None:
        """A verdict nobody can reproduce is not a verdict."""
        _note(tmp_path, "04 - Concepts/Bare.md", self.BARE)

        report = verify(
            tmp_path, auto_fix=False, required_frontmatter=["headline"]
        ).report

        assert report["required_frontmatter"] == ["headline"]


# ---------------------------------------------------------------------------
# MOC consistency follows the declared taxonomy
# ---------------------------------------------------------------------------

CLEAN = "---\nstatus: draft\nrelated: []\nsummary: A note.\n---\n\nBody.\n"

DECLARED_NOTE_TYPES = [
    {"name": "concept", "folder": "01 - Concepts"},
    {"name": "company", "folder": "02 - Companies"},
]


class TestMocConsistencyFollowsTheDeclaredTaxonomy:
    def _vault_with_moc(self, tmp_path: Path, folder: str) -> Path:
        _note(tmp_path, "00 - MOC/Concepts MOC.md", "# Concepts\n\n- [[Listed]]\n")
        _note(tmp_path, f"{folder}/Listed.md", CLEAN)
        _note(tmp_path, f"{folder}/Unlisted.md", CLEAN)
        return tmp_path

    def test_a_declared_folder_is_checked_against_its_moc(self, tmp_path: Path) -> None:
        self._vault_with_moc(tmp_path, "01 - Concepts")

        result = verify(tmp_path, auto_fix=False, spec_note_types=DECLARED_NOTE_TYPES)

        gaps = {r["file"] for r in _checks(result, "moc_gap")}
        assert gaps == {"01 - Concepts/Unlisted.md"}

    def test_another_vaults_folder_names_do_not_leak_in(self, tmp_path: Path) -> None:
        """``04 - Concepts`` is feeds-vault's folder, not this vault's. Grading a
        generated vault against it is the "inert or actively misdirected"
        half of #226."""
        self._vault_with_moc(tmp_path, "04 - Concepts")

        result = verify(tmp_path, auto_fix=False, spec_note_types=DECLARED_NOTE_TYPES)

        assert not _checks(result, "moc_gap")

    def test_a_vault_that_declares_nothing_keeps_the_legacy_map(
        self, tmp_path: Path
    ) -> None:
        """The vault this was ported from is still described correctly."""
        self._vault_with_moc(tmp_path, "04 - Concepts")

        result = verify(tmp_path, auto_fix=False)

        assert "04 - Concepts" in MOC_TO_FOLDERS["Concepts MOC"]
        assert {r["file"] for r in _checks(result, "moc_gap")} == {
            "04 - Concepts/Unlisted.md"
        }

    def test_moc_gaps_never_fail_a_vault(self, tmp_path: Path) -> None:
        """A MOC gap is a housekeeping observation, not a defective note."""
        _note(tmp_path, "00 - MOC/Concepts MOC.md", "# Concepts\n")
        for i in range(10):
            _note(tmp_path, f"01 - Concepts/N{i}.md", CLEAN)

        result = verify(tmp_path, auto_fix=False, spec_note_types=DECLARED_NOTE_TYPES)

        assert len(_checks(result, "moc_gap")) == 10
        assert result.verdict != "FAIL"
