"""Issue #26 — an archived vault tells its own agents not to write research.

CLAUDE.md, AGENTS.md and the `/research` command carry a short notice when the
vault is archived at render time; `regenerate-agents` brings an existing vault
in line (both ways) without disturbing anything else in those files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework import cli
from research_framework.generator.templates import render_all
from research_framework.spec.schema import SpecConfig
from tests._helpers.vault_factory import build_minimal_vault

MARKER = "Vault archived"


def _read(vault: Path) -> dict[str, str]:
    return {
        "CLAUDE.md": (vault / "CLAUDE.md").read_text(encoding="utf-8"),
        "AGENTS.md": (vault / "AGENTS.md").read_text(encoding="utf-8"),
        "research": (vault / ".claude" / "commands" / "research.md").read_text(
            encoding="utf-8"
        ),
    }


def _set_archived(vault: Path, value: bool) -> None:
    settings = vault / "settings.yaml"
    body = settings.read_text(encoding="utf-8").replace("archived: true\n", "")
    if value:
        body = "archived: true\n" + body
    settings.write_text(body, encoding="utf-8")


def _regenerate(vault: Path) -> int:
    return cli.main(["regenerate-agents", str(vault), "--force"])


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    return build_minimal_vault(tmp_path, install_fake_agent=False)


def test_live_vault_carries_no_notice(vault: Path) -> None:
    for name, text in _read(vault).items():
        assert MARKER not in text, name


def test_fresh_render_of_an_archived_vault_carries_the_notice(vault: Path) -> None:
    _set_archived(vault, True)
    parsed = json.loads((vault / "_pipeline" / "spec-parse.json").read_text("utf-8"))
    render_all(SpecConfig.from_dict(parsed), vault)

    for name in ("CLAUDE.md", "AGENTS.md"):
        text = (vault / name).read_text(encoding="utf-8")
        assert MARKER in text, name
        assert "archived: false" in text, f"{name}: must say how to reverse it"


def test_regenerate_agents_adds_the_notice_to_all_three(vault: Path) -> None:
    _set_archived(vault, True)
    assert _regenerate(vault) == 0

    for name, text in _read(vault).items():
        assert MARKER in text, name
        assert "must not" in text.lower(), f"{name}: must forbid writing notes"
        assert "archived: false" in text, f"{name}: must say how to reverse it"


def test_notice_leads_the_file_so_it_cannot_be_missed(vault: Path) -> None:
    _set_archived(vault, True)
    _regenerate(vault)

    claude = (vault / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.index(MARKER) < claude.index("## Scope")


def test_regenerate_is_idempotent_and_reversible(vault: Path) -> None:
    live = _read(vault)

    _set_archived(vault, True)
    _regenerate(vault)
    once = _read(vault)
    _regenerate(vault)
    assert _read(vault) == once, "a second run must not stack notices"
    assert once["CLAUDE.md"].count(MARKER) == 1

    _set_archived(vault, False)
    _regenerate(vault)
    assert _read(vault) == live, "un-archiving must restore the original files"


def test_regenerate_preserves_hand_edits_outside_the_notice(vault: Path) -> None:
    claude = vault / "CLAUDE.md"
    claude.write_text(
        claude.read_text(encoding="utf-8") + "\nHAND-WRITTEN-LINE\n", encoding="utf-8"
    )
    _set_archived(vault, True)
    _regenerate(vault)
    assert "HAND-WRITTEN-LINE" in claude.read_text(encoding="utf-8")
