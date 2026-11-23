"""The ``stamp_note_currency`` migration step (spec 087 FR-021, FR-022; T011)."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import date
from pathlib import Path

import pytest

from research_framework.generator.scaffold import _render_vault_gitignore
from research_framework.pipeline import backlog, currency_stamp, layout_migration
from research_framework.spec.schema import NoteTypeConfig, SpecConfig
from research_framework.vault.frontmatter import parse_frontmatter_str
from tests._helpers.legacy_layout import git
from tests._helpers.vault_factory import build_minimal_vault, commit_vault

TODAY = date(2026, 11, 23)
FOLDER = "data_vault/01 - Concepts"


def _note(frontmatter: str, body: str = "# A note\n\nThe body, untouched.\n") -> str:
    return f"---\ntype: concept\nsummary: s\n{frontmatter}---\n\n{body}"


def _git_vault(tmp_path: Path, notes: dict[str, str]) -> Path:
    vault = tmp_path / "vault"
    folder = vault / FOLDER
    folder.mkdir(parents=True)
    for name, text in notes.items():
        (folder / f"{name}.md").write_text(text, encoding="utf-8", newline="")
    (vault / ".gitignore").write_text(
        _render_vault_gitignore("data_vault"), encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q", "-b", "main", str(vault)], check=True)
    git(vault, "config", "user.email", "t@e.com")
    git(vault, "config", "user.name", "T")
    git(vault, "add", "-A")
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2022-04-04T10:00:00",
        "GIT_COMMITTER_DATE": "2022-04-04T10:00:00",
    }
    subprocess.run(
        ["git", "-C", str(vault), "commit", "-qm", "initial"],
        check=True,
        env=env,
        capture_output=True,
    )
    return vault


def _stamped(vault: Path, name: str) -> dict:
    return parse_frontmatter_str((vault / FOLDER / f"{name}.md").read_text("utf-8"))[0]


def test_as_of_comes_from_accessed_then_updated_then_created_then_git(
    tmp_path: Path,
) -> None:
    vault = _git_vault(
        tmp_path,
        {
            "accessed-dicts": _note(
                "source_urls:\n"
                "  - {url: https://a.example, accessed: 2025-03-01}\n"
                "  - {url: https://b.example, accessed: 2025-06-15}\n"
                "updated: 2024-01-01\n"
            ),
            "accessed-strings": _note(
                "source_urls:\n"
                "  - 'https://a.example - A title, accessed 2024-11-02'\n"
                "  - 'https://b.example - B title, accessed 2024-02-20'\n"
                "created: 2020-01-01\n"
            ),
            "updated": _note("updated: 2024-05-05\ncreated: 2023-01-01\n"),
            "created": _note("created: '2023-02-02'\n"),
            "from-git": _note(""),
        },
    )
    untracked = vault / FOLDER / "brand-new.md"
    untracked.write_text(_note(""), encoding="utf-8")

    plan = currency_stamp.plan_stamps(vault, today=TODAY)

    got = {Path(s.rel).stem: s.as_of for s in plan.stamps}
    assert got == {
        "accessed-dicts": "2025-06-15",  # the newest accessed date wins
        "accessed-strings": "2024-11-02",
        "updated": "2024-05-05",
        "created": "2023-02-02",
        "from-git": "2022-04-04",  # the file's first commit
        "brand-new": "2026-11-23",  # nothing at all: today
    }
    assert plan.oldest == "2022-04-04" and plan.newest == "2026-11-23"


def test_no_body_and_no_existing_frontmatter_line_changes(tmp_path: Path) -> None:
    originals = {
        "plain": _note("updated: 2024-05-05\n"),
        "comment": _note("# keep this comment\nupdated: 2024-05-05  # and this\n"),
        "odd-scalars": _note(
            "version: 0123\nflag: no\nratio: 1.10\nupdated: 2024-05-05\n"
        ),
        "crlf": "---\r\ntype: concept\r\nupdated: 2024-05-05\r\n---\r\n\r\nBody.\r\n",
        "no-trailing-newline": "---\ntype: concept\nupdated: 2024-05-05\n---\nBody",
        "dashes-in-body": _note(
            "updated: 2024-05-05\n", "Text\n\n---\n\nmore --- text\n"
        ),
        "partial-as-of": _note("as_of: 2023-09-09\nupdated: 2024-05-05\n"),
        "partial-currency": _note("currency: declining\nupdated: 2024-05-05\n"),
    }
    vault = _git_vault(tmp_path, originals)

    plan = currency_stamp.plan_stamps(vault, today=TODAY)
    currency_stamp.apply_stamps(vault, plan)

    for name, original in originals.items():
        now = (vault / FOLDER / f"{name}.md").read_bytes().decode("utf-8")
        removed = [
            line
            for line in re.split(r"(?<=\n)", now)
            if re.match(r"(as_of|currency): ", line)
            and line not in re.split(r"(?<=\n)", original)
        ]
        stripped = now
        for line in removed:
            stripped = stripped.replace(line, "", 1)
        assert stripped == original, name  # the file minus the added lines
        assert len(removed) == {"partial-as-of": 1, "partial-currency": 1}.get(name, 2)
    # and what is added is what the plan said
    assert _stamped(vault, "plain")["as_of"] == date(2024, 5, 5)
    assert _stamped(vault, "plain")["currency"] == "current"
    assert _stamped(vault, "partial-as-of")["as_of"] == date(2023, 9, 9)
    assert _stamped(vault, "partial-currency")["currency"] == "declining"


def test_alias_exempt_and_already_stamped_notes_are_left_alone(
    tmp_path: Path,
) -> None:
    keep = {
        "alias": "---\nnote_type: alias\nredirect_to: x\n---\nsee x\n",
        "exempt": _note("verifier_status: exempt\n"),
        "stamped": _note("as_of: 2025-01-01\ncurrency: current\n"),
        "unparseable": "---\ntype: concept\nbad: [unclosed\n---\n\nBody\n",
        "no-frontmatter": "# Just a heading\n\nNo frontmatter here.\n",
        "_index": "---\ntitle: index\n---\n",
    }
    vault = _git_vault(
        tmp_path, {**keep, "needs-stamp": _note("updated: 2024-01-01\n")}
    )
    (vault / "data_vault" / "_templates").mkdir()
    (vault / "data_vault" / "_templates" / "concept.md").write_text(_note(""))
    before = {p: p.read_bytes() for p in (vault / "data_vault").rglob("*.md")}

    plan = currency_stamp.plan_stamps(vault, today=TODAY)

    assert [Path(s.rel).stem for s in plan.stamps] == ["needs-stamp"]
    assert plan.skipped == 2  # the unparseable one and the one with no frontmatter
    currency_stamp.apply_stamps(vault, plan)
    changed = {p.name for p, content in before.items() if p.read_bytes() != content}
    assert changed == {"needs-stamp.md"}
    # and a second plan finds nothing left to do
    again = currency_stamp.plan_stamps(vault, today=TODAY)
    assert again.stamps == []


def test_dry_run_second_run_and_the_commit_shape(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    vault = _git_vault(
        tmp_path,
        {
            "a": _note("updated: 2024-05-05\n"),
            "b": _note("created: 2023-02-02\n"),
            "c": _note("as_of: 2025-01-01\ncurrency: current\n"),
            "bad": "---\nx: [\n---\n",
        },
    )
    head = git(vault, "rev-parse", "HEAD")

    dry = layout_migration.migrate(vault, dry_run=True)
    text = "\n".join(dry.messages)
    assert dry.exit_code == 0
    assert "stamp_note_currency" in text
    assert "2 note(s)" in text and "2023-02-02" in text and "2024-05-05" in text
    assert git(vault, "rev-parse", "HEAD") == head
    assert git(vault, "status", "--porcelain").strip() == ""

    with caplog.at_level(logging.INFO):
        result = layout_migration.migrate(vault)
    assert result.exit_code == 0
    assert (
        "stamped 2 note(s) with as_of and currency, skipped 1; "
        "as_of from 2023-02-02 to 2024-05-05"
    ) in caplog.text
    assert git(vault, "log", "-1", "--format=%s") == "framework: stamp note currency\n"
    files = git(vault, "show", "--name-status", "--no-renames", "--format=", "HEAD")
    assert sorted(line.split("\t") for line in files.splitlines()) == [
        ["M", f"{FOLDER}/a.md"],
        ["M", f"{FOLDER}/b.md"],
    ]
    assert git(vault, "status", "--porcelain").strip() == ""

    # idempotent: nothing more to stamp, no commit
    head = git(vault, "rev-parse", "HEAD")
    again = layout_migration.migrate(vault)
    assert again.exit_code == 0 and again.committed is None
    assert any("already migrated" in m for m in again.messages)
    assert git(vault, "rev-parse", "HEAD") == head


def test_an_unstamped_vault_is_not_a_legacy_vault(tmp_path: Path) -> None:
    from research_framework.pipeline import state_layout

    vault = _git_vault(tmp_path, {"a": _note("updated: 2024-05-05\n")})

    assert state_layout.legacy_paths_present(vault) == []
    assert not state_layout.is_legacy_layout(vault)
    state_layout.require_migrated(vault)  # does not refuse


def test_without_git_the_notes_are_stamped_and_nothing_is_committed(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    (vault / FOLDER).mkdir(parents=True)
    (vault / FOLDER / "a.md").write_text(_note("updated: 2024-05-05\n"))

    result = layout_migration.migrate(vault)

    assert result.exit_code == 0 and result.committed is None
    assert _stamped(vault, "a")["currency"] == "current"


@pytest.mark.e2e
def test_the_first_cycles_after_stamping_review_at_most_the_update_share(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stamping queues nothing itself; the sweep queues what is due and the cycle
    split bounds how many are worked per cycle (FR-022)."""
    from research_framework.pipeline.orchestrator import run_single_cycle

    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault = build_minimal_vault(
        tmp_path,
        num_categories=1,
        num_targets_per_category=30,
        max_cycles=2,
        spec_overrides={
            "note_types": [
                NoteTypeConfig(
                    name="concept",
                    description="d",
                    folder="01 - Concepts",
                    min_word_count=30,
                    review_after_days=30,
                )
            ]
        },
    )
    spec = SpecConfig.from_dict(
        json.loads((vault / "_pipeline" / "spec-parse.json").read_text("utf-8"))
    )
    category = spec.coverage_targets.categories[0].name
    folder = vault / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(1, 13):  # a pre-087 vault: twelve notes, none stamped
        (folder / f"old-note-{i:02d}.md").write_text(
            "---\ntype: concept\nsummary: s\nsource_urls: [https://example.org/s]\n"
            f"coverage_category: {category}\nupdated: 2020-01-{i:02d}\n---\n\n"
            + "body " * 40
            + "\n",
            encoding="utf-8",
        )
    commit_vault(vault)

    migrated = layout_migration.migrate(vault, force=True)
    assert migrated.exit_code == 0
    assert backlog.update_topics(vault) == []  # stamping queued nothing itself
    assert all(
        _stamped(vault, f"old-note-{i:02d}")["currency"] == "current"
        for i in range(1, 13)
    )
    assert git(vault, "show", "HEAD:" + f"{FOLDER}/old-note-01.md").count("as_of:") == 1

    worked: list[int] = []
    shares: list[int] = []
    for cycle in (1, 2):
        run_single_cycle(
            vault, cycle_num=cycle, budget_cap=10.0, max_cycles=2, spec=spec
        )
        sidecar = (
            vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-update-outcomes.json"
        )
        worked.append(len(json.loads(sidecar.read_text("utf-8"))["results"]))
        plan = (vault / "_pipeline" / "research-plan.md").read_text("utf-8")
        shares.append(int(re.search(r"^update_quota: (\d+)$", plan, re.M).group(1)))
        git(vault, "add", "-A", "-f", "data_vault")
        subprocess.run(
            [
                "git",
                "-C",
                str(vault),
                "commit",
                "-qm",
                f"cycle {cycle}",
                "--allow-empty",
            ],
            check=True,
            capture_output=True,
        )

    assert all(share >= 1 for share in shares)
    assert worked == shares  # exactly the share, never the whole backlog at once
    # twelve were due; far fewer than twelve were worked, the rest still queued
    assert sum(worked) < 12
    assert len(backlog.update_topics(vault)) >= 12 - sum(worked) > 0
