"""Nothing the runner dispatches may spend money without a record (spec 080 US2).

A weekly run over eight vaults had no framework-owned record of what it spent:
no pipeline dispatch wrote a cost sidecar at all (spec 078 D6), and
``--budget-cap`` was refused precisely because there was no spend to check a
cap against. FR-010 decides ``078`` T005 in the affirmative — every dispatch
asks for a sidecar under the run directory.

The other half is FR-012's asymmetry, which is the part worth reading twice: a
sidecar that was **requested** and did not arrive is ``null`` and a ``WARNING``,
never ``0``. A run that reports ``$0.00`` for a phase that dispatched an agent
is worse than one that says it does not know, because the first is a number an
operator will add up.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline import run_receipt
from research_framework.pipeline.runner import (
    DONE,
    FAILED,
    STATE_FILE,
    WAITING,
    _blank_state,
    _save_state,
    run_full,
    run_resume,
)

#: A stand-in agent that records the argv it was given and writes the sidecar
#: it was asked for, with a known cost. Recording argv is the point of Test 1:
#: what is under test is the REQUEST, not whether a cooperative agent happened
#: to write a file.
_AGENT = """\
import json, sys
from pathlib import Path

args = sys.argv[1:]
stage = args[args.index("--stage") + 1]
vault = Path(args[args.index("--vault") + 1])
(vault / "_pipeline").mkdir(parents=True, exist_ok=True)
with (vault / "_pipeline" / "argv.log").open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\\n")

if stage == "scout":
    (vault / "_pipeline" / "scout-report.json").write_text(json.dumps({
        "schema_version": "2.0", "phase": "scout",
        "topics_found": {"new": [{"title": "T"}], "existing": [], "total": 1},
        "sources_consulted": ["Vendor changelogs"],
    }), encoding="utf-8")
elif stage == "research":
    (vault / "_pipeline" / "research-report.json").write_text(json.dumps({
        "schema_version": "2.0", "phase": "research",
        "notes_created": ["t.md"], "notes_updated": [],
    }), encoding="utf-8")

if "--cost-sidecar" in args:
    sidecar = Path(args[args.index("--cost-sidecar") + 1])
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps({
        "schema_version": "1.1", "stage": stage, "agent": "fake",
        "agent_kind": "fake", "tier": "basic", "status": "ok", "exit_code": 0,
        "cost_usd": 0.5, "cost_source": "estimate", "tokens_in": 1,
        "tokens_out": 2, "latency_ms": 3, "started_at": "2026-09-10T00:00:00Z",
        "completed_at": "2026-09-10T00:00:01Z", "cycle": 1,
    }), encoding="utf-8")
sys.exit(0)
"""

#: Exits 1 but still writes the sidecar its dispatcher asked for, marked
#: failed — which is what the real ``agent_call.py`` does (078 FR-015).
_AGENT_FAILS_WITH_A_SIDECAR = """\
import json, sys
from pathlib import Path

args = sys.argv[1:]
stage = args[args.index("--stage") + 1]
if "--cost-sidecar" in args:
    sidecar = Path(args[args.index("--cost-sidecar") + 1])
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps({
        "schema_version": "1.1", "stage": stage, "agent": "fake",
        "agent_kind": "fake", "tier": "basic", "status": "failed", "exit_code": 1,
        "cost_usd": 0.125, "cost_source": "estimate", "tokens_in": 1,
        "tokens_out": 0, "latency_ms": 2, "started_at": "2026-09-10T00:00:00Z",
        "completed_at": "2026-09-10T00:00:01Z", "cycle": 1,
    }), encoding="utf-8")
sys.exit(1)
"""

#: Exits 0 and writes nothing at all — the sidecar was requested and never
#: arrived. That is the scenario FR-012 is written for.
_AGENT_WRITES_NO_SIDECAR = """\
import json, sys
from pathlib import Path

args = sys.argv[1:]
stage = args[args.index("--stage") + 1]
vault = Path(args[args.index("--vault") + 1])
(vault / "_pipeline").mkdir(parents=True, exist_ok=True)
if stage == "scout":
    (vault / "_pipeline" / "scout-report.json").write_text(json.dumps({
        "schema_version": "2.0", "phase": "scout",
        "topics_found": {"new": [{"title": "T"}], "existing": [], "total": 1},
        "sources_consulted": ["Vendor changelogs"],
    }), encoding="utf-8")
sys.exit(0)
"""


def _vault(tmp_path: Path, agent: str = _AGENT) -> Path:
    vault = tmp_path / "vault"
    script = vault / "scripts" / "agent_call.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(agent, encoding="utf-8")
    prompts = vault / "_pipeline" / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    (prompts / "scout-prompt.md").write_text("Scout {CYCLE_NUM}\n", encoding="utf-8")
    (prompts / "dfs-prompt.md").write_text("Research {CYCLE_NUM}\n", encoding="utf-8")
    (vault / "data_vault").mkdir(parents=True, exist_ok=True)
    return vault


def _run_dir(vault: Path) -> Path:
    run_id = json.loads((vault / STATE_FILE).read_text(encoding="utf-8"))["run_id"]
    return run_receipt.run_dir_for(vault, run_id)


def _phase(vault: Path, name: str) -> dict:
    state = json.loads((vault / STATE_FILE).read_text(encoding="utf-8"))
    return state["phases"][name]


def _receipt(vault: Path) -> dict:
    return json.loads((_run_dir(vault) / "run.json").read_text(encoding="utf-8"))


def _argv_lines(vault: Path) -> list[list[str]]:
    path = vault / "_pipeline" / "argv.log"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------


def test_every_dispatch_requests_a_cost_sidecar_under_the_run_directory(
    tmp_path: Path,
) -> None:
    """FR-010. Asserted on the argv, not on the file: the request is the
    framework's obligation, writing it is the dispatcher's."""
    vault = _vault(tmp_path)

    run_full(vault, quiet=True)
    run_resume(vault, quiet=True)

    run_dir = _run_dir(vault)
    dispatched = {}
    for argv in _argv_lines(vault):
        stage = argv[argv.index("--stage") + 1]
        assert "--cost-sidecar" in argv, f"{stage} dispatched with no cost record"
        dispatched[stage] = Path(argv[argv.index("--cost-sidecar") + 1])

    assert set(dispatched) == {"scout", "research"}
    for stage, path in dispatched.items():
        assert path.parent == run_dir / "agent-calls"
        assert path.name == f"{stage}.json"
        assert path.is_file()


def test_output_file_is_not_requested(tmp_path: Path) -> None:
    """FR-011. ``--output-file`` is written only on exit 0, so it would be
    absent in exactly the runs an operator needs to read; the merged log
    already holds the agent's stdout."""
    vault = _vault(tmp_path)

    run_full(vault, quiet=True)

    for argv in _argv_lines(vault):
        assert "--output-file" not in argv


def test_a_failed_dispatch_still_leaves_a_sidecar_marked_failed(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path, _AGENT_FAILS_WITH_A_SIDECAR)

    run_full(vault, quiet=True)

    sidecar = _run_dir(vault) / "agent-calls" / "scout.json"
    assert sidecar.is_file()
    assert json.loads(sidecar.read_text(encoding="utf-8"))["status"] == "failed"
    scout = _phase(vault, "scout")
    assert scout["status"] == FAILED
    assert scout["summary"]["cost_sidecar"] == str(sidecar)
    assert scout["summary"]["cost_usd"] == 0.125


def test_a_missing_sidecar_is_null_cost_with_a_warning_never_zero(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """FR-012. The asymmetry is the point: a requested-and-absent sidecar is
    unknown cost, not free."""
    vault = _vault(tmp_path, _AGENT_WRITES_NO_SIDECAR)

    with caplog.at_level("WARNING"):
        run_full(vault, quiet=True)

    summary = _phase(vault, "scout")["summary"]
    expected = str(_run_dir(vault) / "agent-calls" / "scout.json")
    assert summary["cost_sidecar"] == expected
    assert summary["cost_usd"] is None
    assert expected in "\n".join(r.getMessage() for r in caplog.records)
    assert _receipt(vault)["cost"]["sidecars_missing"] == 1
    assert _receipt(vault)["cost"]["total_usd"] == 0.0


def test_the_receipt_total_is_the_sum_of_readable_sidecars(tmp_path: Path) -> None:
    """FR-013, built from sidecars on disk rather than from a run, so the
    arithmetic is asserted independently of how the files got there."""
    vault = tmp_path / "vault"
    run_dir, _ = run_receipt.ensure_run_dir(vault, "2026-09-10-0900")
    assert run_dir is not None
    state = _blank_state("2026-09-10-0900", "2026-09-10T09:00:00Z")
    for index, (stage, cost) in enumerate(
        (("scout", 0.25), ("research", 1.5), ("report", 0.125)), start=1
    ):
        sidecar = run_dir / "agent-calls" / f"{stage}.json"
        sidecar.write_text(
            json.dumps({"cost_usd": cost, "cost_source": "estimate"}), encoding="utf-8"
        )
        state["phases"][stage]["status"] = DONE
        state["phases"][stage]["summary"] = {"cost_sidecar": str(sidecar)}
        _ = index

    receipt = run_receipt.build_receipt(
        vault, state, phases=("scout", "research", "report"), framework_version="1.3.0"
    )

    assert receipt["cost"]["total_usd"] == 1.875
    assert receipt["cost"]["sidecars_read"] == 3
    assert receipt["cost"]["sidecars_missing"] == 0
    assert receipt["phases"]["research"]["cost_usd"] == 1.5
    assert receipt["phases"]["research"]["cost_source"] == "estimate"


def test_a_sidecar_with_no_numeric_cost_is_unknown_not_zero(tmp_path: Path) -> None:
    """A file that exists and carries no usable ``cost_usd`` is the same
    finding as no file at all: spec 078 FR-015's "no zero is silent" binds the
    reader too."""
    vault = tmp_path / "vault"
    run_dir, _ = run_receipt.ensure_run_dir(vault, "r")
    assert run_dir is not None
    sidecar = run_dir / "agent-calls" / "scout.json"
    sidecar.write_text(json.dumps({"cost_usd": "free"}), encoding="utf-8")

    assert run_receipt.read_sidecar_cost(sidecar) == (None, None)

    state = _blank_state("r", "2026-09-10T09:00:00Z")
    state["phases"]["scout"]["status"] = DONE
    state["phases"]["scout"]["summary"] = {"cost_sidecar": str(sidecar)}
    receipt = run_receipt.build_receipt(
        vault, state, phases=("scout",), framework_version="1.3.0"
    )
    assert receipt["cost"]["sidecars_missing"] == 1
    assert receipt["phases"]["scout"]["cost_usd"] is None


def test_a_phase_that_dispatched_nothing_is_not_counted_as_a_missing_sidecar(
    tmp_path: Path,
) -> None:
    """``collect``, ``extract`` and ``verify`` run in-process and ``triage`` is
    a human. None of them asks for a sidecar, so none of them can be missing
    one — otherwise every run would report four phantom misses and the "lower
    bound" label would mean nothing."""
    vault = _vault(tmp_path)
    state = _blank_state("2026-09-10-0900", "2026-09-10T09:00:00Z")
    for phase in ("collect", "extract"):
        state["phases"][phase]["status"] = DONE
    state["phases"]["triage"]["status"] = WAITING
    _save_state(vault, state)
    run_receipt.ensure_run_dir(vault, "2026-09-10-0900")

    receipt = run_receipt.build_receipt(
        vault,
        state,
        phases=("collect", "extract", "triage"),
        framework_version="1.3.0",
    )

    assert receipt["cost"]["sidecars_missing"] == 0
    assert receipt["cost"]["sidecars_read"] == 0
