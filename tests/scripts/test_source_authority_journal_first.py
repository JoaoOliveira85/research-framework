"""spec 053 US2 (T013-T015) — journal-first plasticity proof.

A vault with NO behaviour source (derived trunk = a `domain` journal source)
must enforce on the SAME generalized gates as a code-first vault:
- spec validates (the trunk is domain, not behaviour — the code-first invariants
  must NOT fire);
- Gate 1 (grounding) demands the authoritative **domain** role;
- Gate 3 (trunk-seed) seeds from the journal trunk and does NOT require
  code/behaviour (the pure-domain `if signatures:` guard).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from research_framework.spec.parser import parse
from research_framework.spec.schema import derive_trunk
from research_framework.spec.validator import validate
from tests._helpers.fake_module import write_fake_preflight

FIXTURE = Path(__file__).parent.parent / "fixtures" / "vault-journal-first"
GROUNDING = (
    Path(__file__).parent.parent.parent / "scripts" / "check_code_source_coverage.py"
)
VALIDATE_CYCLE = Path(__file__).parent.parent.parent / "scripts" / "validate_cycle.py"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True
    )


def _stage(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "data_vault").mkdir(parents=True)
    (vault / "_pipeline" / "cycles").mkdir(parents=True)
    spec = parse(FIXTURE / "research.spec.md")
    (vault / "_pipeline" / "spec-parse.json").write_text(
        json.dumps(spec.to_dict()), encoding="utf-8"
    )
    return vault


def _write_journals_module(vault: Path, url: str) -> None:
    """A `journals` module enumerating one feed URL — its source_id inherits the
    `Journals` data_source role (domain) via the module-slug match."""
    mod = vault / "modules" / "journals"
    mod.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "journals",
        "version": "0.1.0",
        "description": "journals module",
        "triggers": [],
        "entry_point": "extractor.py",
        "schema_examples": "{}",
        "preflight": {"entry_point": "preflight.py"},
        "source_id_from": {"feeds": "url"},
    }
    (mod / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (mod / "sources.yaml").write_text(
        yaml.safe_dump({"feeds": [{"url": url}]}), encoding="utf-8"
    )
    write_fake_preflight(mod)


def _write_finding(vault: Path, name: str, urls: list[str]) -> None:
    lines = ["---", f"title: {name}", "type: finding", "source_urls:"]
    for u in urls:
        lines += [f'  - url: "{u}"', '    title: "x"', "    accessed: 2026-06-02"]
    lines += ["---", "", f"# {name}", "", "## Evidence", "", "Some finding."]
    (vault / "data_vault" / f"{name}.md").write_text("\n".join(lines), encoding="utf-8")


# --- spec validation (the journal-first edge — T015) ---


def test_journal_first_spec_validates_as_non_code_first() -> None:
    """The journal-first spec parses + validates. The derived trunk is the
    domain `Journals` source — the code-first behaviour-primary invariants must
    NOT fire just because a source sits at priority 1."""
    spec = parse(FIXTURE / "research.spec.md")
    validate(spec)  # must not raise
    trunk = derive_trunk(spec)
    assert trunk is not None and trunk.name == "Journals"
    assert trunk.role == "domain"
    # No behaviour source exists at all.
    assert all(ds.role != "behaviour" for ds in spec.data_sources)


# --- Gate 1: grounding requires the authoritative (domain) role ---


def test_grounding_finding_citing_journal_passes(tmp_path: Path) -> None:
    vault = _stage(tmp_path)
    url = "https://rss.arxiv.org/rss/cs.LG/paper-123"
    _write_journals_module(vault, url)
    _write_finding(vault, "good-finding", [url])
    result = _run(GROUNDING, str(vault))
    assert result.returncode == 0, result.stdout + result.stderr


def test_grounding_finding_without_domain_source_fails(tmp_path: Path) -> None:
    vault = _stage(tmp_path)
    _write_journals_module(vault, "https://rss.arxiv.org/rss/cs.LG/paper-123")
    # cites an unrelated URL that resolves to no declared domain source
    _write_finding(vault, "ungrounded", ["https://example.com/random-blog"])
    result = _run(GROUNDING, str(vault))
    assert result.returncode == 1, result.stdout


# --- Gate 3: trunk-seed seeds from the journal trunk, no behaviour required ---


def test_trunk_seed_journal_first_continues(tmp_path: Path) -> None:
    vault = _stage(tmp_path)
    report = {
        "schema_version": "3",
        "cycle": 1,
        "phase": "scout",
        "timestamp": "2026-06-02T00:00:00Z",
        "dimensions_covered": [
            "technical",
            "organizational",
            "domain",
            "market",
            "temporal",
        ],
        "topics_from_trunk": [
            {
                "id": "CT-1-001",
                "topic_type": "finding",
                "source_file": "rss.arxiv.org/cs.LG/paper-123",
                "source_snippet": "abstract",
                "proposed_filename": "Paper 123.md",
            }
        ],
        "intent_from_confluence": [],
        "proposed_filenames": ["Paper 123.md"],
        "sources_consulted": ["Journals", "Reddit"],
        "termination_condition": None,
        "notes_created": [],
        "unresolved_wikilinks": [],
        "budget_consumed_usd": 1.0,
    }
    report_path = vault / "_pipeline" / "cycles" / "cycle-001-scout.json"
    report_path.write_text(json.dumps(report))
    result = _run(VALIDATE_CYCLE, str(report_path), "--vault", str(vault))
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "not under enumerated repo" not in combined
    assert "priority=1" not in combined and "role=behaviour" not in combined
