"""RED tests for mid-run required-source degradation threshold (T069 / US5). T073–T074 turn these green."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from research_framework.pipeline._helpers.cycle_state import CycleRuntimeState


def _import_notify():
    from research_framework.pipeline import cycle_runner

    fn = getattr(cycle_runner, "notify_required_source_degraded", None)
    if fn is None:
        pytest.fail("T074: add cycle_runner.notify_required_source_degraded(...)")
    return fn


def _vault_with_pipeline(parent: Path, settings: dict | None = None) -> Path:
    vault = parent / "v-thresh"
    pl = vault / "_pipeline"
    pl.mkdir(parents=True)
    if settings is not None:
        vault.joinpath("settings.yaml").write_text(
            yaml.safe_dump(settings, sort_keys=False),
            encoding="utf-8",
        )
    return vault


def test_one_required_degraded_warns_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marks: list[tuple[str, str, Path]] = []

    # 029 FR-005: observe the REAL 3-arg mark_degraded(name, reason, vault_dir)
    # signature (no *args) so an arity regression in the call site breaks this
    # test loudly instead of being hidden behind a permissive lambda.
    def _mark(name: str, reason: str, vault_dir: Path) -> None:
        marks.append((name, reason, vault_dir))

    monkeypatch.setattr(
        "research_framework.pipeline.source_manager.mark_degraded",
        _mark,
        raising=False,
    )
    notify = _import_notify()
    vault = _vault_with_pipeline(tmp_path)
    state = CycleRuntimeState()
    rc = notify(
        vault,
        source_name="repo-a",
        role="required",
        reason="timeout",
        runtime_state=state,
    )
    assert rc in (
        0,
        None,
        "warn",
        "WARN",
    ), "single required degradation must not abort the cycle"
    assert len(marks) == 1
    assert marks[0][0] == "repo-a"


def test_two_required_degraded_aborts_with_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "research_framework.pipeline.source_manager.mark_degraded",
        lambda *_a, **_k: None,
        raising=False,
    )
    notify = _import_notify()
    vault = _vault_with_pipeline(
        tmp_path,
        {"pipeline": {"source_failure_thresholds": {"required_quorum_loss": 2}}},
    )
    state = CycleRuntimeState()
    assert (
        notify(
            vault,
            source_name="repo-a",
            role="required",
            reason="slow",
            runtime_state=state,
        )
        != 2
    )
    assert (
        notify(
            vault,
            source_name="repo-b",
            role="required",
            reason="down",
            runtime_state=state,
        )
        == 2
    )


def test_threshold_configurable_via_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "research_framework.pipeline.source_manager.mark_degraded",
        lambda *_a, **_k: None,
        raising=False,
    )
    notify = _import_notify()
    vault = _vault_with_pipeline(
        tmp_path,
        {
            "pipeline": {
                "source_failure_thresholds": {"required_quorum_loss": 1},
                # Optional flat alias (spec Agent L); implementation may read either key.
                "required_source_failure_threshold": 1,
            }
        },
    )
    state = CycleRuntimeState()
    assert (
        notify(
            vault,
            source_name="only-one",
            role="required",
            reason="x",
            runtime_state=state,
        )
        == 2
    )


def test_enrichment_failures_never_abort_by_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "research_framework.pipeline.source_manager.mark_degraded",
        lambda *_a, **_k: None,
        raising=False,
    )
    notify = _import_notify()
    vault = _vault_with_pipeline(tmp_path)
    state = CycleRuntimeState()
    for i in range(10):
        out = notify(
            vault,
            source_name=f"rss-{i}",
            role="enrichment",
            reason="unreachable",
            runtime_state=state,
        )
        assert out != 2, (
            "enrichment-only failures must not trip required-source quorum abort"
        )
