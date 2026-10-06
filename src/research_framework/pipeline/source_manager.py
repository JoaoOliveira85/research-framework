"""Manage _pipeline/sources.db — adaptive source discovery and quality tracking."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import yaml

from research_framework.pipeline.settings import SettingsError, load_vault_settings

from ..spec.schema import DataSourceConfig, SpecConfig

_LOG = logging.getLogger(__name__)

DB_FILENAME = "_pipeline/sources.db"

_CREATE_SOURCES = """
CREATE TABLE IF NOT EXISTS sources (
    name                     TEXT PRIMARY KEY,
    type                     TEXT,
    role                     TEXT,
    url                      TEXT,
    first_seen_cycle         INTEGER,
    locked                   INTEGER DEFAULT 0,
    status                   TEXT DEFAULT 'active',
    consecutive_empty_cycles INTEGER DEFAULT 0
);
"""

_CREATE_SOURCE_CYCLES = """
CREATE TABLE IF NOT EXISTS source_cycles (
    name               TEXT REFERENCES sources(name),
    cycle              INTEGER,
    notes_generated    INTEGER DEFAULT 0,
    topics_covered     INTEGER DEFAULT 0,
    tags_generated     INTEGER DEFAULT 0,
    notes_referencing  INTEGER DEFAULT 0,
    PRIMARY KEY (name, cycle)
);
"""


def _db_path(vault_dir: Path) -> Path:
    return vault_dir / "_pipeline" / "sources.db"


def _connect(vault_dir: Path) -> sqlite3.Connection:
    """Open/create the DB with WAL mode for safe concurrent reads."""
    db = _db_path(vault_dir)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_CREATE_SOURCES)
    conn.execute(_CREATE_SOURCE_CYCLES)
    conn.commit()
    return conn


def seed(vault_dir: Path, spec: SpecConfig) -> None:
    """Create sources.db and insert spec.data_sources with locked=1.

    Idempotent: safe to call on an existing vault (skips existing rows).
    Called by scaffold.py at generation time.
    """
    (vault_dir / "_pipeline").mkdir(parents=True, exist_ok=True)
    conn = _connect(vault_dir)
    with conn:
        for ds in spec.data_sources:
            # Determine url: check if any repo has a url, else use empty string
            url = ""
            if ds.repos:
                url = ds.repos[0].url or ""
            conn.execute(
                """
                INSERT OR IGNORE INTO sources(name, type, role, url, locked, status)
                VALUES (?, ?, ?, ?, 1, 'active')
                """,
                (ds.name, ds.type, ds.role, url),
            )
    conn.close()


def append_discovered(vault_dir: Path, new_sources: list[dict]) -> None:
    """Insert newly discovered sources with locked=0. Skip duplicates by name.

    Each dict should have at minimum: name, type, role, url.
    """
    db = _db_path(vault_dir)
    if not db.exists():
        return
    conn = _connect(vault_dir)
    with conn:
        for src in new_sources:
            conn.execute(
                """
                INSERT OR IGNORE INTO sources(name, type, role, url, locked, status)
                VALUES (?, ?, ?, ?, 0, 'active')
                """,
                (
                    src.get("name", ""),
                    src.get("type", ""),
                    src.get("role", ""),
                    src.get("url", ""),
                ),
            )
    conn.close()


def _decay_threshold(vault_dir: Path) -> int:
    """Read decay_after_n_cycles from vault settings, default 3."""
    pipeline_path = vault_dir / "_pipeline" / "settings.yaml"
    if pipeline_path.is_file():
        # Holdout: _pipeline/settings.yaml is not the B7 vault-root contract;
        # keep legacy path for per-pipeline overrides until a follow-up unifies paths.
        try:
            data = yaml.safe_load(pipeline_path.read_text(encoding="utf-8")) or {}
            stages = data.get("stages") or {}
            sm = stages.get("source_manager") or {}
            val = sm.get("decay_after_n_cycles")
            if val is not None:
                return int(val)
        except Exception:
            pass
    try:
        val = (
            load_vault_settings(vault_dir)
            .stage("source_manager")
            .extras.get("decay_after_n_cycles")
        )
        if val is not None:
            return int(val)
    except (SettingsError, TypeError, ValueError):
        pass
    return 3


def normalize_source_url(url: str | None) -> str:
    """Canonicalize a URL for attribution **matching** (029 FR-003 / contract §1).

    Lowercases scheme + host, strips a single trailing ``/`` from the path,
    drops the ``#fragment``, and **preserves the query string** (many feeds
    disambiguate by ``?q=`` / ``?v=``). A non-URL input (a bare source name) is
    returned stripped + lowercased so the name-fallback works uniformly. Never
    hits the network and never re-orders/strips query params.
    """
    if not url:
        return ""
    raw = url.strip()
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        # Bare name / non-URL — lowercase + strip only.
        return raw.lower()
    host = (parts.hostname or "").lower()
    if ":" in host:
        # IPv6 literal — urlsplit() strips the surrounding brackets; re-add them
        # so the reconstructed netloc stays well-formed.
        host = f"[{host}]"
    netloc = host
    if parts.port is not None:
        netloc = f"{host}:{parts.port}"
    if parts.username is not None:
        userinfo = parts.username
        if parts.password is not None:
            userinfo = f"{userinfo}:{parts.password}"
        netloc = f"{userinfo}@{netloc}"
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))


def _note_cites_source(frontmatter: dict, source_name: str, source_url: str) -> bool:
    """Does a note's frontmatter cite this source? (029 FR-003 / contract §2).

    Normalized-URL match **OR** raw source-name substring fallback (Q3). Shared
    by ``record_cycle`` (per-cycle) and ``_count_notes_referencing`` (all-time)
    so the two metrics can never diverge on matching semantics. Malformed
    entries are skipped, never raised on (Edge Cases).
    """
    sources = frontmatter.get("source_urls") or []
    if not isinstance(sources, list):
        sources = [sources]
    n_url = normalize_source_url(source_url)
    for entry in sources:
        if entry is None:
            continue
        entry_str = str(entry)
        if n_url and n_url in normalize_source_url(entry_str):
            return True
        if source_name and source_name in entry_str:
            return True
    return False


def _read_frontmatter_lenient(md_file: Path) -> dict | None:
    """Parse a note's YAML frontmatter, returning ``None`` on any problem.

    Holdout from the spec-025 B4 canonical parser: the attribution scan must
    **skip** malformed notes (the canonical parser raises ``FrontmatterParseError``
    on bad YAML). A single bad note must never abort metrics.
    """
    try:
        text = md_file.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    # Find the closing fence on its own line (`\n---`) rather than the next
    # `---` anywhere, so a `---` embedded inside a YAML value can't truncate the
    # frontmatter mid-parse.
    end = text.find("\n---", 3)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        _LOG.debug("[sources] skipping note with malformed frontmatter: %s", md_file)
        return None
    return fm if isinstance(fm, dict) else None


def _resolve_note_frontmatter(vault_dir: Path, note_name: str) -> dict | None:
    """Resolve a ``notes_created`` entry (bare filename or vault-relative path)
    to its frontmatter, mirroring ``coverage.assign_categories`` resolution."""
    data_vault = vault_dir / "data_vault"
    if not data_vault.exists():
        return None
    basename = Path(str(note_name)).name
    matches = list(data_vault.rglob(basename))
    if not matches:
        return None
    return _read_frontmatter_lenient(matches[0])


def _count_notes_referencing(vault_dir: Path, source_name: str, source_url: str) -> int:
    """Count distinct notes in data_vault/ whose frontmatter cites this source
    (all-time metric). Routes through the shared :func:`_note_cites_source`."""
    data_vault = vault_dir / "data_vault"
    if not data_vault.exists():
        return 0
    count = 0
    for md_file in data_vault.rglob("*.md"):
        fm = _read_frontmatter_lenient(md_file)
        if fm is None:
            continue
        if _note_cites_source(fm, source_name, source_url):
            count += 1
    return count


def record_cycle(
    vault_dir: Path,
    cycle_num: int,
    research_report: dict,
    notes_dir: Path | None = None,
) -> None:
    """Update source quality metrics after a cycle completes."""
    db = _db_path(vault_dir)
    if not db.exists():
        return

    # Step 1: append any newly discovered sources
    discovered = research_report.get("discovered_sources", []) or []
    if discovered:
        append_discovered(vault_dir, discovered)

    notes_created = research_report.get("notes_created", []) or []
    threshold = _decay_threshold(vault_dir)

    conn = _connect(vault_dir)
    try:
        with conn:
            # Fetch all active sources
            rows = conn.execute(
                "SELECT name, url, locked FROM sources WHERE status='active'"
            ).fetchall()

            for row in rows:
                name = row["name"]
                url = row["url"] or ""

                # Step 2: count notes_generated for this source by reading each
                # newly-created note's frontmatter source_urls (029 FR-002) —
                # NOT by substring-matching the URL/name against file paths.
                # Per-cycle, scoped to this cycle's notes_created.
                notes_generated = 0
                for note_name in notes_created:
                    fm = _resolve_note_frontmatter(vault_dir, note_name)
                    if fm is None:
                        continue
                    if _note_cites_source(fm, name, url):
                        notes_generated += 1

                # Step 3a: count notes_referencing via frontmatter scan
                if notes_dir is not None:
                    notes_referencing = _count_notes_referencing(vault_dir, name, url)
                else:
                    notes_referencing = 0

                # Step 3: upsert source_cycles row
                conn.execute(
                    """
                    INSERT INTO source_cycles(name, cycle, notes_generated, notes_referencing)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(name, cycle) DO UPDATE SET
                        notes_generated = excluded.notes_generated,
                        notes_referencing = excluded.notes_referencing
                    """,
                    (name, cycle_num, notes_generated, notes_referencing),
                )

                # Step 4: update consecutive_empty_cycles
                if notes_generated == 0:
                    conn.execute(
                        "UPDATE sources SET consecutive_empty_cycles = consecutive_empty_cycles + 1 WHERE name=?",
                        (name,),
                    )
                else:
                    conn.execute(
                        "UPDATE sources SET consecutive_empty_cycles = 0 WHERE name=?",
                        (name,),
                    )
                    # FR-007: a previously-degraded source that produces citations
                    # again recovers — append (never rewrite) a resolved line.
                    if _has_unresolved_incident(vault_dir, name):
                        mark_resolved(name, vault_dir)

            # Step 5: archive unlocked sources exceeding decay threshold
            conn.execute(
                """
                UPDATE sources SET status='archived'
                WHERE locked=0
                  AND status='active'
                  AND consecutive_empty_cycles >= ?
                """,
                (threshold,),
            )
    finally:
        conn.close()


def active_sources(vault_dir: Path) -> list[dict]:
    """Return all status='active' rows as dicts."""
    db = _db_path(vault_dir)
    if not db.exists():
        return []
    conn = _connect(vault_dir)
    try:
        rows = conn.execute("SELECT * FROM sources WHERE status='active'").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def merge_into_prompt_context(
    spec: SpecConfig, vault_dir: Path
) -> list[DataSourceConfig]:
    """Combine spec.data_sources (priority order, first) with active discovered
    sources (locked=0, low priority, appended after spec sources).

    Returns a unified list for scout prompt rendering.
    If sources.db doesn't exist, returns spec.data_sources unchanged.
    """
    db = _db_path(vault_dir)
    if not db.exists():
        return list(spec.data_sources)

    conn = _connect(vault_dir)
    try:
        discovered_rows = conn.execute(
            "SELECT name, type, role, url FROM sources WHERE status='active' AND locked=0"
        ).fetchall()
    finally:
        conn.close()

    spec_names = {ds.name for ds in spec.data_sources}
    extra: list[DataSourceConfig] = []
    for row in discovered_rows:
        if row["name"] not in spec_names:
            ds = DataSourceConfig(
                name=row["name"],
                type=row["type"] or "",
                role=row["role"] or "domain",
                priority=9,  # low priority — discovered, not declared
            )
            extra.append(ds)

    return list(spec.data_sources) + extra


def _incidents_path(vault_dir: Path) -> Path:
    return vault_dir / "_pipeline" / "source-incidents.md"


def _append_incident_line(vault_dir: Path, line: str) -> None:
    """Append one incident line, creating the header on first write (FR-006)."""
    pipeline_dir = vault_dir / "_pipeline"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    path = _incidents_path(vault_dir)
    if not path.exists():
        path.write_text("# Source incidents\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def mark_degraded(name: str, reason: str, vault_dir: Path) -> None:
    """Append a degraded incident to `_pipeline/source-incidents.md` (append-only)."""
    ts = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    safe_reason = " ".join((reason or "").split())
    _append_incident_line(vault_dir, f"- {ts} — `{name}` degraded: {safe_reason}\n")


def mark_resolved(name: str, vault_dir: Path) -> None:
    """Append a `resolved` line for a recovered source (FR-007, append-only).

    Never deletes/rewrites the prior `degraded` line — current state is the most
    recent line per source (contract §3).
    """
    ts = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    _append_incident_line(vault_dir, f"- {ts} — `{name}` resolved\n")


def _has_unresolved_incident(vault_dir: Path, name: str) -> bool:
    """True iff the most recent incident line for ``name`` is a ``degraded`` line.

    Drives the FR-007 recovery wiring: a source whose last state is degraded and
    which now produces citations gets a single appended ``resolved`` line.
    """
    path = _incidents_path(vault_dir)
    if not path.exists():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    needle = f"`{name}`"
    for line in reversed(lines):
        if needle not in line:
            continue
        if "degraded" in line:
            return True
        if "resolved" in line:
            return False
    return False


def source_quality_summary(vault_dir: Path) -> list[dict[str, Any]]:
    """Aggregate per-source metrics across all cycles.

    Returns list of dicts with keys:
      name, type, role, url, locked, status,
      total_notes_generated, total_topics_covered, total_tags_generated,
      peak_notes_referencing, cycles_active, last_useful_cycle

    If sources.db doesn't exist, returns [].
    """
    db = _db_path(vault_dir)
    if not db.exists():
        return []

    conn = _connect(vault_dir)
    try:
        rows = conn.execute("""
            SELECT
                s.name, s.type, s.role, s.url, s.locked, s.status,
                COALESCE(SUM(sc.notes_generated), 0)   AS total_notes_generated,
                COALESCE(SUM(sc.topics_covered), 0)    AS total_topics_covered,
                COALESCE(SUM(sc.tags_generated), 0)    AS total_tags_generated,
                COALESCE(MAX(sc.notes_referencing), 0) AS peak_notes_referencing,
                COUNT(sc.cycle)                         AS cycles_active,
                MAX(CASE WHEN sc.notes_generated > 0 THEN sc.cycle ELSE NULL END) AS last_useful_cycle
            FROM sources s
            LEFT JOIN source_cycles sc ON sc.name = s.name
            GROUP BY s.name
            ORDER BY s.name
            """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
