#!/usr/bin/env python3
"""Agent-template asset-reference guard (issue #256).

Agent templates (``src/research_framework/agents/*.md.j2``, the three
renameable ``templates/commands/*.md.j2``) name scripts (``scripts/verify.py``)
and other agent commands (``.claude/commands/research.md``) by file path, and
all of it is rendered blind: nothing checks that what a rendered template
*names* is something a generated vault actually *contains*. Two live defects
would have been caught by this guard before it existed: a dead
``scripts/verify.py`` step in every rendered ``/verify`` (#253), and a
``research.md`` two-source drift (#252).

``tests/agents/test_render.py`` already checks a fixed set of contracts, but
against a ``SimpleNamespace`` fake with the DEFAULT command names — which
cannot catch the specific class of bug this guard targets: a template that
hardcodes a renameable command's default filename. Three fixed-name agent
templates (``scout.md.j2``, ``pipeline.md.j2``, ``verify.md.j2``) hardcode
``.claude/commands/research.md`` in their ``related:`` frontmatter, but
``research`` is one of the three commands ``spec.settings.commands`` can
rename (spec 013) — a vault that renames it to, say, ``/dig`` gets a
``research.md`` reference that resolves to nothing. Rendering only ever
against the default names is exactly how that stays green forever.

This guard instead builds a REAL ``SpecConfig`` (deliberately with
``commands.research`` renamed away from its default, to reproduce the class
of bug above), runs it through the actual generator (``scaffold`` +
``render_all`` + ``copy_scripts``) into a throwaway vault, and asserts that
every ``scripts/*.py`` / ``scripts/*.sh`` and ``.claude/commands/*.md``
reference named by a rendered ``.claude/commands/*.md`` file resolves to a
real file in that generated vault. It also carries the two assertions #254
already added to the ``SimpleNamespace``-based render tests (no "Known
limitation" text, no baked absolute paths) so the real-vault path is covered
too, not only the fake one.

**Exit codes**: ``0`` clean · ``1`` on any finding.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

from research_framework.generator.scaffold import scaffold
from research_framework.generator.scripts import copy_scripts
from research_framework.generator.templates import render_all
from research_framework.spec.schema import (
    BudgetConfig,
    CommandsConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
    SpecSettings,
)

_SCRIPT_REF = re.compile(r"scripts/([A-Za-z0-9_.-]+\.(?:py|sh))")
# Deliberately scoped to the structured `related:` frontmatter entries
# (`  - path: ".claude/commands/research.md"`), not every free-form prose
# mention of a `.claude/commands/*.md` path — some of those are legitimate
# (e.g. pipeline.md.j2 documents `.claude/commands/pipeline.local.md` as a
# file the *user* may optionally create for a local override; that is never
# generated, and flagging it would be a false positive on working docs).
_COMMAND_REF = re.compile(r'-\s*path:\s*"\.claude/commands/([A-Za-z0-9_.-]+\.md)"')
# Mirrors tests/agents/test_render.py's contract (#254): a vault carries its
# commands with it, so nothing rendered may bake a machine-specific path.
_ABSOLUTE_PATH = re.compile(r"(?:^|[^:\w./])(/(?:Users|home|opt|tmp|var|usr|etc)/)")

# Deliberately not "research" — reproduces the #252-class bug where a fixed
# agent template hardcodes a renameable command's DEFAULT filename.
_RENAMED_RESEARCH_COMMAND = "dig"


def _build_spec(vault_dir: Path) -> SpecConfig:
    """A real (non-``SimpleNamespace``) SpecConfig for the guard's throwaway vault."""
    return SpecConfig(
        name="Agent Asset Guard Vault",
        location=vault_dir,
        owner="guard",
        scope=ScopeConfig(
            domain="guard-domain",
            organization="guard-org",
            out_of_scope=["unrelated-topic"],
        ),
        note_types=[
            NoteTypeConfig(
                name="concept",
                description="A guard-check concept note.",
                folder="01 - Concepts",
                min_word_count=30,
            )
        ],
        data_sources=[
            DataSourceConfig(
                name="guard-source",
                type="external",
                description="Guard-check source.",
                priority=1,
            )
        ],
        search_dimensions=["technical"],
        coverage_targets=CoverageTargets(
            categories=[
                CoverageCategory(
                    name="cat_a",
                    note_type="concept",
                    target_count=5,
                    met_count=0,
                    priority=80,
                )
            ]
        ),
        budget=BudgetConfig(),
        settings=SpecSettings(
            commands=CommandsConfig(research=_RENAMED_RESEARCH_COMMAND)
        ),
        forbidden_filename_prefixes=[],
    )


def generate_guard_vault(vault_dir: Path) -> SpecConfig:
    """Render a real, minimal vault into *vault_dir* via the actual generator."""
    spec = _build_spec(vault_dir)
    scaffold(spec, vault_dir, spec_source=None, settings_source=None)
    render_all(spec, vault_dir)
    copy_scripts(vault_dir)
    return spec


def check_agent_asset_references(vault_dir: Path) -> list[str]:
    """Return human-readable problems for every rendered command (empty if clean)."""
    commands_dir = vault_dir / ".claude" / "commands"
    scripts_dir = vault_dir / "scripts"
    command_files = sorted(commands_dir.glob("*.md"))

    problems: list[str] = []
    if not command_files:
        return [f"no rendered commands found under {commands_dir}"]

    for path in command_files:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(vault_dir)

        for ref in sorted(set(_SCRIPT_REF.findall(text))):
            if not (scripts_dir / ref).exists():
                problems.append(
                    f"{rel}: names scripts/{ref}, which the generated vault "
                    "does not contain"
                )

        for ref in sorted(set(_COMMAND_REF.findall(text))):
            if not (commands_dir / ref).exists():
                problems.append(
                    f"{rel}: names .claude/commands/{ref}, which the generated "
                    "vault does not contain (a renamed or retired command?)"
                )

        if "Known limitation" in text:
            problems.append(f"{rel}: stale 'Known limitation' disclaimer (#254)")
        if "unwired stub" in text:
            problems.append(f"{rel}: stale 'unwired stub' disclaimer (#254)")

        found = _ABSOLUTE_PATH.search(text)
        if found:
            problems.append(
                f"{rel}: bakes a machine-specific absolute path "
                f"{found.group(1)!r} (#254)"
            )

    return problems


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rf-agent-asset-guard-") as tmp:
        vault_dir = Path(tmp) / "vault"
        vault_dir.mkdir(parents=True, exist_ok=True)
        generate_guard_vault(vault_dir)
        problems = check_agent_asset_references(vault_dir)

    if problems:
        print(
            "[check_agent_asset_references] FAIL — a rendered agent command "
            "names an asset the generated vault does not contain:",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print(
        "[check_agent_asset_references] OK — every rendered "
        ".claude/commands/*.md reference (scripts/*.py, scripts/*.sh, "
        ".claude/commands/*.md) resolves in a generated vault; no stale "
        "disclaimers or baked absolute paths."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
