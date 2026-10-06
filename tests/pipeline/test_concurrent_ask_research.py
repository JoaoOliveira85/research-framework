from __future__ import annotations

import fnmatch
import json
import threading
from pathlib import Path

import pytest

from research_framework.pipeline.cycle_runner import run_cycle_steps
from tests._helpers.vault_factory import build_minimal_vault

pytestmark = pytest.mark.e2e


def _scan_cycle_jsons(vault: Path, errors: list) -> None:
    """One pass over every cycle JSON, appended to ``errors`` on a parse
    failure. Named per-file: a bare "Expecting value: line 1 column 1" would
    force the next reader to bisect every writer under `_pipeline/cycles/`
    to find the non-atomic one (it was steps/scout.py's post-tagging rewrite
    of cycle-NNN-scout.json; see issue #312's e2e run)."""
    cycles = vault / "_pipeline/cycles"
    for path in cycles.glob("cycle-*-*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}: {exc}")


def _read_notes(vault: Path, errors: list, stop: threading.Event) -> None:
    dv = vault / "data_vault"
    while not stop.is_set():
        for path in dv.rglob("*.md"):
            if path.name.startswith("_"):
                continue
            text = path.read_text(encoding="utf-8")
            if text.startswith("---") and text.count("---") < 2 and len(text) < 80:
                errors.append(ValueError(f"torn frontmatter: {path}"))
                stop.set()
                return


def test_concurrent_cycle_json_reads_never_invalid_during_fixture_research(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A free-running reader thread racing an unsynchronized writer can go
    the whole test without ever landing inside the narrow write-in-flight
    window — that race, not the property itself, is what let this test flake
    instead of failing reliably back when a writer wasn't atomic (issue
    #312). ``pipeline.atomic_write`` never calls ``Path.write_text`` on a
    cycle JSON's own final path — only on a same-directory temp file, made
    visible in one ``os.replace``. So any call that reaches
    ``Path.write_text`` on ``cycle-*-*.json`` directly is, by construction,
    exactly the open("w")-truncates-then-writes shape #312 fixed. Replaying
    that call's own truncate phase with a forced reader scan in between
    makes the interleaving deterministic: a regression to this shape fails
    every run, not once in a while.
    """
    vault = build_minimal_vault(tmp_path, max_cycles=1)
    cycles_dir = vault / "_pipeline" / "cycles"
    errors: list = []
    reader_ready = threading.Event()
    scan_done = threading.Event()
    stop = threading.Event()

    def reader_loop() -> None:
        while not stop.is_set():
            if not reader_ready.wait(timeout=0.5):
                continue
            reader_ready.clear()
            _scan_cycle_jsons(vault, errors)
            scan_done.set()

    def _sync_scan() -> None:
        reader_ready.set()
        scan_done.wait(timeout=5)
        scan_done.clear()

    real_write_text = Path.write_text

    def guarded_write_text(self: Path, data: str, *args: object, **kwargs: object):
        if self.parent != cycles_dir or not fnmatch.fnmatch(
            self.name, "cycle-*-*.json"
        ):
            return real_write_text(self, data, *args, **kwargs)
        real_write_text(self, "", encoding="utf-8")
        _sync_scan()
        result = real_write_text(self, data, *args, **kwargs)
        _sync_scan()
        return result

    monkeypatch.setattr(Path, "write_text", guarded_write_text)

    reader = threading.Thread(target=reader_loop, daemon=True)
    reader.start()
    try:
        run_cycle_steps(vault, cycle_num=1)
    finally:
        stop.set()
        reader_ready.set()
        reader.join(timeout=10)

    assert not errors


def test_concurrent_data_vault_note_reads_never_empty_frontmatter_only(
    tmp_path: Path,
) -> None:
    vault = build_minimal_vault(tmp_path, max_cycles=1)
    errors: list = []
    stop = threading.Event()
    reader = threading.Thread(target=_read_notes, args=(vault, errors, stop))
    reader.start()
    run_cycle_steps(vault, cycle_num=1)
    stop.set()
    reader.join(timeout=30)
    assert not errors
