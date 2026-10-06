"""D2: per-cycle ``cycle.log`` FileHandler (spec 048 v1.1)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from research_framework.observability.cycle_log import cycle_log_handler


def test_cycle_log_captures_logger_info(tmp_path: Path) -> None:
    log_path = tmp_path / "_pipeline" / "cycles" / "cycle-001" / "cycle.log"
    test_logger = logging.getLogger("research_framework.test.cycle_log")

    with cycle_log_handler(tmp_path, 1):
        test_logger.info("hello from cycle")

    assert log_path.is_file()
    content = log_path.read_text(encoding="utf-8")
    assert "hello from cycle" in content
    assert "[INFO]" in content


def test_cycle_log_no_handler_leak_across_two_contexts(tmp_path: Path) -> None:
    baseline = len(logging.root.handlers)
    test_logger = logging.getLogger("research_framework.test.cycle_log.leak")

    with cycle_log_handler(tmp_path, 1):
        test_logger.info("cycle one")

    with cycle_log_handler(tmp_path, 2):
        test_logger.info("cycle two")

    assert len(logging.root.handlers) == baseline


def test_cycle_log_open_failure_is_fail_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import research_framework.observability.cycle_log as mod

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(mod.logging.FileHandler, "__init__", _boom)
    baseline = len(logging.root.handlers)
    with cycle_log_handler(tmp_path, 1):
        logging.getLogger("research_framework.test.cycle_log.failopen").info("ok")
    assert len(logging.root.handlers) == baseline


def test_cycle_log_closes_on_exception(tmp_path: Path) -> None:
    baseline = len(logging.root.handlers)
    log_path = tmp_path / "_pipeline" / "cycles" / "cycle-001" / "cycle.log"
    test_logger = logging.getLogger("research_framework.test.cycle_log.exception")

    with pytest.raises(RuntimeError, match="boom"):
        with cycle_log_handler(tmp_path, 1):
            test_logger.info("before failure")
            raise RuntimeError("boom")

    assert len(logging.root.handlers) == baseline
    assert log_path.is_file()
    assert "before failure" in log_path.read_text(encoding="utf-8")
