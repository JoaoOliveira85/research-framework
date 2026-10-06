"""Spec 066 FR4 — ``./vault re-grade`` verb.

Contract: specs/066-credibility-model-calibration/contracts/regrade-verb.contract.md
Tier: 2/3 (filesystem + git + the deterministic credibility model; zero LLM).
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

from research_framework.cli.regrade import RegradeOutcome, run_regrade
from research_framework.vault.frontmatter import parse_frontmatter

_SPEC = textwrap.dedent(
    """\
    ---
    name: Regrade Test Vault
    owner: tester
    scope:
      domain: "Testing the re-grade verb"
      organization: "test"
    note_types:
      - name: concept
        description: "concept notes"
        folder: "01 - Concepts"
        min_word_count: 0
    data_sources: []
    search_dimensions: ["domain"]
    coverage_targets:
      categories:
        - name: concepts
          note_type: concept
          target_count: 5
          met_count: 0
          required: true
    budget:
      max_usd: 10.0
      max_cycles: 5
    max_cycles: 5
    ---

    # Regrade Test Vault
    """
)

_COVERAGE_TARGETS = {
    "last_updated": "",
    "cycle_number": 0,
    "categories": [
        {
            "name": "concepts",
            "note_type": "concept",
            "target_count": 5,
            "met_count": 0,
            "required": True,
            "display_name": "Concepts",
        }
    ],
}


def _build_vault(tmp_path: Path, *, policy: str = "warn", git: bool = True) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline" / "quarantine").mkdir(parents=True, exist_ok=True)
    (vault / "data_vault" / "01 - Concepts").mkdir(parents=True, exist_ok=True)
    (vault / "research.spec.md").write_text(_SPEC, encoding="utf-8")
    settings = {"pipeline": {"max_cycles": 5, "budget_usd": 10.0}}
    if policy != "warn":
        settings["credibility"] = {"unknown_domain_policy": policy}
    (vault / "settings.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")
    import json

    (vault / "_pipeline" / "coverage-targets.json").write_text(
        json.dumps(_COVERAGE_TARGETS), encoding="utf-8"
    )
    if git:
        subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"], cwd=vault, check=True
        )
        subprocess.run(["git", "config", "user.name", "t"], cwd=vault, check=True)
        subprocess.run(["git", "add", "-A"], cwd=vault, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=vault, check=True)
    return vault


def _quarantine(
    vault: Path,
    name: str,
    *,
    url: str,
    notes: list[str],
    coverage_category: str = "Concepts",
) -> Path:
    fm = {
        "title": name,
        "type": "concept",
        "coverage_category": coverage_category,
        "verifier_status": "rejected",
        "verifier_notes": notes,
        "source_urls": [{"url": url}],
    }
    p = vault / "_pipeline" / "quarantine" / f"{name}.md"
    p.write_text(
        "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\nBody.\n", encoding="utf-8"
    )
    return p


_CRED_NOTE = "citation lacks credibility and no source default applies"


# --- reinstatement ----------------------------------------------------------


def test_catalog_hit_note_is_reinstated(tmp_path: Path) -> None:
    vault = _build_vault(tmp_path)
    note = _quarantine(vault, "Fastify", url="https://fastify.dev/", notes=[_CRED_NOTE])
    rc = run_regrade(vault, json_output=False)
    assert rc == 0
    assert not note.exists()
    dest = vault / "data_vault" / "01 - Concepts" / "Fastify.md"
    assert dest.is_file()
    fm = yaml.safe_load(dest.read_text(encoding="utf-8").split("---")[1])
    assert fm["verifier_status"] == "verified"
    assert "verifier_notes" not in fm


def test_reinstatement_commits(tmp_path: Path) -> None:
    vault = _build_vault(tmp_path)
    _quarantine(vault, "Fastify", url="https://fastify.dev/", notes=[_CRED_NOTE])
    run_regrade(vault, json_output=False)
    log = subprocess.run(
        ["git", "log", "--pretty=%s"], cwd=vault, capture_output=True, text=True
    ).stdout
    assert "regrade(" in log and "1 note reinstated" in log


# --- still quarantined ------------------------------------------------------


def test_catalog_miss_under_reject_stays_quarantined(tmp_path: Path) -> None:
    vault = _build_vault(tmp_path, policy="reject")
    note = _quarantine(
        vault, "Unknown", url="https://kubernetes.default.svc/x", notes=[_CRED_NOTE]
    )
    run_regrade(vault, json_output=False)
    assert note.exists()  # still in quarantine


def test_catalog_miss_under_warn_is_reinstated(tmp_path: Path) -> None:
    vault = _build_vault(tmp_path, policy="warn")
    note = _quarantine(
        vault, "Unknown", url="https://kubernetes.default.svc/x", notes=[_CRED_NOTE]
    )
    run_regrade(vault, json_output=False)
    # warn policy: an ungraded WARN does not block reinstatement.
    assert not note.exists()


# --- skipped non-credibility ------------------------------------------------


def test_non_credibility_rejection_skipped(tmp_path: Path) -> None:
    vault = _build_vault(tmp_path)
    note = _quarantine(
        vault,
        "Semantic",
        url="https://fastify.dev/",
        notes=[_CRED_NOTE, "presents a planned feature as shipped"],
    )
    run_regrade(vault, json_output=False)
    assert note.exists()  # untouched — agent-semantic note present


# --- a `---` inside a frontmatter value --------------------------------------

# Keys in the order the verifier's stamp writes them (``yaml.dump`` sorts), so
# ``verifier_notes`` sits below the slug URL.
_SLUG_URL = "https://fastify.dev/docs/kafka---a-guide"


def _quarantine_with_slug_url(vault: Path, name: str, notes: list[str]) -> Path:
    fm = {
        "coverage_category": "Concepts",
        "source_urls": [{"url": _SLUG_URL}],
        "title": name,
        "type": "concept",
        "verifier_notes": notes,
        "verifier_status": "rejected",
    }
    p = vault / "_pipeline" / "quarantine" / f"{name}.md"
    p.write_text(
        "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\nBody.\n",
        encoding="utf-8",
    )
    return p


def test_reinstatement_keeps_a_frontmatter_value_containing_dashes(
    tmp_path: Path,
) -> None:
    """The frontmatter ends at a ``---`` line, not at the first ``---`` substring."""
    vault = _build_vault(tmp_path)
    note = _quarantine_with_slug_url(vault, "Slug", [_CRED_NOTE])

    run_regrade(vault, json_output=False)

    assert not note.exists()
    dest = vault / "data_vault" / "01 - Concepts" / "Slug.md"
    fm, body = parse_frontmatter(dest)
    assert fm == {
        "coverage_category": "Concepts",
        "source_urls": [{"url": _SLUG_URL}],
        "title": "Slug",
        "type": "concept",
        "verifier_status": "verified",
    }
    assert body == "Body.\n"


def test_non_credibility_rejection_below_a_dashes_value_is_skipped(
    tmp_path: Path,
) -> None:
    """A cut frontmatter hid ``verifier_notes``, so the rejection read as none."""
    vault = _build_vault(tmp_path)
    note = _quarantine_with_slug_url(
        vault, "Semantic", [_CRED_NOTE, "presents a planned feature as shipped"]
    )
    before = note.read_text(encoding="utf-8")

    run_regrade(vault, json_output=False)

    assert not (vault / "data_vault" / "01 - Concepts" / "Semantic.md").exists()
    assert note.read_text(encoding="utf-8") == before


# --- dry-run + idempotency --------------------------------------------------


def test_dry_run_touches_nothing(tmp_path: Path) -> None:
    vault = _build_vault(tmp_path)
    note = _quarantine(vault, "Fastify", url="https://fastify.dev/", notes=[_CRED_NOTE])
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=vault, capture_output=True, text=True
    ).stdout.strip()
    run_regrade(vault, dry_run=True, json_output=False)
    assert note.exists()
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=vault, capture_output=True, text=True
    ).stdout.strip()
    assert head_before == head_after


def test_empty_quarantine_is_noop(tmp_path: Path) -> None:
    vault = _build_vault(tmp_path)
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=vault, capture_output=True, text=True
    ).stdout.strip()
    rc = run_regrade(vault, json_output=False)
    assert rc == 0
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=vault, capture_output=True, text=True
    ).stdout.strip()
    assert head_before == head_after  # no empty commit


def test_second_run_is_noop(tmp_path: Path) -> None:
    vault = _build_vault(tmp_path)
    _quarantine(vault, "Fastify", url="https://fastify.dev/", notes=[_CRED_NOTE])
    run_regrade(vault, json_output=False)
    head_after_first = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=vault, capture_output=True, text=True
    ).stdout.strip()
    run_regrade(vault, json_output=False)
    head_after_second = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=vault, capture_output=True, text=True
    ).stdout.strip()
    assert head_after_first == head_after_second


# --- --note filter + JSON ---------------------------------------------------


def test_note_filter_only_named(tmp_path: Path) -> None:
    vault = _build_vault(tmp_path)
    a = _quarantine(vault, "Fastify", url="https://fastify.dev/", notes=[_CRED_NOTE])
    b = _quarantine(vault, "Express", url="https://expressjs.com/", notes=[_CRED_NOTE])
    run_regrade(vault, notes=["Fastify.md"], json_output=False)
    assert not a.exists()
    assert b.exists()  # not named → untouched


def test_json_output_shape(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = _build_vault(tmp_path)
    _quarantine(vault, "Fastify", url="https://fastify.dev/", notes=[_CRED_NOTE])
    run_regrade(vault, json_output=True)
    import json as _json

    out = _json.loads(capsys.readouterr().out)
    assert out["vault"]
    assert len(out["reinstated"]) == 1
    assert out["reinstated"][0]["note"] == "Fastify.md"
    assert out["commit"]


# --- RegradeOutcome dataclass ----------------------------------------------


def test_regrade_outcome_to_dict() -> None:
    o = RegradeOutcome(note="X.md", action="reinstated", destination="data_vault/X.md")
    d = o.to_dict()
    assert d["note"] == "X.md"
    assert d["action"] == "reinstated"
    assert d["remaining"] == []
