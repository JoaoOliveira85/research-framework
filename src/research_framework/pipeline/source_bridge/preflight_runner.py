"""Spawn + interpret a module's preflight subprocess (spec 051 FR4).

Used by ``orchestrator.run_extraction`` (once per module at cycle start) and the
``refresh-sources`` sweep. Fail-closed: a crash, timeout, non-zero exit, or
unparseable stdout all map to a ``fatal_fail`` verdict, so a broken preflight
skips only its own module — never crashes the cycle (Principle VIII isolation).
The wall-clock cap is enforced by the same ``terminate_process_tree`` machinery
the extractor uses (spec 050 / spec 051 FR5).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from research_framework.pipeline.atomic_write import write_json
from research_framework.pipeline.process_tree import (
    popen_session,
    terminate_process_tree,
)

from .preflight_types import PreflightResult

_DEFAULT_TIMEOUT_SECONDS = 30


def _load_raw_sources(vault_dir: Path, module: str) -> dict[str, Any]:
    path = vault_dir / "modules" / module / "sources.yaml"
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return raw if isinstance(raw, dict) else {}


def _load_raw_watermarks(vault_dir: Path, module: str) -> dict[str, Any]:
    path = vault_dir / "_pipeline" / "sources" / module / "watermarks.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _infer_probe_telemetry(
    manifest: Any,
    result: PreflightResult,
    *,
    elapsed_ms: int,
) -> dict[str, Any]:
    """Derive module probe telemetry from a completed preflight subprocess."""
    auth = getattr(manifest, "authentication", None)
    env_vars = list(auth.env_vars) if auth and auth.env_vars else []
    messages = list(result.messages)
    lower = [m.lower() for m in messages]

    if env_vars:
        auth_ms = elapsed_ms
        if any("missing env var" in m for m in lower) or result.verdict == "fatal_fail":
            auth_status = "fail"
        else:
            auth_status = "ok"
    else:
        auth_status = "skip"
        auth_ms = 0

    conn_msgs = [m for m in messages if "connectivity probe" in m.lower()]
    if conn_msgs:
        connectivity_status = "warn" if result.verdict == "warning" else "fail"
        connectivity_ms = elapsed_ms
    elif result.verdict == "fatal_fail":
        connectivity_status = "fail"
        connectivity_ms = elapsed_ms if not env_vars else 0
    else:
        connectivity_status = "ok"
        connectivity_ms = elapsed_ms if auth_status == "skip" else 0

    errors: list[str] = []
    if result.verdict == "fatal_fail":
        errors = messages or ["preflight fatal_fail"]
    elif result.verdict == "warning":
        errors = [
            m
            for m in messages
            if "connectivity probe" in m.lower() or "missing env var" in m.lower()
        ]

    return {
        "module": manifest.name,
        "auth_probe_status": auth_status,
        "auth_probe_ms": auth_ms,
        "connectivity_status": connectivity_status,
        "connectivity_ms": connectivity_ms,
        "errors": errors,
    }


def _persist_module_probe(vault_dir: Path, probe: dict[str, Any]) -> None:
    path = vault_dir / "_pipeline" / "preflight.json"
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            data = {}
    probes_raw = data.get("module_probes")
    probes: list[dict[str, Any]] = (
        [p for p in probes_raw if isinstance(p, dict)]
        if isinstance(probes_raw, list)
        else []
    )
    probes = [p for p in probes if p.get("module") != probe["module"]]
    probes.append(probe)
    data["module_probes"] = probes
    write_json(path, data)


def run_preflight(vault_dir: Path, manifest: Any) -> PreflightResult:
    """Spawn ``<module>/<preflight.entry_point> preflight`` and parse the
    ``PreflightResult``. Fail-closed on every error path."""
    module = manifest.name
    module_dir = vault_dir / "modules" / module
    preflight = getattr(manifest, "preflight", None) or {}
    entry = preflight.get("entry_point")
    if not entry:
        result = PreflightResult.fatal(
            [f"module {module!r} declares no preflight.entry_point"]
        )
        _persist_module_probe(
            vault_dir, _infer_probe_telemetry(manifest, result, elapsed_ms=0)
        )
        return result
    script = module_dir / entry
    if not script.is_file():
        result = PreflightResult.fatal(
            [f"preflight script {entry!r} not found for module {module!r}"]
        )
        _persist_module_probe(
            vault_dir, _infer_probe_telemetry(manifest, result, elapsed_ms=0)
        )
        return result
    # Defensive: a malformed external manifest (e.g. timeout_seconds: "30s" or
    # null) must NOT raise here — that would crash the cycle instead of failing
    # closed. Default on parse failure, then clamp to the schema's [1, 300].
    try:
        timeout = int(preflight.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT_SECONDS
    timeout = max(1, min(timeout, 300))

    request = json.dumps(
        {
            "schema_version": "1.0",
            "sources": _load_raw_sources(vault_dir, module),
            "watermarks": _load_raw_watermarks(vault_dir, module),
        }
    )

    proc = popen_session(
        [sys.executable, str(script), "preflight"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(module_dir),
    )
    started = time.perf_counter()
    try:
        out, err = proc.communicate(request, timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_process_tree(proc)
        result = PreflightResult.fatal(
            [f"preflight for module {module!r} exceeded {timeout}s wall clock"]
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        _persist_module_probe(
            vault_dir, _infer_probe_telemetry(manifest, result, elapsed_ms=elapsed_ms)
        )
        return result
    elapsed_ms = max(1, int((time.perf_counter() - started) * 1000))
    if proc.returncode != 0:
        result = PreflightResult.fatal(
            [
                f"preflight for module {module!r} exited {proc.returncode}: "
                f"{(err or '').strip()[:200]}"
            ]
        )
        _persist_module_probe(
            vault_dir, _infer_probe_telemetry(manifest, result, elapsed_ms=elapsed_ms)
        )
        return result
    try:
        result = PreflightResult.from_json(json.loads(out or "{}"))
    except (json.JSONDecodeError, ValueError) as exc:
        result = PreflightResult.fatal(
            [f"preflight for module {module!r} emitted invalid output: {exc}"]
        )
        _persist_module_probe(
            vault_dir, _infer_probe_telemetry(manifest, result, elapsed_ms=elapsed_ms)
        )
        return result
    _persist_module_probe(
        vault_dir, _infer_probe_telemetry(manifest, result, elapsed_ms=elapsed_ms)
    )
    return result
