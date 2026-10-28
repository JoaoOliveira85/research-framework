"""Issue #26 — edge cases of the archived notice in agent-instruction files.

`apply_archived_notice` edits files an operator has hand-edited, so it must
find the right place, keep the file's own line endings, and remove only what
it wrote.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pytest

from research_framework import cli
from research_framework.pipeline.archived import (
    apply_archived_notice,
    sync_archived_notice,
)

BEGIN = "<!-- archived-notice:begin -->"
END = "<!-- archived-notice:end -->"
MARKER = "Vault archived"


def _no_bare_lf(text: str) -> bool:
    return "\n" not in text.replace("\r\n", "")


# --------------------------------------------------------------------------
# Where the notice goes
# --------------------------------------------------------------------------


def test_notice_follows_the_title_not_a_yaml_comment_in_front_matter() -> None:
    text = "---\n# a yaml comment\nkey: 1\n---\n# Title\n\nBody\n"
    out = apply_archived_notice(text, True)
    assert out.index(MARKER) > out.index("# Title")
    assert out.startswith("---\n# a yaml comment\nkey: 1\n---\n# Title\n")


def test_notice_skips_a_title_like_line_inside_a_code_fence() -> None:
    text = "```sh\n# not a heading\n```\n\n# Real title\n\nBody\n"
    out = apply_archived_notice(text, True)
    assert out.index(MARKER) > out.index("# Real title")
    assert out.index("# not a heading") < out.index(BEGIN)


def test_tilde_fences_are_fences_too() -> None:
    text = "~~~\n# not a heading\n~~~\n# Real\nBody\n"
    out = apply_archived_notice(text, True)
    assert out.index(BEGIN) > out.index("# Real")


def test_no_title_goes_after_front_matter() -> None:
    text = "---\nkey: 1\n---\nBody only\n"
    out = apply_archived_notice(text, True)
    assert out.startswith("---\nkey: 1\n---\n" + BEGIN)
    assert out.endswith("Body only\n")


def test_no_title_and_no_front_matter_goes_to_the_top() -> None:
    out = apply_archived_notice("Just prose\n", True)
    assert out.startswith(BEGIN)
    assert out.endswith("Just prose\n")


# --------------------------------------------------------------------------
# Removal
# --------------------------------------------------------------------------


def test_round_trip_is_byte_identical_and_keeps_the_blank_line_before() -> None:
    text = "# Title\n\nParagraph\n\n## Section\n"
    assert apply_archived_notice(apply_archived_notice(text, True), False) == text


def test_removal_does_not_eat_a_preceding_newline() -> None:
    stale = f"Intro\n\n{BEGIN}\nold text\n{END}\nNext\n"
    assert apply_archived_notice(stale, False) == "Intro\n\nNext\n"


def test_a_stale_block_without_a_trailing_newline_is_removed() -> None:
    stale = f"# Title\n{BEGIN}\nold text\n{END}"
    assert apply_archived_notice(stale, False) == "# Title\n"


def test_applying_twice_never_stacks() -> None:
    once = apply_archived_notice("# T\n\nBody\n", True)
    assert apply_archived_notice(once, True) == once
    assert once.count(BEGIN) == 1


def test_an_orphan_begin_is_left_alone_and_warned_about(
    caplog: pytest.LogCaptureFixture,
) -> None:
    text = f"# T\n{BEGIN}\nhand-written, never closed\n\nBody\n"
    with caplog.at_level(logging.WARNING):
        out = apply_archived_notice(text, False)
    assert out == text, "nothing to remove: an orphan is not a block"
    assert any("orphan" in r.getMessage().lower() for r in caplog.records)


def test_an_orphan_begin_does_not_swallow_text_up_to_a_later_complete_block(
    caplog: pytest.LogCaptureFixture,
) -> None:
    text = f"# T\n{BEGIN}\nkeep this paragraph\n\n{BEGIN}\nold notice\n{END}\nBody\n"
    with caplog.at_level(logging.WARNING):
        out = apply_archived_notice(text, False)
    assert "keep this paragraph" in out
    assert "old notice" not in out
    assert out.count(BEGIN) == 1, "only the orphan remains"
    assert any("orphan" in r.getMessage().lower() for r in caplog.records)


def test_an_orphan_end_is_left_alone_and_warned_about(
    caplog: pytest.LogCaptureFixture,
) -> None:
    text = f"# T\n\nstray {END}\n"
    with caplog.at_level(logging.WARNING):
        assert apply_archived_notice(text, False) == text
    assert any("orphan" in r.getMessage().lower() for r in caplog.records)


# --------------------------------------------------------------------------
# Line endings (file-level, byte IO)
# --------------------------------------------------------------------------


def _vault_with(tmp_path: Path, *, claude: bytes, archived: bool = True) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "archived: true\n" if archived else "archived: false\n", encoding="utf-8"
    )
    (vault / "CLAUDE.md").write_bytes(claude)
    return vault


def test_crlf_files_keep_crlf_and_round_trip_byte_for_byte(tmp_path: Path) -> None:
    original = b"# Title\r\n\r\nBody line\r\n"
    vault = _vault_with(tmp_path, claude=original)

    sync_archived_notice(vault)
    archived = (vault / "CLAUDE.md").read_bytes().decode("utf-8")
    assert MARKER in archived
    assert _no_bare_lf(archived), "inserted lines must use the file's CRLF"

    (vault / "settings.yaml").write_text("archived: false\n", encoding="utf-8")
    sync_archived_notice(vault)
    assert (vault / "CLAUDE.md").read_bytes() == original


def test_lf_files_stay_lf(tmp_path: Path) -> None:
    vault = _vault_with(tmp_path, claude=b"# Title\n\nBody\n")
    sync_archived_notice(vault)
    assert b"\r" not in (vault / "CLAUDE.md").read_bytes()


def test_an_already_correct_file_is_not_rewritten(tmp_path: Path) -> None:
    vault = _vault_with(tmp_path, claude=b"# Title\n\nBody\n", archived=False)
    assert sync_archived_notice(vault) == []


# --------------------------------------------------------------------------
# The notice-only path (no overwrite of customised commands)
# --------------------------------------------------------------------------


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _notice_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / ".claude" / "commands").mkdir(parents=True)
    (vault / "settings.yaml").write_text("archived: true\n", encoding="utf-8")
    (vault / "CLAUDE.md").write_text("# V — CLAUDE.md\n\nHand edits\n", "utf-8")
    (vault / "AGENTS.md").write_text("# V — AGENTS.md\n\nIndex\n", "utf-8")
    commands = vault / ".claude" / "commands"
    (commands / "research.md").write_text(
        "---\ndescription: mine\n---\n# /research — customised\n\nSteps\n", "utf-8"
    )
    (commands / "ask.md").write_text("# /ask — customised\n", encoding="utf-8")
    return vault


def test_notice_only_touches_just_the_three_files_and_needs_no_spec_parse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _notice_vault(tmp_path)
    before = _snapshot(vault)
    assert not (vault / "_pipeline" / "spec-parse.json").exists()

    rc = cli.main(["regenerate-agents", str(vault), "--notice-only"])

    assert rc == 0, capsys.readouterr().err
    after = _snapshot(vault)
    changed = {k for k in after if after[k] != before.get(k)}
    assert changed == {
        "CLAUDE.md",
        "AGENTS.md",
        ".claude/commands/research.md",
    }
    research = (vault / ".claude" / "commands" / "research.md").read_text("utf-8")
    assert "customised" in research and "description: mine" in research
    assert research.index(MARKER) > research.index("# /research")


def test_notice_only_removes_it_again_when_unarchived(tmp_path: Path) -> None:
    vault = _notice_vault(tmp_path)
    before = _snapshot(vault)
    cli.main(["regenerate-agents", str(vault), "--notice-only"])
    (vault / "settings.yaml").write_text("archived: false\n", encoding="utf-8")

    assert cli.main(["regenerate-agents", str(vault), "--notice-only"]) == 0
    assert _snapshot(vault) == before | {
        "settings.yaml": _snapshot(vault)["settings.yaml"]
    }


def test_notice_follows_a_renamed_research_command(tmp_path: Path) -> None:
    vault = _notice_vault(tmp_path)
    commands = vault / ".claude" / "commands"
    (commands / "research.md").rename(commands / "dig.md")
    (vault / "_pipeline").mkdir()
    (vault / "_pipeline" / "spec-parse.json").write_text(
        json.dumps({"settings": {"commands": {"research": "dig"}}}), encoding="utf-8"
    )

    changed = {p.name for p in sync_archived_notice(vault)}

    assert "dig.md" in changed
    assert MARKER in (commands / "dig.md").read_text(encoding="utf-8")


def test_notice_only_still_validates_the_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cli.main(["regenerate-agents", str(tmp_path / "nope"), "--notice-only"])
    assert rc == 2
    assert "not a directory" in capsys.readouterr().err


def test_vault_update_syncs_the_notice(tmp_path: Path) -> None:
    from research_framework.pipeline.vault_update import sync_agent_notice

    vault = _notice_vault(tmp_path)
    changed = sync_agent_notice(vault)

    assert {p.name for p in changed} == {"CLAUDE.md", "AGENTS.md", "research.md"}
    assert MARKER in (vault / "CLAUDE.md").read_text(encoding="utf-8")


def test_the_vault_shim_runs_the_notice_sync_during_update() -> None:
    from research_framework._assets import asset_path

    shim = (asset_path("templates") / "vault-script.sh.j2").read_text(encoding="utf-8")
    assert "sync_agent_notice" in shim


def test_the_notice_names_no_command_and_no_placeholder() -> None:
    notice = apply_archived_notice("# T\n", True)
    assert "archived: false" in notice
    assert "<vault>" not in notice
    assert "regenerate-agents" not in notice
