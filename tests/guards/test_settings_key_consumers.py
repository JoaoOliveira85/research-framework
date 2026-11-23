"""Tier 2: every typed ``pipeline:`` settings key has a reader (spec 087 SC-005)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:  # ``scripts/`` is not an installed package
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.guards import run_all  # noqa: E402
from scripts.guards import settings_key_consumers as guard  # noqa: E402


def test_an_unread_pipeline_key_fails_and_the_tree_passes() -> None:
    # fail closed: the scan saw the keys and the modules it claims to
    report = guard.audit()
    assert {"max_cycles", "cycles_per_run", "cycle_split"} <= set(report.keys)
    assert len(report.files) > 100

    assert report.unread == []
    assert report.stale_allowlist == []

    planted = guard.audit(keys=[*report.keys, "planted_unread_pipeline_key"])
    assert planted.unread == ["planted_unread_pipeline_key"]
    assert guard.main([]) == 0


def test_a_docstring_or_comment_does_not_count_as_a_reader(tmp_path: Path) -> None:
    prose = tmp_path / "prose.py"
    prose.write_text(
        '"""Mentions planted_key in prose only."""\n# planted_key again\nx = 1\n'
    )
    reads = tmp_path / "reads.py"
    reads.write_text('value = settings.get("planted_key")\n')

    assert guard.audit(keys=["planted_key"], files=[prose]).unread == ["planted_key"]
    assert guard.audit(keys=["planted_key"], files=[reads]).unread == []


def test_the_guard_is_in_the_battery() -> None:
    names = [g.name for g in run_all.guard_battery()]
    assert "settings-key-consumers" in names
    assert "tests/guards/test_settings_key_consumers.py" in run_all.GUARD_TEST_PATHS
