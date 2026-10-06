"""Tests for scripts/source_ledger.py — read-only Source-Consideration Ledger (spec 048 v2).

Contract: specs/048-observability-v1/contracts/source-ledger-v2.contract.md
Tier: 2 (same tier as tests/scripts/test_raw_capture.py)
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "source_ledger.py"
CONTRACT_PATH = (
    Path(__file__).parent.parent.parent
    / "specs"
    / "048-observability-v1"
    / "contracts"
    / "source-ledger-v2.contract.md"
)


def _load():
    spec = importlib.util.spec_from_file_location("source_ledger", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["source_ledger"] = module
    spec.loader.exec_module(module)
    return module


def _contract_schema_version() -> str:
    """The ``schema_version`` literal documented in the contract's JSON example.

    There are three unrelated "version" tokens in this corpus (#297): the
    contract filename's ``v2`` (spec 048's scope phase), the artifact's own
    ``schema_version``, and dated ``FR-NNN`` amendment notes. Only
    ``schema_version`` is the one a consumer may branch on — this pins the
    doc's stated value so it cannot drift from the producer silently.
    """
    text = CONTRACT_PATH.read_text(encoding="utf-8")
    m = re.search(r'"schema_version":\s*"([^"]+)"', text)
    assert m, "contract's example JSON no longer documents a schema_version"
    return m.group(1)


def test_schema_version_matches_contract_doc():
    mod = _load()
    assert mod.SCHEMA_VERSION == _contract_schema_version()


def test_emitted_ledger_schema_version_matches_contract_doc():
    from tests.scripts.conftest import fixture_vault, run_ledger

    vault = fixture_vault(Path("used"))
    path = vault / "_pipeline" / "cycles" / "cycle-001-source-ledger.json"
    if path.is_file():
        path.unlink()
    assert run_ledger(vault, "--cycle", "1").returncode == 0
    ledger = json.loads(path.read_text(encoding="utf-8"))
    assert ledger["schema_version"] == _contract_schema_version()


def test_verdict_enum_members():
    mod = _load()
    # Added 2026-06-03, FR-022/FR-023: LEDGER_DISAGREEMENT (7th member).
    assert {v.value for v in mod.Verdict} == {
        "USED",
        "LEDGER_DISAGREEMENT",
        "QUALITY_REJECT",
        "ACCESS_FAIL",
        "SKIPPED_RELEVANCE",
        "PIPELINE_DROP",
        "NOT_REACHED",
    }


def test_failure_verdicts_frozenset():
    mod = _load()
    assert mod.FAILURE_VERDICTS == {
        mod.Verdict.ACCESS_FAIL,
        mod.Verdict.PIPELINE_DROP,
        mod.Verdict.QUALITY_REJECT,
    }


def test_resolve_verdict_used():
    mod = _load()
    signals = mod.VerdictSignals(notes_generated=2, notes_referencing=1)
    assert mod.resolve_verdict(signals) == mod.Verdict.USED


def test_resolve_verdict_quality_reject():
    mod = _load()
    signals = mod.VerdictSignals(
        notes_generated=1,
        notes_referencing=0,
        quality_rejected=True,
    )
    assert mod.resolve_verdict(signals) == mod.Verdict.QUALITY_REJECT


def test_resolve_verdict_access_fail():
    mod = _load()
    signals = mod.VerdictSignals(fetch_attempted=True, fetch_outcome="failed")
    assert mod.resolve_verdict(signals) == mod.Verdict.ACCESS_FAIL


def test_resolve_verdict_skipped_relevance():
    mod = _load()
    signals = mod.VerdictSignals(reason="Not relevant to vault scope")
    assert mod.resolve_verdict(signals) == mod.Verdict.SKIPPED_RELEVANCE


def test_resolve_verdict_pipeline_drop():
    mod = _load()
    signals = mod.VerdictSignals(stage_ran=True)
    assert mod.resolve_verdict(signals) == mod.Verdict.PIPELINE_DROP


def test_resolve_verdict_not_reached():
    mod = _load()
    signals = mod.VerdictSignals(stage_ran=False)
    assert mod.resolve_verdict(signals) == mod.Verdict.NOT_REACHED


@pytest.mark.parametrize(
    ("signals_kwargs", "expected"),
    [
        (
            {
                "notes_generated": 2,
                "notes_referencing": 1,
                "quality_rejected": True,
                "fetch_attempted": True,
                "fetch_outcome": "failed",
                "reason": "ignored",
                "stage_ran": True,
            },
            "USED",
        ),
        (
            {
                "notes_generated": 1,
                "notes_referencing": 0,
                "quality_rejected": True,
                "fetch_attempted": True,
                "fetch_outcome": "failed",
            },
            "QUALITY_REJECT",
        ),
        (
            {
                "fetch_attempted": True,
                "fetch_outcome": "failed",
                "reason": "off-topic",
                "stage_ran": True,
            },
            "ACCESS_FAIL",
        ),
    ],
)
def test_resolve_verdict_precedence_total_order(signals_kwargs, expected):
    mod = _load()
    signals = mod.VerdictSignals(**signals_kwargs)
    assert mod.resolve_verdict(signals) == mod.Verdict(expected)


def test_collapse_verdict_run_rollup():
    mod = _load()
    verdicts = [
        mod.Verdict.PIPELINE_DROP,
        mod.Verdict.USED,
        mod.Verdict.NOT_REACHED,
    ]
    assert mod.collapse_verdict(verdicts) == mod.Verdict.USED


def test_cli_missing_vault_exits_2():
    from tests.scripts.conftest import run_ledger

    result = run_ledger(None)
    assert result.returncode == 2


def test_cli_missing_spec_exits_2(tmp_path):
    from tests.scripts.conftest import run_ledger

    vault = tmp_path / "empty-vault"
    vault.mkdir()
    result = run_ledger(vault)
    assert result.returncode == 2


VERDICT_FIXTURES = {
    "used": "USED",
    "skipped_relevance": "SKIPPED_RELEVANCE",
    "access_fail": "ACCESS_FAIL",
    "quality_reject": "QUALITY_REJECT",
    "pipeline_drop": "PIPELINE_DROP",
    "not_reached": "NOT_REACHED",
}


@pytest.mark.parametrize(
    ("fixture_name", "expected_verdict"),
    list(VERDICT_FIXTURES.items()),
)
def test_build_cycle_ledger_terminal_verdicts(fixture_name, expected_verdict):
    from tests.scripts.conftest import fixture_vault, load_ledger_json, run_ledger

    vault = fixture_vault(Path(fixture_name))
    result = run_ledger(vault, "--cycle", "1")
    assert result.returncode == 0, result.stderr
    ledger = load_ledger_json(vault)
    assert ledger["reconciled"] is True
    assert len(ledger["entries"]) == 1
    entry = ledger["entries"][0]
    assert entry["verdict"] == expected_verdict
    if expected_verdict == "SKIPPED_RELEVANCE":
        assert entry["reason"]
    else:
        assert entry["reason"] is None


def test_build_cycle_ledger_reconciliation_invariant():
    from tests.scripts.conftest import fixture_vault, load_ledger_json, run_ledger

    vault = fixture_vault(Path("reconcile"))
    result = run_ledger(vault, "--cycle", "1")
    assert result.returncode == 0
    ledger = load_ledger_json(vault)
    spec_names = {
        "GitHub Pull Requests",
        "Product Confluence Space",
        "Industry RSS Feed",
        "Optional Blog Archive",
    }
    assert {entry["name"] for entry in ledger["entries"]} == spec_names
    assert len(ledger["entries"]) == len(spec_names)


def test_partial_run_missing_scout_not_reached(tmp_path):
    from tests.scripts.conftest import run_ledger

    shutil = __import__("shutil")
    vault = tmp_path / "partial"
    shutil.copytree(
        Path(__file__).parent.parent / "fixtures" / "source_ledger" / "used",
        vault,
    )
    scout = vault / "_pipeline" / "cycles" / "cycle-002-scout.json"
    research = vault / "_pipeline" / "cycles" / "cycle-002-research.json"
    assert not scout.exists()
    research.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "cycle": 2,
                "capture_failures": [
                    {
                        "url": "https://github.com/example/repo/pull/1",
                        "reason": "403 Forbidden",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    incidents = vault / "_pipeline" / "source-incidents.md"
    incidents.write_text(
        "- 2026-06-03T00:00:00Z — `GitHub Pull Requests` degraded: auth failed\n",
        encoding="utf-8",
    )
    result = run_ledger(vault, "--cycle", "2")
    assert result.returncode == 0
    ledger = json.loads(
        (vault / "_pipeline" / "cycles" / "cycle-002-source-ledger.json").read_text(
            encoding="utf-8"
        )
    )
    assert all(entry["verdict"] == "NOT_REACHED" for entry in ledger["entries"])


def test_capture_failures_do_not_crash_without_ds_url(tmp_path):
    from tests.scripts.conftest import run_ledger

    shutil = __import__("shutil")
    vault = tmp_path / "capture-fail"
    shutil.copytree(
        Path(__file__).parent.parent / "fixtures" / "source_ledger" / "used",
        vault,
    )
    research = vault / "_pipeline" / "cycles" / "cycle-001-research.json"
    research.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "cycle": 1,
                "capture_failures": [
                    {
                        "url": "https://github.com/example/repo/pull/1",
                        "reason": "403 Forbidden",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_ledger(vault, "--cycle", "1")
    assert result.returncode == 0, result.stderr
    ledger = json.loads(
        (vault / "_pipeline" / "cycles" / "cycle-001-source-ledger.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(ledger["entries"]) == 1


def test_cycle_ledger_json_deterministic():
    from tests.scripts.conftest import fixture_vault, run_ledger

    vault = fixture_vault(Path("used"))
    path = vault / "_pipeline" / "cycles" / "cycle-001-source-ledger.json"
    if path.is_file():
        path.unlink()
    assert run_ledger(vault, "--cycle", "1").returncode == 0
    first = path.read_bytes()
    assert run_ledger(vault, "--cycle", "1").returncode == 0
    second = path.read_bytes()
    assert first == second


def test_build_run_rollup_by_role_histogram():
    from tests.scripts.conftest import fixture_vault, run_ledger

    vault = fixture_vault(Path("reconcile"))
    result = run_ledger(vault, "--json")
    rollup = json.loads(result.stdout)
    assert rollup["by_role"]
    for entry in rollup["entries"]:
        role_counts = rollup["by_role"].get(entry["role"], {})
        assert role_counts.get(entry["verdict"], 0) >= 1


def test_fr019_exit_0_when_all_required_ok():
    from tests.scripts.conftest import fixture_vault, run_ledger

    vault = fixture_vault(Path("used"))
    assert run_ledger(vault).returncode == 0


def test_fr019_exit_1_on_required_access_fail():
    from tests.scripts.conftest import fixture_vault, run_ledger

    vault = fixture_vault(Path("access_fail"))
    result = run_ledger(vault)
    assert result.returncode == 1
    assert "Required-source failures" in result.stdout


def test_fr019_exit_1_on_required_pipeline_drop():
    from tests.scripts.conftest import fixture_vault, run_ledger

    vault = fixture_vault(Path("pipeline_drop"))
    assert run_ledger(vault).returncode == 1


def test_fr019_exit_1_on_required_quality_reject():
    from tests.scripts.conftest import fixture_vault, run_ledger

    vault = fixture_vault(Path("quality_reject"))
    result = run_ledger(vault)
    assert result.returncode == 1
    assert "QUALITY_REJECT" in result.stdout


def test_optional_source_failure_does_not_affect_exit(tmp_path):
    from tests.scripts.conftest import run_ledger

    shutil = __import__("shutil")
    vault = tmp_path / "optional-fail"
    shutil.copytree(
        Path(__file__).parent.parent / "fixtures" / "source_ledger" / "used",
        vault,
    )
    spec = vault / "research.spec.md"
    text = spec.read_text(encoding="utf-8")
    text = text.replace("required: true", "required: false", 1)
    spec.write_text(text, encoding="utf-8")
    incidents = vault / "_pipeline" / "source-incidents.md"
    incidents.write_text(
        "- 2026-06-03T00:00:00Z — `GitHub Pull Requests` degraded: auth failed\n",
        encoding="utf-8",
    )
    assert run_ledger(vault).returncode == 0


def test_required_not_reached_exit_0():
    from tests.scripts.conftest import fixture_vault, run_ledger

    vault = fixture_vault(Path("not_reached"))
    assert run_ledger(vault).returncode == 0


def test_exit_2_on_reconciliation_break():
    mod = _load()
    rollup = mod.RunRollup(
        vault="/tmp/vault",
        cycles_covered=[1],
        entries=[],
        by_role={},
        required_failures=[],
        reconciled=False,
    )
    assert mod.compute_exit_code(rollup) == 2
    payload = json.loads(mod.render_rollup_json(rollup))
    assert payload["reconciled"] is False


def test_render_rollup_markdown_matches_contract():
    from tests.scripts.conftest import fixture_vault, run_ledger

    vault = fixture_vault(Path("access_fail"))
    result = run_ledger(vault, "--write-rollup")
    assert result.returncode == 1
    assert "## By role" in result.stdout
    assert "## ⚠ Required-source failures (FR-019)" in result.stdout
    md = vault / "_pipeline" / "source-ledger-run.md"
    assert md.is_file()
    assert "FR-019" in md.read_text(encoding="utf-8")


def test_cli_json_stdout():
    from tests.scripts.conftest import fixture_vault, run_ledger

    vault = fixture_vault(Path("used"))
    result = run_ledger(vault, "--json")
    assert result.returncode == 0
    rollup = json.loads(result.stdout)
    for key in (
        "vault",
        "cycles_covered",
        "entries",
        "by_role",
        "required_failures",
        "reconciled",
    ):
        assert key in rollup
