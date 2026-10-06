"""Subprocess-contract tests for the _template module preflight reference (spec 038)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from research_framework.pipeline.source_bridge.preflight_types import PreflightResult

MODULE_DIR = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "research_framework"
    / "modules"
    / "_template"
)
PREFLIGHT = MODULE_DIR / "preflight.py"
MANIFEST = MODULE_DIR / "manifest.yaml"


def _run_preflight(sources: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PREFLIGHT), "preflight"],
        input=json.dumps(
            {
                "schema_version": "1.0",
                "sources": sources,
                "watermarks": {},
            }
        ),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_template_preflight_documents_probe_pattern() -> None:
    """Template keeps JSON subprocess contract; manifest documents optional blocks."""
    manifest_text = MANIFEST.read_text(encoding="utf-8")
    assert "authentication:" in manifest_text
    assert "failure_policy:" in manifest_text

    preflight_text = PREFLIGHT.read_text(encoding="utf-8")
    assert "PREFLIGHT_FAKE_ENV" in preflight_text

    proc = _run_preflight({"example_sources": [{"url": "https://example.com/item"}]})
    assert proc.returncode == 0, proc.stderr
    result = PreflightResult.from_json(json.loads(proc.stdout))
    assert result.verdict == "success"
