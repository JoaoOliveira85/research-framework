"""Tests for scripts/topic_propose.py — Phase 2 semantic harvest.

The module exposes a ``propose(vault, cycle, *, agent_caller=None)``
entry point; tests stub ``agent_caller`` with a canned JSON string
rather than spawning subprocesses. The real caller (``agent_call.py`` in a
subprocess) has its own section at the end.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "topic_propose.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("topic_propose", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["topic_propose"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def topic_propose():
    return _load_module()


# ---------------------------------------------------------------------------
# Vault fixtures
# ---------------------------------------------------------------------------


def _write_settings(
    vault: Path,
    *,
    enabled: bool = True,
    max_proposals: int = 10,
    max_degree: int = 2,
    on_missing: str = "skip",
    relation_types: list[str] | None = None,
) -> None:
    relations = relation_types or [
        "variant",
        "prerequisite",
        "contrast",
        "sibling",
        "downstream_effect",
        "user_question",
    ]
    rels = "\n".join(f"      - {r}" for r in relations)
    (vault / "settings.yaml").write_text(
        "default_executor:\n"
        "  runtime: claude\n"
        "  model: sonnet\n"
        "stages:\n"
        "  topic_propose:\n"
        f"    enabled: {'true' if enabled else 'false'}\n"
        f"    model: haiku\n"
        f"    max_proposals: {max_proposals}\n"
        f"    max_degree: {max_degree}\n"
        f"    on_missing_out_of_scope: {on_missing}\n"
        f"    relation_types:\n{rels}\n",
        encoding="utf-8",
    )


def _write_spec(vault: Path, out_of_scope: list[str] | None) -> None:
    scope: dict[str, Any] = {"domain": "Home cooking"}
    if out_of_scope is not None:
        scope["out_of_scope"] = out_of_scope
    (vault / "_pipeline" / "spec-parse.json").write_text(
        json.dumps({"name": "Recipe Vault", "scope": scope}),
        encoding="utf-8",
    )


def _write_research(
    vault: Path,
    cycle: int,
    notes_created: list[str],
    notes_updated: list[str] | None = None,
) -> None:
    (vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-research.json").write_text(
        json.dumps(
            {
                "cycle": cycle,
                "phase": "research",
                "notes_created": notes_created,
                "notes_updated": notes_updated or [],
            }
        ),
        encoding="utf-8",
    )


def _seed_vault(
    tmp_path: Path,
    *,
    out_of_scope: list[str] | None,
    settings_kwargs: dict[str, Any] | None = None,
    touched_contents: dict[str, str] | None = None,
) -> Path:
    vault = tmp_path / "vault"
    (vault / "data_vault" / "concept").mkdir(parents=True)
    (vault / "_pipeline" / "cycles").mkdir(parents=True)
    (vault / "_pipeline" / "research-backlog.md").write_text(
        "# Research Backlog\n\nTopics deferred from scout passes.\n",
        encoding="utf-8",
    )
    _write_settings(vault, **(settings_kwargs or {}))
    _write_spec(vault, out_of_scope)
    contents = touched_contents or {
        "Oven.md": "# Oven\n\nAn oven bakes food. Related to [[Kitchen appliance]].\n",
    }
    for name, body in contents.items():
        (vault / "data_vault" / "concept" / name).write_text(body, encoding="utf-8")
    _write_research(vault, 1, [f"concept/{n}" for n in contents])
    return vault


def _stub_agent(
    proposals: list[dict[str, Any]], rejected: list[dict[str, Any]] | None = None
):
    payload = {"proposals": proposals, "rejected": rejected or []}
    body = json.dumps(payload)

    def _call(_prompt: str) -> str:
        return body

    return _call


def _read_manifest(vault: Path, cycle: int) -> dict[str, Any]:
    return json.loads(
        (vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-propose.json").read_text(
            encoding="utf-8"
        )
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_disabled_by_default_when_flag_false(tmp_path: Path, topic_propose) -> None:
    vault = _seed_vault(
        tmp_path,
        out_of_scope=["molecular thermodynamics"],
        settings_kwargs={"enabled": False},
    )
    result = topic_propose.propose(vault, 1, agent_caller=_stub_agent([]))
    assert result["skipped"] is True
    assert "disabled" in result["reason"].lower()
    assert not (vault / "_pipeline" / "cycles" / "cycle-001-propose.json").exists()


def test_happy_path_accepts_valid_proposal(tmp_path: Path, topic_propose) -> None:
    vault = _seed_vault(tmp_path, out_of_scope=["molecular thermodynamics"])
    caller = _stub_agent(
        [
            {
                "title": "Gas Oven",
                "relation_type": "variant",
                "parent_note": "data_vault/concept/Oven.md",
                "justification": "Recipes don't distinguish combustion vs resistive heating.",
                "degree": 1,
                "scope_check": "in_scope",
                "suggested_note_type": "concept",
            }
        ]
    )
    result = topic_propose.propose(vault, 1, agent_caller=caller)
    assert result["skipped"] is False
    assert result["accepted"] == 1
    assert result["rejected"] == 0

    m = _read_manifest(vault, 1)
    assert m["proposals"][0]["title"] == "Gas Oven"
    assert m["proposals"][0]["parent_note"] == "data_vault/concept/Oven.md"

    backlog = (vault / "_pipeline" / "research-backlog.md").read_text(encoding="utf-8")
    assert "Gas Oven" in backlog
    assert "topic-propose:cycle=001" in backlog


def test_parent_note_missing_rejected(tmp_path: Path, topic_propose) -> None:
    vault = _seed_vault(tmp_path, out_of_scope=["thermodynamics"])
    caller = _stub_agent(
        [
            {
                "title": "Ghost Parent Child",
                "relation_type": "variant",
                "parent_note": "data_vault/concept/Nowhere.md",
                "justification": "Child of a note that doesn't exist.",
                "degree": 1,
            }
        ]
    )
    topic_propose.propose(vault, 1, agent_caller=caller)
    m = _read_manifest(vault, 1)
    assert m["proposals"] == []
    assert m["rejected"][0]["rejected_by"] == "parent_missing"


def test_unknown_relation_type_rejected(tmp_path: Path, topic_propose) -> None:
    vault = _seed_vault(tmp_path, out_of_scope=["thermodynamics"])
    caller = _stub_agent(
        [
            {
                "title": "Something",
                "relation_type": "tangent",  # not in enum
                "parent_note": "data_vault/concept/Oven.md",
                "justification": "x",
                "degree": 1,
            }
        ]
    )
    topic_propose.propose(vault, 1, agent_caller=caller)
    m = _read_manifest(vault, 1)
    assert m["proposals"] == []
    assert m["rejected"][0]["rejected_by"] == "bad_relation"


def test_out_of_scope_term_in_title_rejected(tmp_path: Path, topic_propose) -> None:
    vault = _seed_vault(tmp_path, out_of_scope=["thermodynamics"])
    caller = _stub_agent(
        [
            {
                "title": "Thermodynamics of baking",
                "relation_type": "prerequisite",
                "parent_note": "data_vault/concept/Oven.md",
                "justification": "Underlying physics.",
                "degree": 1,
            }
        ]
    )
    topic_propose.propose(vault, 1, agent_caller=caller)
    m = _read_manifest(vault, 1)
    assert m["proposals"] == []
    assert m["rejected"][0]["rejected_by"] == "scope_check"
    assert "thermodynamics" in m["rejected"][0]["reason"].lower()


def test_degree_exceeded_rejected(tmp_path: Path, topic_propose) -> None:
    """Parent that is neither touched nor wikilinked from touched → inferred degree 3 → rejected."""
    vault = _seed_vault(tmp_path, out_of_scope=["thermodynamics"])
    # Create a note that is NOT touched this cycle and is NOT wikilinked from the touched Oven note.
    (vault / "data_vault" / "concept" / "Orphan.md").write_text(
        "# Orphan\n", encoding="utf-8"
    )

    caller = _stub_agent(
        [
            {
                "title": "Far tangent",
                "relation_type": "variant",
                "parent_note": "data_vault/concept/Orphan.md",
                "justification": "Something about Orphan.",
                # Let the script infer degree — it should infer 3 and reject.
            }
        ]
    )
    topic_propose.propose(vault, 1, agent_caller=caller)
    m = _read_manifest(vault, 1)
    assert m["proposals"] == []
    assert m["rejected"][0]["rejected_by"] == "degree_exceeded"


def test_cap_exceeded(tmp_path: Path, topic_propose) -> None:
    vault = _seed_vault(
        tmp_path,
        out_of_scope=["thermodynamics"],
        settings_kwargs={"max_proposals": 2},
    )
    props = [
        {
            "title": f"Child {i}",
            "relation_type": "variant",
            "parent_note": "data_vault/concept/Oven.md",
            "justification": f"Variant #{i} of oven.",
            "degree": 1,
        }
        for i in range(5)
    ]
    topic_propose.propose(vault, 1, agent_caller=_stub_agent(props))
    m = _read_manifest(vault, 1)
    assert len(m["proposals"]) == 2
    cap = [r for r in m["rejected"] if r["rejected_by"] == "cap_exceeded"]
    assert len(cap) == 3


def test_dedupe_against_phase1_manifest(tmp_path: Path, topic_propose) -> None:
    vault = _seed_vault(tmp_path, out_of_scope=["thermodynamics"])
    (vault / "_pipeline" / "cycles" / "cycle-001-harvest.json").write_text(
        json.dumps(
            {
                "followups": [{"title": "Gas Oven"}],
            }
        ),
        encoding="utf-8",
    )
    caller = _stub_agent(
        [
            {
                "title": "Gas Oven",
                "relation_type": "variant",
                "parent_note": "data_vault/concept/Oven.md",
                "justification": "Already caught by Phase 1.",
                "degree": 1,
            }
        ]
    )
    topic_propose.propose(vault, 1, agent_caller=caller)
    m = _read_manifest(vault, 1)
    assert m["proposals"] == []
    assert m["rejected"][0]["rejected_by"] == "dedupe_phase1"


def test_dedupe_against_existing_note(tmp_path: Path, topic_propose) -> None:
    vault = _seed_vault(tmp_path, out_of_scope=["thermodynamics"])
    (vault / "data_vault" / "concept" / "Gas Oven.md").write_text(
        "# Gas Oven\n", encoding="utf-8"
    )
    caller = _stub_agent(
        [
            {
                "title": "Gas Oven",
                "relation_type": "variant",
                "parent_note": "data_vault/concept/Oven.md",
                "justification": "Already in vault.",
                "degree": 1,
            }
        ]
    )
    topic_propose.propose(vault, 1, agent_caller=caller)
    m = _read_manifest(vault, 1)
    assert m["proposals"] == []
    assert m["rejected"][0]["rejected_by"] == "dedupe_existing_note"


def test_missing_out_of_scope_skip(tmp_path: Path, topic_propose) -> None:
    vault = _seed_vault(
        tmp_path,
        out_of_scope=[],  # empty
        settings_kwargs={"on_missing": "skip"},
    )
    result = topic_propose.propose(vault, 1, agent_caller=_stub_agent([]))
    assert result["skipped"] is True
    # Manifest still written so downstream tools can see the reason.
    m = _read_manifest(vault, 1)
    assert m["stats"]["rejected_reason"].startswith("no_out_of_scope")


def test_malformed_agent_json_writes_empty_manifest(
    tmp_path: Path, topic_propose
) -> None:
    vault = _seed_vault(tmp_path, out_of_scope=["thermodynamics"])

    def _broken(_p: str) -> str:
        return "this is not JSON at all"

    result = topic_propose.propose(vault, 1, agent_caller=_broken)
    assert "error" in result
    m = _read_manifest(vault, 1)
    assert m["proposals"] == []
    assert "malformed_agent_output" in m["stats"]["rejected_reason"]


def test_persistent_rejects_file_records_scope_rejections(
    tmp_path: Path, topic_propose
) -> None:
    """Only scope_check rejections persist; cap_exceeded / dedup do not."""
    vault = _seed_vault(tmp_path, out_of_scope=["thermodynamics"])
    caller = _stub_agent(
        [
            # scope rejection — should persist
            {
                "title": "Thermodynamics primer",
                "relation_type": "prerequisite",
                "parent_note": "data_vault/concept/Oven.md",
                "justification": "Underlying physics.",
                "degree": 1,
            },
            # dedupe rejection — should NOT persist
            {
                "title": "Oven",  # collides with existing note
                "relation_type": "variant",
                "parent_note": "data_vault/concept/Oven.md",
                "justification": "…",
                "degree": 1,
            },
        ]
    )
    topic_propose.propose(vault, 1, agent_caller=caller)
    rejects_path = vault / "_pipeline" / "propose-rejects.md"
    assert rejects_path.is_file()
    body = rejects_path.read_text(encoding="utf-8")
    assert "Thermodynamics primer" in body
    assert "Oven" not in body.replace(
        "Thermodynamics", ""
    )  # make sure the sole 'Oven' line isn't there


def test_coexistence_with_phase1_backlog_block(tmp_path: Path, topic_propose) -> None:
    """Both managed blocks can live in the same research-backlog.md."""
    vault = _seed_vault(tmp_path, out_of_scope=["thermodynamics"])
    # Simulate Phase 1 having already written its block.
    (vault / "_pipeline" / "research-backlog.md").write_text(
        "# Research Backlog\n\n"
        "<!-- topic-harvest:cycle=001 -->\n"
        "## Harvest — cycle 001 (2026-04-29)\n"
        "- **Kitchen appliance** — cited by 1 note(s): `foo`\n"
        "<!-- /topic-harvest:cycle=001 -->\n",
        encoding="utf-8",
    )
    caller = _stub_agent(
        [
            {
                "title": "Gas Oven",
                "relation_type": "variant",
                "parent_note": "data_vault/concept/Oven.md",
                "justification": "Recipes reference oven temperatures.",
                "degree": 1,
            }
        ]
    )
    topic_propose.propose(vault, 1, agent_caller=caller)
    body = (vault / "_pipeline" / "research-backlog.md").read_text(encoding="utf-8")
    assert "topic-harvest:cycle=001" in body
    assert "topic-propose:cycle=001" in body
    assert "Kitchen appliance" in body
    assert "Gas Oven" in body


def test_agent_rejections_carried_through_to_manifest(
    tmp_path: Path, topic_propose
) -> None:
    """Self-rejections from the agent are preserved verbatim as diagnostic signal."""
    vault = _seed_vault(tmp_path, out_of_scope=["thermodynamics"])
    caller = _stub_agent(
        proposals=[],
        rejected=[
            {
                "title": "Restaurant staffing",
                "relation_type": "user_question",
                "parent_note": "data_vault/concept/Oven.md",
                "justification": "Kitchens use ovens.",
                "rejected_by": "scope_check",
                "reason": "home cooking vault, not commercial",
            }
        ],
    )
    topic_propose.propose(vault, 1, agent_caller=caller)
    m = _read_manifest(vault, 1)
    assert any(r["title"] == "Restaurant staffing" for r in m["rejected"])


# ---------------------------------------------------------------------------
# The real caller: stopping the script stops the agent it dispatched
# ---------------------------------------------------------------------------
#
# Real processes all the way down: the script, the real ``agent_call.py`` and
# a stand-in for the ``claude`` binary (``CLAUDE_BIN``) that says where it is
# and stays. No LLM is involved. Only pids this test started are signalled.

_AGENT_LIFETIME_S = 30


def _an_agent_that_stays(tmp_path: Path) -> tuple[Path, Path]:
    """A ``claude`` that records its own pid and its parent's — the wrapper's."""
    pidfile = tmp_path / "agent.pid"
    impl = tmp_path / "fake_claude.py"
    impl.write_text(
        "import os, sys, time\n"
        f"with open({str(pidfile)!r}, 'w') as fh:\n"
        "    fh.write(f'{os.getpid()} {os.getppid()}')\n"
        "sys.stdin.read()\n"
        f"time.sleep({_AGENT_LIFETIME_S})\n",
        encoding="utf-8",
    )
    stub = tmp_path / "claude"
    stub.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{impl}" "$@"\n', encoding="utf-8"
    )
    stub.chmod(0o755)
    return stub, pidfile


def _is_gone(pid: int, *, within_s: float = 5.0) -> bool:
    import os
    import time

    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
@pytest.mark.parametrize("signame", ["SIGTERM", "SIGINT"])
def test_stopping_the_script_stops_the_wrapper_and_the_agent(
    tmp_path: Path, signame: str
) -> None:
    """``agent_call.py`` was started with a plain ``subprocess.run``. SIGTERM
    killed this script on the spot and left the wrapper and its agent running;
    an interrupt had ``subprocess.run`` SIGKILL the wrapper, which a wrapper
    cannot forward to the agent it runs in a session of its own."""
    import os
    import shutil
    import signal
    import subprocess
    import time

    signum = getattr(signal, signame)
    vault = _seed_vault(tmp_path, out_of_scope=["baking"])
    (vault / "scripts").mkdir()
    shutil.copy(REPO_ROOT / "scripts" / "agent_call.py", vault / "scripts")
    stub, pidfile = _an_agent_that_stays(tmp_path)
    env = {**os.environ, "CLAUDE_BIN": str(stub)}
    env.pop("RESEARCH_FRAMEWORK_DEFAULT_AGENT", None)

    agent: int | None = None
    wrapper: int | None = None
    with (tmp_path / "propose.log").open("wb") as log:
        script = subprocess.Popen(
            [sys.executable, str(SCRIPT_PATH), str(vault), "1"],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and script.poll() is None:
                pids = pidfile.read_text().split() if pidfile.exists() else []
                if len(pids) == 2:
                    agent, wrapper = int(pids[0]), int(pids[1])
                    break
                time.sleep(0.05)
            assert agent is not None and wrapper is not None, (
                "the stand-in agent never started — nothing was tested:\n"
                + (tmp_path / "propose.log").read_text(errors="replace")
            )

            os.kill(script.pid, signum)  # the script alone, as ``kill <pid>``
            returncode = script.wait(timeout=30)

            assert _is_gone(wrapper), (
                f"the script got {signame} and agent_call.py, which it had "
                "started, is still running"
            )
            assert _is_gone(agent), (
                f"the script got {signame} and the agent it had dispatched "
                "is still running"
            )
            assert returncode == -signum, (
                "being stopped must still look like death by that signal to "
                f"whoever sent it, got {returncode}"
            )
        finally:
            for pid in (agent, wrapper, script.pid):
                if pid is not None:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass


def _a_claude_that_answers(tmp_path: Path, body: str, *, exit_code: int = 0) -> Path:
    """A ``claude`` that reads the prompt, prints *body* and exits."""
    impl = tmp_path / "answering_claude.py"
    impl.write_text(
        "import sys\n"
        "sys.stdin.read()\n"
        f"sys.stdout.write({body!r})\n"
        f"sys.stderr.write('agent said no\\n' if {exit_code} else '')\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    stub = tmp_path / "claude"
    stub.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{impl}" "$@"\n', encoding="utf-8"
    )
    stub.chmod(0o755)
    return stub


def _vault_with_the_real_wrapper(tmp_path: Path) -> Path:
    import shutil

    vault = _seed_vault(tmp_path, out_of_scope=["baking"])
    (vault / "scripts").mkdir()
    shutil.copy(REPO_ROOT / "scripts" / "agent_call.py", vault / "scripts")
    return vault


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
def test_the_real_caller_returns_what_the_agent_printed(
    tmp_path: Path, topic_propose, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault_with_the_real_wrapper(tmp_path)
    answer = json.dumps(
        {
            "proposals": [
                {
                    "title": "Gas Oven",
                    "relation_type": "variant",
                    "parent_note": "data_vault/concept/Oven.md",
                    "justification": "A fuel variant of the oven.",
                    "degree": 1,
                }
            ],
            "rejected": [],
        }
    )
    monkeypatch.setenv("CLAUDE_BIN", str(_a_claude_that_answers(tmp_path, answer)))
    monkeypatch.delenv("RESEARCH_FRAMEWORK_DEFAULT_AGENT", raising=False)

    result = topic_propose.propose(vault, 1)

    assert "error" not in result, result
    assert [p["title"] for p in _read_manifest(vault, 1)["proposals"]] == ["Gas Oven"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
def test_the_real_caller_reports_a_failed_agent_call(
    tmp_path: Path, topic_propose, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault_with_the_real_wrapper(tmp_path)
    monkeypatch.setenv(
        "CLAUDE_BIN", str(_a_claude_that_answers(tmp_path, "", exit_code=3))
    )
    monkeypatch.delenv("RESEARCH_FRAMEWORK_DEFAULT_AGENT", raising=False)

    result = topic_propose.propose(vault, 1)

    assert "agent call failed: agent_call.py exited" in result["error"]
    assert "agent said no" in result["error"]
