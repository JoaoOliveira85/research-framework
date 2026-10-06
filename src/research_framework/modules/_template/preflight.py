#!/usr/bin/env python3
"""Preflight skeleton for a new source module (spec 051 FR4, spec 038 probe pattern).

Reference file — ``_template/`` is NOT a shipped module. Copy into
``modules/<name>/preflight.py`` and wire module-specific checks in ``check()``.

Spec 038 probe pattern (duplicate module-side — no ``src/`` imports):

1. Declare ``authentication.env_vars`` / ``failure_policy`` in ``manifest.yaml``.
2. Env-var presence via ``os.environ`` + ``<MODULE>_PREFLIGHT_FAKE_ENV`` JSON
   fixture override for hermetic tests.
3. Optional connectivity HEAD probe via ``<MODULE>_PREFLIGHT_HEAD_FIXTURE`` (see
   ``modules/rss/preflight.py``) — connectivity failures are ``warning``, not
   ``fatal_fail``, unless ``failure_policy: block_cycle`` elevates them.

Subprocess contract: ``main()`` reads JSON from stdin, prints ``PreflightResult``
JSON to stdout. Contract:
``specs/051-post-revival-hardening/contracts/preflight.contract.md``.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

_MODULE = "example"
# When porting: mirror ``manifest.yaml`` ``authentication.env_vars`` here.
_MANDATORY_ENV_VARS: tuple[str, ...] = ()


def _result(
    verdict: str,
    *,
    corrections: list[dict[str, Any]] | None = None,
    messages: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "verdict": verdict,
        "corrections": corrections or [],
        "messages": messages or [],
    }


def _fake_env_prefix() -> str:
    return _MODULE.upper()


def _load_fake_env() -> dict[str, str] | None:
    fixture = os.environ.get(f"{_fake_env_prefix()}_PREFLIGHT_FAKE_ENV", "").strip()
    if not fixture:
        return None
    try:
        with open(fixture, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _env_value(var: str, fake_env: dict[str, str] | None) -> str | None:
    if fake_env is not None:
        value = fake_env.get(var)
        return str(value).strip() if value else None
    value = os.environ.get(var)
    return value.strip() if value else None


def _auth_probe_messages() -> tuple[list[str], bool]:
    fake_env = _load_fake_env()
    messages: list[str] = []
    missing = False
    for var in _MANDATORY_ENV_VARS:
        if not _env_value(var, fake_env):
            messages.append(f"module '{_MODULE}': missing env var {var}")
            missing = True
    return messages, missing


def check(
    sources: dict[str, Any],
    watermarks: dict[str, Any],
    *,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    del watermarks, timeout_seconds
    auth_messages, auth_missing = _auth_probe_messages()
    if auth_missing:
        return _result("fatal_fail", messages=auth_messages)
    if not isinstance(sources, dict) or not sources:
        return _result(
            "fatal_fail", messages=["no sources declared — nothing to extract"]
        )
    return _result("success")


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "preflight"
    payload = json.loads(sys.stdin.read() or "{}")
    if command == "preflight":
        out = check(
            payload.get("sources") or {},
            payload.get("watermarks") or {},
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
        )
    else:
        out = _result("fatal_fail", messages=[f"unknown command: {command}"])
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
