"""Spec 083 T013 FR-005: a fake-agent cycle writes nothing unregistered under state/."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.pipeline import state_layout
from research_framework.pipeline.cycle_runner import run_cycle_steps
from tests._helpers import fake_cli_binary
from tests._helpers.vault_factory import build_minimal_vault

pytestmark = pytest.mark.e2e

# The scaffold's template-version stamp sits beside the files it describes.
ALSO_ALLOWED = {".tmpl-versions.json"}
# SQLite's own sidecars of the registered database (git-ignored by the stanza).
SQLITE = tuple(state_layout.SQLITE_SIDECAR_SUFFIXES)


def _registered(rel: str) -> bool:
    if Path(rel).name in ALSO_ALLOWED:
        return True
    for art in state_layout.STATE_ARTEFACTS:
        new = art.new_rel.removeprefix(f"{state_layout.STATE_DIR}/")
        if art.kind == "dir":
            if rel.startswith(new):
                return True
        elif art.kind == "per_module_file":
            head, tail = new.split("<module>/", 1)
            parts = rel.split("/")
            if rel.startswith(head) and len(parts) == 3 and rel.endswith("/" + tail):
                return True
        elif rel == new or (
            art.name == "sources_db" and any(rel == new + s for s in SQLITE)
        ):
            return True
    return False


def test_a_cycle_writes_nothing_unregistered_under_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault = build_minimal_vault(
        tmp_path,
        num_categories=1,
        num_targets_per_category=3,
        max_cycles=1,
        install_fake_agent=False,
    )
    fake_cli_binary.activate(monkeypatch, tmp_path / "bin")
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 1\n  budget_usd: 10.0\n"
        "default_executor:\n  runtime: claude\n  model: sonnet\n  timeout_s: 60\n",
        encoding="utf-8",
    )
    run_cycle_steps(vault, cycle_num=1, budget_cap=10.0, max_cycles=1)

    state = state_layout.state_dir(vault)
    assert state.is_dir()
    written = sorted(
        p.relative_to(state).as_posix() for p in state.rglob("*") if p.is_file()
    )
    assert "coverage-targets.json" in written  # the scaffold's own state is there
    stray = [rel for rel in written if not _registered(rel)]
    assert stray == [], f"files under _pipeline/state/ not in the registry: {stray}"
