"""Synthetic spec-020 extractor used by the FR-007 line-buffered probe.

This script emulates the stdin/stdout JSON contract of a real source-module
extractor while writing predictable timed stderr lines that the
``test_bridge_log_is_line_buffered`` test can poll for. It is INVOKED AS A
SUBPROCESS by the test harness (never imported), so the file must be
self-contained — no project imports, stdlib only.

Behaviour
---------

1. Read a JSON object from stdin (the test harness writes one and closes).
   Recognised optional keys::

       {"exit_code": int, "sleep_seconds": float, "num_stages": int}

   Defaults: ``exit_code=0``, ``sleep_seconds=1.0``, ``num_stages=3``.

2. Emit ``num_stages`` stderr lines of the form ``[STAGE-N]\n`` (N from 1).
   Between each pair of lines, ``time.sleep(sleep_seconds)``.

3. Write a minimal valid ``SignalPayload``-shaped JSON object to stdout
   (verdict ``"ok"`` when ``exit_code == 0``, ``"error"`` otherwise).

4. Exit with ``exit_code``.

The script flushes stderr after every write so the framework's line-buffered
reader thread observes each line as it is emitted — the entire premise of
FR-007's two-second-latency acceptance criterion.
"""

from __future__ import annotations

import json
import sys
import time


def _read_request() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        request = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(request, dict):
        return {}
    return request


def main() -> int:
    request = _read_request()
    exit_code = int(request.get("exit_code", 0))
    sleep_seconds = float(request.get("sleep_seconds", 1.0))
    num_stages = int(request.get("num_stages", 3))

    for stage in range(1, num_stages + 1):
        sys.stderr.write(f"[STAGE-{stage}]\n")
        sys.stderr.flush()
        if stage < num_stages:
            time.sleep(sleep_seconds)

    verdict = "ok" if exit_code == 0 else "error"
    payload = {
        "schema_version": "1.0",
        "module": "sentinel",
        "source_id": request.get("source_id", "sentinel-source"),
        "bridge_version": "0.0.0",
        "verdict": verdict,
        "facts": {},
        "notable": [],
        "last_error": None if exit_code == 0 else f"sentinel exited {exit_code}",
    }
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
