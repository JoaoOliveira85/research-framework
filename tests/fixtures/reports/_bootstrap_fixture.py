"""Bootstrap committed digest fixture data (spec 035 T004)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _write(rel: str, content: str) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    _write(
        "research.spec.md",
        """---
name: digest-fixture-vault
owner: research-framework-tests
scope:
  domain: Minimal vault for spec-035 cross-cycle digest harness.
note_types:
  - name: concept
    folder: "03 - Concepts"
  - name: service
    folder: "01 - Services"
  - name: flow
    folder: "02 - Flows"
data_sources:
  - name: youtube-rss
    type: rss
    priority: 2
  - name: payment-repo
    type: code
    priority: 1
coverage_targets:
  categories:
    - name: concepts
      note_type: concept
      target_count: 5
    - name: services
      note_type: service
      target_count: 4
    - name: flows
      note_type: flow
      target_count: 3
---
""",
    )
    _write(
        "coverage-targets.json",
        json.dumps(
            {
                "last_updated": "2026-06-01T10:00:00Z",
                "cycle_number": 3,
                "categories": [
                    {
                        "name": "concepts",
                        "note_type": "concept",
                        "target_count": 5,
                        "met_count": 2,
                    },
                    {
                        "name": "services",
                        "note_type": "service",
                        "target_count": 4,
                        "met_count": 1,
                    },
                    {
                        "name": "flows",
                        "note_type": "flow",
                        "target_count": 3,
                        "met_count": 0,
                    },
                ],
            },
            indent=2,
        )
        + "\n",
    )
    _write(
        "_pipeline/source-incidents.md",
        "# Source incidents\n\n- 2026-06-03T12:00:00Z — `youtube-rss` degraded: feed timeout\n",
    )

    notes = {
        "data_vault/03 - Concepts/Alpha Signal.md": """---
title: Alpha Signal
type: concept
summary: Top-ranked digest signal with strong inbound citations and fresh yield.
sources_consulted:
  - youtube-rss
lifecycle:
  created_at_cycle: 3
  first_written: "2026-06-06T14:00:00Z"
related:
  - Baseline Concept
---
## Overview
Alpha Signal receives inbound links from peers.
## Related
- [[Baseline Concept]]
""",
        "data_vault/03 - Concepts/Baseline Concept.md": """---
title: Baseline Concept
type: concept
summary: Average concept note from cycle 1.
lifecycle:
  created_at_cycle: 1
  first_written: "2026-06-01T10:30:00Z"
related:
  - Alpha Signal
---
## Overview
Links to [[Alpha Signal]].
""",
        "data_vault/03 - Concepts/Peer Note B.md": """---
title: Peer Note B
type: concept
summary: Second peer linking to Alpha Signal.
lifecycle:
  created_at_cycle: 2
  first_written: "2026-06-03T11:00:00Z"
related:
  - Alpha Signal
---
## Overview
Also links [[Alpha Signal]].
""",
        "data_vault/03 - Concepts/Peer Note C.md": """---
title: Peer Note C
type: concept
summary: Third peer linking to Alpha Signal.
lifecycle:
  created_at_cycle: 2
  first_written: "2026-06-03T11:15:00Z"
related:
  - Alpha Signal
---
## Overview
Third inbound link to [[Alpha Signal]].
""",
        "data_vault/01 - Services/Payment Gateway.md": """---
title: Payment Gateway
type: service
summary: Service note written in cycle 1.
sources_consulted:
  - payment-repo
lifecycle:
  created_at_cycle: 1
  first_written: "2026-06-01T11:00:00Z"
---
## Overview
Initial service coverage.
""",
        "data_vault/02 - Flows/Checkout Flow.md": """---
title: Checkout Flow
type: flow
summary: Flow note from cycle 3.
lifecycle:
  created_at_cycle: 3
  first_written: "2026-06-06T15:00:00Z"
---
## Overview
New flow documentation.
""",
    }
    for rel, body in notes.items():
        _write(rel, body)

    reports = {
        1: {
            "generated_at": "2026-06-01T12:00:00Z",
            "cycle_finished_at": "2026-06-01T12:00:00Z",
            "coverage_snapshot": {
                "concepts": {"target": 5, "met": 1, "fill_pct": 0.2},
                "services": {"target": 4, "met": 2, "fill_pct": 0.5},
                "flows": {"target": 3, "met": 0, "fill_pct": 0.0},
            },
        },
        2: {
            "generated_at": "2026-06-03T12:00:00Z",
            "cycle_finished_at": "2026-06-03T12:00:00Z",
            "coverage_snapshot": {
                "concepts": {"target": 5, "met": 2, "fill_pct": 0.4},
                "services": {"target": 4, "met": 2, "fill_pct": 0.5},
                "flows": {"target": 3, "met": 0, "fill_pct": 0.0},
            },
        },
        3: {
            "generated_at": "2026-06-06T12:00:00Z",
            "cycle_finished_at": "2026-06-06T12:00:00Z",
            "coverage_snapshot": {
                "concepts": {"target": 5, "met": 2, "fill_pct": 0.4},
                "services": {"target": 4, "met": 1, "fill_pct": 0.25},
                "flows": {"target": 3, "met": 0, "fill_pct": 0.0},
            },
        },
    }
    for num, payload in reports.items():
        body = {
            "schema_version": "1",
            "cycle_number": num,
            "exit_status": "success",
            **payload,
        }
        _write(
            f"_pipeline/cycles/cycle-{num:03d}-quality-report.json",
            json.dumps(body, indent=2) + "\n",
        )
        (ROOT / f"_pipeline/cycles/cycle-{num:03d}").mkdir(parents=True, exist_ok=True)

    _write(
        "_pipeline/cycles/cycle-001-report.md",
        "# Cycle 1 — opened services coverage\n",
    )
    _write(
        "_pipeline/cycles/cycle-002-report.md",
        "# Cycle 2 — peer concepts linked\n",
    )

    sidecars = {
        "cycle-001/agent-calls/scout.json": {
            "agent_kind": "scout",
            "cost_usd": 0.05,
            "cycle": 1,
        },
        "cycle-001/agent-calls/research.json": {
            "agent_kind": "research",
            "cost_usd": 0.10,
            "cycle": 1,
        },
        "cycle-002/agent-calls/scout.json": {
            "agent_kind": "scout",
            "cost_usd": 0.08,
            "cycle": 2,
        },
        "cycle-002/agent-calls/note_writer-batch-1.json": {
            "agent_kind": "note_writer",
            "cost_usd": 0.12,
            "cycle": 2,
        },
        "cycle-003/agent-calls/scout.json": {
            "agent_kind": "scout",
            "cost_usd": 0.10,
            "cycle": 3,
        },
        "cycle-003/agent-calls/research.json": {
            "agent_kind": "research",
            "cost_usd": 0.15,
            "cycle": 3,
        },
    }
    for rel, payload in sidecars.items():
        body = {"schema_version": "1.1", "status": "ok", **payload}
        _write(f"_pipeline/cycles/{rel}", json.dumps(body, indent=2) + "\n")

    db = ROOT / "_pipeline/sources.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE sources (
            name TEXT PRIMARY KEY, type TEXT, role TEXT, url TEXT,
            first_seen_cycle INTEGER, locked INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active', consecutive_empty_cycles INTEGER DEFAULT 0
        );
        CREATE TABLE source_cycles (
            name TEXT, cycle INTEGER,
            notes_generated INTEGER DEFAULT 0,
            topics_covered INTEGER DEFAULT 0,
            tags_generated INTEGER DEFAULT 0,
            notes_referencing INTEGER DEFAULT 0,
            PRIMARY KEY (name, cycle)
        );
        """
    )
    conn.execute(
        "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
        (
            "youtube-rss",
            "rss",
            "domain",
            "https://youtube.example/rss",
            1,
            1,
            "active",
            0,
        ),
    )
    conn.execute(
        "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
        ("payment-repo", "code", "behaviour", "file:///payment", 1, 1, "active", 0),
    )
    rows = [
        ("youtube-rss", 1, 2, 1, 0, 1),
        ("youtube-rss", 2, 1, 1, 0, 2),
        ("youtube-rss", 3, 0, 0, 0, 4),
        ("payment-repo", 1, 1, 1, 0, 0),
        ("payment-repo", 2, 0, 0, 0, 0),
        ("payment-repo", 3, 0, 0, 0, 0),
    ]
    conn.executemany("INSERT INTO source_cycles VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    print(f"bootstrapped {ROOT}")


if __name__ == "__main__":
    main()
