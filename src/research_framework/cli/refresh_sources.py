"""refresh-sources CLI (spec 023 FR-013)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from ..pipeline.settings import SettingsError, VaultSettings, load_vault_settings

LEGACY_COLLECTOR_ALLOWLIST = frozenset({"reddit_rss.py"})
STDERR_TAIL_MAX = 2048
_CONNECTIVITY_PROBE_URL = "https://example.com/"
_CONNECTIVITY_FIXTURE_ENV = "REFRESH_SOURCES_CONNECTIVITY_FIXTURE"
_GH_AUTH_COMMAND = ("gh", "auth", "status")


def _discover_collectors(vault_dir: Path, settings: VaultSettings) -> list[str]:
    rs = settings.refresh_sources
    if rs.collectors:
        return list(rs.collectors)
    scripts = vault_dir / "scripts"
    names = {p.name for p in scripts.glob("collect_*.py") if p.is_file()}
    for name in LEGACY_COLLECTOR_ALLOWLIST:
        if (scripts / name).is_file():
            names.add(name)
    return sorted(names)


def _validate_only_names(names: list[str]) -> str | None:
    for name in names:
        if name.startswith("collect_") and name.endswith(".py"):
            continue
        if name in LEGACY_COLLECTOR_ALLOWLIST:
            continue
        return name
    return None


def _preflight_sweep(vault_dir: Path) -> list[dict]:
    """Run each installed module's preflight (spec 051 FR4) — a discrete pass
    independent of the legacy collector loop. Uses the framework's own
    interpreter (not the vault venv), so it runs before the venv check.
    Fail-closed per module via run_preflight."""
    from ..pipeline.source_bridge.discovery import walk_modules
    from ..pipeline.source_bridge.preflight_runner import run_preflight

    rows: list[dict] = []
    for manifest in walk_modules(vault_dir):
        result = run_preflight(vault_dir, manifest)
        rows.append({"module": manifest.name, **result.to_dict()})
    return rows


def _report_preflight(rows: list[dict]) -> None:
    for row in rows:
        if row["verdict"] == "fatal_fail":
            print(
                f"[refresh-sources] preflight FAILED for module {row['module']}: "
                f"{'; '.join(row['messages']) or '(no message)'}",
                file=sys.stderr,
            )
        elif row["verdict"] == "warning":
            for msg in row["messages"]:
                print(
                    f"[refresh-sources] preflight [{row['module']}]: {msg}",
                    file=sys.stderr,
                )


def _report_host_checks(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        if row.get("status") != "warn":
            continue
        check = row.get("check", "host")
        print(
            f"[refresh-sources] host-check WARN ({check}): {row.get('message', '')}",
            file=sys.stderr,
        )


def _vault_uses_github(vault_dir: Path) -> bool:
    modules_root = vault_dir / "modules"
    if not modules_root.is_dir():
        return False
    for manifest_path in sorted(modules_root.glob("*/manifest.yaml")):
        sources_path = manifest_path.parent / "sources.yaml"
        if sources_path.is_file():
            try:
                raw = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue
            if isinstance(raw, dict):
                for entries in raw.values():
                    if not isinstance(entries, list):
                        continue
                    for entry in entries:
                        if isinstance(entry, dict):
                            text = str(entry.get("url") or entry.get("path") or "")
                        else:
                            text = str(entry)
                        if "github.com" in text.lower():
                            return True
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(manifest, dict):
            continue
        for trig in manifest.get("triggers") or []:
            if (
                isinstance(trig, dict)
                and "github" in str(trig.get("pattern", "")).lower()
            ):
                return True
    return False


def _missing_code_repo_paths(vault_dir: Path) -> list[tuple[str, str]]:
    sources_path = vault_dir / "modules" / "code" / "sources.yaml"
    if not sources_path.is_file():
        return []
    try:
        raw = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return []
    if not isinstance(raw, dict):
        return []
    missing: list[tuple[str, str]] = []
    for entry in raw.get("github_repos") or []:
        if isinstance(entry, dict) and entry.get("path"):
            path_str = str(entry["path"])
            if not Path(path_str).expanduser().exists():
                missing.append(("code", path_str))
    return missing


def _default_run_command(
    cmd: list[str], **kwargs: Any
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, **kwargs)


def _default_connectivity_probe() -> tuple[bool, str]:
    fixture = os.environ.get(_CONNECTIVITY_FIXTURE_ENV, "").strip()
    if fixture:
        try:
            data = json.loads(Path(fixture).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, "connectivity probe fixture unreadable"
        if isinstance(data, dict) and data.get("ok"):
            return True, ""
        if isinstance(data, dict):
            return False, str(data.get("error") or "connectivity probe failed")
        return False, "connectivity probe failed"

    req = urllib.request.Request(
        _CONNECTIVITY_PROBE_URL,
        method="HEAD",
        headers={"User-Agent": "research-framework-refresh-sources/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if 200 <= resp.status < 400:
                return True, ""
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code} {exc.reason}"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return False, str(exc)


def _check_gh_auth(
    *,
    run_command: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    try:
        proc = run_command(
            list(_GH_AUTH_COMMAND),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return {
            "check": "gh_auth",
            "status": "warn",
            "message": f"gh auth status probe failed: {exc}",
        }
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "not authenticated").strip()
        return {
            "check": "gh_auth",
            "status": "warn",
            "message": f"gh auth status failed: {detail[:200]}",
        }
    return {"check": "gh_auth", "status": "ok", "message": ""}


def _check_connectivity(
    *,
    connectivity_probe: Callable[[], tuple[bool, str]],
) -> dict[str, Any]:
    ok, detail = connectivity_probe()
    if ok:
        return {"check": "connectivity", "status": "ok", "message": ""}
    return {
        "check": "connectivity",
        "status": "warn",
        "message": f"connectivity probe failed: {detail}",
    }


def _host_checks(
    vault_dir: Path,
    *,
    run_command: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    connectivity_probe: Callable[[], tuple[bool, str]] | None = None,
) -> list[dict[str, Any]]:
    """Host-level WARN checks (FR-012): gh auth, connectivity, local repo paths."""
    runner = run_command or _default_run_command
    probe = connectivity_probe or _default_connectivity_probe
    rows: list[dict[str, Any]] = []
    if _vault_uses_github(vault_dir):
        rows.append(_check_gh_auth(run_command=runner))
    rows.append(_check_connectivity(connectivity_probe=probe))
    for module, path in _missing_code_repo_paths(vault_dir):
        rows.append(
            {
                "check": "local_repo_path",
                "status": "warn",
                "message": (
                    f"module {module!r}: code repo path {path!r} does not exist on disk"
                ),
                "module": module,
            }
        )
    return rows


def _row(script, status, exit_code, duration_s, raw_dirs, stderr_tail="", reason=""):
    d = {
        "script": script,
        "status": status,
        "exit_code": exit_code,
        "duration_s": duration_s,
        "raw_dirs": raw_dirs,
        "stderr_tail": stderr_tail,
    }
    if reason:
        d["reason"] = reason
    return d


def _run_collector(vault_dir, venv_python, script, *, timeout_s, verbose):
    script_path = vault_dir / "scripts" / script
    if not script_path.is_file():
        return _row(script, "skipped", 0, 0.0, [], reason="missing")
    if verbose:
        print(f"[refresh-sources] running {script} ...", file=sys.stderr, flush=True)
    t0 = time.monotonic()
    try:
        run_kwargs: dict = {
            "cwd": vault_dir,
            "text": True,
            "timeout": timeout_s,
            "env": {**os.environ, "PYTHONUNBUFFERED": "1"},
        }
        if verbose:
            run_kwargs["stdout"] = None
            run_kwargs["stderr"] = None
        else:
            run_kwargs["capture_output"] = True
        proc = subprocess.run(
            [str(venv_python), str(script_path)],
            **run_kwargs,
        )
        dur = time.monotonic() - t0
        stem = script.removeprefix("collect_").removesuffix(".py")
        raw_dirs = (
            [f"raw_data/{stem}"] if (vault_dir / "raw_data" / stem).is_dir() else []
        )
        stderr_tail = ""
        if not verbose:
            stderr_tail = (proc.stderr or "")[-STDERR_TAIL_MAX:]
        return _row(
            script,
            "ok" if proc.returncode == 0 else "failed",
            proc.returncode,
            dur,
            raw_dirs,
            stderr_tail,
        )
    except subprocess.TimeoutExpired as exc:
        dur = time.monotonic() - t0
        tail = (
            (exc.stderr or "")[-STDERR_TAIL_MAX:]
            if isinstance(exc.stderr, str)
            else "timeout"
        )
        return _row(script, "failed", 124, dur, [], tail)


def _emit(
    vault_dir,
    collectors,
    partial_failure,
    exit_code,
    as_json,
    dry_run,
    preflight=None,
    host_checks=None,
    reason="",
):
    if as_json:
        print(
            json.dumps(
                {
                    "vault": str(vault_dir),
                    "partial_failure": partial_failure,
                    "collectors": collectors,
                    "preflight": preflight or [],
                    "host_checks": host_checks or [],
                    "dry_run": dry_run,
                },
                indent=2,
            )
        )
    elif dry_run:
        for c in collectors:
            print(f"  would run: {c['script']}", file=sys.stderr)
    else:
        ok = sum(1 for c in collectors if c["status"] == "ok")
        fail = sum(1 for c in collectors if c["status"] == "failed")
        print(f"[refresh-sources] ok={ok} failed={fail}", file=sys.stderr)
    if reason:
        # Spec 077 FR-017: a non-zero exit says why on stderr in every mode;
        # under --json and --dry-run nothing else reaches it.
        print(f"[refresh-sources] {reason}", file=sys.stderr)
    return exit_code


def cmd_refresh_sources(args: argparse.Namespace) -> int:
    vault_dir = Path(args.vault).resolve()
    try:
        settings = load_vault_settings(vault_dir)
    except SettingsError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    # spec 051 FR4: sweep installed-module preflights up front (uses the
    # framework interpreter, so it runs before the vault-venv check below).
    # Not on a dry run: a preflight executes module code and records its probe
    # in `_pipeline/preflight.json`, and a dry run executes and writes nothing.
    preflight_rows = [] if args.dry_run else _preflight_sweep(vault_dir)
    host_rows = _host_checks(vault_dir)
    if not args.dry_run:
        _report_preflight(preflight_rows)
        _report_host_checks(host_rows)
    venv_python = vault_dir / ".venv" / "bin" / "python"
    if not venv_python.is_file():
        print(f"ERROR: venv python not found: {venv_python}", file=sys.stderr)
        return _emit(
            vault_dir, [], False, 2, args.json, args.dry_run, preflight_rows, host_rows
        )
    names = _discover_collectors(vault_dir, settings)
    if args.only:
        names = list(args.only)
        bad = _validate_only_names(names)
        if bad is not None:
            print(
                f"unknown collector '{bad}': must match collect_*.py or be in the legacy allowlist",
                file=sys.stderr,
            )
            return 2
    if not names:
        return _emit(
            vault_dir,
            [],
            False,
            2,
            args.json,
            args.dry_run,
            preflight_rows,
            host_rows,
            reason="no collectors to run: no scripts/collect_*.py or legacy "
            "allowlist script, and none listed in refresh_sources.collectors",
        )
    if args.dry_run:
        cols = []
        for name in names:
            sp = vault_dir / "scripts" / name
            cols.append(
                _row(
                    name,
                    "skipped" if not sp.is_file() else "ok",
                    0,
                    0.0,
                    [],
                    reason="missing" if not sp.is_file() else "",
                )
            )
        return _emit(
            vault_dir, cols, False, 0, args.json, True, preflight_rows, host_rows
        )
    cols = [
        _run_collector(
            vault_dir,
            venv_python,
            n,
            timeout_s=settings.refresh_sources.timeout_s,
            verbose=args.verbose,
        )
        for n in names
    ]
    ok = sum(1 for c in cols if c["status"] == "ok")
    failed = [c["script"] for c in cols if c["status"] == "failed"]
    fail = len(failed)
    if ok == 0 and fail == 0:
        # Every collector was skipped as missing: nothing ran, which is the
        # "no collectors" exit (spec 077), not success.
        return _emit(
            vault_dir,
            cols,
            False,
            2,
            args.json,
            False,
            preflight_rows,
            host_rows,
            reason="no collector ran: every collector is missing from scripts/: "
            + ", ".join(c["script"] for c in cols),
        )
    if ok == 0 and fail > 0:
        return _emit(
            vault_dir,
            cols,
            False,
            2,
            args.json,
            False,
            preflight_rows,
            host_rows,
            reason=f"every collector failed: {', '.join(failed)}",
        )
    if fail > 0:
        return _emit(
            vault_dir,
            cols,
            True,
            1,
            args.json,
            False,
            preflight_rows,
            host_rows,
            reason=f"{fail} of {len(cols)} collectors failed: {', '.join(failed)}",
        )
    return _emit(vault_dir, cols, False, 0, args.json, False, preflight_rows, host_rows)
