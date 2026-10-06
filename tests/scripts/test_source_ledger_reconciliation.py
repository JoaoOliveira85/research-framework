"""Spec 048 v2.1 amendment — ledger ↔ citation reconciliation.

Pins the three amendment requirements (codebase-vault rc1 defect 3.4 — the ledger
asserted ACCESS_FAIL/PIPELINE_DROP on sources the notes cited):

* **B1 (FR-023)** — `_note_citation_hosts` builds the corpus of hosts the notes
  actually cite from `source_urls` frontmatter.
* **B2 (FR-022)** — `reconcile_against_citations` relabels a cited-but-failed
  verdict as `LEDGER_DISAGREEMENT`, preserving the join verdict in
  `disagreement_was`; a genuinely-unread source keeps its verdict.
* **B3 (FR-024)** — `read_via` attributes a read to `direct`/`mcp`/`unknown`
  (an MCP-only source is never silently dropped).
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "source_ledger.py"
FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures" / "source_ledger"


def _load():
    spec = importlib.util.spec_from_file_location("source_ledger", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["source_ledger"] = module
    spec.loader.exec_module(module)
    return module


def _write_note(path: Path, *, source_urls: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"title: {path.stem}",
        "note_type: concept",
        "coverage_category: concepts",
        "summary: A note.",
        "source_urls:",
        *[f"  - {u}" for u in source_urls],
        "---",
        "",
        "Body.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# B1 — note-citation corpus
# ---------------------------------------------------------------------------


def test_note_citation_hosts_collects_hosts(tmp_path):
    mod = _load()
    vault = tmp_path / "v"
    notes = vault / "data_vault" / "03 - Concepts"
    _write_note(
        notes / "a.md",
        source_urls=[
            "https://github.com/example/repo/pull/1",
            "https://confluence.example.com/x/page",
        ],
    )
    _write_note(notes / "b.md", source_urls=["https://github.com/example/other"])
    # Index/template notes must be excluded from the corpus.
    _write_note(
        vault / "data_vault" / "_index.md",
        source_urls=["https://ignored.example.com/x"],
    )

    corpus = mod._note_citation_hosts(vault)

    assert set(corpus) == {"github.com", "confluence.example.com"}
    assert corpus["github.com"] == 2
    assert corpus["confluence.example.com"] == 1
    assert "ignored.example.com" not in corpus


def test_note_citation_hosts_empty_when_no_data_vault(tmp_path):
    mod = _load()
    assert mod._note_citation_hosts(tmp_path / "missing") == {}


# ---------------------------------------------------------------------------
# B2 — LEDGER_DISAGREEMENT reconciliation
# ---------------------------------------------------------------------------


def _entry(mod, name, verdict, hosts):
    return mod.SourceLedgerEntry(
        name=name,
        role="behaviour",
        required=True,
        priority=1,
        verdict=verdict,
        hosts=hosts,
    )


def test_reconcile_relabels_cited_access_fail(tmp_path):
    mod = _load()
    cited = _entry(mod, "GitHub", mod.Verdict.ACCESS_FAIL, ["github.com"])
    uncited = _entry(mod, "Blog", mod.Verdict.NOT_REACHED, ["blog.example.com"])
    used = _entry(mod, "RSS", mod.Verdict.USED, ["rss.example.com"])

    mod.reconcile_against_citations(
        [cited, uncited, used], {"github.com": 3, "rss.example.com": 1}
    )

    # The cited-but-failed source flips; its join verdict is preserved.
    assert cited.verdict == mod.Verdict.LEDGER_DISAGREEMENT
    assert cited.disagreement_was == "ACCESS_FAIL"
    # A genuinely-unread source keeps its verdict.
    assert uncited.verdict == mod.Verdict.NOT_REACHED
    assert uncited.disagreement_was is None
    # USED is never relabelled.
    assert used.verdict == mod.Verdict.USED
    assert used.disagreement_was is None


def test_reconcile_is_noop_for_empty_corpus(tmp_path):
    mod = _load()
    e = _entry(mod, "GitHub", mod.Verdict.ACCESS_FAIL, ["github.com"])
    mod.reconcile_against_citations([e], {})
    assert e.verdict == mod.Verdict.ACCESS_FAIL


def test_cited_but_access_fail_becomes_disagreement_end_to_end(tmp_path):
    """The rc1 repro: a source verdicted ACCESS_FAIL by the join, yet cited by a
    note, must self-flag LEDGER_DISAGREEMENT and stop counting as a required
    failure."""
    mod = _load()
    vault = tmp_path / "v"
    shutil.copytree(FIXTURE_ROOT / "access_fail", vault)
    _write_note(
        vault / "data_vault" / "03 - Concepts" / "note.md",
        source_urls=["https://github.com/example/repo/pull/1"],
    )

    rollup = mod.build_run_rollup(vault, [1])

    entry = next(e for e in rollup.entries if e.name == "GitHub Pull Requests")
    assert entry.verdict == mod.Verdict.LEDGER_DISAGREEMENT
    assert entry.disagreement_was == "ACCESS_FAIL"
    # A cited source can never be a required-source failure (FR-023 invariant).
    assert "GitHub Pull Requests" not in rollup.required_failures
    assert mod.compute_exit_code(rollup) == 0


def test_uncited_access_fail_stays_failure_end_to_end(tmp_path):
    """Control: no citing note ⇒ ACCESS_FAIL stands (and remains a required
    failure)."""
    mod = _load()
    vault = tmp_path / "v"
    shutil.copytree(FIXTURE_ROOT / "access_fail", vault)
    # No data_vault notes ⇒ empty corpus.

    rollup = mod.build_run_rollup(vault, [1])

    entry = next(e for e in rollup.entries if e.name == "GitHub Pull Requests")
    assert entry.verdict == mod.Verdict.ACCESS_FAIL
    assert entry.disagreement_was is None
    assert "GitHub Pull Requests" in rollup.required_failures


# ---------------------------------------------------------------------------
# B3 — direct vs MCP read attribution
# ---------------------------------------------------------------------------


def test_read_via_mcp_for_mcp_access_method(tmp_path):
    mod = _load()
    from research_framework.spec.schema import DataSourceConfig

    src = DataSourceConfig(name="Confluence", type="external", access_method="mcp")
    # No direct fetch signal at all — must still attribute to MCP, not drop.
    signals = mod.VerdictSignals(stage_ran=False)
    assert mod._read_via(src, signals) == "mcp"


def test_read_via_direct_for_fetch_signal(tmp_path):
    mod = _load()
    from research_framework.spec.schema import DataSourceConfig

    src = DataSourceConfig(name="GitHub", type="code")
    signals = mod.VerdictSignals(fetch_attempted=True, fetch_outcome="ok")
    assert mod._read_via(src, signals) == "direct"


def test_read_via_unknown_when_unattributable(tmp_path):
    mod = _load()
    from research_framework.spec.schema import DataSourceConfig

    src = DataSourceConfig(name="Mystery", type="external")
    signals = mod.VerdictSignals(stage_ran=False)
    assert mod._read_via(src, signals) == "unknown"


def test_read_via_serialized_in_entry_dict(tmp_path):
    mod = _load()
    entry = _entry(mod, "GitHub", mod.Verdict.USED, ["github.com"])
    entry.read_via = "direct"
    payload = mod._entry_to_dict(entry)
    assert payload["read_via"] == "direct"
    assert payload["disagreement_was"] is None
