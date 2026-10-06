"""Render agent-definition templates for a given vault spec."""

import datetime
import types
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..pipeline.abstraction import effective_forbidden_filename_prefixes
from ..spec.schema import SpecConfig

_TEMPLATES_DIR = Path(__file__).parent
_AGENT_NAMES: tuple[str, ...] = (
    "scout",
    "research",
    "verify",
    "report",
    "extract",
    "pipeline",
    "ask",
    "write",
)

# The three commands a spec may rename. They are NOT rendered from this
# package: their one source is ``templates/commands/<name>.md.j2``, the source
# ``generate`` writes, and their destination stem comes from
# ``spec.settings.commands``. Rendering a second template to the same file
# under a fixed name is how a plain ``regenerate-agents`` used to swap a
# vault's ``/research`` personality, or leave a stray ``research.md`` beside a
# vault's renamed one (#252).
_RENAMEABLE_COMMANDS: tuple[str, ...] = ("ask", "research", "write")


def command_stems(spec: Any) -> dict[str, str]:
    """Return {command name: destination stem} for the renameable commands.

    A spec that declares no ``settings.commands`` — a ``SimpleNamespace``
    reconstructed from ``spec-parse.json``, say — keeps the default names.
    """
    commands = getattr(getattr(spec, "settings", None), "commands", None)
    return {
        name: str(getattr(commands, name, None) or name)
        for name in _RENAMEABLE_COMMANDS
    }


def _adapt_settings(spec: Any) -> Any:
    """Return ``spec.settings`` with ``commands`` guaranteed to be populated."""
    resolved = types.SimpleNamespace(**command_stems(spec))
    settings = getattr(spec, "settings", None)
    if settings is None:
        return types.SimpleNamespace(commands=resolved)
    adapted = types.SimpleNamespace(**vars(settings))
    adapted.commands = resolved
    return adapted


def _adapt_spec(spec: Any) -> Any:
    """Return a spec-like object compatible with all command templates.

    Two shapes have to render the same templates: ``SpecConfig`` instances
    (live CLI) and ``SimpleNamespace`` fakes (tests, and the fallback
    ``regenerate-agents`` builds from ``spec-parse.json``). Under
    ``StrictUndefined`` every attribute a template reaches for must exist, so
    the two the fakes routinely lack are synthesised here: flat
    ``scope_include`` / ``scope_exclude`` (``SpecConfig`` nests them under
    ``spec.scope``) and ``settings.commands``.
    """
    ns = types.SimpleNamespace(**vars(spec))
    if not (hasattr(spec, "scope_include") and hasattr(spec, "scope_exclude")):
        scope = getattr(spec, "scope", None)
        ns.scope_include = list(getattr(scope, "boundaries", []) or [])
        ns.scope_exclude = list(getattr(scope, "out_of_scope", []) or [])
    ns.settings = _adapt_settings(spec)
    return ns


def _make_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        keep_trailing_newline=True,
        undefined=StrictUndefined,
    )


def _render_renameable_command(command_name: str, spec: Any) -> str:
    """Render one renameable command from the generator's own template."""
    from ..generator.templates import _env, _templates_src

    env = _env(_templates_src())
    tmpl = env.get_template(f"commands/{command_name}.md.j2")
    return tmpl.render(spec=_adapt_spec(spec))


def render_agent(agent_name: str, spec: Any, *, today: str | None = None) -> str:
    """Render one agent template against *spec*; return the rendered text."""
    if agent_name not in _AGENT_NAMES:
        raise ValueError(f"unknown agent: {agent_name!r}; known: {_AGENT_NAMES}")
    if agent_name in _RENAMEABLE_COMMANDS:
        return _render_renameable_command(agent_name, spec)
    env = _make_env()
    tmpl = env.get_template(f"{agent_name}.md.j2")
    today_str = today or datetime.date.today().isoformat()
    return tmpl.render(spec=_adapt_spec(spec), today=today_str)


def render_all_agents(spec: Any, *, today: str | None = None) -> dict[str, str]:
    """Return {agent_name: rendered_text} for every agent in AGENT_NAMES."""
    return {name: render_agent(name, spec, today=today) for name in _AGENT_NAMES}


def write_agents(
    vault_root: Path,
    spec: Any,
    *,
    today: str | None = None,
    only: list[str] | None = None,
    overwrite: bool = False,
) -> list[Path]:
    """Render and write agent files into ``<vault_root>/.claude/commands/``.

    - ``only``: restrict to the named agents.
    - ``overwrite``: if False, skip files that already exist (the user-owned
      policy from spec 013 rule 7). The ``regenerate-agents`` CLI is the
      explicit channel to set this True.

    Returns the list of paths actually written.
    """
    commands_dir = vault_root / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    rendered = render_all_agents(spec, today=today)
    stems = command_stems(spec)
    written: list[Path] = []
    targets = set(only) if only else set(_AGENT_NAMES)
    for name, text in rendered.items():
        if name not in targets:
            continue
        target = commands_dir / f"{stems.get(name, name)}.md"
        if target.exists() and not overwrite:
            continue
        target.write_text(text, encoding="utf-8")
        written.append(target)
    return written


def _research_plan_block(vault_dir: Path) -> str:
    plan_path = vault_dir / "_pipeline" / "research-plan.md"
    if plan_path.is_file():
        body = plan_path.read_text(encoding="utf-8")
    else:
        body = "(no research plan available for this cycle)"
    return f"## Research Plan\n\n{body}\n\n"


def _forbidden_filename_prefixes_block(spec: SpecConfig) -> str:
    prefixes = effective_forbidden_filename_prefixes(spec)
    if not prefixes:
        return ""
    lines = [
        "## Forbidden filename prefixes",
        "",
        "Do NOT propose any topic whose canonical filename starts with any of:",
    ]
    for prefix in prefixes:
        lines.append(f"- {prefix}")
    lines.append("")
    return "\n".join(lines)


def _render_scout_prompt_template_text(spec: SpecConfig) -> str:
    from ..generator.templates import _env, _templates_src

    env = _env(_templates_src())
    return env.get_template("prompts/scout-prompt.md.j2").render(
        spec=spec,
        target_topics=[],
        exclude_topics=[],
        forbidden_prefixes=effective_forbidden_filename_prefixes(spec),
    )


def _render_dfs_prompt_template_text(spec: SpecConfig) -> str:
    from ..generator.templates import _env, _templates_src

    env = _env(_templates_src())
    return env.get_template("prompts/dfs-prompt.md.j2").render(
        spec=spec,
        target_topics=[],
        exclude_topics=[],
    )


def render_scout_prompt_for_cycle(vault_dir: Path, spec: SpecConfig) -> str:
    return "".join(
        (
            _research_plan_block(vault_dir),
            _forbidden_filename_prefixes_block(spec),
            _render_scout_prompt_template_text(spec),
        )
    )


def render_note_writer_prompt_for_cycle(vault_dir: Path, spec: SpecConfig) -> str:
    return _research_plan_block(vault_dir) + _render_dfs_prompt_template_text(spec)
