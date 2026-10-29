"""`./vault update` re-renders outdated stage prompts (#12).

`_pipeline/prompts/{scout,dfs}-prompt.md` are rendered into a vault at
scaffold time. Before this, nothing re-rendered the DFS prompt in an existing
vault, so a vault scaffolded on DFS template v1 never received the note
writer's batch-only rule or the `skipped_topics` contract; an upgrade rehearsal
on ten real vaults left all ten on v1.

The refresh runs inside `vault_update.sync_vault_scripts` because that is the
post-upgrade hook every existing vault's `./vault update` already calls — a
new hook in the shim template would only reach vaults whose shim is
regenerated. A prompt is re-rendered only when its recorded
`_template_version` is older than the shipped template's; a file with no
recorded version is not a framework render and is left alone; the replaced
bytes are kept in `_pipeline/prompts/.previous/`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from research_framework.generator.templates import render_all, render_stage_prompt
from research_framework.pipeline.template_drift import read_template_version
from research_framework.pipeline.vault_update import (
    refresh_vault_prompts,
    shipped_prompt_version,
    sync_vault_scripts,
)
from tests._helpers.vault_factory import build_minimal_vault

_PROMPTS = Path("_pipeline") / "prompts"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return build_minimal_vault(tmp_path, install_fake_agent=False)


def _downgrade(path: Path, version: int) -> bytes:
    """Make *path* look like a render of an older template version."""
    text = path.read_text(encoding="utf-8")
    old = re.sub(
        r"^_template_version: \d+$",
        f"_template_version: {version}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    old = old.replace("skipped_topics", "OLD-TEMPLATE-TEXT")
    path.write_text(old, encoding="utf-8")
    return old.encode("utf-8")


def test_update_re_renders_an_outdated_dfs_prompt(vault: Path) -> None:
    dfs = vault / _PROMPTS / "dfs-prompt.md"
    fresh = dfs.read_bytes()
    old = _downgrade(dfs, 1)

    changed = sync_vault_scripts(vault)

    assert dfs.read_bytes() == fresh
    assert read_template_version(dfs) == shipped_prompt_version("dfs-prompt.md")
    assert (vault / _PROMPTS / ".previous" / "dfs-prompt.md").read_bytes() == old
    assert "_pipeline/prompts/dfs-prompt.md" in changed


def test_a_current_prompt_is_left_untouched(vault: Path) -> None:
    dfs = vault / _PROMPTS / "dfs-prompt.md"
    before = dfs.read_bytes()

    assert refresh_vault_prompts(vault) == []
    assert dfs.read_bytes() == before
    assert not (vault / _PROMPTS / ".previous").exists()


def test_a_prompt_without_a_recorded_version_is_not_overwritten(vault: Path) -> None:
    """No `_template_version` means it is not a framework render."""
    dfs = vault / _PROMPTS / "dfs-prompt.md"
    dfs.write_text("My own note-writer prompt.\n", encoding="utf-8")

    assert refresh_vault_prompts(vault) == []
    assert dfs.read_text(encoding="utf-8") == "My own note-writer prompt.\n"


def test_a_prompt_newer_than_the_shipped_template_is_not_overwritten(
    vault: Path,
) -> None:
    dfs = vault / _PROMPTS / "dfs-prompt.md"
    newer = _downgrade(dfs, shipped_prompt_version("dfs-prompt.md") + 1)

    assert refresh_vault_prompts(vault) == []
    assert dfs.read_bytes() == newer


def test_both_stage_prompts_are_refreshed(vault: Path) -> None:
    for name in ("scout-prompt.md", "dfs-prompt.md"):
        _downgrade(vault / _PROMPTS / name, 1)

    assert sorted(refresh_vault_prompts(vault)) == [
        "_pipeline/prompts/dfs-prompt.md",
        "_pipeline/prompts/scout-prompt.md",
    ]


def test_without_a_readable_spec_nothing_is_touched(vault: Path) -> None:
    (vault / "_pipeline" / "spec-parse.json").unlink()
    dfs = vault / _PROMPTS / "dfs-prompt.md"
    old = _downgrade(dfs, 1)

    assert refresh_vault_prompts(vault) == []
    assert dfs.read_bytes() == old


def test_the_script_opt_out_does_not_stop_the_prompt_refresh(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RV_SKIP_SCRIPT_SYNC", "1")
    _downgrade(vault / _PROMPTS / "dfs-prompt.md", 1)

    assert sync_vault_scripts(vault) == ["_pipeline/prompts/dfs-prompt.md"]


@pytest.mark.parametrize("name", ["scout-prompt.md", "dfs-prompt.md"])
def test_render_stage_prompt_matches_what_generate_writes(
    vault: Path, tmp_path: Path, name: str
) -> None:
    """The update renderer and `render_all` must not drift apart."""
    from research_framework.pipeline.vault_update import _load_spec_parse

    spec = _load_spec_parse(vault)
    assert spec is not None
    out = tmp_path / "fresh"
    render_all(spec, out)

    assert render_stage_prompt(spec, out, name) == (out / _PROMPTS / name).read_text(
        encoding="utf-8"
    )
