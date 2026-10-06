"""Subprocess extractor contract tests (spec 020 US6)."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import textwrap
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from research_framework.observability import BridgeLogWriter, publish_bridge_writer
from research_framework.pipeline.source_bridge import extractor as extractor_module
from research_framework.pipeline.source_bridge.discovery import parse_manifest
from research_framework.pipeline.source_bridge.extractor import (
    ExtractorError,
    get_source_version,
    invoke_extractor,
    partial_to_signal,
    salvage_partial_json,
)
from research_framework.pipeline.source_bridge.isolation import isolated_call
from tests._helpers.fake_module import write_fake_extractor


def _manifest(vault: Path) -> object:
    return parse_manifest(vault / "modules" / "stub" / "manifest.yaml")


def test_extractor_stdin_stdout_json_roundtrip(bridge_vault: Path) -> None:
    manifest = _manifest(bridge_vault)
    data = invoke_extractor(
        bridge_vault,
        manifest,
        command="extract",
        stdin_payload={"source": {"path": "/tmp"}, "source_id": "s1"},
        source_id="s1",
    )
    assert data["verdict"] == "ok"


def test_get_source_version_subprocess_json_contract(bridge_vault: Path) -> None:
    manifest = _manifest(bridge_vault)
    version = get_source_version(
        bridge_vault,
        manifest,
        {"path": "/tmp"},
    )
    assert version == "v1"


def test_extractor_nonzero_exit_retries_once(bridge_vault: Path) -> None:
    mod = bridge_vault / "modules" / "stub"
    write_fake_extractor(mod, fail_attempts={1})
    manifest = _manifest(bridge_vault)

    def _run() -> dict:
        return invoke_extractor(
            bridge_vault,
            manifest,
            command="extract",
            stdin_payload={"source": {"path": "/tmp"}, "source_id": "s1"},
            source_id="s1",
        )

    result = isolated_call(
        _run,
        vault_dir=bridge_vault,
        module="stub",
        source_id="s1",
        kind="extractor",
    )
    assert result is not None
    assert result["verdict"] == "ok"


def test_extractor_salvage_partial_json_on_crash() -> None:
    partial = salvage_partial_json(
        'log line\n{"verdict": "error", "partial": true, "facts": {}}\n'
    )
    assert partial is not None
    assert partial.get("partial") is True


def test_extractor_tolerant_json_parse_via_blob_extractor(bridge_vault: Path) -> None:
    mod = bridge_vault / "modules" / "stub"
    payload = {
        "module": "stub",
        "source_id": "s",
        "source_version": "v1",
        "bridge_version": "0.3.2",
        "extracted_at": "2026-01-01T00:00:00Z",
        "verdict": "ok",
        "truncated": False,
        "partial": False,
        "facts": {},
        "notable": [],
    }
    (mod / "extractor.py").write_text(
        textwrap.dedent(
            f"""
            import json, sys
            print("log prefix")
            print(json.dumps({repr(payload)}))
            print("log suffix")
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    manifest = _manifest(bridge_vault)
    data = invoke_extractor(
        bridge_vault,
        manifest,
        command="extract",
        stdin_payload={"source": {"path": "/tmp"}, "source_id": "s"},
        source_id="s",
    )
    assert data["verdict"] == "ok"


def test_extractor_double_failure_isolated_with_error_verdict(
    bridge_vault: Path,
) -> None:
    mod = bridge_vault / "modules" / "stub"
    write_fake_extractor(mod, fail_attempts={1, 2})
    manifest = _manifest(bridge_vault)

    def _run() -> dict:
        return invoke_extractor(
            bridge_vault,
            manifest,
            command="extract",
            stdin_payload={"source": {"path": "/tmp"}, "source_id": "s1"},
            source_id="s1",
        )

    result = isolated_call(
        _run,
        vault_dir=bridge_vault,
        module="stub",
        source_id="s1",
        kind="extractor",
    )
    assert result is None
    qdir = bridge_vault / "_pipeline" / "sources" / "stub" / "quarantine"
    assert list(qdir.glob("*.partial.json")) == []


def test_extractor_heartbeat_timeout_hard_kills_at_600s(bridge_vault: Path) -> None:
    mod = bridge_vault / "modules" / "stub"
    (mod / "extractor.py").write_text(
        textwrap.dedent(
            """
            import sys, time
            if __name__ == "__main__":
                time.sleep(2)
                sys.exit(0)
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    manifest = _manifest(bridge_vault)
    times = iter([0.0, 0.0, 700.0, 700.0])

    with (
        patch(
            "research_framework.pipeline.source_bridge.extractor.time.monotonic",
            side_effect=lambda: next(times, 700.0),
        ),
        patch(
            "research_framework.pipeline.source_bridge.extractor.time.sleep",
        ),
        pytest.raises(ExtractorError, match="heartbeat"),
    ):
        invoke_extractor(
            bridge_vault,
            manifest,
            command="extract",
            stdin_payload={"source": {"path": "/tmp"}},
            timeout_seconds=900,
            source_id="slow",
        )


def test_validators_run_before_cache_write(bridge_vault: Path) -> None:
    (bridge_vault / "stub.validators.yaml").write_text(
        yaml.dump({"facts": {"technologies": {"required": True, "min_items": 1}}}),
        encoding="utf-8",
    )
    from research_framework.pipeline.source_bridge.orchestrator import run_extraction

    summary = run_extraction(bridge_vault, 1)
    assert summary.get("extractions", 0) >= 0
    sig_dir = bridge_vault / "_pipeline" / "sources" / "stub" / "signals"
    if sig_dir.is_dir():
        for path in sig_dir.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("verdict") == "ok" and not data.get("facts", {}).get(
                "technologies"
            ):
                pytest.fail("validator should block empty technologies")


def test_extractor_salvage_partial_via_partial_to_signal(bridge_vault: Path) -> None:
    manifest = _manifest(bridge_vault)
    payload = partial_to_signal(
        {"source_version": "v1", "facts": {}},
        manifest=manifest,
        source_id="s",
        bridge_version="0.3.2",
    )
    assert payload.verdict == "error"
    assert payload.partial is True


# ---------------------------------------------------------------------------
# Pipes and process group: the extractor must not be able to hang the bridge
# ---------------------------------------------------------------------------

_OK_SIGNAL = {
    "module": "stub",
    "source_id": "s",
    "source_version": "v1",
    "bridge_version": "0.3.2",
    "extracted_at": "2026-01-01T00:00:00Z",
    "verdict": "ok",
    "truncated": False,
    "partial": False,
    "facts": {},
    "notable": [],
}


def _extractor(bridge_vault: Path, body: str) -> object:
    """Replace the stub module's extractor with ``body``."""
    script = bridge_vault / "modules" / "stub" / "extractor.py"
    script.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    return _manifest(bridge_vault)


def _extract(bridge_vault: Path, manifest: object, **kwargs: object) -> dict:
    return invoke_extractor(
        bridge_vault,
        manifest,
        command="extract",
        stdin_payload={"source": {"path": "/tmp"}, "source_id": "s"},
        timeout_seconds=60,
        source_id="s",
        **kwargs,
    )


def test_extractor_stdout_larger_than_the_pipe_is_read(bridge_vault: Path) -> None:
    """Nothing read stdout until the extractor had exited, and an extractor
    with more than a pipe's worth (64 KiB) of signal to print cannot exit."""
    manifest = _extractor(
        bridge_vault,
        f"""
        import json, signal, sys
        signal.alarm(10)  # a write blocked on a full pipe dies here
        sys.stdin.read()
        payload = {_OK_SIGNAL!r}
        payload["facts"] = {{"blob": "x" * 300_000}}
        print(json.dumps(payload))
        """,
    )

    data = _extract(bridge_vault, manifest)

    assert data["verdict"] == "ok"
    assert len(data["facts"]["blob"]) == 300_000


def test_extractor_stderr_larger_than_the_pipe_does_not_block_it(
    bridge_vault: Path,
) -> None:
    """Without a ``bridge.log`` writer nothing read stderr while it ran."""
    manifest = _extractor(
        bridge_vault,
        f"""
        import json, signal, sys
        signal.alarm(10)  # a write blocked on a full pipe dies here
        sys.stdin.read()
        sys.stderr.write("progress " * 40_000 + "\\n")
        print(json.dumps({_OK_SIGNAL!r}))
        """,
    )

    data = _extract(bridge_vault, manifest)

    assert data["verdict"] == "ok"


def test_what_the_extractor_left_running_does_not_hold_the_call(
    bridge_vault: Path, tmp_path: Path
) -> None:
    """An extractor that exits leaving a child (a ``yt-dlp`` fork, a headless
    browser) with its stdout open: the read used to wait for that child."""
    ticks = tmp_path / "grandchild.ticks"
    manifest = _extractor(
        bridge_vault,
        f"""
        import json, os, subprocess, sys, time
        sys.stdin.read()
        subprocess.Popen([sys.executable, "-c", '''
        import os, time
        with open({str(ticks) + ".pid"!r}, "w") as fh:
            fh.write(str(os.getpid()))
        for _ in range(400):  # ~20s: bounded even if nothing stops it
            with open({str(ticks)!r}, "a") as fh:
                print("tick", file=fh)
            time.sleep(0.05)
        '''])
        for _ in range(200):  # leave only once the grandchild is ticking
            if os.path.exists({str(ticks)!r}) and os.path.getsize({str(ticks)!r}):
                break
            time.sleep(0.05)
        print(json.dumps({_OK_SIGNAL!r}))
        """,
    )

    try:
        started = time.monotonic()
        data = _extract(bridge_vault, manifest)
        elapsed = time.monotonic() - started

        assert data["verdict"] == "ok"
        assert elapsed < 12.0, (
            f"the extractor exited at once and the call took {elapsed:.1f}s: it "
            "waited for EOF on a pipe its grandchild was holding"
        )
        size = ticks.stat().st_size
        time.sleep(0.5)
        assert ticks.stat().st_size == size, "the grandchild outlived the call"
    finally:
        try:
            os.kill(int(Path(f"{ticks}.pid").read_text()), signal.SIGKILL)
        except (OSError, ValueError):
            pass


def test_an_error_after_the_spawn_does_not_leak_the_extractor(
    bridge_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whatever goes wrong on our side once the extractor is running, it must
    not be left behind doing a whole extraction for nobody."""
    manifest = _extractor(
        bridge_vault,
        """
        import sys, time
        sys.stdin.read()
        time.sleep(20)
        """,
    )
    spawned: list[subprocess.Popen] = []
    real_popen_session = extractor_module.popen_session

    def recording_popen_session(*args: object, **kwargs: object) -> subprocess.Popen:
        proc = real_popen_session(*args, **kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(extractor_module, "popen_session", recording_popen_session)

    class _FullDisk(BridgeLogWriter):
        def start_extractor(self, module: str, source: str, pid: int) -> None:
            raise OSError(28, "No space left on device")

    try:
        with (
            _FullDisk(bridge_vault / "bridge.log") as writer,
            publish_bridge_writer(writer),
            pytest.raises(OSError, match="No space left"),
        ):
            _extract(bridge_vault, manifest)

        (proc,) = spawned
        assert proc.poll() is not None, (
            "invoke_extractor raised and left the extractor it had started running"
        )
    finally:
        for proc in spawned:
            proc.kill()
            proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# bridge.log framing must never decide whether a source can be extracted
# ---------------------------------------------------------------------------

# specs/048-observability-v1/contracts/bridge-log-format.contract.md § Header line
_BRIDGE_HEADER = re.compile(
    r"^=== module: (?P<module>[\w-]+), source: (?P<source>[^,\n]+), "
    r"pid: (?P<pid>\d+), "
    r"started: (?P<started>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}) ===$"
)


def test_a_comma_in_the_source_id_does_not_fail_the_extraction(
    bridge_vault: Path,
) -> None:
    """A source id is whatever ``sources.yaml`` says: a URL, a path, a name.
    The header line cannot carry a comma or a newline, and the writer raising
    on one made every such source unextractable while a cycle was logging."""
    manifest = _manifest(bridge_vault)
    log_path = bridge_vault / "_pipeline" / "cycles" / "cycle-001" / "bridge.log"

    with BridgeLogWriter(log_path) as writer, publish_bridge_writer(writer):
        data = invoke_extractor(
            bridge_vault,
            manifest,
            command="extract",
            stdin_payload={"source": {"path": "/tmp"}, "source_id": "s"},
            source_id="https://example.org/wiki/Smith,_John\nJr",
        )

    assert data["verdict"] == "ok"
    header = log_path.read_text(encoding="utf-8").splitlines()[0]
    match = _BRIDGE_HEADER.match(header)
    assert match, f"header does not follow the contract: {header!r}"
    assert match["source"] == "https://example.org/wiki/Smith%2C_John%0AJr"


# § Footer line — success path (same contract)
_BRIDGE_FOOTER = re.compile(
    r"^=== exit: (?P<code>\d+), duration: (?P<duration>\d+\.\d{3})s, "
    r"payload_status: (?P<verdict>ok|empty|error) ===$"
)


def test_an_extractor_killed_by_a_signal_is_reported_as_such(
    bridge_vault: Path,
) -> None:
    """``Popen`` reports death by signal N as ``-N``. The footer takes a Unix
    exit code, the writer refused the negative number, and its ``ValueError``
    replaced the real failure, the salvaged output and the footer."""
    manifest = _extractor(
        bridge_vault,
        """
        import os, signal, sys
        sys.stdin.read()
        print('{"verdict": "error", "partial": true, "facts": {"seen": 1}}', flush=True)
        os.kill(os.getpid(), signal.SIGKILL)  # the OOM killer, say
        """,
    )
    log_path = bridge_vault / "_pipeline" / "cycles" / "cycle-001" / "bridge.log"

    with (
        BridgeLogWriter(log_path) as writer,
        publish_bridge_writer(writer),
        pytest.raises(ExtractorError, match="extractor exited -9") as excinfo,
    ):
        _extract(bridge_vault, manifest)

    assert excinfo.value.partial == {
        "verdict": "error",
        "partial": True,
        "facts": {"seen": 1},
    }
    footer = _BRIDGE_FOOTER.match(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert footer, "the invocation was left without its footer line"
    assert footer["code"] == "137"  # 128 + SIGKILL, as a shell reports it
    assert footer["verdict"] == "error"
