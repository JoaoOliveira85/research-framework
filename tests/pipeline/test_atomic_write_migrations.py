"""Assert Phase-1 writers delegate to pipeline.atomic_write (spec 023 FR-018)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from research_framework.pipeline import (
    plan_narrator,
    research_plan,
    runner,
    verifier,
    wikilinks,
)
from research_framework.pipeline.research_plan import (
    CategoryFillState,
    ResearchPlan,
)
from research_framework.pipeline.steps import postprocess, run_research, run_scout
from research_framework.pipeline.steps._types import (
    CycleContext,
    ResearchResult,
    ScoutedTopic,
    ScoutResult,
)
from tests.pipeline.test_batch_orchestration import (
    _patch_cycle_runner_subprocess,
    _write_plan,
)
from tests.pipeline.test_cycle_runner import _make_vault


def _ctx(vault: Path) -> CycleContext:
    pipeline = vault / "_pipeline"
    cycles = pipeline / "cycles"
    return CycleContext(
        vault_dir=vault,
        cycle_num=1,
        cycle_dir=cycles / "cycle-001",
        settings={},
        scripts_dir=vault / "scripts",
        pipeline_dir=pipeline,
        cycles_dir=cycles,
        prompts_dir=pipeline / "prompts",
        python_bin="python3",
        env={"RV_PYTHON": "python3"},
    )


def _write_scout_plan(vault: Path) -> None:
    plan = ResearchPlan(
        cycle_number=1,
        generated_at="2026-05-15T12:00:00Z",
        framework_version="0.3.2",
        coverage_state=[
            CategoryFillState(
                name="concepts",
                target_count=10,
                met_count=0,
                fill_pct=0.0,
                priority=50,
            )
        ],
        priority_queue=[],
        cycle_focus=["concepts"],
        cycle_quota=5,
        exclusions=[],
        narrative_header="",
    )
    (vault / "_pipeline" / "research-plan.md").write_text(
        plan.to_markdown(), encoding="utf-8"
    )


def test_research_step_batch_json_calls_atomic_write(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_plan(vault, quota=1)
    cycles = vault / "_pipeline/cycles"
    scout_path = cycles / "cycle-001-scout.json"
    scout_path.write_text(
        json.dumps({"topics_found": {"new": [{"title": "Alpha"}], "existing": []}}),
        encoding="utf-8",
    )
    (cycles / "cycle-001-research.json").write_text(
        json.dumps({"notes_created": [], "notes_updated": []}),
        encoding="utf-8",
    )

    def _fake_run(cmd, **kwargs):
        mock = MagicMock(returncode=0, stdout=b"")
        return mock

    scout = ScoutResult(
        topics_found=[ScoutedTopic(title="Alpha")],
        sg_trips=[],
        duration_ms=1,
        cost_usd=0.0,
        raw_json_path=scout_path,
        exit_code=0,
    )

    with (
        patch(
            "research_framework.pipeline.steps.research._atomic_write_json"
        ) as write_json,
        _patch_cycle_runner_subprocess(_fake_run),
    ):
        run_research(_ctx(vault), scout)

    batch_paths = [str(c.args[0]) for c in write_json.call_args_list]
    assert any("cycle-001-batch-" in p and p.endswith(".json") for p in batch_paths)


def test_research_step_research_json_calls_atomic_write(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_plan(vault, quota=1)
    cycles = vault / "_pipeline/cycles"
    scout_path = cycles / "cycle-001-scout.json"
    scout_path.write_text(json.dumps({"topics_found": {"new": []}}), encoding="utf-8")

    def _fake_run(cmd, **kwargs):
        return MagicMock(returncode=0, stdout=b"")

    scout = ScoutResult(
        topics_found=[],
        sg_trips=[],
        duration_ms=0,
        cost_usd=0.0,
        raw_json_path=scout_path,
        exit_code=0,
    )

    with (
        patch(
            "research_framework.pipeline.steps.research._atomic_write_json"
        ) as write_json,
        _patch_cycle_runner_subprocess(_fake_run),
    ):
        run_research(_ctx(vault), scout)

    research_paths = [str(c.args[0]) for c in write_json.call_args_list]
    assert any(p.endswith("cycle-001-research.json") for p in research_paths)


def test_postprocess_step_cycle_json_calls_atomic_write(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    (vault / "_pipeline/vault-metrics.json").write_text("{}", encoding="utf-8")
    cycles = vault / "_pipeline/cycles"
    with patch.object(postprocess, "_atomic_write_json") as aw:
        postprocess.run_postprocess(
            _ctx(vault),
            ResearchResult([], [], 0, 0.0, cycles / "cycle-001-research.json"),
        )
        assert any("postprocess.json" in str(c[0][0]) for c in aw.call_args_list)


def test_scout_step_plan_write_calls_atomic_write(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_scout_plan(vault)
    scout_path = vault / "_pipeline/cycles/cycle-001-scout.json"
    scout_doc = {
        "topics_found": {"new": [{"title": "ScoutTopic"}], "existing": [], "total": 1},
        "cost_estimate_usd": 0.01,
    }

    def _fake_run(cmd, **kwargs):
        script = Path(cmd[1]).name if len(cmd) > 1 else ""
        if (
            script == "agent_call.py"
            and "--stage" in cmd
            and cmd[cmd.index("--stage") + 1] == "scout"
        ):
            scout_path.write_text(json.dumps(scout_doc), encoding="utf-8")
        return MagicMock(returncode=0, stdout=b"")

    with (
        patch("research_framework.pipeline.atomic_write.write_text") as write_text,
        _patch_cycle_runner_subprocess(_fake_run),
    ):
        result = run_scout(_ctx(vault))

    assert result.exit_code == 0
    written = [str(c.args[0]) for c in write_text.call_args_list]
    assert any(p.endswith("research-plan.md") for p in written)
    assert any("cycle-001-research-plan.md" in p for p in written)


def test_verifier_stamp_frontmatter_calls_atomic_write(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("---\nstatus: draft\n---\nbody\n", encoding="utf-8")
    with patch("research_framework.pipeline.atomic_write.write_text") as aw:
        verifier._stamp_frontmatter(note, "verified", [])
        aw.assert_called_once()


def test_verifier_stamp_keeps_a_frontmatter_value_containing_dashes(
    tmp_path: Path,
) -> None:
    """The closing delimiter is a ``---`` LINE. Splitting on the first ``---``
    substring cut the frontmatter inside a slug URL and moved the rest of it
    into the body — on every note the verifier stamped."""
    from research_framework.vault.frontmatter import parse_frontmatter

    url = "https://dev.to/someone/kafka---a-practical-guide-4kd2"
    note = tmp_path / "kafka.md"
    note.write_text(
        "---\ntitle: Kafka Guide\nsource_urls:\n"
        f"  - {url}\n  - https://kafka.apache.org/documentation/\n---\n"
        "# Kafka\n\nBody.\n",
        encoding="utf-8",
    )

    verifier._stamp_frontmatter(note, "verified", [])

    fm, body = parse_frontmatter(note)
    assert fm["verifier_status"] == "verified"
    assert fm["title"] == "Kafka Guide"
    assert fm["source_urls"] == [url, "https://kafka.apache.org/documentation/"]
    assert body.strip() == "# Kafka\n\nBody."


def test_verifier_stamp_ignores_an_indented_dashes_line_in_a_block_scalar(
    tmp_path: Path,
) -> None:
    """The closing delimiter is ``---`` at column 0. An indented ``---`` is
    content of a YAML block scalar — the canonical parser reads it as such — but
    the stamp matched it after ``strip()``, cut the frontmatter there and moved
    every key below it into the body."""
    from research_framework.vault.frontmatter import parse_frontmatter

    note = tmp_path / "kafka.md"
    note.write_text(
        "---\ntitle: Kafka Guide\nsummary: |\n  First paragraph.\n  ---\n"
        "  Second paragraph.\ncoverage_category: messaging\n---\n"
        "# Kafka\n\nBody.\n",
        encoding="utf-8",
    )
    before, _ = parse_frontmatter(note)

    verifier._stamp_frontmatter(note, "verified", [])

    fm, body = parse_frontmatter(note)
    assert fm == {**before, "verifier_status": "verified"}
    assert fm["coverage_category"] == "messaging"
    assert body == "# Kafka\n\nBody.\n"


def test_wikilinks_normalization_calls_atomic_write(tmp_path: Path) -> None:
    dv = tmp_path / "data_vault"
    dv.mkdir()
    (dv / "foo.md").write_text("# foo\n", encoding="utf-8")
    (dv / "bar.md").write_text("[[Foo]]\n", encoding="utf-8")
    with patch("research_framework.pipeline.atomic_write.write_text") as aw:
        assert wikilinks.auto_fix_moved_wikilinks(tmp_path) == 1
        aw.assert_called()


def test_runner_local_atomic_helpers_delegate_to_module(tmp_path: Path) -> None:
    with patch("research_framework.pipeline.atomic_write.write_json") as aw:
        runner._atomic_write_json(tmp_path / "state.json", {"x": 1})
        aw.assert_called_once()


def test_research_plan_and_plan_narrator_delegate_atomic_write(tmp_path: Path) -> None:
    target = tmp_path / "plan.md"
    with patch("research_framework.pipeline.atomic_write.write_text") as aw:
        research_plan._atomic_write_text(target, "body")
        plan_narrator._atomic_write_text(target, "body2")
        assert aw.call_count == 2
