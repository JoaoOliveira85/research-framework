"""Spec 063 US5 (T021) — Q4 auto-run at clean exit + shim exposure.

- The orchestrator records the scorecard at a clean finalise without changing the
  run's own 0/1/2 exit code (the acceptance verdict is a separate signal).
- ``regenerate-shim`` re-renders an existing vault's shim to expose ``acceptance``.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.pipeline import orchestrator


def test_autorun_writes_scorecard(clean_vault):
    orchestrator._autorun_acceptance(clean_vault)
    acc = clean_vault / "_pipeline" / "acceptance"
    assert list(acc.glob("report-*.json")), "expected a scorecard JSON"
    assert list(acc.glob("REPORT-*.md")), "expected a scorecard markdown"


def test_autorun_never_raises_on_broken_vault(tmp_path):
    # No data_vault, no spec — must degrade silently, never raise.
    (tmp_path / "_pipeline").mkdir()
    orchestrator._autorun_acceptance(tmp_path)  # no exception == pass


def test_autorun_does_not_alter_exit_code(clean_vault, monkeypatch):
    """The hook fires inside _finalise(rc=0); the returned rc is unchanged even
    if the snapshot it grades would itself FAIL gates."""

    def _fake_build(vault, *a, **k):
        # A scorecard whose own exit_code is 1 (FAIL) must NOT leak into the run.
        return {
            "overall": {
                "status": "FAIL",
                "exit_code": 1,
                "fail_count": 3,
                "warn_count": 0,
            }
        }

    def _fake_write(vault, scorecard):
        return (vault / "report.json", vault / "REPORT.md")

    monkeypatch.setattr(
        "research_framework.cli.acceptance.build_scorecard", _fake_build
    )
    monkeypatch.setattr(
        "research_framework.cli.acceptance.write_scorecard", _fake_write
    )
    # The helper returns None regardless of the scorecard verdict.
    assert orchestrator._autorun_acceptance(clean_vault) is None


def test_regenerate_shim_exposes_acceptance_verb():
    """The shipped shim template routes the acceptance verb (so regenerate-shim
    re-renders existing vault shims to expose it)."""
    from research_framework._assets import asset_path

    template = (asset_path("templates") / "vault-script.sh.j2").read_text(
        encoding="utf-8"
    )
    assert "acceptance)" in template
    assert "research_framework.cli acceptance" in template


def test_parser_registers_acceptance_verb():
    from research_framework.cli._parser import build_parser

    parser = build_parser()
    ns = parser.parse_args(["acceptance", "--vault", "/tmp/x", "--json", "--strict"])
    assert ns.func.__name__ == "_cmd_acceptance"
    assert ns.vault == Path("/tmp/x")
    assert ns.json is True
    assert ns.strict is True
