#!/usr/bin/env python3
"""Test shim — delegates to tests/_helpers/fake_agent.py.

Installed in place of scripts/agent_call.py by the vault_factory so the
production cycle_runner.py invokes the fake without any source change.

The repo root is resolved at runtime in three strategies (in order):

  1. ``$RESEARCH_FRAMEWORK_REPO_ROOT`` env-var override (CI escape hatch).
  2. Walk up from this file's location looking for the helpers tree.
     Works for any shim living inside the repo (e.g. committed fixture
     vaults under ``tests/fixtures/``).
  3. Fall back to the path baked at install time. This branch is ONLY
     populated when ``install_shim()`` writes the shim OUTSIDE the repo
     tree (typically a pytest ``tmp_path``). For installs INSIDE the
     repo the baked value is ``None`` and the strategy raises a clear
     RuntimeError — Strategy 2 should have succeeded.

This keeps committed fixture shims environment-independent (their
content is stable across worktrees) while still letting tmp_path-based
e2e tests bake an absolute path at install time.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


_BAKED_REPO_ROOT = None


def _resolve_repo_root() -> str:
    """Find a worktree root containing ``tests/_helpers/fake_agent.py``."""
    env_root = os.environ.get("RESEARCH_FRAMEWORK_REPO_ROOT")
    if env_root and (Path(env_root) / "tests" / "_helpers" / "fake_agent.py").is_file():
        return env_root
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "tests" / "_helpers" / "fake_agent.py").is_file():
            return str(parent)
    if _BAKED_REPO_ROOT is not None and (
        Path(_BAKED_REPO_ROOT) / "tests" / "_helpers" / "fake_agent.py"
    ).is_file():
        return _BAKED_REPO_ROOT
    raise RuntimeError(
        "fake-agent shim: could not resolve the research-framework repo root. "
        "Tried (1) $RESEARCH_FRAMEWORK_REPO_ROOT, (2) walking up from "
        f"{Path(__file__).resolve()}, (3) the install-time baked path "
        f"({_BAKED_REPO_ROOT!r}). Set $RESEARCH_FRAMEWORK_REPO_ROOT to a "
        "worktree root containing tests/_helpers/fake_agent.py, or run "
        "the shim from inside the worktree tree."
    )


_REPO_ROOT = _resolve_repo_root()

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
# pythonpath for any nested subprocess the fake might spawn (it doesn't,
# but a future change could).
existing = os.environ.get("PYTHONPATH", "")
parts = existing.split(os.pathsep) if existing else []
if _REPO_ROOT not in parts:
    os.environ["PYTHONPATH"] = os.pathsep.join([_REPO_ROOT] + parts)

from tests._helpers import fake_agent  # noqa: E402


# Duck-typed AgentCallResult — matches the shape that
# ``scripts/agent_call.AgentCallResult`` exposes (stdout, stderr,
# exit_code). plan_narrator.prepend_narrative reads only ``stdout`` and
# ``exit_code``, so a SimpleNamespace is enough. Installed alongside
# ``main`` so callers that import this module (e.g. plan_narrator's
# in-process bootstrap) get a working ``dispatch`` without spawning
# the real ``claude``/``codex`` binary. See spec 025 A1 contract and
# fake-agent.contract.md.
from types import SimpleNamespace  # noqa: E402


def _allocate_fake_sidecar_path(cycle_dir: Path, stage: str) -> Path:
    agent_calls = cycle_dir / "agent-calls"
    agent_calls.mkdir(parents=True, exist_ok=True)
    base = agent_calls / f"{stage}.json"
    if not base.exists():
        return base
    n = 2
    while (agent_calls / f"{stage}-{n}.json").exists():
        n += 1
    return agent_calls / f"{stage}-{n}.json"


def dispatch(stage, prompt, *, tier="standard", agent=None, model=None,
             vault_dir=None, cycle_dir=None, timeout_s=None):
    """Test-mode dispatch — returns canned output for known stages.

    The signature mirrors ``scripts/agent_call.dispatch`` parameter for
    parameter, ``model`` included: ``processors/extract.py`` passes it on
    every call, so without it the extract seam TypeErrored under the fake and
    the extract tests had to stub the bootstrap rather than exercise the shim
    (issue #262). ``tests/_helpers/test_fake_agent_parity.py`` derives the
    expected parameter set from the real function and fails on drift.
    """
    del prompt, agent, model, timeout_s
    cycle_num = 1
    if cycle_dir is not None:
        for part in cycle_dir.parts:
            if part.startswith("cycle-") and part[6:].isdigit():
                cycle_num = int(part[6:])
                break
    if stage in ("plan_narrator", "research_plan_narrator"):
        stdout = (
            f"Cycle {cycle_num} priority rationale "
            "(fake-agent canned narrator)."
        )
        exit_code = 0
    elif stage == "probe_retrieval":
        stdout = '{"probes": {}}'
        exit_code = 0
    else:
        return SimpleNamespace(
            stdout="",
            stderr=f"fake-agent.dispatch: stage {stage!r} has no in-process handler",
            exit_code=1,
            cost_usd=0.0,
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
        )
    if cycle_dir is not None:
        sidecar_path = _allocate_fake_sidecar_path(cycle_dir, stage)
        # Qualified: this file is a shim, not the fake module. Only
        # ``fake_agent`` and ``SimpleNamespace`` are imported here, so an
        # unqualified name raises NameError — and every caller of this
        # dispatch (plan_narrator, _probe_staging) swallows Exception into a
        # canned fallback, which is how issue #259 stayed invisible for a
        # release.
        fake_agent._write_cost_sidecar_v11(
            sidecar_path,
            stage=stage,
            cycle=cycle_num,
            scenario="happy",
        )
    return SimpleNamespace(
        stdout=stdout,
        stderr="",
        exit_code=exit_code,
        cost_usd=0.0,
        tokens_in=0,
        tokens_out=0,
        latency_ms=0,
    )


if __name__ == "__main__":
    sys.exit(fake_agent.main(sys.argv[1:]))
