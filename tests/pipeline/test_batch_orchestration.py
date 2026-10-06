"""Batched note-writer orchestration integration (T053, US4, feature 017).

Patches ``subprocess.run`` inside :mod:`research_framework.pipeline.cycle_runner` so
``agent_call.py`` (note-writer stage) is fully mocked. Assertions target the
post-T056 batch loop (five invocations, per-batch SG-005, batch JSONs) — the
current runner issues a single DFS note-writer call (RED).
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from research_framework.pipeline.research_plan import (
    CategoryFillState,
    PrioritizedTopic,
    ResearchPlan,
)


def _patch_cycle_runner_subprocess(fake_run):
    """See :func:`tests.pipeline.test_cycle_runner._patch_cycle_runner_subprocess`.

    Mirrors the same helper because the v0.2.23 streaming redesign routes
    ``agent_call.py`` invocations through ``subprocess.Popen`` rather than
    ``subprocess.run``; tests that only patched the latter lost visibility
    into the note-writer stage.
    """

    def _fake_popen(cmd, **kwargs):
        completed = fake_run(cmd, **kwargs)
        popen_mock = MagicMock()
        popen_mock.pid = 4242
        popen_mock.stdout = iter([])
        popen_mock.returncode = completed.returncode
        popen_mock.wait = MagicMock(return_value=completed.returncode)
        popen_mock.poll = MagicMock(return_value=completed.returncode)
        popen_mock.terminate = MagicMock()
        popen_mock.kill = MagicMock()
        return popen_mock

    cm = contextlib.ExitStack()
    cm.enter_context(
        patch(
            "research_framework.pipeline.cycle_runner.subprocess.run",
            side_effect=fake_run,
        )
    )
    cm.enter_context(
        patch(
            "research_framework.pipeline.cycle_runner.subprocess.Popen",
            side_effect=_fake_popen,
        )
    )
    return cm


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    scripts = vault / "scripts"
    prompts = vault / "_pipeline" / "prompts"
    cycles = vault / "_pipeline" / "cycles"
    for d in (scripts, prompts, cycles, vault / "data_vault"):
        d.mkdir(parents=True, exist_ok=True)
    for name in (
        "vault_metrics.py",
        "agent_call.py",
        "validate_cycle.py",
        "validate_vault.py",
        "check_template_compliance.py",
        "check_acronym_links.py",
        "topic_harvest.py",
    ):
        (scripts / name).write_text("# stub\n", encoding="utf-8")
    (prompts / "scout-prompt.md").write_text(
        "scout {CYCLE_NUM} {SCOUT_REPORT}\n", encoding="utf-8"
    )
    (prompts / "dfs-prompt.md").write_text(
        "dfs {CYCLE_NUM} {SCOUT_REPORT} {RESEARCH_REPORT}\n", encoding="utf-8"
    )
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}", encoding="utf-8")
    return vault


def _write_plan(vault: Path, *, quota: int) -> None:
    q = [
        PrioritizedTopic(title=f"topic-{i}", category="concepts", priority_score=0.9)
        for i in range(max(quota, 25))
    ]
    plan = ResearchPlan(
        cycle_number=1,
        generated_at="2026-05-15T12:00:00Z",
        framework_version="0.2.18",
        coverage_state=[
            CategoryFillState(
                name="concepts",
                target_count=100,
                met_count=0,
                fill_pct=0.0,
                priority=50,
            )
        ],
        priority_queue=q,
        cycle_focus=["concepts"],
        cycle_quota=quota,
        exclusions=[],
        narrative_header="",
    )
    (vault / "_pipeline" / "research-plan.md").write_text(
        plan.to_markdown(), encoding="utf-8"
    )


def _scout_topics(n: int) -> str:
    return json.dumps({"topics_found": {"new": [{"title": f"t{i}"} for i in range(n)]}})


class TestBatchedNoteWriterOrchestration:
    def test_quota_twenty_requires_five_note_writer_invocations(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        _write_plan(vault, quota=20)
        cycle_num = 1
        c3 = f"{cycle_num:03d}"
        scout_path = vault / "_pipeline" / "cycles" / f"cycle-{c3}-scout.json"
        scout_path.write_text(_scout_topics(25), encoding="utf-8")
        research_path = vault / "_pipeline" / "cycles" / f"cycle-{c3}-research.json"
        research_path.write_text(
            json.dumps({"notes_created": [], "notes_updated": []}), encoding="utf-8"
        )

        writer_calls: list[list[str]] = []
        counter = {"n": 0}

        def _fake_run(cmd, **kwargs):
            script_name = Path(cmd[1]).name
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = b""
            if script_name == "agent_call.py" and "--stage" in cmd:
                idx = cmd.index("--stage")
                stage = cmd[idx + 1]
                if stage == "note_writer":
                    writer_calls.append(list(cmd))
                    counter["n"] += 1
                    dv = vault / "data_vault"
                    created = []
                    for j in range(4):
                        fn = f"batch{counter['n']}_note{j}.md"
                        created.append(fn)
                        (dv / fn).write_text(
                            "---\n"
                            "type: concept\n"
                            "coverage_category: concepts\n"
                            "source_urls:\n  - https://ex.test\n"
                            "summary: x\n"
                            "lifecycle:\n  created_at_cycle: 1\n"
                            "---\n\nbody\n",
                            encoding="utf-8",
                        )
                    prev = json.loads(research_path.read_text(encoding="utf-8"))
                    prev.setdefault("notes_created", []).extend(created)
                    research_path.write_text(
                        json.dumps(prev, indent=2), encoding="utf-8"
                    )
            return mock

        with _patch_cycle_runner_subprocess(_fake_run):
            from research_framework.pipeline.cycle_runner import run_cycle_steps

            rc = run_cycle_steps(
                vault,
                cycle_num,
                budget_cap=10.0,
                max_cycles=5,
                scripts_dir=vault / "scripts",
            )
        assert rc == 0
        assert len(writer_calls) == 5, (
            f"expected 5 note-writer invocations for quota 20 @ 4 notes/invocation, "
            f"got {len(writer_calls)}"
        )

    def test_batch_four_prompt_contains_sg005_correction_after_batch_three_fail(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        _write_plan(vault, quota=20)
        c3 = "001"
        (vault / "_pipeline" / "cycles" / f"cycle-{c3}-scout.json").write_text(
            _scout_topics(25), encoding="utf-8"
        )
        (vault / "_pipeline" / "cycles" / f"cycle-{c3}-research.json").write_text(
            json.dumps({"notes_created": [], "notes_updated": []}), encoding="utf-8"
        )

        inv = {"n": 0}
        # The SG-005 directive wording changed in 0.2.20 to stop nudging the
        # correction agent toward cosmetic frontmatter edits (the v0.2.19
        # cycle-6 "bookkeeping fraud" failure mode). The orchestrator still
        # MUST include the gate's correction_hint in the next batch prompt;
        # this assertion just checks for the new, anti-fraud phrasing.
        directive_marker = "write a new note in data_vault/"

        def _fake_run(cmd, **kwargs):
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = b""
            if Path(cmd[1]).name == "agent_call.py" and "--stage" in cmd:
                idx = cmd.index("--stage")
                if cmd[idx + 1] == "note_writer":
                    inv["n"] += 1
                    pfn = cmd[cmd.index("--prompt-file") + 1]
                    text = Path(pfn).read_text(encoding="utf-8")
                    if inv["n"] == 4:
                        assert directive_marker in text
            return mock

        with _patch_cycle_runner_subprocess(_fake_run):
            from research_framework.pipeline.cycle_runner import run_cycle_steps

            run_cycle_steps(
                vault, 1, budget_cap=10.0, max_cycles=5, scripts_dir=vault / "scripts"
            )
        assert inv["n"] == 5

    def test_batches_one_two_committed_before_batch_three_fail(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        _write_plan(vault, quota=20)
        c3 = "001"
        (vault / "_pipeline" / "cycles" / f"cycle-{c3}-scout.json").write_text(
            _scout_topics(25), encoding="utf-8"
        )
        (vault / "_pipeline" / "cycles" / f"cycle-{c3}-research.json").write_text(
            json.dumps({"notes_created": [], "notes_updated": []}), encoding="utf-8"
        )

        def _fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = b""
            return m

        with _patch_cycle_runner_subprocess(_fake_run):
            from research_framework.pipeline.cycle_runner import run_cycle_steps

            run_cycle_steps(
                vault, 1, budget_cap=10.0, max_cycles=5, scripts_dir=vault / "scripts"
            )
        for bn in (1, 2):
            p = vault / "_pipeline" / "cycles" / f"cycle-{c3}-batch-{bn:03d}.json"
            assert p.is_file(), (
                "accepted batches 1–2 must persist across batch-3 SG-005 FAIL"
            )

    def test_cycle_end_five_batch_reports_with_expected_acceptance(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        _write_plan(vault, quota=20)
        c3 = "001"
        (vault / "_pipeline" / "cycles" / f"cycle-{c3}-scout.json").write_text(
            _scout_topics(25), encoding="utf-8"
        )
        (vault / "_pipeline" / "cycles" / f"cycle-{c3}-research.json").write_text(
            json.dumps({"notes_created": [], "notes_updated": []}), encoding="utf-8"
        )

        def _fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = b""
            return m

        with _patch_cycle_runner_subprocess(_fake_run):
            from research_framework.pipeline.cycle_runner import run_cycle_steps

            run_cycle_steps(
                vault, 1, budget_cap=10.0, max_cycles=5, scripts_dir=vault / "scripts"
            )

        for bn in range(1, 6):
            path = vault / "_pipeline" / "cycles" / f"cycle-{c3}-batch-{bn:03d}.json"
            assert path.is_file()
            doc = json.loads(path.read_text(encoding="utf-8"))
            if bn == 3:
                assert doc.get("accepted") is False
                assert doc.get("correction_directive_in") == ""
            elif bn == 4:
                assert doc.get("accepted") is True
                assert doc.get("correction_directive_in")
            else:
                assert doc.get("accepted") is True
