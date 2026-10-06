"""Spec 074 — `cycle --target-topics` must reach the scout prompt.

`_cmd_cycle` called `run_single_cycle` **without a spec**. The orchestrator
guards the scout-prompt re-render on `spec is not None`
(`orchestrator.py:552`), so `_render_cycle_scout_prompt` never ran and
`target_topics` was discarded. Every layer below was correct — the renderer
does prepend them — so the flag was accepted, documented in `--help`, threaded
through two call layers, and inert.

Reproduced against 1.0.0 on a live vault: the supplied strings appeared nowhere
in `_pipeline/`.

Same family as spec 070's F1 (`data_sources[].url` parsed by nobody) and F4
(a `reason` the prompt never asked for): configuration the framework accepts
and silently ignores. The rule this file pins is that it must never be silent —
either the topics reach the scout, or the command refuses.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from research_framework.cli.research_cycles import _cmd_cycle


def _args(vault: Path, topics: list[str] | None) -> argparse.Namespace:
    return argparse.Namespace(
        vault=vault, cycle=2, budget_cap=1.0, target_topics=topics
    )


_SPEC = """---
name: "Target Topics Test"
owner: "test"
topic: |
  A vault used only to prove that --target-topics reaches the scout prompt.
goal: |
  Exercise the CLI seam.
sources:
  - name: "Web"
    type: external
    kind: strategy_hint
---
"""


@pytest.fixture
def spec_vault(tmp_path: Path) -> Path:
    """A vault whose research.spec.md actually LOADS.

    `build_minimal_vault` writes a deliberately partial spec (the cycle runner
    reads only a few fields), and `load_spec` validates during load — so that
    fixture cannot stand in for a real vault here. Every live vault's spec
    loads, which is the case this seam has to work for.
    """
    from tests._helpers.vault_factory import build_minimal_vault

    vault = build_minimal_vault(tmp_path, install_fake_agent=False)
    (vault / "research.spec.md").write_text(_SPEC, encoding="utf-8")
    return vault


def test_spec_is_passed_through_so_target_topics_survive(
    spec_vault: Path, monkeypatch
) -> None:
    """The regression: without a spec the orchestrator drops the topics."""
    seen: dict = {}

    def _capture(vault_dir, cycle_num, *a, **kw):
        seen.update(kw)
        seen["vault_dir"] = vault_dir
        return 0

    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_single_cycle", _capture
    )

    rc = _cmd_cycle(_args(spec_vault, ["Retrieval eval harnesses"]))

    assert rc == 0
    assert seen.get("spec") is not None, "spec must reach run_single_cycle"
    assert seen.get("target_topics") == ["Retrieval eval harnesses"]


def test_topics_without_a_loadable_spec_refuse_rather_than_vanish(
    tmp_path: Path, monkeypatch
) -> None:
    """If the topics cannot be honoured, say so — never silently discard."""
    bare = tmp_path / "bare"
    (bare / "_pipeline").mkdir(parents=True)

    called: list[int] = []
    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_single_cycle",
        lambda *a, **k: called.append(1) or 0,
    )

    rc = _cmd_cycle(_args(bare, ["Some topic"]))

    assert rc != 0, "a discarded --target-topics must not look like success"
    assert not called, "the cycle must not run with the flag silently dropped"


def test_no_topics_and_no_spec_still_runs(tmp_path: Path, monkeypatch) -> None:
    """Regression: the flagless path is unchanged for a spec-less vault."""
    bare = tmp_path / "bare"
    (bare / "_pipeline").mkdir(parents=True)
    called: list[int] = []
    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_single_cycle",
        lambda *a, **k: called.append(1) or 0,
    )

    assert _cmd_cycle(_args(bare, None)) == 0
    assert called


def test_resume_is_set_when_topics_are_given(spec_vault: Path, monkeypatch) -> None:
    """`resume=True` is what makes the orchestrator take the re-render path."""
    seen: dict = {}
    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_single_cycle",
        lambda vault_dir, cycle_num, *a, **kw: (seen.update(kw), 0)[1],
    )

    _cmd_cycle(_args(spec_vault, ["T"]))

    assert seen.get("resume") is True


# --------------------------------------------------------------------------
# Spec 073 seam — `ask.md` escalates through this command, so a query's
# discoveries become durable here.
# --------------------------------------------------------------------------


def test_a_query_cycle_records_discovered_ground(spec_vault: Path, monkeypatch) -> None:
    from research_framework.pipeline import spec_append

    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_single_cycle", lambda *a, **k: 0
    )
    monkeypatch.setattr(
        spec_append,
        "cited_hosts_for_cycle",
        lambda v, c: [
            spec_append.DiscoveredSource("https://www.prodata.dk/", "cited by note.md")
        ],
    )

    rc = _cmd_cycle(_args(spec_vault, ["contract-and-consultancy channel"]))

    assert rc == 0
    text = (spec_vault / "research.spec.md").read_text(encoding="utf-8")
    assert spec_append.BEGIN_MARKER in text
    assert "www.prodata.dk" in text
    assert "unassessed" in text


def test_a_backlog_cycle_records_nothing(spec_vault: Path, monkeypatch) -> None:
    """No --target-topics means it was not a query; the spec is untouched."""
    from research_framework.pipeline.spec_append import BEGIN_MARKER

    before = (spec_vault / "research.spec.md").read_text(encoding="utf-8")
    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_single_cycle", lambda *a, **k: 0
    )

    _cmd_cycle(_args(spec_vault, None))

    after = (spec_vault / "research.spec.md").read_text(encoding="utf-8")
    assert after == before
    assert BEGIN_MARKER not in after


def test_spec_append_failure_never_changes_the_exit_code(
    spec_vault: Path, monkeypatch
) -> None:
    """The research already succeeded; bookkeeping must not undo that."""
    from research_framework.pipeline import spec_append

    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_single_cycle", lambda *a, **k: 0
    )

    def _boom(*a, **k):
        raise RuntimeError("region is malformed")

    monkeypatch.setattr(spec_append, "record_query_discoveries", _boom)

    assert _cmd_cycle(_args(spec_vault, ["some topic"])) == 0
