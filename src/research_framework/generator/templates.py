"""Render Jinja2 templates into a generated vault."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .._assets import asset_path
from ..pipeline.abstraction import resolve_forbidden_filename_prefixes
from ..spec.schema import SpecConfig


def _templates_src() -> Path:
    """Resolve the bundled ``templates/`` directory (packaged or dev)."""
    return asset_path("templates")


def _render_template_changelog(spec: SpecConfig) -> str:
    """Render ``_templates/CHANGELOG.md`` — the template version registry.

    Modelled on the ``codebase-vault`` convention
    (``~/Documents/codebase-vault/Codebase Vault/_templates/CHANGELOG.md``):
    a "Current Versions" table that the vault-health check consults to flag
    notes whose frontmatter ``template_version`` is older than what's listed
    here, plus a "Version History" section for future hand-edited entries.

    The initial entries are all ``1.0.0`` — the first generated vault ships
    at version 1. Bump via hand-edit when a template changes (agents must not
    self-bump; that decision belongs to the vault maintainer).
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    lines = [
        "---",
        'title: "Template Changelog"',
        "type: meta",
        f"updated: {today}",
        "---",
        "",
        "# Template Changelog",
        "",
        "Tracks changes to this vault's note templates. When a template changes,",
        "notes rendered from older versions can be detected by comparing their",
        "frontmatter ``template_version`` against the current version listed",
        "below.",
        "",
        "`scripts/vault_health.py --check-template-version` reads this table and",
        "reports (or, with `--apply`, upgrades) notes whose stamp is out of date.",
        "",
        "## Current Versions",
        "",
        "| Template | Version | Last Changed | Notes |",
        "|----------|---------|-------------|-------|",
    ]
    for nt in spec.note_types:
        lines.append(
            f"| {nt.name}.md | {nt.template_version} | {today} | Initial version |"
        )
    lines += [
        "",
        "## Version History",
        "",
        "Hand-edit this section when you change a template in ``_templates/``.",
        "Use SemVer: MINOR for additive changes (new section, new optional key),",
        "MAJOR for renames/removals that break existing notes.",
        "",
    ]
    for nt in spec.note_types:
        lines += [
            f"### {nt.name}.md",
            "",
            f"#### {nt.template_version} ({today})",
            f"- Initial template for ``{nt.name}`` notes.",
            "",
        ]
    return "\n".join(lines)


def _env(templates_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def render_scout_prompt(
    spec: SpecConfig,
    vault_dir: Path,
    target_topics: list[str] | None = None,
    exclude_topics: list[str] | None = None,
    templates_dir: Path | None = None,
) -> Path:
    """Re-render just `_pipeline/prompts/scout-prompt.md` with resume context.

    Used by the orchestrator on `--resume` cycles so the scout prompt includes
    the unmet expected filenames (target) and the already-covered set (exclude).
    """
    src = templates_dir or _templates_src()
    env = _env(src)
    prompt_path = vault_dir / "_pipeline" / "prompts" / "scout-prompt.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(
        env.get_template("prompts/scout-prompt.md.j2").render(
            spec=spec,
            target_topics=target_topics or [],
            exclude_topics=exclude_topics or [],
            forbidden_prefixes=resolve_forbidden_filename_prefixes(spec, vault_dir)
            or [],
        ),
        encoding="utf-8",
    )
    return prompt_path


def render_all(
    spec: SpecConfig,
    vault_dir: Path,
    templates_dir: Path | None = None,
    target_topics: list[str] | None = None,
    exclude_topics: list[str] | None = None,
) -> None:
    """Render all vault templates into `vault_dir` using `spec`.

    `target_topics` and `exclude_topics` are feature-002 resume-mode aids: they
    feed into the scout prompt template so a `--resume` cycle scouts only the
    unmet expected filenames and knows what to skip.
    """
    src = templates_dir or _templates_src()
    if not src.exists():
        raise FileNotFoundError(f"templates source directory not found: {src}")

    env = _env(src)
    prompt_ctx = {
        "spec": spec,
        "target_topics": target_topics or [],
        "exclude_topics": exclude_topics or [],
        # A vault that switched the gates off is not told about prefixes it
        # will never be graded on.
        "forbidden_prefixes": resolve_forbidden_filename_prefixes(spec, vault_dir)
        or [],
    }

    # Top-level files
    (vault_dir / "CLAUDE.md").write_text(
        env.get_template("CLAUDE.md.j2").render(spec=spec), encoding="utf-8"
    )
    (vault_dir / "AGENTS.md").write_text(
        env.get_template("AGENTS.md.j2").render(spec=spec), encoding="utf-8"
    )
    (vault_dir / "README.md").write_text(
        env.get_template("README.md.j2").render(spec=spec), encoding="utf-8"
    )
    (vault_dir / "vault-config.yaml").write_text(
        env.get_template("vault-config.yaml.j2").render(spec=spec), encoding="utf-8"
    )
    update_script = vault_dir / "update_vault.py"
    update_script.write_text(
        env.get_template("update_vault.py.j2").render(spec=spec),
        encoding="utf-8",
    )
    update_script.chmod(update_script.stat().st_mode | 0o755)

    # Index files (Layer 1 skeletons — populated later by indexer)
    (vault_dir / "_index.md").write_text(
        env.get_template("index-files/_index.md.j2").render(spec=spec),
        encoding="utf-8",
    )
    (vault_dir / "_concepts.md").write_text(
        env.get_template("index-files/_concepts.md.j2").render(spec=spec),
        encoding="utf-8",
    )
    (vault_dir / "_graph.md").write_text(
        env.get_template("index-files/_graph.md.j2").render(spec=spec),
        encoding="utf-8",
    )

    # Note-type templates + template CHANGELOG (M5).
    # Each note-type template stamps its ``template_version`` into generated
    # notes' frontmatter; CHANGELOG.md is the single source of truth the
    # vault-health check uses to detect outdated notes.
    templates_out = vault_dir / "_templates"
    templates_out.mkdir(exist_ok=True)
    note_type_tpl = env.get_template("note-type.md.j2")
    for nt in spec.note_types:
        (templates_out / f"{nt.name}.md").write_text(
            note_type_tpl.render(spec=spec, nt=nt), encoding="utf-8"
        )
    (templates_out / "CHANGELOG.md").write_text(
        _render_template_changelog(spec), encoding="utf-8"
    )

    # Prompts
    prompts_out = vault_dir / "_pipeline" / "prompts"
    prompts_out.mkdir(parents=True, exist_ok=True)
    (prompts_out / "scout-prompt.md").write_text(
        env.get_template("prompts/scout-prompt.md.j2").render(**prompt_ctx),
        encoding="utf-8",
    )
    (prompts_out / "dfs-prompt.md").write_text(
        env.get_template("prompts/dfs-prompt.md.j2").render(**prompt_ctx),
        encoding="utf-8",
    )

    # Every `.claude/commands/<name>.md` — the five pipeline agent definitions
    # and the three renameable slash commands — goes through one writer, so
    # `generate` and `regenerate-agents` cannot disagree about which template
    # owns a file or what it is called. `write_agents` renders ask/research/
    # write from `templates/commands/` (below `src`) and resolves their
    # destination stem from `spec.settings.commands`: a user who wants
    # /research-framework instead of /ask sets `commands.ask` in their spec and
    # gets `.claude/commands/research-framework.md`.
    from ..agents import write_agents

    write_agents(vault_dir, spec, overwrite=False)
