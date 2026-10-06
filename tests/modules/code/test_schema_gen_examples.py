"""Code module few-shot examples."""

from __future__ import annotations

from pathlib import Path


def test_few_shot_md_non_empty() -> None:
    path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "research_framework"
        / "modules"
        / "code"
        / "few-shot.md"
    )
    text = path.read_text(encoding="utf-8")
    assert len(text.strip()) > 20
