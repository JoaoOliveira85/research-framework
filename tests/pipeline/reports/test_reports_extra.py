"""Optional [reports] extra tests (spec 040 T011)."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_reports_extra_lists_fpdf2_beside_budget() -> None:
    root = Path(__file__).resolve().parents[3]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    assert "budget" in extras
    assert "reports" in extras
    assert any("fpdf2" in entry for entry in extras["reports"])
    budget_idx = list(extras.keys()).index("budget")
    reports_idx = list(extras.keys()).index("reports")
    assert reports_idx == budget_idx + 1
