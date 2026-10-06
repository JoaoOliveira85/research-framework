"""Guard: the benchmark harness is an opt-in eval surface, wired into NO CI gate
and imported by NO pipeline hot path (spec 056 FR-001 / SC-007 / SC-010; T035)."""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[3]


def test_benchmark_script_not_in_build_or_release() -> None:
    """No CI gate (build.sh or any workflow) may invoke the benchmark (FR-001)."""
    gates = [_REPO / "build.sh", *(_REPO / ".github" / "workflows").glob("*.yml")]
    offenders: list[str] = []
    for gate in gates:
        text = gate.read_text(encoding="utf-8")
        if "benchmark_executors" in text or "research_framework.benchmark" in text:
            offenders.append(gate.name)
    assert not offenders, "benchmark wired into a CI gate: " + ", ".join(offenders)


def test_pipeline_does_not_import_benchmark_package() -> None:
    """No src module OUTSIDE benchmark/ may import the benchmark package (SC-010)."""
    src = _REPO / "src" / "research_framework"
    offenders: list[str] = []
    for path in src.rglob("*.py"):
        if "benchmark" in path.parts:  # the package itself is allowed
            continue
        text = path.read_text(encoding="utf-8")
        if "research_framework.benchmark" in text or "from .benchmark" in text:
            offenders.append(str(path.relative_to(_REPO)))
    assert not offenders, "benchmark imported on a pipeline path: " + ", ".join(
        offenders
    )


def test_llm_dispatch_allowlist_remains_empty() -> None:
    """The benchmark is NOT an allowlisted in-src dispatch exception (SC-007)."""
    allowlist = _REPO / "tests" / "_helpers" / "llm_dispatch_allowlist.yaml"
    parsed = yaml.safe_load(allowlist.read_text(encoding="utf-8"))
    assert not parsed, "llm_dispatch_allowlist.yaml must stay empty"


def test_pipeline_scan_is_not_vacuous() -> None:
    """Fail closed (#278): `test_pipeline_does_not_import_benchmark_package`
    reports zero offenders when `src.rglob("*.py")` finds nothing, which is
    indistinguishable from "scanned every module, none import benchmark"."""
    src = _REPO / "src" / "research_framework"
    scanned = [p for p in src.rglob("*.py") if "benchmark" not in p.parts]
    assert len(scanned) >= 50, (
        f"only {len(scanned)} non-benchmark .py file(s) found under {src} — "
        "expected at least 50. A scan that finds nothing to check is not "
        "the same thing as a scan that found nothing wrong."
    )
