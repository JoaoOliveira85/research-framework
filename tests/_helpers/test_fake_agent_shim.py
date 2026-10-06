"""Contract tests for the INSTALLED fake-agent shim.

``tests/_helpers/test_fake_agent_contract.py`` exercises ``fake_agent``'s
own CLI and Python API. Nothing exercised the *shim* — the small script
``install_shim`` renders from ``_SHIM_TEMPLATE`` and drops at
``<vault>/scripts/agent_call.py``. That gap let two defects live in the
template for a whole release:

* the in-process ``dispatch()`` referenced a helper name the shim never
  imports, so every ``cycle_dir``-carrying dispatch raised ``NameError``
  and the caller fell back to a canned path (issue #259);
* the committed fixture shims under ``tests/fixtures/quality/`` had drifted
  83 lines from the template, so ``build.sh --quality`` (which copies the
  committed tree) and pytest (which re-installs) ran two different fakes
  (issue #260).

Neither was visible to ``tests/quality/test_fake_agent_interception.py``:
that guard inspects ``subprocess.Popen`` argv, and an exception inside an
in-process call is not a spawned subprocess.
"""

from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path

import pytest

from research_framework.quality.runner import REGISTERED_FIXTURES
from tests._helpers import fake_agent

REPO_ROOT = Path(__file__).resolve().parents[2]
QUALITY_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "quality"
COMMITTED_SHIMS = sorted(QUALITY_FIXTURES.glob("*/scripts/agent_call.py"))


def _load_installed_shim(shim_path: Path, name: str) -> types.ModuleType:
    """Import an installed shim the way ``plan_narrator`` bootstraps it."""
    spec = importlib.util.spec_from_file_location(name, shim_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def installed_shim(tmp_path: Path) -> types.ModuleType:
    return _load_installed_shim(
        fake_agent.install_shim(tmp_path / "scripts"), "fake_agent_shim_under_test"
    )


# ---------------------------------------------------------------------------
# In-process dispatch (issue #259)
# ---------------------------------------------------------------------------


class TestShimDispatch:
    """``dispatch(cycle_dir=...)`` is the path ``plan_narrator`` and
    ``_probe_staging`` take. It must succeed, not raise into their
    ``except Exception`` fallbacks."""

    def test_narrator_dispatch_with_a_cycle_dir_succeeds(
        self, installed_shim: types.ModuleType, tmp_path: Path
    ) -> None:
        cycle_dir = tmp_path / "_pipeline" / "cycles" / "cycle-003"

        result = installed_shim.dispatch(
            "plan_narrator", "prompt body", cycle_dir=cycle_dir
        )

        assert result.exit_code == 0, result.stderr
        assert "fake-agent canned narrator" in result.stdout
        # The cycle number is read off the cycle dir, not defaulted to 1.
        assert "Cycle 3" in result.stdout

    def test_narrator_dispatch_writes_a_cost_sidecar(
        self, installed_shim: types.ModuleType, tmp_path: Path
    ) -> None:
        cycle_dir = tmp_path / "_pipeline" / "cycles" / "cycle-003"

        installed_shim.dispatch("plan_narrator", "prompt body", cycle_dir=cycle_dir)

        sidecar = cycle_dir / "agent-calls" / "plan_narrator.json"
        assert sidecar.is_file(), sorted(p.name for p in cycle_dir.rglob("*"))
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        assert payload["stage"] == "plan_narrator"
        assert payload["agent_kind"] == "fake"
        assert payload["cycle"] == 3
        assert payload["exit_code"] == 0

    def test_repeated_dispatches_do_not_overwrite_one_sidecar(
        self, installed_shim: types.ModuleType, tmp_path: Path
    ) -> None:
        cycle_dir = tmp_path / "_pipeline" / "cycles" / "cycle-001"

        installed_shim.dispatch("probe_retrieval", "p", cycle_dir=cycle_dir)
        installed_shim.dispatch("probe_retrieval", "p", cycle_dir=cycle_dir)

        written = sorted(p.name for p in (cycle_dir / "agent-calls").iterdir())
        assert written == ["probe_retrieval-2.json", "probe_retrieval.json"]

    def test_dispatch_without_a_cycle_dir_still_returns_stdout(
        self, installed_shim: types.ModuleType
    ) -> None:
        result = installed_shim.dispatch("probe_retrieval", "p")

        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"probes": {}}

    def test_dispatch_reports_an_unhandled_stage_rather_than_faking_success(
        self, installed_shim: types.ModuleType, tmp_path: Path
    ) -> None:
        result = installed_shim.dispatch(
            "scout", "p", cycle_dir=tmp_path / "_pipeline" / "cycles" / "cycle-001"
        )

        assert result.exit_code == 1
        assert "no in-process handler" in result.stderr


class TestNarratorRunUsesTheDispatchedNarrative:
    """The end the bug was actually felt at: ``prepend_narrative`` catches
    every ``Exception`` into a canned rationale and an incident line, so a
    broken shim looked exactly like a healthy run to the e2e tier."""

    def test_a_shimmed_vault_records_no_dispatch_incident(self, tmp_path: Path) -> None:
        from research_framework.pipeline.plan_narrator import prepend_narrative
        from tests._helpers.vault_factory import build_minimal_vault

        vault = build_minimal_vault(tmp_path)

        prepend_narrative(vault, cycle_number=1)

        incidents = vault / "_pipeline" / "narrator-incidents.md"
        assert not incidents.exists(), incidents.read_text(encoding="utf-8")

    def test_a_shimmed_vault_splices_the_dispatched_narrative(
        self, tmp_path: Path
    ) -> None:
        from research_framework.pipeline.plan_narrator import prepend_narrative
        from tests._helpers.vault_factory import build_minimal_vault

        vault = build_minimal_vault(tmp_path)

        prepend_narrative(vault, cycle_number=1)

        plan = (vault / "_pipeline" / "research-plan.md").read_text(encoding="utf-8")
        assert "fake-agent canned narrator" in plan

    def test_a_shimmed_vault_leaves_the_narrator_sidecar_behind(
        self, tmp_path: Path
    ) -> None:
        from research_framework.pipeline.plan_narrator import prepend_narrative
        from tests._helpers.vault_factory import build_minimal_vault

        vault = build_minimal_vault(tmp_path)

        prepend_narrative(vault, cycle_number=1)

        sidecar = (
            vault
            / "_pipeline"
            / "cycles"
            / "cycle-001"
            / "agent-calls"
            / "plan_narrator.json"
        )
        assert sidecar.is_file()


# ---------------------------------------------------------------------------
# Committed fixture shims (issue #260)
# ---------------------------------------------------------------------------


class TestCommittedFixtureShimsMatchTheTemplate:
    """``install_shim``'s docstring promises a re-install inside the repo is a
    ``git status`` no-op. Only this test makes that promise enforceable — and
    it is the only thing standing between ``build.sh --quality`` (which copies
    the committed tree) and pytest (which re-installs) running two different
    fakes."""

    def test_every_quality_fixture_ships_one(self) -> None:
        """Guards the parametrisation below: an empty glob would make each
        comparison vacuous instead of failing."""
        assert {p.parents[1].name for p in COMMITTED_SHIMS} == set(REGISTERED_FIXTURES)

    @pytest.mark.parametrize(
        "committed", COMMITTED_SHIMS, ids=[p.parents[1].name for p in COMMITTED_SHIMS]
    )
    def test_committed_shim_equals_a_fresh_render(self, committed: Path) -> None:
        # An in-repo install bakes ``None`` (``_baked_root_for``), which is
        # what makes committed shims byte-stable across worktrees.
        expected = fake_agent.render_shim(None)

        assert committed.read_text(encoding="utf-8") == expected, (
            f"{committed.relative_to(REPO_ROOT)} is a stale generation of "
            "_SHIM_TEMPLATE — regenerate it with fake_agent.install_shim()"
        )
