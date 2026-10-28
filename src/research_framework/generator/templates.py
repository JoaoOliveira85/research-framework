"""Render Jinja2 templates into a generated vault."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .._assets import asset_path
from ..pipeline.abstraction import resolve_forbidden_filename_prefixes
from ..spec.schema import NoteTypeConfig, SpecConfig


def _templates_src() -> Path:
    """Resolve the bundled ``templates/`` directory (packaged or dev)."""
    return asset_path("templates")


TEMPLATE_REGISTRY = "CHANGELOG.md"
"""The template version registry, ``<vault>/_templates/CHANGELOG.md``."""

_TABLE_HEADER = "| Template | Version | Last Changed | Notes |"


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _render_template_changelog(spec: SpecConfig) -> str:
    """Render a fresh ``_templates/CHANGELOG.md`` — the template version registry.

    Modelled on the ``codebase-vault`` convention
    (``~/Documents/codebase-vault/Codebase Vault/_templates/CHANGELOG.md``):
    a "Current Versions" table that the vault-health check consults to flag
    notes whose frontmatter ``template_version`` is older than what's listed
    here, plus a "Version History" section for hand-edited entries.

    The initial entries carry each note type's ``template_version``. An existing
    registry is never regenerated from scratch: see :func:`_merge_template_changelog`.
    """
    today = _today()
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
        _TABLE_HEADER,
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


def _merge_template_changelog(spec: SpecConfig, existing: str) -> str:
    """Bring an existing registry up to *spec* without discarding what is in it.

    The templates are re-rendered on every scaffold and ``./vault update``, but
    the registry also carries a hand-edited "Version History", so it is merged,
    not replaced: a note type whose version is new or has changed gets its table
    row rewritten and a history entry appended; every other line is kept
    verbatim. Nothing changed means the text comes back byte-identical.
    """
    lines = existing.split("\n")
    today = _today()
    changed = False

    def _row(i: int) -> list[str]:
        return [c.strip() for c in lines[i].strip().strip("|").split("|")]

    try:
        header = next(i for i, ln in enumerate(lines) if ln.strip() == _TABLE_HEADER)
    except StopIteration:
        return _render_template_changelog(spec)
    first = header + 2  # skip the header and its separator
    last = first - 1
    while last + 1 < len(lines) and lines[last + 1].lstrip().startswith("|"):
        last += 1
    rows = {_row(i)[0]: i for i in range(first, last + 1)}

    history: list[tuple[str, str, str]] = []  # (key, version, note)
    appended: list[str] = []
    for nt in spec.note_types:
        key = f"{nt.name}.md"
        version = nt.template_version
        if key in rows:
            previous = _row(rows[key])[1]
            if previous == version:
                continue
            lines[rows[key]] = (
                f"| {key} | {version} | {today} | Version {previous} to {version} |"
            )
            history.append((key, version, f"Re-rendered; version was {previous}."))
        else:
            appended.append(f"| {key} | {version} | {today} | Initial version |")
            history.append((key, version, f"Initial template for ``{nt.name}`` notes."))
        changed = True
    lines[last + 1 : last + 1] = appended

    for key, version, note in history:
        entry = ["", f"#### {version} ({today})", f"- {note}"]
        try:
            at = next(i for i, ln in enumerate(lines) if ln.strip() == f"### {key}")
        except StopIteration:
            lines += ["", f"### {key}", *entry, ""]
            continue
        end = next(
            (
                i
                for i in range(at + 1, len(lines))
                if lines[i].startswith(("## ", "### "))
            ),
            len(lines),
        )
        while end > at + 1 and not lines[end - 1].strip():
            end -= 1  # insert after the block's last content line
        lines[end:end] = entry

    if not changed:
        return existing
    merged = "\n".join(lines)
    return re.sub(r"(?m)^updated: .*$", f"updated: {today}", merged, count=1)


def _write_if_changed(path: Path, text: str) -> bool:
    """Write *text* unless the file already holds it. True when written."""
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.write_text(text, encoding="utf-8")
    return True


def render_note_type_templates(
    spec: SpecConfig, vault_dir: Path, templates_dir: Path | None = None
) -> list[Path]:
    """Render ``<vault>/_templates/<type>.md`` plus the version registry.

    The single renderer for note templates. They are framework-owned: this runs
    on scaffold and on ``./vault update`` and always re-renders, overwriting any
    operator edit, so a section added to the spec reaches a vault scaffolded
    earlier. Files that already hold the rendered text are left untouched.

    Returns the paths actually written.
    """
    env = _env(templates_dir or _templates_src())
    out = vault_dir / "_templates"
    out.mkdir(parents=True, exist_ok=True)
    note_type_tpl = env.get_template("note-type.md.j2")
    written: list[Path] = []
    for nt in spec.note_types:
        path = out / f"{nt.name}.md"
        if _write_if_changed(path, note_type_tpl.render(spec=spec, nt=nt)):
            written.append(path)
    registry = out / TEMPLATE_REGISTRY
    try:
        existing = registry.read_text(encoding="utf-8")
    except OSError:
        existing = None
    text = (
        _render_template_changelog(spec)
        if existing is None
        else _merge_template_changelog(spec, existing)
    )
    if _write_if_changed(registry, text):
        written.append(registry)
    return written


def _legacy_corpus_template(nt: NoteTypeConfig) -> str:
    """What the removed ``<corpus>/_templates/`` writer emitted for *nt*.

    Kept only so :func:`remove_legacy_corpus_templates` can recognise a file the
    framework wrote; nothing renders from it.
    """
    lines = [
        f"# {nt.name}",
        "",
        f"> Template for {nt.name} notes. Required sections below.",
        "",
    ]
    for section in nt.required_sections:
        lines += [f"## {section}", ""]
    lines += ["### Contextual questions", ""]
    lines += [f"- {q}" for q in nt.contextual_questions]
    lines.append("")
    return "\n".join(lines)


def remove_legacy_corpus_templates(spec: SpecConfig, vault_dir: Path) -> list[str]:
    """Delete the corpus-level templates an older framework wrote.

    Before issue #20 scaffold also wrote a second, section-only skeleton per note
    type to ``<corpus>/_templates/<type>.md``. A file is removed only when it
    holds exactly the text that writer produced for a note type of *spec*, so an
    operator's own file — or one they edited — is never touched. The directory
    goes too, but only if that leaves it empty.

    Returns the removed paths, relative to *vault_dir* with ``/`` separators.
    """
    tmpl_dir = vault_dir / spec.vault_corpus_dir / "_templates"
    if not tmpl_dir.is_dir():
        return []
    removed: list[str] = []
    for nt in spec.note_types:
        path = tmpl_dir / f"{nt.name.replace(' ', '_').lower()}.md"
        try:
            if path.read_text(encoding="utf-8") != _legacy_corpus_template(nt):
                continue
            path.unlink()
        except OSError:
            continue
        removed.append(path.relative_to(vault_dir).as_posix())
    try:
        tmpl_dir.rmdir()
    except OSError:
        pass  # not empty: the operator has files there
    return removed


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

    from ..agents._render import citation_roles

    # Top-level files
    (vault_dir / "CLAUDE.md").write_text(
        env.get_template("CLAUDE.md.j2").render(
            spec=spec, citation_roles=citation_roles(spec)
        ),
        encoding="utf-8",
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

    # Note-type templates + template CHANGELOG (M5): the one renderer, shared
    # with scaffold and `./vault update`.
    render_note_type_templates(spec, vault_dir, src)

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
