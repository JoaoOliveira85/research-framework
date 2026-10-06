"""Contract tests for ``tests/_helpers/fake_agent.py`` (feature 018, T007).

Asserts every clause of ``specs/018-testing-strategy/contracts/fake-agent.contract.md``.
If a future change breaks the fake-agent contract, these tests are the
first to fail — louder than any tier-4 e2e regression and far cheaper
to triage.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests._helpers import fake_agent

# ---------------------------------------------------------------------------
# Shared minimal vault fixture (no dependency on vault_factory.py yet —
# the contract test sets the minimum required pipeline state by hand so
# it can run before T013 lands).
# ---------------------------------------------------------------------------


def _write_minimal_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline" / "cycles").mkdir(parents=True)
    (vault / "_pipeline" / "prompts").mkdir(parents=True)
    (vault / "data_vault" / "01 - Concepts").mkdir(parents=True)

    spec_dict: dict[str, Any] = {
        "name": "fake-agent-contract",
        "location": str(vault.resolve()),
        "owner": "tests",
        "scope": {
            "domain": "test",
            "organization": "test-org",
            "out_of_scope": ["crypto"],
        },
        "note_types": [
            {
                "name": "concept",
                "description": "A concept note.",
                "folder": "01 - Concepts",
                "min_word_count": 30,
            }
        ],
        "data_sources": [
            {"name": "synthetic", "type": "external", "description": "x", "priority": 2}
        ],
        "search_dimensions": ["technical"],
        "coverage_targets": {
            "categories": [
                {
                    "name": "cat_a",
                    "note_type": "concept",
                    "target_count": 3,
                    "met_count": 0,
                },
                {
                    "name": "cat_b",
                    "note_type": "concept",
                    "target_count": 2,
                    "met_count": 0,
                },
            ]
        },
        "budget": {"max_usd": 1.0, "max_cycles": 5},
        "max_cycles": 5,
    }
    (vault / "_pipeline" / "spec-parse.json").write_text(
        json.dumps(spec_dict, indent=2), encoding="utf-8"
    )
    targets_dict = {
        "last_updated": "2026-05-17T00:00:00Z",
        "cycle_number": 0,
        "categories": spec_dict["coverage_targets"]["categories"],
    }
    (vault / "_pipeline" / "coverage-targets.json").write_text(
        json.dumps(targets_dict, indent=2), encoding="utf-8"
    )
    return vault


def _write_scout_prompt(vault: Path, cycle: int) -> Path:
    p = vault / "_pipeline" / "prompts" / f"cycle-{cycle:03d}-scout-prompt.rendered.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"Cycle {cycle} scout prompt — please emit scout report.",
        encoding="utf-8",
    )
    return p


def _write_batch_prompt(vault: Path, cycle: int, topics: list[dict]) -> Path:
    p = vault / "_pipeline" / "prompts" / f"cycle-{cycle:03d}-batch-prompt.rendered.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"Cycle {cycle} batch note-writer prompt.\n\n"
        f"## Batch topics (JSON)\n\n```json\n{json.dumps(topics, indent=2)}\n```\n"
    )
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Contract assertions
# ---------------------------------------------------------------------------


def test_scout_stage_emits_v2_schema(tmp_path: Path) -> None:
    """Scout output has every key required by validate_cycle.REQUIRED_REPORT_FIELDS_V2."""
    vault = _write_minimal_vault(tmp_path)
    out = fake_agent.write_scout(vault, cycle=1, scenario="happy")
    assert out.is_file(), f"scout report not produced at {out}"
    doc = json.loads(out.read_text(encoding="utf-8"))

    required = {
        "schema_version",
        "cycle",
        "phase",
        "timestamp",
        "dimensions_covered",
        "topics_from_code",
        "intent_from_confluence",
        "sources_consulted",
        "budget_consumed_usd",
    }
    missing = sorted(required - set(doc))
    assert not missing, f"missing v2 fields: {missing}"
    assert doc["schema_version"] == "2.0"
    assert doc["phase"] == "scout"
    assert doc["cycle"] == 1
    assert isinstance(doc["topics_from_code"], list) and doc["topics_from_code"], (
        "topics_from_code must be non-empty in happy scenario"
    )
    # SG-001 / merge_scout_topics path:
    tf = doc.get("topics_found") or {}
    assert isinstance(tf.get("new"), list) and tf["new"], (
        "topics_found.new must be non-empty for SG-001 / merge_scout_topics"
    )
    for row in tf["new"]:
        assert isinstance(row, dict) and row.get("title"), row


def test_scout_stage_passes_validate_cycle(tmp_path: Path) -> None:
    """Real validate_cycle.py exits 0 on fake-produced scout."""
    vault = _write_minimal_vault(tmp_path)
    scout_path = fake_agent.write_scout(vault, cycle=1, scenario="happy")

    repo_root = Path(__file__).resolve().parents[2]
    validate_cycle = repo_root / "scripts" / "validate_cycle.py"
    assert validate_cycle.is_file(), validate_cycle

    proc = subprocess.run(
        [
            sys.executable,
            str(validate_cycle),
            str(scout_path),
            "--vault",
            str(vault),
            "--max-cycles",
            "5",
            "--budget-cap",
            "1.0",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"validate_cycle exit {proc.returncode}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )


def test_note_writer_stage_writes_one_note_per_batch_topic(tmp_path: Path) -> None:
    vault = _write_minimal_vault(tmp_path)
    topics = [
        {
            "title": "cat_a topic 1",
            "category": "cat_a",
            "priority_score": 1.0,
            "provenance": "scout",
        },
        {
            "title": "cat_a topic 2",
            "category": "cat_a",
            "priority_score": 0.9,
            "provenance": "scout",
        },
        {
            "title": "cat_b topic 1",
            "category": "cat_b",
            "priority_score": 0.8,
            "provenance": "scout",
        },
    ]
    prompt = _write_batch_prompt(vault, 1, topics)
    paths = fake_agent.process_batch(vault, prompt, cycle=1, scenario="happy")
    assert len(paths) == 3, paths
    for p, t in zip(paths, topics):
        assert p.is_file()
        text = p.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        fm_block = text.split("---", 2)[1]
        fm = yaml.safe_load(fm_block) or {}
        for key in ("type", "coverage_category", "source_urls", "summary"):
            assert fm.get(key), f"missing/empty {key} in {p.name}: {fm}"
        assert fm["coverage_category"] == t["category"]
        assert int((fm.get("lifecycle") or {}).get("created_at_cycle")) == 1


def test_note_writer_stage_appends_to_research_json_atomically(tmp_path: Path) -> None:
    vault = _write_minimal_vault(tmp_path)
    research = vault / "_pipeline" / "cycles" / "cycle-001-research.json"
    research.write_text(
        json.dumps(
            {"notes_created": ["pre-existing.md"], "notes_updated": []}, indent=2
        ),
        encoding="utf-8",
    )
    topics = [
        {"title": "cat_a topic 1", "category": "cat_a"},
        {"title": "cat_a topic 2", "category": "cat_a"},
    ]
    prompt = _write_batch_prompt(vault, 1, topics)
    fake_agent.process_batch(vault, prompt, cycle=1, scenario="happy")
    doc = json.loads(research.read_text(encoding="utf-8"))
    assert "pre-existing.md" in doc["notes_created"], doc
    # Vault-relative paths (verifier stage resolves notes under data_vault/):
    assert "data_vault/01 - Concepts/cat-a-topic-1.md" in doc["notes_created"], doc
    assert "data_vault/01 - Concepts/cat-a-topic-2.md" in doc["notes_created"], doc
    # The v2 research report shape required by validate_cycle:
    assert doc["schema_version"] == "2.0"
    assert doc["phase"] == "research"
    assert doc["cycle"] == 1
    sources = doc["sources_consulted"]
    assert isinstance(sources, dict) and sources, doc
    for key, entry in sources.items():
        assert isinstance(entry, dict) and entry.get("searched") is True


def test_determinism_byte_identical_outputs_for_same_inputs(tmp_path: Path) -> None:
    vault1 = _write_minimal_vault(tmp_path / "run1")
    vault2 = _write_minimal_vault(tmp_path / "run2")
    p1 = fake_agent.write_scout(vault1, cycle=2, scenario="happy")
    p2 = fake_agent.write_scout(vault2, cycle=2, scenario="happy")
    assert p1.read_bytes() == p2.read_bytes(), "scout output must be byte-identical"

    topics = [
        {"title": "cat_a topic 1", "category": "cat_a"},
        {"title": "cat_b topic 1", "category": "cat_b"},
    ]
    bp1 = _write_batch_prompt(vault1, 2, topics)
    bp2 = _write_batch_prompt(vault2, 2, topics)
    n1 = fake_agent.process_batch(vault1, bp1, cycle=2, scenario="happy")
    n2 = fake_agent.process_batch(vault2, bp2, cycle=2, scenario="happy")
    assert [p.name for p in n1] == [p.name for p in n2]
    for a, b in zip(n1, n2):
        assert a.read_bytes() == b.read_bytes(), f"note {a.name} differs between runs"


def test_empty_scout_scenario_emits_empty_topics_lists(tmp_path: Path) -> None:
    vault = _write_minimal_vault(tmp_path)
    out = fake_agent.write_scout(vault, cycle=1, scenario="empty_scout")
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["topics_from_code"] == []
    assert (doc.get("topics_found") or {}).get("new") == []
    assert doc["schema_version"] == "2.0"


def test_fail_frontmatter_scenario_omits_source_urls(tmp_path: Path) -> None:
    vault = _write_minimal_vault(tmp_path)
    topics = [{"title": "cat_a topic 1", "category": "cat_a"}]
    prompt = _write_batch_prompt(vault, 1, topics)
    paths = fake_agent.process_batch(
        vault, prompt, cycle=1, scenario="fail_frontmatter"
    )
    assert paths
    text = paths[0].read_text(encoding="utf-8")
    fm = yaml.safe_load(text.split("---", 2)[1]) or {}
    assert "source_urls" not in fm or not fm.get("source_urls")


def test_cli_round_trip_via_subprocess(tmp_path: Path) -> None:
    """Smoke: `python -m tests._helpers.fake_agent --stage scout ...` produces a valid report."""
    vault = _write_minimal_vault(tmp_path)
    prompt = _write_scout_prompt(vault, cycle=3)
    cost = vault / "_pipeline" / "cycles" / "cycle-003-scout.cost.json"

    repo_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests._helpers.fake_agent",
            "--vault",
            str(vault),
            "--stage",
            "scout",
            "--prompt-file",
            str(prompt),
            "--cost-sidecar",
            str(cost),
        ],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        env={**__import__("os").environ, "PYTHONPATH": str(repo_root)},
    )
    assert proc.returncode == 0, proc.stderr
    scout_out = vault / "_pipeline" / "cycles" / "cycle-003-scout.json"
    assert scout_out.is_file()
    assert cost.is_file()
    doc = json.loads(cost.read_text(encoding="utf-8"))
    assert doc["cost_usd"] == 0.0
    assert doc["scenario"] == "happy"


def test_shim_installation_writes_executable_script(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    shim = fake_agent.install_shim(scripts)
    assert shim.is_file()
    # Re-installing must be idempotent (overwrite, not append).
    shim2 = fake_agent.install_shim(scripts)
    assert shim2.read_text(encoding="utf-8") == shim.read_text(encoding="utf-8")
    assert shim.stat().st_mode & 0o111, "shim must be marked executable"


def test_resolve_scenario_per_stage_overrides_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "empty_scout")
    monkeypatch.setenv("FAKE_AGENT_NOTE_WRITER_SCENARIO", "fail_frontmatter")
    assert fake_agent._resolve_scenario("scout") == "empty_scout"
    assert fake_agent._resolve_scenario("note_writer") == "fail_frontmatter"


def test_resolve_scenario_rejects_unknown_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "definitely_invalid")
    with pytest.raises(ValueError):
        fake_agent._resolve_scenario("scout")


# ---------------------------------------------------------------------------
# v2 stage extensions (spec 024 US2 — verifier, narrator, probe_retrieval)
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_fake_agent_subprocess(
    tmp_path: Path,
    *,
    stage: str,
    env: dict[str, str],
    cycle: int = 3,
    output_file: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    vault = _write_minimal_vault(tmp_path)
    prompt = vault / "_pipeline" / "prompts" / f"cycle-{cycle:03d}-prompt.rendered.md"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text(
        f"Cycle {cycle} rendered prompt for fake-agent contract test.\n",
        encoding="utf-8",
    )
    cmd = [
        sys.executable,
        "-m",
        "tests._helpers.fake_agent",
        "--vault",
        str(vault),
        "--stage",
        stage,
        "--prompt-file",
        str(prompt),
    ]
    if output_file is not None:
        cmd.extend(["--output-file", str(output_file)])
    repo_root = _repo_root()
    merged_env = {**__import__("os").environ, "PYTHONPATH": str(repo_root), **env}
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        env=merged_env,
    )


def _assert_byte_identical_runs(
    tmp_path: Path,
    *,
    stage: str,
    env: dict[str, str],
    cycle: int = 3,
    output_file: Path | None = None,
) -> bytes:
    out1 = tmp_path / "run1"
    out2 = tmp_path / "run2"
    out1.mkdir()
    out2.mkdir()
    of1 = output_file
    of2 = output_file
    if output_file is not None:
        of1 = out1 / output_file.name
        of2 = out2 / output_file.name
    proc1 = _run_fake_agent_subprocess(
        out1, stage=stage, env=env, cycle=cycle, output_file=of1
    )
    proc2 = _run_fake_agent_subprocess(
        out2, stage=stage, env=env, cycle=cycle, output_file=of2
    )
    assert proc1.returncode == 0, proc1.stderr
    assert proc2.returncode == 0, proc2.stderr
    if of1 is not None and of1.is_file():
        b1, b2 = of1.read_bytes(), of2.read_bytes()
    else:
        b1, b2 = proc1.stdout.encode(), proc2.stdout.encode()
    assert b1 == b2, "outputs must be byte-identical across two invocations"
    return b1


def test_verifier_accept_emits_canonical_verdict(tmp_path: Path) -> None:
    env = {"FAKE_AGENT_VERIFIER_SCENARIO": "accept"}
    raw = _assert_byte_identical_runs(
        tmp_path, stage="verifier", env=env, output_file=Path("verdict.json")
    )
    doc = json.loads(raw.decode("utf-8"))
    assert doc["verdict"] == "accept"
    assert doc["violations"] == []
    assert doc.get("suggested_fix") is None


def test_verifier_reject_emits_violations(tmp_path: Path) -> None:
    out = tmp_path / "verdict.json"
    proc = _run_fake_agent_subprocess(
        tmp_path,
        stage="verifier",
        env={"FAKE_AGENT_VERIFIER_SCENARIO": "reject"},
        output_file=out,
    )
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["verdict"] == "reject"
    assert len(doc["violations"]) >= 1
    for v in doc["violations"]:
        assert v.get("code") and v.get("message")
    assert doc.get("suggested_fix")


def test_verifier_malformed_json_exercises_parser_tolerance(tmp_path: Path) -> None:
    out = tmp_path / "verdict-raw.txt"
    proc = _run_fake_agent_subprocess(
        tmp_path,
        stage="verifier",
        env={"FAKE_AGENT_VERIFIER_SCENARIO": "malformed_json"},
        output_file=out,
    )
    assert proc.returncode == 0, proc.stderr
    content = out.read_text(encoding="utf-8")
    from research_framework.pipeline.verifier import _extract_json_blob

    verdict = _extract_json_blob(content)
    assert verdict is not None, content
    assert verdict["verdict"] == "reject"


def test_narrator_happy_emits_short_markdown(tmp_path: Path) -> None:
    cycle = 7
    env = {"FAKE_AGENT_RESEARCH_PLAN_NARRATOR_SCENARIO": "happy"}
    b1 = _assert_byte_identical_runs(
        tmp_path, stage="research_plan_narrator", env=env, cycle=cycle
    )
    text = b1.decode("utf-8")
    assert text.strip()
    assert len(text.split()) <= 200
    assert f"cycle {cycle}" in text


def test_probe_retrieval_happy_emits_array(tmp_path: Path) -> None:
    env = {"FAKE_AGENT_PROBE_RETRIEVAL_SCENARIO": "happy"}
    b1 = _assert_byte_identical_runs(tmp_path, stage="probe_retrieval", env=env)
    rows = json.loads(b1.decode("utf-8"))
    assert isinstance(rows, list) and len(rows) >= 2
    for row in rows:
        assert row.get("query") and row.get("answer")
        sources = row.get("sources")
        assert isinstance(sources, list) and sources
        for url in sources:
            assert isinstance(url, str) and url.startswith("http")


def test_unknown_scenario_fails_loud(tmp_path: Path) -> None:
    proc = _run_fake_agent_subprocess(
        tmp_path,
        stage="verifier",
        env={"FAKE_AGENT_VERIFIER_SCENARIO": "does_not_exist"},
    )
    assert proc.returncode == 2
    assert "does_not_exist" in proc.stderr


# ---------------------------------------------------------------------------
# Weekly-runner stages + unknown-stage fail-closed (issue #261)
# ---------------------------------------------------------------------------


def _run_stage_with_prompt(
    vault: Path, *, stage: str, prompt_body: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Invoke the fake CLI against an already-built vault and a chosen prompt.

    ``_run_fake_agent_subprocess`` builds its own vault and writes a fixed
    prompt; the runner stages are about what the *prompt body* names, so they
    need to choose it.
    """
    prompt = vault / "_pipeline" / "stage-prompt.rendered.md"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text(prompt_body, encoding="utf-8")
    repo_root = _repo_root()
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tests._helpers.fake_agent",
            "--vault",
            str(vault),
            "--stage",
            stage,
            "--prompt-file",
            str(prompt),
        ],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        env={
            **__import__("os").environ,
            "PYTHONPATH": str(repo_root),
            **(env or {}),
        },
    )


def _research_prompt(vault: Path) -> str:
    """The shape `runner._render_stage_prompt` produces for the research stage."""
    return (
        "DFS research cycle 1.\n"
        f"Read the scout report at `{vault / '_pipeline' / 'scout-report.json'}`.\n"
        f"Write the JSON report to: `{vault / '_pipeline' / 'research-report.json'}`\n"
    )


def test_unknown_stage_fails_closed(tmp_path: Path) -> None:
    """A stage the fake does not implement must not read as a green run.

    Before issue #261 the fake exited 0 and wrote a ``status: ok`` sidecar for
    every unrecognised ``--stage``, so a typo or an unwired stage passed the
    e2e tier silently.
    """
    vault = _write_minimal_vault(tmp_path)
    cost = tmp_path / "cost.json"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests._helpers.fake_agent",
            "--vault",
            str(vault),
            "--stage",
            "reserch",
            "--prompt-file",
            str(_write_scout_prompt(vault, cycle=1)),
            "--cost-sidecar",
            str(cost),
        ],
        capture_output=True,
        text=True,
        cwd=str(_repo_root()),
        env={**__import__("os").environ, "PYTHONPATH": str(_repo_root())},
    )

    assert proc.returncode == 2, proc.stdout
    assert "reserch" in proc.stderr
    assert "FAKE_AGENT_ALLOW_UNKNOWN_STAGE" in proc.stderr
    # #261 asserted "no sidecar at all", which overshot its own reasoning: the
    # thing that made a failure read green was ``status: ok``, not the file's
    # existence. Since #262 the fake records the failure the way the real
    # dispatcher does, so a failed stage IS visible in the agent-calls index.
    sidecar = json.loads(cost.read_text(encoding="utf-8"))
    assert sidecar["status"] == "failed"
    assert sidecar["exit_code"] == 2


def test_unknown_stage_opt_in_restores_the_no_op(tmp_path: Path) -> None:
    """The escape hatch for a caller that genuinely wants the old no-op."""
    vault = _write_minimal_vault(tmp_path)

    proc = _run_stage_with_prompt(
        vault,
        stage="some_auxiliary_stage",
        prompt_body="Cycle 1 auxiliary prompt.\n",
        env={"FAKE_AGENT_ALLOW_UNKNOWN_STAGE": "1"},
    )

    assert proc.returncode == 0, proc.stderr


def test_research_stage_writes_the_report_the_prompt_names(tmp_path: Path) -> None:
    vault = _write_minimal_vault(tmp_path)

    proc = _run_stage_with_prompt(
        vault, stage="research", prompt_body=_research_prompt(vault)
    )

    assert proc.returncode == 0, proc.stderr
    report = vault / "_pipeline" / "research-report.json"
    assert report.is_file()
    doc = json.loads(report.read_text(encoding="utf-8"))
    assert doc["schema_version"] == "2.0"
    assert doc["phase"] == "research"
    assert isinstance(doc["sources_consulted"], dict) and doc["sources_consulted"]


def test_research_stage_fails_when_the_prompt_names_no_report(tmp_path: Path) -> None:
    """Positive proof that the rendered prompt carried the artifact path.

    A prompt that still holds the raw ``{RESEARCH_REPORT}`` placeholder — or
    names no report at all — is a rendering bug, and the fake is the only
    thing positioned to see it.
    """
    vault = _write_minimal_vault(tmp_path)

    proc = _run_stage_with_prompt(
        vault,
        stage="research",
        prompt_body="DFS research cycle 1.\nWrite the JSON report to: `{RESEARCH_REPORT}`\n",
    )

    assert proc.returncode == 2
    assert "research-report.json" in proc.stderr


def test_report_stage_writes_the_weekly_export(tmp_path: Path) -> None:
    vault = _write_minimal_vault(tmp_path)

    proc = _run_stage_with_prompt(
        vault, stage="report", prompt_body="# Weekly Report Agent\n\nCycle 1.\n"
    )

    assert proc.returncode == 0, proc.stderr
    export = vault / "_pipeline" / "exports" / "weekly-report.md"
    assert export.is_file()
    text = export.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "type: weekly-report" in text


def test_scenario_discovery_walk() -> None:
    """Every scenario JSON under fake_agent_scenarios/ has a matching test."""
    contract_path = Path(__file__).resolve()
    source = contract_path.read_text(encoding="utf-8")
    root = fake_agent.SCENARIOS_ROOT
    assert root.is_dir(), root
    orphans: list[str] = []
    for stage_dir in sorted(root.iterdir()):
        if not stage_dir.is_dir():
            continue
        stage = stage_dir.name
        for scenario_file in sorted(stage_dir.glob("*.json")):
            scenario = scenario_file.stem
            needle = f"test_{stage}_{scenario}_"
            if needle not in source:
                orphans.append(f"{stage}/{scenario}.json")
    assert not orphans, f"scenario files without matching tests: {orphans}"
