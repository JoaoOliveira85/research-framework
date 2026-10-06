"""The run receipt — one directory per run (spec 080, issue #221).

After an unattended night the operator opens ONE place per vault. Before this,
the rendered prompts were flat files under ``_pipeline/`` that the next run
overwrote, the agent logs were timestamped siblings, the verify detail was a
third path, and the state file named some of them in a per-phase ``summary``
that ``full`` discarded on its next invocation.

What is under test here is the record, not the pipeline: the agent is a
stand-in Python script, so no LLM is reached and every assertion is about what
the runner wrote down.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline import run_receipt
from research_framework.pipeline.runner import (
    DONE,
    PHASES,
    STATE_FILE,
    WAITING,
    _blank_state,
    _save_state,
    run_finish,
    run_full,
    run_resume,
    run_scout,
)

_AGENT_WRITES_ITS_ARTIFACT = """\
import json, sys
from pathlib import Path

args = sys.argv[1:]
stage = args[args.index("--stage") + 1]
vault = Path(args[args.index("--vault") + 1])
sidecar = None
if "--cost-sidecar" in args:
    sidecar = Path(args[args.index("--cost-sidecar") + 1])

pipeline = vault / "_pipeline"
pipeline.mkdir(parents=True, exist_ok=True)
if stage == "scout":
    (pipeline / "scout-report.json").write_text(json.dumps({
        "schema_version": "2.0", "phase": "scout",
        "topics_found": {"new": [{"title": "A topic"}], "existing": [], "total": 1},
        "sources_consulted": ["Vendor changelogs"],
    }), encoding="utf-8")
elif stage == "research":
    (pipeline / "research-report.json").write_text(json.dumps({
        "schema_version": "2.0", "phase": "research",
        "notes_created": ["a-topic.md"], "notes_updated": [],
    }), encoding="utf-8")
elif stage == "report":
    out = pipeline / "exports" / "weekly-report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("# Weekly briefing\\n", encoding="utf-8")

if sidecar is not None:
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps({
        "schema_version": "1.1", "stage": stage, "agent": "fake",
        "agent_kind": "fake", "tier": "basic", "status": "ok", "exit_code": 0,
        "cost_usd": 0.25, "cost_source": "runtime", "tokens_in": 10,
        "tokens_out": 20, "latency_ms": 5, "started_at": "2026-09-10T00:00:00Z",
        "completed_at": "2026-09-10T00:00:05Z", "cycle": 1,
    }), encoding="utf-8")
sys.exit(0)
"""


def _vault(tmp_path: Path, *, agent: str = _AGENT_WRITES_ITS_ARTIFACT) -> Path:
    """A vault with a stand-in agent and every stage's prompt source present."""
    vault = tmp_path / "vault"
    script = vault / "scripts" / "agent_call.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(agent, encoding="utf-8")

    prompts = vault / "_pipeline" / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    (prompts / "scout-prompt.md").write_text(
        "Scout cycle {CYCLE_NUM} -> {SCOUT_REPORT}\n", encoding="utf-8"
    )
    (prompts / "dfs-prompt.md").write_text(
        "Research {CYCLE_NUM}: {SCOUT_REPORT} -> {RESEARCH_REPORT}\n", encoding="utf-8"
    )
    report_def = vault / ".claude" / "commands" / "report.md"
    report_def.parent.mkdir(parents=True, exist_ok=True)
    report_def.write_text("# Weekly Report Agent\n", encoding="utf-8")
    (vault / "data_vault").mkdir(parents=True, exist_ok=True)
    return vault


def _state_run_id(vault: Path) -> str:
    return json.loads((vault / STATE_FILE).read_text(encoding="utf-8"))["run_id"]


def _run_dir(vault: Path) -> Path:
    return run_receipt.run_dir_for(vault, _state_run_id(vault))


def _receipt(vault: Path) -> dict:
    return json.loads((_run_dir(vault) / "run.json").read_text(encoding="utf-8"))


def _awaiting_triage(vault: Path, run_id: str = "2026-09-01-0300") -> None:
    state = _blank_state(run_id, "2026-09-01T03:00:00Z")
    for phase in ("collect", "extract", "scout"):
        state["phases"][phase]["status"] = DONE
    state["phases"]["triage"]["status"] = WAITING
    _save_state(vault, state)


# ---------------------------------------------------------------------------
# T001 — the directory and the receipt
# ---------------------------------------------------------------------------


def test_full_allocates_a_run_directory_named_by_the_state_file(
    tmp_path: Path,
) -> None:
    """FR-001: the directory is derivable from the state file alone."""
    vault = _vault(tmp_path)

    run_full(vault, quiet=True)

    run_dir = _run_dir(vault)
    assert run_dir.is_dir()
    assert (run_dir / "run.json").is_file()
    assert (run_dir / "run-report.md").is_file()
    for sub in ("logs", "prompts", "agent-calls"):
        assert (run_dir / sub).is_dir()


def test_two_runs_in_one_minute_do_not_share_a_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-002 / D1: ``_make_run_id`` is minute-granular. Two ``full`` runs in
    one minute used to share an id and the second silently overwrote the
    first's state, because there was nothing else to collide with."""
    vault = _vault(tmp_path)
    monkeypatch.setattr(
        "research_framework.pipeline.runner._make_run_id", lambda: "2026-09-10-0900"
    )

    run_full(vault, quiet=True)
    first = run_receipt.run_dir_for(vault, "2026-09-10-0900")
    before = {p: p.read_bytes() for p in first.rglob("*") if p.is_file()}

    run_full(vault, quiet=True)

    assert _state_run_id(vault) == "2026-09-10-0900-2"
    assert run_receipt.run_dir_for(vault, "2026-09-10-0900-2").is_dir()
    after = {p: p.read_bytes() for p in first.rglob("*") if p.is_file()}
    assert after == before, "the second run rewrote the first run's record"


def test_run_json_is_a_pure_function_of_state_and_disk(tmp_path: Path) -> None:
    """FR-006. Built twice from the same inputs, the receipt is identical —
    no timestamp of its own, no counter, nothing generated. That is what makes
    rewriting it on every phase close safe: there is no state to lose."""
    vault = _vault(tmp_path)
    run_full(vault, quiet=True)
    state = json.loads((vault / STATE_FILE).read_text(encoding="utf-8"))

    first = run_receipt.build_receipt(
        vault, state, phases=tuple(PHASES), framework_version="1.2.0"
    )
    second = run_receipt.build_receipt(
        vault, state, phases=tuple(PHASES), framework_version="1.2.0"
    )

    assert first == second
    for phase in PHASES:
        assert first["phases"][phase]["status"] == state["phases"][phase]["status"]


def test_the_receipt_names_the_run_and_the_vault(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    run_full(vault, quiet=True)

    receipt = _receipt(vault)
    assert receipt["schema_version"] == "1.0"
    assert receipt["run_id"] == _state_run_id(vault)
    assert receipt["vault"] == str(vault.resolve())
    assert receipt["verbs"] == ["full"]
    assert receipt["reconstructed"] is False


def test_the_receipt_is_open_until_every_phase_is_terminal(tmp_path: Path) -> None:
    """FR-007: ``finished_at`` is null while the run is open. After ``full``
    the run is parked at triage — the operator has not answered yet."""
    vault = _vault(tmp_path)
    run_full(vault, quiet=True)

    assert _receipt(vault)["finished_at"] is None

    run_resume(vault, quiet=True)
    run_finish(vault, quiet=True)

    assert _receipt(vault)["finished_at"] is not None


# ---------------------------------------------------------------------------
# T003 — a second run does not erase the first
# ---------------------------------------------------------------------------


def test_a_second_full_run_leaves_the_first_run_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    ids = iter(["2026-09-10-0900", "2026-09-10-0901"])
    monkeypatch.setattr(
        "research_framework.pipeline.runner._make_run_id", lambda: next(ids)
    )

    run_full(vault, quiet=True)
    first = run_receipt.run_dir_for(vault, "2026-09-10-0900")
    before = {
        p.relative_to(first): p.read_bytes() for p in first.rglob("*") if p.is_file()
    }

    run_full(vault, quiet=True)

    after = {
        p.relative_to(first): p.read_bytes() for p in first.rglob("*") if p.is_file()
    }
    assert after == before


def test_resume_and_finish_write_into_the_run_named_by_state(tmp_path: Path) -> None:
    """FR-004: one run, three verbs, one directory."""
    vault = _vault(tmp_path)

    run_full(vault, quiet=True)
    run_resume(vault, quiet=True)
    run_finish(vault, quiet=True)

    runs = sorted(p for p in run_receipt.runs_root(vault).iterdir() if p.is_dir())
    assert len(runs) == 1
    logs = {p.name for p in (runs[0] / "logs").glob("*.log")}
    assert {"scout.log", "research.log", "report.log"} <= logs
    assert _receipt(vault)["verbs"] == ["full", "resume", "finish"]


def test_a_pre_receipt_state_file_is_reconstructed_not_refused(
    tmp_path: Path,
) -> None:
    """FR-004: a state file written before this spec shipped has a ``run_id``
    and no directory. That is a run to reconstruct, not a run to refuse."""
    vault = _vault(tmp_path)
    _awaiting_triage(vault)
    assert not run_receipt.runs_root(vault).exists()

    rc = run_finish(vault, quiet=True)

    receipt = _receipt(vault)
    assert receipt["reconstructed"] is True
    assert rc in (0, 1), "reconstruction must not be what fails a run"
    assert receipt["phases"]["verify"]["status"] in (DONE, "failed")


def test_a_redriven_stage_suffixes_rather_than_overwrites(tmp_path: Path) -> None:
    """FR-005. The first pass's record is often the reason for the second."""
    vault = _vault(tmp_path)
    run_full(vault, quiet=True)

    run_scout(vault, quiet=True)

    run_dir = _run_dir(vault)
    assert (run_dir / "logs" / "scout.log").is_file()
    assert (run_dir / "logs" / "scout-2.log").is_file()
    assert (run_dir / "agent-calls" / "scout.json").is_file()
    assert (run_dir / "agent-calls" / "scout-2.json").is_file()
    assert (run_dir / "prompts" / "scout.rendered.md").is_file()
    assert (run_dir / "prompts" / "scout-2.rendered.md").is_file()


# ---------------------------------------------------------------------------
# T004 — the human receipt and the ERROR line
# ---------------------------------------------------------------------------


def test_run_report_answers_which_phase_failed_how_long_and_what_it_cost() -> None:
    """FR-008, rendered from a receipt rather than a run, so the three
    questions are asserted independently of how the run got that shape."""
    receipt = {
        "run_id": "2026-09-10-0900",
        "vault": "/vaults/tech",
        "started_at": "2026-09-10T09:00:00Z",
        "finished_at": "2026-09-10T09:04:00Z",
        "framework_version": "1.3.0",
        "reconstructed": False,
        "verbs": ["full"],
        "phases": {
            "scout": {
                "status": "done",
                "duration_s": 42.0,
                "cost_usd": 0.25,
                "cost_source": "runtime",
                "sidecar": "/vaults/tech/_pipeline/runs/x/agent-calls/scout.json",
                "errors": [],
            },
            "research": {
                "status": "failed",
                "duration_s": 7.0,
                "cost_usd": None,
                "cost_source": None,
                "sidecar": "/vaults/tech/_pipeline/runs/x/agent-calls/research.json",
                "errors": ["research agent exited with code 2", "and another"],
            },
        },
        "artifacts": {"scout_report": "/vaults/tech/_pipeline/scout-report.json"},
        "cost": {"total_usd": 0.25, "sidecars_read": 1, "sidecars_missing": 1},
    }

    text = run_receipt.render_run_report(receipt)

    assert "research" in text
    assert "research agent exited with code 2" in text
    assert "42s" in text and "7s" in text
    assert "$0.2500" in text
    assert "lower bound" in text.lower(), (
        "a total computed with a sidecar missing must never look exact"
    )


def test_a_failed_phase_names_the_run_directory(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """FR-009: the ERROR line names the run directory as well as the state
    file, because the run directory is where the agent's own account is."""
    vault = _vault(tmp_path, agent="import sys; sys.exit(3)\n")

    with caplog.at_level("ERROR"):
        run_full(vault, quiet=True)

    errors = "\n".join(r.getMessage() for r in caplog.records)
    assert str(_run_dir(vault)) in errors
    assert str(vault / STATE_FILE) in errors


def test_a_fresh_bare_verb_is_a_new_run_not_a_reconstructed_one(
    tmp_path: Path,
) -> None:
    """ "Reconstructed" means phases ran before the directory existed. A bare
    ``pipeline <vault> scout`` on a vault with no state file mints a new
    ``run_id`` and creates its first directory — that is a new run, and
    marking it recovered would make the flag meaningless on the runs that
    genuinely are."""
    vault = _vault(tmp_path)
    assert not (vault / STATE_FILE).exists()

    run_scout(vault, quiet=True)

    assert _receipt(vault)["reconstructed"] is False


def test_a_run_report_that_cannot_be_replaced_is_left_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run-report.md`` is rewritten on every phase close; a rewrite that fails
    must leave the last complete rendering, not a torn or empty file."""
    from research_framework.pipeline import atomic_write

    vault = tmp_path / "vault"
    state = _blank_state("2026-09-01-0300", "2026-09-01T03:00:00Z")
    run_dir, _ = run_receipt.ensure_run_dir(vault, state["run_id"])
    assert run_dir is not None
    kwargs = {"phases": tuple(state["phases"]), "framework_version": "test"}
    assert run_receipt.write_receipt(vault, state, **kwargs) is not None
    report = run_dir / "run-report.md"
    before = report.read_text(encoding="utf-8")
    assert before

    real_replace = atomic_write.os.replace

    def _disk_full_for_the_report(src, dst):
        if Path(dst).name == "run-report.md":
            raise OSError(28, "No space left on device")
        return real_replace(src, dst)

    monkeypatch.setattr(atomic_write.os, "replace", _disk_full_for_the_report)
    state["phases"]["scout"]["status"] = DONE
    assert run_receipt.write_receipt(vault, state, **kwargs) is None

    assert report.read_text(encoding="utf-8") == before
