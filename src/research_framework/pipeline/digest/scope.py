"""Date range + in-range cycle enumeration for digest (spec 035 FR-010/011)."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

_CYCLE_DIR_RE = re.compile(r"^cycle-(\d{3})$")
_QUALITY_REPORT_RE = re.compile(r"^cycle-(\d{3})-quality-report\.json$")


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date


@dataclass(frozen=True)
class CycleScope:
    number: int
    cycle_dir: Path
    quality_report_path: Path
    finished_at: datetime
    report_path: Path | None


@dataclass
class DigestScope:
    vault_dir: Path
    date_range: DateRange
    cycles: list[CycleScope] = field(default_factory=list)
    git_base: str = "unknown"
    git_head: str = "unknown"
    vault_identity: str = ""
    warnings: list[str] = field(default_factory=list)


def parse_iso_date(value: str) -> date:
    text = value.strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    return date.fromisoformat(text)


def resolve_last_period(flag: str, *, today: date | None = None) -> DateRange:
    # UTC, the clock `_cycle_in_range` buckets cycles by.
    anchor = today or datetime.now(UTC).date()
    if flag == "last-week":
        return DateRange(start=anchor - timedelta(days=7), end=anchor)
    if flag == "last-month":
        return DateRange(start=anchor - timedelta(days=30), end=anchor)
    if flag == "last-quarter":
        return DateRange(start=anchor - timedelta(days=90), end=anchor)
    raise ValueError(f"unknown period flag: {flag}")


def _parse_report_timestamp(data: dict[str, object]) -> datetime | None:
    for key in ("cycle_finished_at", "generated_at", "cycle_started_at"):
        raw = data.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
    return None


def _cycle_in_range(finished_at: datetime, date_range: DateRange) -> bool:
    day = finished_at.astimezone(UTC).date()
    return date_range.start <= day <= date_range.end


def _load_quality_report(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def enumerate_cycles(vault_dir: Path, date_range: DateRange) -> list[CycleScope]:
    cycles_dir = vault_dir / "_pipeline" / "cycles"
    if not cycles_dir.is_dir():
        return []

    by_number: dict[int, CycleScope] = {}
    for entry in sorted(cycles_dir.iterdir(), key=lambda p: p.name):
        match = _QUALITY_REPORT_RE.match(entry.name)
        if not match:
            if _CYCLE_DIR_RE.match(entry.name):
                continue
            continue
        number = int(match.group(1))
        data = _load_quality_report(entry)
        if data is None:
            continue
        finished = _parse_report_timestamp(data)
        if finished is None or not _cycle_in_range(finished, date_range):
            continue
        cycle_dir = cycles_dir / f"cycle-{number:03d}"
        report_path = cycles_dir / f"cycle-{number:03d}-report.md"
        by_number[number] = CycleScope(
            number=number,
            cycle_dir=cycle_dir,
            quality_report_path=entry,
            finished_at=finished,
            report_path=report_path if report_path.is_file() else None,
        )
    return [by_number[n] for n in sorted(by_number)]


def earliest_cycle_date(vault_dir: Path) -> date | None:
    cycles_dir = vault_dir / "_pipeline" / "cycles"
    if not cycles_dir.is_dir():
        return None
    earliest: date | None = None
    for entry in cycles_dir.iterdir():
        match = _QUALITY_REPORT_RE.match(entry.name)
        if not match:
            continue
        data = _load_quality_report(entry)
        if data is None:
            continue
        finished = _parse_report_timestamp(data)
        if finished is None:
            continue
        day = finished.astimezone(UTC).date()
        if earliest is None or day < earliest:
            earliest = day
    return earliest


def clamp_since(vault_dir: Path, since: date) -> date:
    earliest = earliest_cycle_date(vault_dir)
    if earliest is None:
        return since
    return max(since, earliest)


def _git_rev_range(vault_dir: Path, date_range: DateRange) -> tuple[str, str]:
    if not (vault_dir / ".git").exists():
        return "unknown", "unknown"
    since_iso = date_range.start.isoformat()
    until_iso = (date_range.end + timedelta(days=1)).isoformat()
    try:
        base = subprocess.run(
            [
                "git",
                "-C",
                str(vault_dir),
                "rev-list",
                "-1",
                "--before",
                since_iso,
                "HEAD",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        ).stdout.strip()
        head = subprocess.run(
            [
                "git",
                "-C",
                str(vault_dir),
                "log",
                "-1",
                f"--until={until_iso}",
                "--format=%H",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "unknown", "unknown"
    return base or "unknown", head or "unknown"


def _git_commit_date(vault_dir: Path, sha: str) -> datetime | None:
    if sha in {"", "unknown"} or not (vault_dir / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(vault_dir), "show", "-s", "--format=%cI", sha],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        ).stdout.strip()
        if not out:
            return None
        return datetime.fromisoformat(out.replace("Z", "+00:00"))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def resolve_ship_sha(vault_dir: Path, cycle: CycleScope, head_sha: str) -> str:
    del vault_dir, cycle
    if head_sha not in {"", "unknown"}:
        return head_sha[:12]
    return "unknown"


def build_scope(vault_dir: Path, date_range: DateRange) -> DigestScope:
    identity = vault_dir.name
    spec_path = vault_dir / "research.spec.md"
    if spec_path.is_file():
        try:
            for line in spec_path.read_text(encoding="utf-8").splitlines()[:20]:
                if line.startswith("name:"):
                    identity = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass
    git_base, git_head = _git_rev_range(vault_dir, date_range)
    return DigestScope(
        vault_dir=vault_dir,
        date_range=date_range,
        cycles=enumerate_cycles(vault_dir, date_range),
        git_base=git_base,
        git_head=git_head,
        vault_identity=identity,
    )


__all__ = [
    "CycleScope",
    "DateRange",
    "DigestScope",
    "build_scope",
    "clamp_since",
    "earliest_cycle_date",
    "enumerate_cycles",
    "parse_iso_date",
    "resolve_last_period",
    "resolve_ship_sha",
    "_git_commit_date",
]
