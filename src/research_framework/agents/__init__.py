"""Agent definition templates (Jinja2 .md.j2 files) and rendering helpers.

Each generic agent (`scout`, `research`, `verify`, `report`, `extract`,
`pipeline`, `ask`, `write`) ships as a framework template. The renderer
materialises them into `<vault>/.claude/commands/<name>.md` at scaffold
time, using values from the vault's `SpecConfig`.

Agent files in a vault stay user-owned after first write (per
specs/013-vault-migrator/lessons-learned.md rule 7). The framework's
explicit `regenerate-agents <vault>` subcommand is the opt-in channel
to refresh them when a vault wants upstream improvements.
"""

from __future__ import annotations

from pathlib import Path

from ._render import render_agent, render_all_agents, write_agents

__all__ = [
    "TEMPLATES_DIR",
    "AGENT_NAMES",
    "render_agent",
    "render_all_agents",
    "write_agents",
]

TEMPLATES_DIR = Path(__file__).parent

# Authoritative list of generic agent names. Each <name> in this tuple has
# a corresponding `<name>.md.j2` Jinja2 template alongside this module.
AGENT_NAMES: tuple[str, ...] = (
    "scout",
    "research",
    "verify",
    "report",
    "extract",
    "pipeline",
    "ask",
    "write",
)
