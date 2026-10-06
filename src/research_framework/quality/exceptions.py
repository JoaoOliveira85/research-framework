"""Harness failure sentinel exceptions (spec 022, regression-report contract § 5)."""

from __future__ import annotations

from dataclasses import dataclass


class HarnessFailure(Exception):
    """Base for harness failures that map to exit code 1 or 2."""

    category: str = "harness"

    def format_stderr_line(self, fixture: str) -> str:
        raise NotImplementedError


@dataclass
class RegressionFailure(HarnessFailure):
    """At least one metric crossed the fail threshold (exit 1)."""

    metric: str
    delta_pct: float | str
    baseline_value: float
    current_value: float
    _fixture: str
    category: str = "regression"

    def format_stderr_line(self, fixture: str) -> str:
        fx = self._fixture or fixture
        return (
            f"{fx}.{self.metric} dropped {self.delta_pct}% "
            f"(baseline={self.baseline_value}, current={self.current_value}); "
            f"see _pipeline/quality/regression-report.json"
        )


class BaselineMissingError(HarnessFailure):
    category = "baseline-missing"

    def format_stderr_line(self, fixture: str) -> str:
        return (
            f"baseline missing for fixture {fixture}; run `./build.sh --quality` "
            f"locally on the ship branch and commit the generated baseline"
        )


class BaselineStaleError(HarnessFailure):
    category = "baseline-stale"

    def __init__(
        self,
        *,
        baseline_hash: str,
        current_hash: str,
    ) -> None:
        self.baseline_hash = baseline_hash
        self.current_hash = current_hash
        super().__init__()

    def format_stderr_line(self, fixture: str) -> str:
        return (
            f"baseline stale for fixture {fixture}; coverage-targets-hash mismatch "
            f"(baseline={self.baseline_hash}, current={self.current_hash}); "
            f"re-baseline required via `./vault quality-baseline-update {fixture}`"
        )


class FixtureNotInitialisedError(HarnessFailure):
    category = "fixture-not-initialised"

    def format_stderr_line(self, fixture: str) -> str:
        return (
            f"fixture {fixture} not initialised — run "
            f"`./vault quality-fixture-init {fixture}` first"
        )


class CycleRunnerCrashError(HarnessFailure):
    category = "cycle-runner-crash"

    def __init__(self, *, cycle_number: int) -> None:
        self.cycle_number = cycle_number
        super().__init__()

    def format_stderr_line(self, fixture: str) -> str:
        return (
            f"cycle runner crashed on fixture {fixture} cycle {self.cycle_number}; "
            f"see _pipeline/quality/{fixture}/logs/"
        )


class DeterminismViolationError(HarnessFailure):
    category = "determinism-violation"

    def format_stderr_line(self, fixture: str) -> str:
        return (
            f"fixture {fixture} produced non-deterministic output across two "
            f"back-to-back runs; diff at _pipeline/quality/{fixture}.current-diff.txt"
        )
