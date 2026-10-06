"""Unit tests for CycleRuntimeState (spec 049 US3)."""

from research_framework.pipeline._helpers.cycle_state import CycleRuntimeState


def test_cycle_runtime_state_defaults_falsy():
    state = CycleRuntimeState()
    assert state.should_abort is False
    assert state.note_writer_cap_tripped is False


def test_cycle_runtime_state_instances_are_independent():
    first = CycleRuntimeState()
    second = CycleRuntimeState()
    first.should_abort = True
    assert second.should_abort is False
    first.note_writer_cap_tripped = True
    assert second.note_writer_cap_tripped is False
