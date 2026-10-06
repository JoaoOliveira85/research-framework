"""Cost-safety gating: ack modes, --max-usd cap, cost provenance (spec 056 §3; T023–T026)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from research_framework.benchmark import gating, reporter, runner
from research_framework.benchmark import matrix as M

_CLI_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "benchmark_executors.py"


class _FakeStream:
    """Minimal stdin/stdout stand-in so we can force a (non-)TTY in-process."""

    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "benchmark_executors_under_test", _CLI_SCRIPT
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_headless_refuses_without_ack() -> None:
    """No TTY + no --yes + no env ⇒ refuse; the CLI never reaches dispatch (SC-003, T023)."""
    decision = gating.resolve_ack(
        yes=False, env_ack=None, stdin_isatty=False, stdout_isatty=False
    )
    assert decision.proceed is False
    assert decision.mode == "headless"


def test_headless_env_ack_proceeds() -> None:
    """RF_BENCHMARK_ACK=1 is the documented headless opt-in."""
    decision = gating.resolve_ack(
        yes=False, env_ack="1", stdin_isatty=False, stdout_isatty=False
    )
    assert decision.proceed is True
    assert decision.mode == "env"


def test_tty_requires_confirm() -> None:
    """Interactive TTY: 'n' refuses (no dispatch), 'y' proceeds (T024)."""
    refused = gating.resolve_ack(
        yes=False,
        env_ack=None,
        stdin_isatty=True,
        stdout_isatty=True,
        prompt_fn=lambda _msg: "n",
    )
    assert refused.proceed is False
    assert refused.mode == "tty"

    confirmed = gating.resolve_ack(
        yes=False,
        env_ack=None,
        stdin_isatty=True,
        stdout_isatty=True,
        prompt_fn=lambda _msg: "y",
    )
    assert confirmed.proceed is True
    assert confirmed.mode == "tty"


def test_yes_flag_bypasses_prompt() -> None:
    """--yes proceeds regardless of TTY state (and is recorded as such)."""
    decision = gating.resolve_ack(
        yes=True,
        env_ack=None,
        stdin_isatty=True,
        stdout_isatty=True,
        prompt_fn=lambda _msg: (_ for _ in ()).throw(
            AssertionError("prompted with --yes")
        ),
    )
    assert decision.proceed is True
    assert decision.mode == "yes"


def test_cost_cap_inclusive_semantics() -> None:
    """Equality is allowed; strict exceed stops (spec-033 parity)."""
    cap = gating.CostCap(0.05)
    assert cap.exceeded(0.05) is False  # inclusive
    assert cap.exceeded(0.0500001) is True
    assert gating.CostCap(None).exceeded(9999.0) is False  # no cap set


def test_max_usd_stops_with_partial_report(
    fixture_dir: Path, matrix_path: Path, manifest: dict, tmp_path: Path
) -> None:
    """A cap below the matrix total stops mid-sweep; reported cells are preserved (FR-007, T025)."""
    cells = M.expand_cells(M.load_matrix(matrix_path))
    run_dir = reporter.create_run_dir(tmp_path, reporter.run_id_now())
    report = runner.run_matrix(
        cells,
        fixture_dir=fixture_dir,
        run_dir=run_dir,
        manifest=manifest,
        matrix_path=matrix_path,
        dispatch_fn=runner.hermetic_dispatch,
        cost_cap=gating.CostCap(0.05),
        ack_mode="dry-run",
        max_usd=0.05,
    )
    reported = report["cells"]
    assert 0 < len(reported) < len(cells)  # partial
    assert (run_dir / "report.json").is_file()  # partial report still written
    spent = sum(c["cost_usd"] for c in reported if c.get("cost_usd") is not None)
    # Stops the first time cumulative strictly exceeds the cap.
    assert spent > 0.05


def test_cost_provenance_mapping() -> None:
    """Sidecar cost_source → report vocabulary, FR-013 'none' sentinel handling.

    agent_call writes ``cost_source: none`` + ``cost_usd: 0`` when it had NO signal
    and the estimator failed — that is NOT a real $0 and must report n/a, not be
    summed into spend (FR-013). ``estimated`` keeps its provenance; measured
    ``runtime``/``runtime_tokens`` (incl. ollama's true local $0) report ``sidecar``.
    """
    assert gating.cost_fields({"cost_usd": 0, "cost_source": "none"}) == (None, "n/a")
    assert gating.cost_fields({"cost_usd": 0.02, "cost_source": "estimated"}) == (
        0.02,
        "estimated",
    )
    assert gating.cost_fields({"cost_usd": 0.05, "cost_source": "runtime"}) == (
        0.05,
        "sidecar",
    )
    # ollama: a genuine measured $0 (local) — summed as real, not n/a.
    assert gating.cost_fields({"cost_usd": 0.0, "cost_source": "runtime"}) == (
        0.0,
        "sidecar",
    )
    assert gating.cost_fields({"cost_usd": 0.01, "cost_source": "runtime_tokens"}) == (
        0.01,
        "sidecar",
    )


def test_cost_na_when_sidecar_missing_cost(
    fixture_dir: Path, matrix_path: Path, manifest: dict, tmp_path: Path
) -> None:
    """No usable sidecar cost ⇒ (None, 'n/a') — never a fabricated $0 (FR-013, T026)."""
    assert gating.cost_fields(None) == (None, "n/a")
    assert gating.cost_fields({}) == (None, "n/a")
    assert gating.cost_fields({"cost_usd": None}) == (None, "n/a")
    assert gating.cost_fields({"cost_usd": 0.02}) == (0.02, "sidecar")

    # End-to-end: an ok cell whose dispatch carried no cost reports n/a, not 0.
    def costless(cell, *, fixture_dir, cell_dir):
        base = runner.hermetic_dispatch(
            cell, fixture_dir=fixture_dir, cell_dir=cell_dir
        )
        base.cost_usd = None
        base.cost_source = "n/a"
        base.sidecar = None
        return base

    cells = M.apply_scope(
        M.expand_cells(M.load_matrix(matrix_path)), tasks=["verifier"]
    )
    run_dir = reporter.create_run_dir(tmp_path, reporter.run_id_now())
    report = runner.run_matrix(
        cells,
        fixture_dir=fixture_dir,
        run_dir=run_dir,
        manifest=manifest,
        matrix_path=matrix_path,
        dispatch_fn=costless,
        ack_mode="dry-run",
    )
    assert all(
        c["cost_usd"] is None and c["cost_source"] == "n/a" for c in report["cells"]
    )


def test_cli_headless_refuses_without_ack(monkeypatch) -> None:
    """End-to-end: headless live `main()` exits 3 and never reaches dispatch (SC-003)."""
    cli = _load_cli()
    monkeypatch.delenv("RF_BENCHMARK_ACK", raising=False)
    monkeypatch.setattr(cli.sys, "stdin", _FakeStream(tty=False))
    monkeypatch.setattr(cli.sys, "stdout", _FakeStream(tty=False))

    def _boom_run(*_a, **_k):
        raise AssertionError("run_matrix reached despite headless refusal")

    def _boom_dir(*_a, **_k):
        raise AssertionError("create_run_dir reached despite headless refusal")

    monkeypatch.setattr(cli.runner, "run_matrix", _boom_run)
    monkeypatch.setattr(cli.reporter, "create_run_dir", _boom_dir)

    # Live path (no --dry-run), no --yes, no env, no TTY ⇒ refuse with exit 3.
    rc = cli.main(["--task", "scout", "--executor", "claude"])
    assert rc == 3
