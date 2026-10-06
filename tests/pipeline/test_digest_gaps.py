"""Gap detector tests (spec 035 FR-008).

``fill_pct`` values are fractions, the scale the cycle quality report stores
(spec 017 ``cycle-quality-report.schema.json``: 0..1).
"""

from __future__ import annotations

from research_framework.pipeline.digest.ranker import detect_gaps


def test_gap_detection() -> None:
    categories = [
        {"name": "services", "target_count": 4},
        {"name": "flows", "target_count": 3},
        {"name": "concepts", "target_count": 5},
    ]
    first = {
        "coverage_snapshot": {
            "services": {"fill_pct": 0.5},
            "flows": {"fill_pct": 0.0},
            "concepts": {"fill_pct": 0.2},
        }
    }
    last = {
        "coverage_snapshot": {
            "services": {"fill_pct": 0.25},
            "flows": {"fill_pct": 0.0},
            "concepts": {"fill_pct": 0.4},
        }
    }
    gaps = detect_gaps(
        categories=categories, first_report=first, last_report=last, last_cycle=3
    )
    kinds = {g.category: g.kind for g in gaps}
    assert kinds["services"] == "regressed"
    assert kinds["flows"] == "stagnant"
    assert "concepts" not in kinds

    healthy = detect_gaps(
        categories=categories,
        first_report={
            "coverage_snapshot": {
                "services": {"fill_pct": 0.8},
                "flows": {"fill_pct": 1.0},
                "concepts": {"fill_pct": 1.0},
            }
        },
        last_report={
            "coverage_snapshot": {
                "services": {"fill_pct": 0.9},
                "flows": {"fill_pct": 1.0},
                "concepts": {"fill_pct": 1.0},
            }
        },
        last_cycle=2,
    )
    assert healthy == []
