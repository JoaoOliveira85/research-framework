"""An update that keeps failing is set aside, not retried forever (spec 087,
Fix 2): ``attempts``, ``last_failure`` and ``pipeline.update_max_attempts``."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline import backlog, state_layout
from research_framework.pipeline.settings import SettingsError, load_vault_settings


def _entry(vault: Path, stem: str = "n") -> dict[str, Any]:
    store = json.loads(state_layout.research_backlog_path(vault).read_text("utf-8"))
    return next(e for e in store["entries"] if e["id"] == f"update:{stem}")


def _queue(vault: Path, source: str | None = None, reason: str = "review_due") -> None:
    assert backlog.update(
        vault,
        "scout" if source else "review",
        lambda tx: tx.observe_update(
            "n", reason, prompted_by=[source] if source else None, as_of="2020-01-01"
        ),
    )


def _stems(vault: Path) -> list[str]:
    return [r.stem for r in backlog.update_topics(vault)]


def test_two_failed_attempts_set_the_entry_aside(tmp_path: Path) -> None:
    _queue(tmp_path)

    assert backlog.record_update_failure(tmp_path, "n", "no outcome reported", cycle=3)
    assert _stems(tmp_path) == ["n"]  # one failure: still queued
    assert _entry(tmp_path)["attempts"] == 1
    assert backlog.record_update_failure(tmp_path, "n", "commentary only", cycle=4)

    assert _stems(tmp_path) == []  # at the limit (2): not queued any more
    entry = _entry(tmp_path)
    assert entry["status"] == "open"  # but still open in the store
    assert entry["attempts"] == 2
    assert entry["last_failure"] == {"reason": "commentary only", "cycle": 4}
    (aside,) = backlog.set_aside_updates(tmp_path)
    assert (
        aside.stem,
        aside.attempts,
        aside.last_failure,
        aside.last_failure_cycle,
    ) == (
        "n",
        2,
        "commentary only",
        4,
    )
    # the limit is a parameter, defaulting to the vault's setting
    assert _stems(tmp_path) == []
    assert [r.stem for r in backlog.update_topics(tmp_path, max_attempts=3)] == ["n"]
    # the view says so, under its own sub-heading, with the reason
    text = backlog.view_path(tmp_path).read_text(encoding="utf-8")
    assert "## Notes to update" in text
    assert "### Set aside after 2 failed attempts" in text
    assert "last failure (cycle 4): commentary only" in text
    # a verifier rejection is a failed attempt too
    other = tmp_path / "other"
    other.mkdir()
    _queue(other)
    backlog.close_update(other, "n", "superseded", cycle=2)
    backlog.reopen_update(other, "n", "verifier: commentary", cycle=2)
    assert _entry(other)["attempts"] == 1
    assert _entry(other)["last_failure"]["reason"] == "verifier: commentary"


def test_a_passing_outcome_resets_the_count(tmp_path: Path) -> None:
    _queue(tmp_path)
    backlog.record_update_failure(tmp_path, "n", "x", cycle=1)
    assert _entry(tmp_path)["attempts"] == 1

    assert backlog.close_update(tmp_path, "n", "confirmed", cycle=2)

    entry = _entry(tmp_path)
    assert "attempts" not in entry and "last_failure" not in entry
    # a later sighting reopens it with a clean slate
    _queue(tmp_path, source="https://a.example")
    assert "attempts" not in _entry(tmp_path)
    assert _stems(tmp_path) == ["n"]


def test_new_material_gives_a_set_aside_note_another_try(tmp_path: Path) -> None:
    _queue(tmp_path, source="https://a.example", reason="new_material")
    for cycle in (1, 2):
        backlog.record_update_failure(tmp_path, "n", "unsupported", cycle=cycle)
    assert _stems(tmp_path) == []

    # the same source again is not new material
    _queue(tmp_path, source="https://a.example", reason="new_material")
    assert _stems(tmp_path) == []
    assert _entry(tmp_path)["attempts"] == 2

    # a source not seen before is: another try, and the sources accumulate
    _queue(tmp_path, source="https://b.example", reason="new_material")

    assert _stems(tmp_path) == ["n"]
    assert _entry(tmp_path)["attempts"] == 0
    assert _entry(tmp_path)["prompted_by"] == ["https://a.example", "https://b.example"]


def test_a_review_due_resighting_does_not_reset_the_count(tmp_path: Path) -> None:
    _queue(tmp_path)
    for cycle in (1, 2):
        backlog.record_update_failure(tmp_path, "n", "unsupported", cycle=cycle)

    for _ in range(3):  # the sweep finds the note due again, every cycle
        _queue(tmp_path)

    assert _stems(tmp_path) == []
    assert _entry(tmp_path)["attempts"] == 2
    assert [r.stem for r in backlog.set_aside_updates(tmp_path)] == ["n"]


def test_the_limit_is_a_validated_pipeline_setting(tmp_path: Path) -> None:
    def load(extra: str):
        (tmp_path / "settings.yaml").write_text(
            "pipeline:\n  max_cycles: 5\n  budget_usd: 10.0\n" + extra,
            encoding="utf-8",
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            return load_vault_settings(tmp_path)

    assert load("").update_max_attempts == 2
    assert load("  update_max_attempts: 5\n").update_max_attempts == 5
    for bad in ("0", "-1", "1.5", '"2"', "true"):
        with pytest.raises(SettingsError) as exc:
            load(f"  update_max_attempts: {bad}\n")
        assert "update_max_attempts" in str(exc.value)

    _queue(tmp_path)
    backlog.record_update_failure(tmp_path, "n", "x", cycle=1)
    load("  update_max_attempts: 1\n")
    assert _stems(tmp_path) == []  # read from the vault's settings
    load("  update_max_attempts: 3\n")
    assert _stems(tmp_path) == ["n"]
