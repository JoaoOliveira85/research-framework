"""Pre-Phase-2 source connectivity checks (FR-007, E-008)."""

from __future__ import annotations

import http.client
import json
import subprocess
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from research_framework import __version__
from research_framework.pipeline.atomic_write import write_text
from research_framework.spec.schema import (
    DataSourceConfig,
    SpecConfig,
    SpecValidationError,
)
from research_framework.spec.simple import load as load_spec_simple
from research_framework.vault.frontmatter import split_frontmatter

SourceStatus = Literal["ok", "degraded", "unreachable"]
OverallStatus = Literal["pass", "warn", "fail"]

# What a urllib probe raises that is not a ``URLError``: a read that stalls
# after the connection is made is a bare ``TimeoutError`` (an ``OSError``), a
# URL with no scheme is a ``ValueError`` from ``Request``, and a bad port is an
# ``http.client.InvalidURL``. Each is a verdict on the source, and uncaught it
# was a traceback out of ``preconditions.check`` — that is, out of `--resume`.
_PROBE_ERRORS = (OSError, ValueError, http.client.HTTPException)


def oreilly_mcp_tool_available() -> bool:
    """Return True if the O'Reilly MCP tool is available (override in tests)."""
    return False


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _access_type_label(access_method: str) -> str:
    mapping = {
        "local": "local_repo",
        "github_pr": "github_pr",
        "web": "web",
        "rss": "rss",
        "oreilly": "oreilly",
    }
    return mapping.get(access_method, access_method or "unknown")


def _role_label(required: bool) -> Literal["required", "enrichment"]:
    return "required" if required else "enrichment"


@dataclass
class SourceCheck:
    name: str
    role: Literal["required", "enrichment"]
    type: str
    status: SourceStatus
    detail: str
    checked_at: str
    elapsed_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "type": self.type,
            "status": self.status,
            "detail": self.detail,
            "checked_at": self.checked_at,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class PreflightResult:
    generated_at: str
    framework_version: str
    sources: list[SourceCheck]
    required_unreachable_count: int
    enrichment_unreachable_count: int
    overall_status: OverallStatus
    schema_version: str = field(default="1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "framework_version": self.framework_version,
            "sources": [s.to_dict() for s in self.sources],
            "required_unreachable_count": self.required_unreachable_count,
            "enrichment_unreachable_count": self.enrichment_unreachable_count,
            "overall_status": self.overall_status,
        }

    def to_json_path(self, path: Path) -> None:
        write_text(
            path,
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
        )


def _parse_body_sections(body: str) -> dict[str, Any]:
    """Parse `## Section` blocks in split detailed specs (tests / onboard style)."""
    import re

    pattern = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(body))
    out: dict[str, Any] = {}
    for i, m in enumerate(matches):
        raw_title = m.group(1).strip()
        key = raw_title.lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunk = body[start:end].strip()
        if not chunk:
            continue
        try:
            loaded = yaml.safe_load(chunk)
        except yaml.YAMLError as e:
            raise SpecValidationError(
                [f"YAML in spec body section {raw_title!r}: {e}"]
            ) from e
        if key == "scope" and isinstance(loaded, dict):
            out["scope"] = loaded
        elif key == "note types" and isinstance(loaded, list):
            out["note_types"] = loaded
        elif key == "data sources" and isinstance(loaded, list):
            out["data_sources"] = loaded
        elif key == "search dimensions" and isinstance(loaded, dict):
            out["search_dimensions"] = list(loaded.get("dimensions") or [])
        elif key == "coverage targets" and isinstance(loaded, dict):
            out["coverage_targets"] = loaded
        elif key == "budget" and isinstance(loaded, dict):
            out["budget"] = loaded
    return out


def load_spec_for_preflight(spec_path: Path, vault_dir: Path) -> SpecConfig:
    """Load `research.spec.md`, including split frontmatter + markdown section form."""
    text = spec_path.read_text(encoding="utf-8")
    split = split_frontmatter(text)
    if "## Data Sources" in text and split is not None:
        fm = yaml.safe_load(split[0])
        if isinstance(fm, dict) and "data_sources" not in fm:
            merged = dict(fm)
            merged.update(_parse_body_sections(split[1]))
            return SpecConfig.from_dict(merged)
    try:
        return load_spec_simple(spec_path, location=vault_dir)
    except SpecValidationError:
        if split is None:
            raise
        fm2 = yaml.safe_load(split[0])
        if not isinstance(fm2, dict):
            raise
        merged2 = dict(fm2)
        merged2.update(_parse_body_sections(split[1]))
        return SpecConfig.from_dict(merged2)


def _local_paths_for_source(ds: DataSourceConfig) -> list[Path]:
    paths: list[Path] = []
    for repo in ds.repos:
        lp = (repo.local_path or "").strip()
        if lp:
            paths.append(Path(lp))
    return paths


def _first_repo_url(ds: DataSourceConfig) -> str:
    for repo in ds.repos:
        u = (repo.url or "").strip()
        if u:
            return u
    return ""


def check_source(source: DataSourceConfig, vault_dir: Path) -> SourceCheck:
    checked_at = _utc_now_iso()
    t0 = time.perf_counter_ns()
    detail = ""
    status: SourceStatus = "ok"
    access = (source.access_method or "").strip()
    kind = _access_type_label(access)
    role = _role_label(source.required)

    try:
        if access == "local":
            paths = _local_paths_for_source(source)
            if not paths:
                status = "unreachable"
                detail = "no local_path set on repos for local source"
            else:
                for p in paths:
                    if not p.is_dir():
                        status = "unreachable"
                        detail = f"local path does not exist: {p}"
                        break

        elif access == "github_pr":
            try:
                r = subprocess.run(
                    ["gh", "auth", "status"],
                    cwd=vault_dir,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                if r.returncode != 0:
                    status = "degraded"
                    detail = (r.stderr or r.stdout or b"").decode(
                        "utf-8", errors="replace"
                    ).strip() or "gh auth failed"
                elif source.repos and _first_repo_url(source):
                    repo_url = _first_repo_url(source)
                    r2 = subprocess.run(
                        ["gh", "repo", "view", repo_url],
                        cwd=vault_dir,
                        capture_output=True,
                        timeout=30,
                        check=False,
                    )
                    if r2.returncode != 0:
                        stderr = (r2.stderr or b"").decode("utf-8", errors="replace")
                        if "404" in stderr or "Not Found" in stderr:
                            status = "unreachable"
                            detail = stderr.strip() or "repository not found"
                        else:
                            status = "degraded"
                            detail = stderr.strip() or "gh repo view failed"
            except (OSError, subprocess.SubprocessError) as e:
                # SubprocessError: a `gh` that hangs past the timeout raises
                # TimeoutExpired, which is not an OSError.
                status = "degraded"
                detail = str(e)

        elif access == "web":
            url = _first_repo_url(source)
            if not url:
                status = "unreachable"
                detail = "no URL configured for web source"
            else:
                try:
                    req = urllib.request.Request(
                        url,
                        method="HEAD",
                        headers={"User-Agent": "research-framework-preflight/1.0"},
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        code = getattr(resp, "status", None) or resp.getcode()
                        if code is not None and code >= 400:
                            status = "unreachable"
                            detail = f"HTTP {code}"
                except urllib.error.HTTPError as e:
                    status = "unreachable"
                    detail = f"HTTP {e.code}"
                except urllib.error.URLError as e:
                    status = "unreachable"
                    detail = str(e.reason if hasattr(e, "reason") else e)
                except _PROBE_ERRORS as e:
                    status = "unreachable"
                    detail = str(e) or type(e).__name__

        elif access == "rss":
            url = _first_repo_url(source)
            if not url:
                status = "unreachable"
                detail = "no URL configured for rss source"
            else:
                try:
                    req = urllib.request.Request(
                        url,
                        headers={"User-Agent": "research-framework-preflight/1.0"},
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        code = getattr(resp, "status", None) or resp.getcode()
                        if code is not None and code >= 400:
                            status = "unreachable"
                            detail = f"HTTP {code}"
                        else:
                            read_fn = getattr(resp, "read", None)
                            if callable(read_fn):
                                body = read_fn(64 * 1024)
                            else:
                                body = b"<?xml version='1.0'?><rss></rss>"
                            try:
                                ET.fromstring(body)
                            except (ET.ParseError, LookupError, ValueError):
                                # LookupError / ValueError: an encoding
                                # declaration expat does not know or support.
                                status = "unreachable"
                                detail = "response is not valid XML"
                except urllib.error.HTTPError as e:
                    status = "unreachable"
                    detail = f"HTTP {e.code}"
                except urllib.error.URLError as e:
                    status = "unreachable"
                    detail = str(e.reason if hasattr(e, "reason") else e)
                except _PROBE_ERRORS as e:
                    status = "unreachable"
                    detail = str(e) or type(e).__name__

        elif access == "oreilly":
            if oreilly_mcp_tool_available():
                status = "ok"
            else:
                status = "unreachable"
                detail = "O'Reilly MCP tool not available"

        else:
            status = "unreachable"
            detail = f"unknown access_method: {access!r}"

    finally:
        elapsed_ms = max(0, int((time.perf_counter_ns() - t0) / 1_000_000))

    return SourceCheck(
        name=source.name,
        role=role,
        type=kind,
        status=status,
        detail=detail,
        checked_at=checked_at,
        elapsed_ms=elapsed_ms,
    )


def _backing_source_check(ds: DataSourceConfig, backing: str) -> SourceCheck:
    """A SourceCheck reflecting spec 069 backing (no connectivity probe).

    ``strategy_hint`` → ok (LLM-fetch, no module needed); ``unbacked`` →
    unreachable with the canonical source-named message (fail-closed, FR2).
    """
    from research_framework.spec.source_backing import unbacked_message

    if backing == "strategy_hint":
        status: SourceStatus = "ok"
        detail = "strategy_hint: LLM-fetch guidance, no module required"
    else:
        status = "unreachable"
        detail = unbacked_message(ds.name)
    return SourceCheck(
        name=ds.name,
        role=_role_label(ds.required),
        type=_access_type_label((ds.access_method or "").strip()),
        status=status,
        detail=detail,
        checked_at=_utc_now_iso(),
        elapsed_ms=0,
    )


def check_all(spec: SpecConfig, vault_dir: Path) -> PreflightResult:
    from research_framework.spec.source_backing import (
        build_available_registry,
        source_is_backed,
    )

    started_wall = _utc_now_iso()
    registry = build_available_registry(vault_dir)
    sources: list[SourceCheck] = []
    for ds in spec.data_sources:
        # spec 069 FR2: backing is authoritative. A backed source still gets a
        # live connectivity probe; strategy_hint / unbacked short-circuit.
        backing = source_is_backed(ds, registry)
        if backing == "backed":
            sources.append(check_source(ds, vault_dir))
        else:
            sources.append(_backing_source_check(ds, backing))

    req_unreach = sum(
        1 for s in sources if s.role == "required" and s.status == "unreachable"
    )
    enrich_unreach = sum(
        1 for s in sources if s.role == "enrichment" and s.status == "unreachable"
    )
    any_degraded = any(s.status == "degraded" for s in sources)

    if req_unreach >= 1:
        overall: OverallStatus = "fail"
    elif enrich_unreach >= 1 or any_degraded:
        overall = "warn"
    else:
        overall = "pass"

    result = PreflightResult(
        generated_at=started_wall,
        framework_version=__version__,
        sources=sources,
        required_unreachable_count=req_unreach,
        enrichment_unreachable_count=enrich_unreach,
        overall_status=overall,
    )
    out_path = vault_dir / "_pipeline" / "preflight.json"
    result.to_json_path(out_path)
    return result
