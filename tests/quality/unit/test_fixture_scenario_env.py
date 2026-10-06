"""Tier-1: the harness's per-fixture fake-agent env must be one the fake accepts.

``tests/quality/conftest._fixture_env`` set
``FAKE_AGENT_NOTE_WRITER_SCENARIO='substitution'`` for source-poor. The fake
has no such scenario — it exits 2 on the pair — so the fixture's declared
failure mode (``gap-pursuit-substitution``) was exercised by nothing, and no
test noticed because the cycle aborts at SG-002 before ``note_writer`` is ever
dispatched (issue #265).

This is deliberately tier-1 and unmarked: the e2e tier where the harness runs
does not execute in PR CI, so a guard living there would have caught the same
typo only at release time — if at all.
"""

from __future__ import annotations

import pytest

from research_framework.quality.runner import REGISTERED_FIXTURES
from tests._helpers.fake_agent import (
    _SCENARIO_ENV_PER_STAGE,
    _validate_scenario_for_stage,
)
from tests.quality.conftest import _fixture_env

_STAGE_BY_ENV = {env: stage for stage, env in _SCENARIO_ENV_PER_STAGE.items()}


@pytest.mark.parametrize("fixture_name", sorted(REGISTERED_FIXTURES))
def test_every_scenario_the_harness_sets_exists_in_the_fake(fixture_name: str) -> None:
    for env_var, scenario in _fixture_env(fixture_name).items():
        stage = _STAGE_BY_ENV.get(env_var)
        assert stage is not None, (
            f"{fixture_name} sets {env_var}, which is not a fake-agent "
            f"per-stage scenario variable: {sorted(_STAGE_BY_ENV)}"
        )
        _validate_scenario_for_stage(stage, scenario)
