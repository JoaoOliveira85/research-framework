"""US6 integration: orchestrator reindexes after every cycle (T076)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from research_framework.pipeline.coverage import save_targets
from research_framework.pipeline.orchestrator import run_single_cycle
from research_framework.spec.schema import CoverageCategory, CoverageTargets
from tests._helpers.cycle_runner_stub import no_op_cycle_runner


def _note(
    data_vault: Path,
    folder: str,
    stem: str,
    title: str,
) -> None:
    p = data_vault / folder / f"{stem}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\n"
        f"title: {title}\n"
        f"summary: Summary for {title}\n"
        "coverage_category: concepts\n"
        "source_urls:\n  - https://example.com/x\n"
        "related: []\n"
        "---\n\n"
        f"# {title}\n",
        encoding="utf-8",
    )


def _synth_ten_note_vault(vault: Path) -> None:
    dv = vault / "data_vault"
    combos = [
        ("01-a", "n01", "Note Zero One"),
        ("01-a", "n02", "Note Zero Two"),
        ("02-b", "n03", "Note Zero Three"),
        ("02-b", "n04", "Note Zero Four"),
        ("03-c", "n05", "Note Zero Five"),
        ("03-c", "n06", "Note Zero Six"),
        ("04-d", "n07", "Note Zero Seven"),
        ("04-d", "n08", "Note Zero Eight"),
        ("05-e", "n09", "Note Zero Nine"),
        ("05-e", "n10", "Note Zero Ten"),
    ]
    for folder, stem, title in combos:
        _note(dv, folder, stem, title)


def _minimal_coverage_all_met(vault: Path) -> None:
    """CG-001 threshold 0 when nothing left unmet."""
    save_targets(
        vault,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="concepts",
                    note_type="concept",
                    target_count=1,
                    met_count=1,
                )
            ]
        ),
    )


class TestReindexAtCycleEnd:
    def test_after_cycle_index_files_in_data_vault_reference_all_notes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "_pipeline" / "cycles").mkdir(parents=True)
        _minimal_coverage_all_met(vault)
        _synth_ten_note_vault(vault)

        research = {
            "notes_created": [],
            "notes_updated": [],
        }
        (vault / "_pipeline" / "cycles" / "cycle-001-research.json").write_text(
            json.dumps(research), encoding="utf-8"
        )

        rc = run_single_cycle(
            vault,
            1,
            budget_cap=10.0,
            max_cycles=5,
            spec=None,
            cycle_runner=no_op_cycle_runner(),
        )
        assert rc == 0

        dvp = vault / "data_vault"
        for name in ("_index.md", "_concepts.md", "_graph.md"):
            assert (dvp / name).is_file(), (
                f"expected {name} under data_vault/ after cycle"
            )

        idx = (dvp / "_index.md").read_text(encoding="utf-8")
        for needle in (
            "Note Zero One",
            "Note Zero Two",
            "Note Zero Three",
            "Note Zero Four",
            "Note Zero Five",
            "Note Zero Six",
            "Note Zero Seven",
            "Note Zero Eight",
            "Note Zero Nine",
            "Note Zero Ten",
        ):
            assert needle in idx, f"_index.md must reference {needle!r}"

    def test_reindex_failure_does_not_change_exit_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "_pipeline" / "cycles").mkdir(parents=True)
        _minimal_coverage_all_met(vault)
        _synth_ten_note_vault(vault)
        (vault / "_pipeline" / "cycles" / "cycle-001-research.json").write_text(
            json.dumps({"notes_created": [], "notes_updated": []}),
            encoding="utf-8",
        )

        import research_framework.vault.indexer as indexer_mod

        called: list[Path] = []

        def boom(vd: Path) -> dict[str, Path]:
            called.append(vd)
            raise RuntimeError("reindex failed")

        with patch.object(indexer_mod, "rebuild_all", side_effect=boom, create=True):
            rc = run_single_cycle(
                vault,
                1,
                budget_cap=10.0,
                max_cycles=5,
                spec=None,
                cycle_runner=no_op_cycle_runner(),
            )

        assert rc == 0
        assert called, (
            "orchestrator must call indexer.rebuild_all after each cycle (T078)"
        )
