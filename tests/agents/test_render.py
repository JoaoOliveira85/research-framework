"""Tests for the agent renderer (_render.py)."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_framework._assets import asset_path
from research_framework.agents import (
    AGENT_NAMES,
    render_agent,
    render_all_agents,
    write_agents,
)


@pytest.fixture()
def fake_spec() -> SimpleNamespace:
    return SimpleNamespace(
        name="Test Vault",
        owner="Test Owner",
        location="/tmp/test-vault",
        vault_corpus_dir="test_notes",
        note_types=[
            SimpleNamespace(
                name="Concepts",
                folder="02 - Concepts",
                description="Concept notes",
                required_sections=["Summary", "Details"],
            ),
        ],
        scope_include=["AI tooling"],
        scope_exclude=["Sports"],
        data_sources=[
            {
                "name": "Import AI",
                "type": "newsletter",
                "role": "high-signal weekly digest",
            },
        ],
    )


# A rendered command is read by an agent inside a vault we do not control, so
# anything it names has to survive the vault being moved, cloned or renamed.
# These contracts are what the 2026-09-03 review found broken.
_ABSOLUTE_PATH = re.compile(r"(?:^|[^:\w./])(/(?:Users|home|opt|tmp|var|usr|etc)/)")
_SCRIPT_REF = re.compile(r"scripts/([A-Za-z0-9_.-]+\.(?:py|sh))")


def test_no_rendered_agent_bakes_an_absolute_path(fake_spec: SimpleNamespace) -> None:
    """No rendered command may name a machine-specific absolute path.

    A vault carries its commands with it; a baked path outlives the move.
    """
    for name, text in render_all_agents(fake_spec, today="2026-05-13").items():
        assert fake_spec.location not in text, f"{name}: baked spec.location"
        found = _ABSOLUTE_PATH.search(text)
        assert found is None, f"{name}: absolute path {found.group(1)!r}"


def test_no_rendered_agent_disclaims_a_wired_stage(fake_spec: SimpleNamespace) -> None:
    """Stage caveats rot the moment the stage is wired (PR #209 wired two)."""
    for name, text in render_all_agents(fake_spec, today="2026-05-13").items():
        assert "Known limitation" not in text, f"{name}: stale stage caveat"
        assert "unwired stub" not in text, f"{name}: stale stage caveat"


def test_no_rendered_agent_references_a_missing_script(
    fake_spec: SimpleNamespace,
) -> None:
    """Every `scripts/<name>` a command tells the agent to run must ship.

    A command that names a retired script is broken by construction in every
    vault generated after the retirement, and nothing else notices.
    """
    scripts_dir = asset_path("scripts")
    for name, text in render_all_agents(fake_spec, today="2026-05-13").items():
        for ref in sorted(set(_SCRIPT_REF.findall(text))):
            assert (scripts_dir / ref).exists(), (
                f"{name}: names scripts/{ref}, which the framework no longer ships"
            )


_RELATED_PATH = re.compile(r'-\s*path:\s*"\.claude/commands/([A-Za-z0-9_.-]+\.md)"')


def test_related_frontmatter_follows_a_renamed_research_command(
    fake_spec: SimpleNamespace,
) -> None:
    """A `related:` path to the research command must track its rename.

    `research` is one of the three renameable commands
    (`spec.settings.commands.research`); `scout.md.j2`, `pipeline.md.j2` and
    `verify.md.j2` each name it in their `related:` frontmatter. Before #256
    those three hardcoded the literal ``.claude/commands/research.md`` — a
    vault that renamed `/research` (e.g. to `/dig`) got a dangling reference,
    since only `.claude/commands/dig.md` exists once `write_agents` renders
    the rename (the same class of two-source drift #252 fixed for
    `research.md` itself).
    """
    fake_spec.settings = SimpleNamespace(
        commands=SimpleNamespace(ask="ask", research="dig", write="write")
    )
    rendered = render_all_agents(fake_spec, today="2026-05-13")
    for name in ("scout", "pipeline", "verify"):
        refs = set(_RELATED_PATH.findall(rendered[name]))
        assert "research.md" not in refs, (
            f"{name}: related: frontmatter still names the pre-rename 'research.md'"
        )
        assert "dig.md" in refs, (
            f"{name}: related: frontmatter does not track the renamed research command"
        )


RENAMEABLE = ("ask", "research", "write")


def test_renameable_commands_render_from_the_generator_source(
    fake_spec: SimpleNamespace,
) -> None:
    """`/ask`, `/research` and `/write` have one source: `templates/commands/`.

    That is the source `generate` writes. A second agent template rendering to
    the same file under a fixed name is how a plain `regenerate-agents` used to
    swap a vault's `/research` personality (#252).
    """
    from research_framework.generator.templates import _env, _templates_src

    fake_spec.settings = SimpleNamespace(
        commands=SimpleNamespace(ask="ask", research="research", write="write")
    )
    env = _env(_templates_src())
    for name in RENAMEABLE:
        expected = env.get_template(f"commands/{name}.md.j2").render(spec=fake_spec)
        assert render_agent(name, fake_spec, today="2026-05-13") == expected


def test_write_agents_honours_configured_command_names(
    tmp_path: Path, fake_spec: SimpleNamespace
) -> None:
    """A renamed command keeps its name through a regenerate.

    Writing `research.md` beside a vault's customised `dig.md` leaves two
    research commands and no way for the reader to tell which one is live.
    """
    fake_spec.settings = SimpleNamespace(
        commands=SimpleNamespace(ask="consult", research="dig", write="draft")
    )
    write_agents(tmp_path, fake_spec, today="2026-05-13", overwrite=True)

    commands_dir = tmp_path / ".claude" / "commands"
    for stem in ("consult", "dig", "draft"):
        assert (commands_dir / f"{stem}.md").exists()
    for stem in RENAMEABLE:
        assert not (commands_dir / f"{stem}.md").exists()


def test_render_agent_returns_nonempty_string(fake_spec: SimpleNamespace) -> None:
    """render_agent returns a non-empty string with no unrendered Jinja markers."""
    text = render_agent("scout", fake_spec, today="2026-05-13")
    assert text, "rendered output must not be empty"
    assert not re.search(r"\{\{.*?\}\}", text), "unrendered {{ }} expression found"
    assert not re.search(r"\{%.*?%\}", text), "unrendered {% %} tag found"


def test_render_agent_unknown_raises() -> None:
    """render_agent raises ValueError for an unknown agent name."""
    with pytest.raises(ValueError, match="unknown agent"):
        render_agent("nonexistent", object())


def test_render_all_agents_returns_eight_keys(fake_spec: SimpleNamespace) -> None:
    """render_all_agents returns exactly the 8 AGENT_NAMES keys."""
    result = render_all_agents(fake_spec, today="2026-05-13")
    assert set(result.keys()) == set(AGENT_NAMES)
    assert len(result) == 8


def test_write_agents_fresh_vault_writes_eight(
    tmp_path: Path, fake_spec: SimpleNamespace
) -> None:
    """write_agents writes all 8 files when none exist yet."""
    written = write_agents(tmp_path, fake_spec, today="2026-05-13")
    assert len(written) == 8
    commands_dir = tmp_path / ".claude" / "commands"
    for name in AGENT_NAMES:
        assert (commands_dir / f"{name}.md").exists()


def test_write_agents_no_overwrite_when_files_exist(
    tmp_path: Path, fake_spec: SimpleNamespace
) -> None:
    """write_agents skips files that already exist when overwrite=False (default)."""
    # Pre-create all eight files.
    commands_dir = tmp_path / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    for name in AGENT_NAMES:
        (commands_dir / f"{name}.md").write_text("original", encoding="utf-8")

    written = write_agents(tmp_path, fake_spec, today="2026-05-13")
    assert written == []
    # Content unchanged.
    for name in AGENT_NAMES:
        assert (commands_dir / f"{name}.md").read_text() == "original"


def test_write_agents_overwrite_true_rewrites_all(
    tmp_path: Path, fake_spec: SimpleNamespace
) -> None:
    """write_agents overwrites all 8 files when overwrite=True."""
    commands_dir = tmp_path / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    for name in AGENT_NAMES:
        (commands_dir / f"{name}.md").write_text("original", encoding="utf-8")

    written = write_agents(tmp_path, fake_spec, today="2026-05-13", overwrite=True)
    assert len(written) == 8
    for name in AGENT_NAMES:
        content = (commands_dir / f"{name}.md").read_text()
        assert content != "original"


def test_write_agents_only_writes_one(
    tmp_path: Path, fake_spec: SimpleNamespace
) -> None:
    """write_agents with only=['scout'] writes exactly one file."""
    written = write_agents(tmp_path, fake_spec, today="2026-05-13", only=["scout"])
    assert len(written) == 1
    assert written[0].name == "scout.md"
    commands_dir = tmp_path / ".claude" / "commands"
    assert (commands_dir / "scout.md").exists()
    for name in AGENT_NAMES:
        if name != "scout":
            assert not (commands_dir / f"{name}.md").exists()
