"""Contract test for ``build_quality_fixture`` (spec 022, T015 / research § D6)."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from tests._helpers.vault_factory import build_quality_fixture

_MINIMAL_SPEC = """\
---
name: quality-fixture-contract
owner: tests
scope:
  domain: test-domain
  organization: test-org
  out_of_scope: [crypto]
note_types:
  - name: concept
    description: Synthetic concept for quality harness contract test.
    folder: "01 - Concepts"
    min_word_count: 30
data_sources:
  - name: synthetic
    type: external
    description: Synthetic source.
    priority: 2
search_dimensions: [technical]
coverage_targets:
  categories:
    - name: cat_a
      note_type: concept
      target_count: 3
      met_count: 0
budget:
  max_usd: 10.0
  max_cycles: 3
---

# Quality fixture contract
"""


def test_build_quality_fixture_signature_matches_d6() -> None:
    sig = inspect.signature(build_quality_fixture)
    params = list(sig.parameters)
    assert params[:2] == ["name", "vault_dir"]
    assert "spec_yaml" in sig.parameters
    assert "note_count_target" in sig.parameters
    assert "fake_agent_responses_src" in sig.parameters
    assert sig.return_annotation in (Path, "Path")


def test_build_quality_fixture_writes_expected_layout(tmp_path: Path) -> None:
    vault = tmp_path / "tech-lite"
    responses_src = tmp_path / "responses-src"
    (responses_src / "scout").mkdir(parents=True)
    (responses_src / "scout" / "happy.json").write_text(
        json.dumps({"topics": []}) + "\n",
        encoding="utf-8",
    )

    out = build_quality_fixture(
        "tech-lite",
        vault,
        spec_yaml=_MINIMAL_SPEC,
        note_count_target=18,
        fake_agent_responses_src=responses_src,
    )

    assert out == vault.resolve()
    assert (vault / "research.spec.md").is_file()
    assert (vault / "settings.yaml").is_file()
    assert (vault / "coverage-targets.json").is_file()
    assert (vault / "_templates").is_dir()
    assert (vault / "_templates" / "concept.md").is_file()
    assert (vault / "fake_agent_responses" / "scout" / "happy.json").is_file()
    assert (vault / "scripts" / "agent_call.py").is_file()
    settings = (vault / "settings.yaml").read_text(encoding="utf-8")
    assert "fake_agent_responses_dir" in settings
    assert "max_cycles: 3" in settings


def _contract_file_digest(vault: Path) -> dict[str, str]:
    from tests._helpers.vault_factory import _sha256_bytes, _tree_digest

    paths = {
        "spec": vault / "research.spec.md",
        "settings": vault / "settings.yaml",
        "coverage": vault / "coverage-targets.json",
    }
    out = {key: _sha256_bytes(path.read_bytes()) for key, path in paths.items()}
    out["responses"] = _tree_digest(vault / "fake_agent_responses")
    return out


def test_build_quality_fixture_idempotent_when_inputs_unchanged(tmp_path: Path) -> None:
    vault = tmp_path / "source-poor"
    responses_src = tmp_path / "responses-src"
    (responses_src / "verifier").mkdir(parents=True)
    (responses_src / "verifier" / "accept.json").write_text("{}\n", encoding="utf-8")

    build_quality_fixture(
        "source-poor",
        vault,
        spec_yaml=_MINIMAL_SPEC,
        note_count_target=17,
        fake_agent_responses_src=responses_src,
    )
    before = _contract_file_digest(vault)

    build_quality_fixture(
        "source-poor",
        vault,
        spec_yaml=_MINIMAL_SPEC,
        note_count_target=17,
        fake_agent_responses_src=responses_src,
    )
    assert _contract_file_digest(vault) == before


def test_build_quality_fixture_recopies_when_fake_agent_tree_changes(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "source-rich"
    responses_src = tmp_path / "responses-src"
    stage = responses_src / "note_writer"
    stage.mkdir(parents=True)
    (stage / "happy.json").write_text("{}\n", encoding="utf-8")

    build_quality_fixture(
        "source-rich",
        vault,
        spec_yaml=_MINIMAL_SPEC,
        note_count_target=20,
        fake_agent_responses_src=responses_src,
    )
    (stage / "reject.json").write_text('{"error": true}\n', encoding="utf-8")

    build_quality_fixture(
        "source-rich",
        vault,
        spec_yaml=_MINIMAL_SPEC,
        note_count_target=20,
        fake_agent_responses_src=responses_src,
    )
    assert (vault / "fake_agent_responses" / "note_writer" / "reject.json").is_file()
