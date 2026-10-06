"""Tests for scripts/check_code_source_coverage.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).parent.parent.parent / "scripts" / "check_code_source_coverage.py"
)


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )


def _write_note(
    vault: Path,
    filename: str,
    ntype: str,
    source_urls: list[dict],
) -> Path:
    path = vault / "data_vault" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_lines = [
        "---",
        f"title: {filename.removesuffix('.md')}",
        f"type: {ntype}",
        "tags: []",
        "created: 2026-04-17",
        "updated: 2026-04-17",
        "status: draft",
        'summary: "x"',
        "related: []",
        "source_urls:",
    ]
    for s in source_urls:
        fm_lines.append(f'  - url: "{s["url"]}"')
        fm_lines.append(f'    title: "{s.get("title", "x")}"')
        fm_lines.append("    accessed: 2026-04-17")
    fm_lines += [
        "confidence: high",
        "scope: team",
        'template_version: "1.0.0"',
        "---",
        "",
        f"# {filename}",
    ]
    path.write_text("\n".join(fm_lines))
    return path


def _write_authority_spec(vault: Path) -> None:
    """spec-parse.json declaring the 053 authority model: a `service` note_type
    anchored to `behaviour`, and a behaviour data_source enumerating one repo."""
    (vault / "_pipeline").mkdir(parents=True, exist_ok=True)
    spec_data = {
        "note_types": [
            {
                "name": "service",
                "source_policy": "hard",
                "authoritative_role": "behaviour",
            }
        ],
        "data_sources": [
            {
                "name": "GitHub repos",
                "type": "internal",
                "priority": 1,
                "role": "behaviour",
                "repos": [
                    {
                        "name": "svc",
                        "url": "https://github.com/acme-corp/svc",
                    }
                ],
            },
            {
                "name": "Confluence",
                "type": "external",
                "priority": 2,
                "role": "intent",
            },
        ],
    }
    (vault / "_pipeline" / "spec-parse.json").write_text(json.dumps(spec_data))


class TestGeneralizedGroundingResolution:
    """spec 053 FR-004 / T008 — claim-type T = note_type.authoritative_role;
    a note must cite >=1 source resolving (citation->source_id->data_source->role)
    to T. This replaces classify_url regex-guessing: a behaviour note citing an
    UNDECLARED repo (which the old `^https://github.com/` regex accepted) now
    FAILs, while a declared-repo citation passes."""

    def test_declared_behaviour_repo_passes(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_note(
            vault,
            "our-svc.md",
            "service",
            [{"url": "https://github.com/acme-corp/svc/blob/main/app.py"}],
        )
        _write_authority_spec(vault)
        result = _run(str(vault))
        assert result.returncode == 0, result.stdout + result.stderr

    def test_undeclared_repo_fails_under_authority_model(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_note(
            vault,
            "rogue.md",
            "service",
            [{"url": "https://github.com/random-org/random-repo"}],
        )
        _write_authority_spec(vault)
        result = _run(str(vault))
        assert result.returncode == 1, result.stdout

    def test_only_intent_citation_fails_for_behaviour_note(
        self, tmp_path: Path
    ) -> None:
        vault = tmp_path / "vault"
        _write_note(
            vault,
            "intent-only.md",
            "service",
            [{"url": "https://example.atlassian.net/wiki/x"}],
        )
        _write_authority_spec(vault)
        result = _run(str(vault))
        assert result.returncode == 1, result.stdout


def test_service_github_only_passes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_note(
        vault,
        "OEHK.md",
        "service",
        [{"url": "https://github.com/acme-corp/oehk-service"}],
    )
    result = _run(str(vault))
    assert result.returncode == 0, result.stdout


def test_service_github_plus_confluence_passes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_note(
        vault,
        "OEHK.md",
        "service",
        [
            {"url": "https://github.com/acme-corp/oehk-service"},
            {"url": "https://example.atlassian.net/wiki/spaces/DOCS/pages/1/OEHK"},
        ],
    )
    result = _run(str(vault))
    assert result.returncode == 0


def test_service_confluence_only_fails(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_note(
        vault,
        "OEHK.md",
        "service",
        [{"url": "https://example.atlassian.net/wiki/spaces/DOCS/pages/1/OEHK"}],
    )
    result = _run(str(vault))
    assert result.returncode == 1
    assert "MISSING CODE SOURCE" in result.stdout
    assert "OEHK.md" in result.stdout


def test_concept_no_sources_fails(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_note(vault, "Root Variant.md", "concept", [])
    result = _run(str(vault))
    assert result.returncode == 1
    assert "Root Variant.md" in result.stdout


def test_market_web_only_passes(tmp_path: Path) -> None:
    """Market is a soft type by default — no code source required."""
    vault = tmp_path / "vault"
    _write_note(
        vault,
        "Competitor Landscape.md",
        "market",
        [{"url": "https://www.example.com"}],
    )
    result = _run(str(vault))
    assert result.returncode == 0


def test_decision_file_uri_passes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_note(
        vault,
        "ADR 0003 - Retry Policy.md",
        "decision",
        [{"url": "file:///repo/oehk-service/docs/adr/0003-retry-policy.md"}],
    )
    result = _run(str(vault))
    assert result.returncode == 0


def test_json_output(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_note(vault, "Concept.md", "concept", [])
    result = _run(str(vault), "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["scanned_by_type"]["concept"] == 1
    assert len(payload["violations"]) == 1
    assert payload["violations"][0]["type"] == "concept"


def test_honours_spec_hard_types(tmp_path: Path) -> None:
    """When spec-parse.json declares `process` as hard, enforce it too."""
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    spec_data = {
        "note_types": [
            {"name": "process", "source_policy": "hard"},
            {"name": "market", "source_policy": "soft"},
        ]
    }
    (vault / "_pipeline" / "spec-parse.json").write_text(json.dumps(spec_data))
    _write_note(
        vault,
        "Release Process.md",
        "process",
        [{"url": "https://example.atlassian.net/wiki/x"}],
    )
    result = _run(str(vault))
    assert result.returncode == 1
    assert "Release Process.md" in result.stdout


def test_missing_vault_exits_2(tmp_path: Path) -> None:
    result = _run(str(tmp_path / "nope"))
    assert result.returncode == 2


def test_non_code_first_vault_with_soft_concept_passes(tmp_path: Path) -> None:
    """Recipe/photography/non-code-first vaults declare `concept` as SOFT
    via simple.py's expander. With no hard-type note types in spec-parse.json,
    the coverage gate must report 0 scanned / 0 violations and PASS —
    instead of the v0.2.5/0.2.6 behaviour of flagging every concept note
    as MISSING CODE SOURCE."""
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    spec_data = {
        "note_types": [
            {"name": "concept", "source_policy": "soft"},
            {"name": "source", "source_policy": "soft"},
        ]
    }
    (vault / "_pipeline" / "spec-parse.json").write_text(json.dumps(spec_data))
    _write_note(
        vault,
        "Sopa de legumes.md",
        "concept",
        [{"url": "https://cozinha.continente.pt/receitas/sopa-de-legumes"}],
    )
    result = _run(str(vault))
    assert result.returncode == 0, result.stdout
    assert "MISSING CODE SOURCE" not in result.stdout
    assert "PASS" in result.stdout


def test_spec_code_source_url_patterns_narrow_classification(tmp_path: Path) -> None:
    """Spec can narrow the code-URL regex to a specific org; a github.com URL
    outside that org is then classified as NOT code and fails the gate."""
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    spec_data = {
        "note_types": [{"name": "service", "source_policy": "hard"}],
        "code_source_url_patterns": [r"^https?://github\.com/acme/"],
    }
    (vault / "_pipeline" / "spec-parse.json").write_text(json.dumps(spec_data))
    _write_note(
        vault,
        "foreign-org.md",
        "service",
        [{"url": "https://github.com/other-org/thing"}],
    )
    result = _run(str(vault))
    assert result.returncode == 1
    assert "MISSING CODE SOURCE" in result.stdout


def test_spec_code_source_url_patterns_accept_matching_org(tmp_path: Path) -> None:
    """Same narrowed spec, but the URL does match the configured org."""
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    spec_data = {
        "note_types": [{"name": "service", "source_policy": "hard"}],
        "code_source_url_patterns": [r"^https?://github\.com/acme/"],
    }
    (vault / "_pipeline" / "spec-parse.json").write_text(json.dumps(spec_data))
    _write_note(
        vault,
        "our-svc.md",
        "service",
        [{"url": "https://github.com/acme/our-svc"}],
    )
    result = _run(str(vault))
    assert result.returncode == 0
