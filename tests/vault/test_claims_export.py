"""Tier-3 tests for ``vault.claims_export`` (issue #189).

A real vault on disk from ``build_minimal_vault`` (spec, ``spec-parse.json``,
corpus folder, templates), notes written through the canonical codec
(spec 079 FR-010), and the export read back as a plain dict — the shape a
subprocess consumer sees on stdout.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from research_framework.vault.claims_export import (
    SCHEMA_VERSION,
    ClaimsExportError,
    export_claims,
)
from research_framework.vault.frontmatter import dump_frontmatter
from tests._helpers.vault_factory import build_minimal_vault

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def _write_note(
    vault: Path, rel: str, frontmatter: dict | None, body: str = "# T\n\nbody\n"
) -> Path:
    path = vault / "data_vault" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    text = dump_frontmatter(frontmatter, body) if frontmatter is not None else body
    path.write_text(text, encoding="utf-8")
    return path


def _note(
    title: str,
    *,
    summary: str = "A one-line claim.",
    note_type: str = "concept",
    sources: list | None = None,
    **extra: object,
) -> dict:
    fm: dict = {
        "title": title,
        "type": note_type,
        "summary": summary,
        "tags": ["alpha", 7],
        "source_urls": ["https://example.test/a"] if sources is None else sources,
        "related": [],
        "created": "2026-09-01",
        "updated": "2026-09-02",
        "template_version": "1.0.0",
        "coverage_category": "cat_a",
    }
    fm.update(extra)
    return fm


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    return build_minimal_vault(tmp_path, install_fake_agent=False)


class TestEnvelope:
    def test_envelope_carries_version_provenance_counts_and_sorted_claims(
        self, vault: Path
    ) -> None:
        _write_note(vault, "01 - Concepts/zeta.md", _note("Zeta"))
        _write_note(vault, "01 - Concepts/alpha.md", _note("Alpha"))
        doc = export_claims(vault, now=NOW)

        assert doc["schema_version"] == SCHEMA_VERSION == "1.0"
        assert doc["kind"] == "claims-export"
        assert doc["generated_at"] == NOW.isoformat()
        assert doc["generator"]["name"] == "research-framework"
        assert isinstance(doc["generator"]["version"], str)
        assert doc["vault"]["name"] == vault.name
        assert doc["vault"]["corpus_dir"] == "data_vault"
        assert doc["vault"]["note_types"] == ["concept"]
        assert doc["counts"]["claims"] == 2
        assert [c["id"] for c in doc["claims"]] == [
            "01 - Concepts/alpha",
            "01 - Concepts/zeta",
        ]
        assert doc["warnings"] == []
        # ADR-0013: the producer asserts the EXACT key set it writes, so an
        # accidental extra key cannot ride through `additionalProperties`.
        assert set(doc) == {
            "schema_version",
            "kind",
            "generated_at",
            "generator",
            "vault",
            "counts",
            "warnings",
            "claims",
        }
        assert set(doc["generator"]) == {"name", "version"}
        assert set(doc["vault"]) == {"name", "corpus_dir", "note_types"}

    def test_claim_record_fields(self, vault: Path) -> None:
        _write_note(
            vault,
            "01 - Concepts/alpha.md",
            _note(
                "Alpha",
                summary="  Alpha   is\n the first.  ",
                verifier_status="verified",
                sources=[
                    "https://example.test/plain",
                    {
                        "url": "https://example.test/rich",
                        "title": "Rich",
                        "accessed": "2026-09-01",
                        "credibility": "commentary",
                    },
                    {"title": "no url — dropped"},
                ],
            ),
        )
        [claim] = export_claims(vault, now=NOW)["claims"]
        assert set(claim) == {
            "id",
            "note_path",
            "title",
            "claim",
            "note_type",
            "note_type_declared",
            "tags",
            "verifier_status",
            "coverage_category",
            "template_version",
            "created",
            "updated",
            "quarantined",
            "support_count",
            "sources",
        }
        assert claim["id"] == "01 - Concepts/alpha"
        assert claim["note_path"] == "data_vault/01 - Concepts/alpha.md"
        assert claim["title"] == "Alpha"
        assert claim["claim"] == "Alpha is the first."
        assert claim["note_type"] == "concept"
        assert claim["note_type_declared"] is True
        assert claim["tags"] == ["alpha", "7"]
        assert claim["verifier_status"] == "verified"
        assert claim["coverage_category"] == "cat_a"
        assert claim["template_version"] == "1.0.0"
        assert claim["created"] == "2026-09-01"
        assert claim["updated"] == "2026-09-02"
        assert claim["quarantined"] is False
        assert claim["support_count"] == 2
        assert claim["sources"] == [
            {
                "url": "https://example.test/plain",
                "title": None,
                "accessed": None,
                "credibility_declared": None,
                "credibility": None,
                "coi": False,
            },
            {
                "url": "https://example.test/rich",
                "title": "Rich",
                "accessed": "2026-09-01",
                "credibility_declared": "commentary",
                "credibility": "commentary",
                "coi": False,
            },
        ]

    def test_undeclared_note_type_is_flagged_not_dropped(self, vault: Path) -> None:
        _write_note(vault, "02 - Other/beta.md", _note("Beta", note_type="rumour"))
        [claim] = export_claims(vault, now=NOW)["claims"]
        assert claim["note_type"] == "rumour"
        assert claim["note_type_declared"] is False


class TestCredibilityResolution:
    def test_coi_downgrades_the_effective_level_and_keeps_the_declared_one(
        self, vault: Path
    ) -> None:
        _write_note(
            vault,
            "01 - Concepts/alpha.md",
            _note(
                "Alpha",
                sources=[
                    {
                        "url": "https://example.test/vendor",
                        "credibility": "primary",
                        "coi": True,
                    }
                ],
            ),
        )
        [claim] = export_claims(vault, now=NOW)["claims"]
        [src] = claim["sources"]
        assert src["credibility_declared"] == "primary"
        assert src["credibility"] == "commentary"
        assert src["coi"] is True

    def test_source_default_grounds_an_undeclared_citation(self, vault: Path) -> None:
        """Resolution order per docs/source-credibility.md: explicit → source default."""
        import json

        parse_path = vault / "_pipeline" / "spec-parse.json"
        doc = json.loads(parse_path.read_text(encoding="utf-8"))
        doc["data_sources"][0]["default_credibility"] = "corroborated"
        doc["data_sources"][0]["url"] = "https://grounded.test/feed"
        parse_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

        _write_note(
            vault,
            "01 - Concepts/alpha.md",
            _note("Alpha", sources=["https://grounded.test/article/1"]),
        )
        [claim] = export_claims(vault, now=NOW)["claims"]
        [src] = claim["sources"]
        assert src["credibility_declared"] is None
        assert src["credibility"] == "corroborated"


class TestPlumbingIsSkippedByTheFrameworksOwnRules:
    def test_each_skip_reason_is_counted_and_nothing_leaks_into_claims(
        self, vault: Path
    ) -> None:
        _write_note(vault, "01 - Concepts/real.md", _note("Real"))
        # Scaffold: generator-owned index files and the templates folder.
        _write_note(vault, "_overview.md", None, body="# index\n")
        _write_note(vault, "_templates/foo.md", None, body="# tmpl\n")
        # Exempt: the format's own opt-out, and an alias redirect stub.
        _write_note(
            vault, "01 - Concepts/exempt.md", _note("Ex", verifier_status="exempt")
        )
        _write_note(
            vault,
            "01 - Concepts/ALIAS.md",
            {"note_type": "alias", "redirect_to": "real", "verifier_status": "exempt"},
            body="See [[real]].\n",
        )
        # Malformed and frontmatter-less files never fail the run.
        _write_note(vault, "01 - Concepts/broken.md", None, body="---\ntitle: [\n---\n")
        _write_note(vault, "01 - Concepts/bare.md", None, body="# bare\n")
        # A note without a summary has no claim to export.
        _write_note(vault, "01 - Concepts/nosummary.md", _note("NS", summary=""))
        _write_note(vault, "01 - Concepts/notype.md", {"title": "NT", "summary": "s"})

        doc = export_claims(vault, now=NOW)
        assert [c["title"] for c in doc["claims"]] == ["Real"]
        assert doc["counts"]["claims"] == 1
        # The generator's own corpus files count too: the index trio plus the
        # note-type template under `_templates/` — four, before this test adds
        # `_overview.md` and `_templates/foo.md`.
        assert doc["counts"]["skipped"] == {
            "scaffold": 6,
            "exempt": 2,
            "malformed": 1,
            "no_frontmatter": 1,
            "missing_fields": 2,
        }
        assert doc["counts"]["notes_scanned"] == 13
        assert any("broken.md" in w for w in doc["warnings"])


class TestQuarantine:
    def _quarantine(self, vault: Path) -> None:
        q = vault / "_pipeline" / "quarantine"
        q.mkdir(parents=True, exist_ok=True)
        (q / "rejected.md").write_text(
            dump_frontmatter(
                _note("Rejected", verifier_status="rejected"), "# R\n\nbody\n"
            ),
            encoding="utf-8",
        )

    def test_quarantined_notes_are_excluded_by_default(self, vault: Path) -> None:
        _write_note(vault, "01 - Concepts/real.md", _note("Real"))
        self._quarantine(vault)
        doc = export_claims(vault, now=NOW)
        assert [c["title"] for c in doc["claims"]] == ["Real"]
        assert doc["counts"]["quarantined"] == 0

    def test_include_quarantined_flags_them(self, vault: Path) -> None:
        _write_note(vault, "01 - Concepts/real.md", _note("Real"))
        self._quarantine(vault)
        doc = export_claims(vault, now=NOW, include_quarantined=True)
        by_title = {c["title"]: c for c in doc["claims"]}
        assert by_title["Real"]["quarantined"] is False
        assert by_title["Rejected"]["quarantined"] is True
        assert by_title["Rejected"]["id"] == "quarantine/rejected"
        assert by_title["Rejected"]["note_path"] == "_pipeline/quarantine/rejected.md"
        assert by_title["Rejected"]["verifier_status"] == "rejected"
        assert doc["counts"]["quarantined"] == 1


class TestDegradation:
    def test_missing_spec_warns_and_still_exports(self, vault: Path) -> None:
        (vault / "_pipeline" / "spec-parse.json").unlink()
        (vault / "research.spec.md").unlink()
        _write_note(vault, "01 - Concepts/alpha.md", _note("Alpha"))
        doc = export_claims(vault, now=NOW)
        [claim] = doc["claims"]
        assert claim["note_type_declared"] is None
        assert claim["sources"][0]["credibility"] is None
        assert doc["vault"]["note_types"] == []
        assert any("spec" in w.lower() for w in doc["warnings"])

    def test_not_a_vault_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ClaimsExportError, match="corpus"):
            export_claims(tmp_path)

    def test_export_is_read_only_byte_for_byte(self, vault: Path) -> None:
        """Principle XII: inspection does not mutate what it inspects."""
        _write_note(vault, "01 - Concepts/alpha.md", _note("Alpha"))
        _write_note(vault, "01 - Concepts/broken.md", None, body="---\ntitle: [\n---\n")
        before = _tree_digest(vault / "data_vault")
        export_claims(vault, now=NOW)
        assert _tree_digest(vault / "data_vault") == before

    def test_export_is_deterministic(self, vault: Path) -> None:
        _write_note(vault, "01 - Concepts/b.md", _note("B"))
        _write_note(vault, "01 - Concepts/a.md", _note("A"))
        assert export_claims(vault, now=NOW) == export_claims(vault, now=NOW)
