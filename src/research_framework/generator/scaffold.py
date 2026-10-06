"""Create vault directory structure from a SpecConfig."""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .. import __version__ as _FRAMEWORK_VERSION
from .._assets import asset_path, default_settings_path
from ..spec.schema import NoteTypeConfig, SpecConfig


def _template_stem(nt: NoteTypeConfig) -> str:
    return nt.name.replace(" ", "_").lower()


def _write_data_vault_index_placeholders(data_vault: Path) -> None:
    """Seed ``_index.md`` / ``_concepts.md`` / ``_graph.md`` under the corpus root.

    Idempotent: never overwrites existing files (``rebuild_all`` replaces them later).
    """
    stubs = {
        "_index.md": (
            "# Index\n\n"
            "Placeholder — run the vault indexer to regenerate this file from notes.\n"
        ),
        "_concepts.md": (
            "# Concepts\n\n"
            "Placeholder — coverage-oriented view; populated by the indexer.\n"
        ),
        "_graph.md": (
            "# Graph\n\n"
            "Placeholder — cross-links between notes; populated by the indexer.\n"
        ),
    }
    for name, text in stubs.items():
        p = data_vault / name
        if not p.exists():
            p.write_text(text, encoding="utf-8")


def _write_data_vault_note_type_templates(
    data_vault: Path, note_types: list[NoteTypeConfig]
) -> None:
    """Emit one Markdown template per note type under ``data_vault/_templates/``.

    Idempotent: skips files that already exist so user edits survive re-scaffold.
    """
    tmpl_root = data_vault / "_templates"
    tmpl_root.mkdir(parents=True, exist_ok=True)
    for nt in note_types:
        dest = tmpl_root / f"{_template_stem(nt)}.md"
        if dest.exists():
            continue
        lines = [
            f"# {nt.name}",
            "",
            f"> Template for {nt.name} notes. Required sections below.",
            "",
        ]
        for section in nt.required_sections:
            lines.append(f"## {section}")
            lines.append("")
        lines.append("### Contextual questions")
        lines.append("")
        for q in nt.contextual_questions:
            lines.append(f"- {q}")
        lines.append("")
        dest.write_text("\n".join(lines), encoding="utf-8")


def should_preserve_user_owned_file(vault_dir: Path, rel_path: str) -> bool:
    """Return True when an existing manifest-tracked file must not be overwritten."""
    target = vault_dir / rel_path
    if not target.is_file():
        return False
    from ..pipeline.scaffold_manifest import default_manifest_path, load_manifest
    from ..pipeline.vault_update import is_user_owned

    snapshot = vault_dir / "_pipeline" / "scaffold-manifest-snapshot.json"
    if snapshot.is_file():
        try:
            manifest = json.loads(snapshot.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = load_manifest(default_manifest_path())
    else:
        manifest = load_manifest(default_manifest_path())
    return is_user_owned(manifest, rel_path)


def _render_vault_gitignore(corpus: str) -> str:
    """Return the scaffold's ``.gitignore`` body.

    Tracks the corpus **and the four spec-058 control files**; everything else
    (``scripts/``, ``raw_data/``, ``.venv/``, per-cycle ``_pipeline`` artifacts)
    is regenerable and stays out of version history.

    The control-file re-includes were added 2026-08-27. Before that this file
    was ``/*`` plus a corpus re-include, which git-ignored ``research.spec.md``,
    ``settings.yaml`` and the two ``_pipeline`` control files — precisely the
    set ``vault_health.scan_control_file_git_tracking`` warns about. The
    framework was generating the condition it then warned about, and every one
    of five live vaults reported ``WARN IGNORED research.spec.md``. Worse, an
    operator editing their own spec had no version history for it.

    ``_pipeline`` needs the three-step dance because git cannot re-include a
    file whose parent directory is excluded: un-ignore the directory, re-exclude
    its contents, then un-exclude the two files by name.
    """
    return (
        f"# research-framework: track {corpus}/ + the control files; "
        "everything else is ephemeral.\n"
        "/*\n"
        "!.gitignore\n"
        f"!{corpus}/\n"
        f"!{corpus}/**\n"
        "# Operator-authored control files — these are your inputs, so they are\n"
        "# versioned (spec 058 warns when they are not).\n"
        "!research.spec.md\n"
        "!settings.yaml\n"
        "# `_pipeline/` is regenerable EXCEPT the two control files below. Git\n"
        "# cannot re-include a path under an excluded directory, hence the\n"
        "# un-ignore / re-exclude / un-exclude sequence.\n"
        "!_pipeline/\n"
        "_pipeline/*\n"
        "!_pipeline/research-backlog.md\n"
        "!_pipeline/coverage-targets.json\n"
    )


def scaffold(
    spec: SpecConfig,
    vault_dir: Path,
    *,
    spec_source: Path | None = None,
    settings_source: Path | None = None,
) -> None:
    """Create the full vault directory tree and _pipeline skeleton files.

    Self-containment additions:

    - `spec_source` (optional): the spec file the user passed on the CLI.
      When provided, it is copied verbatim to `{vault_dir}/research.spec.md`
      so the vault carries its own declaration of intent and can be re-run
      (`research-framework generate --resume --spec ./research.spec.md`) without
      referencing the original path.
    - `settings_source` (optional): the `settings.yaml` to copy to
      `{vault_dir}/settings.yaml`. Defaults to the generator's bundled
      `settings.yaml` so every fresh vault has the current defaults.

    Both copies happen at vault root and are `.gitignore`d (tracked vs
    data_vault/ only), so the vault's git history stays clean.
    """
    vault_dir.mkdir(parents=True, exist_ok=True)

    # Raw-data mirror lives INSIDE the vault so any agent running with
    # the vault as its workdir (Codex ``--sandbox workspace-write``, for
    # example) can write captures without tripping the sandbox. Acts as
    # the offline fallback store for ``scripts/vault_health.py``: when an
    # external URL 404s, the health check prefers a local mirror under
    # raw_data/ before reaching out to archive.org. The vault's
    # .gitignore excludes it so tracked history stays limited to
    # data_vault/.
    raw_data_dir = vault_dir / "raw_data"
    raw_data_dir.mkdir(parents=True, exist_ok=True)
    readme = raw_data_dir / "README.md"
    if not readme.exists():
        readme.write_text(
            "---\n_template_version: 1\n---\n"
            "# Raw Data Mirror\n\n"
            "Offline mirror of every external artefact this vault cites. The\n"
            "scout and DFS prompts call `scripts/raw_capture.py <url>` before\n"
            "writing a note that references a URL; the capture lands here with\n"
            "a `meta.json` sidecar recording `url`, `accessed`, `source_type`.\n\n"
            "`scripts/vault_health.py` looks here first when an external URL\n"
            "breaks — see Principle IX (Vault-First Citation) in the vault's\n"
            "CLAUDE.md for why the raw mirror exists at all.\n\n"
            "Layout: `raw_data/{year}/{month}/{slug}-{short-hash}.{ext}` plus\n"
            "a sibling `meta.json` per artefact. Files in this folder are\n"
            "write-once — never hand-edit; rerun `raw_capture.py` to refresh.\n",
            encoding="utf-8",
        )
    (raw_data_dir / ".gitignore").write_text(
        "# raw_data/ stays out of git: it can be large and is regenerable.\n"
        "# The vault's .gitignore also excludes it (tracked vs data_vault/ only).\n"
        "*\n!.gitignore\n!README.md\n",
        encoding="utf-8",
    )
    (raw_data_dir / ".tmpl-versions.json").write_text(
        json.dumps({".gitignore": 1}, indent=2) + "\n", encoding="utf-8"
    )

    # corpus/{folder}/ per note type — name comes from spec.vault_corpus_dir
    data_vault = vault_dir / spec.vault_corpus_dir
    data_vault.mkdir(exist_ok=True)
    for nt in spec.note_types:
        (data_vault / nt.folder).mkdir(parents=True, exist_ok=True)

    _write_data_vault_index_placeholders(data_vault)
    _write_data_vault_note_type_templates(data_vault, spec.note_types)

    (vault_dir / "_templates").mkdir(exist_ok=True)

    # .claude/commands/ for /ask + /research + /write slash commands.
    (vault_dir / ".claude" / "commands").mkdir(parents=True, exist_ok=True)

    # Write .claude/settings.json — pre-authorises all normal operational
    # tool calls so Claude Code can run autonomously inside this vault.
    _write_claude_settings(vault_dir)

    # Write vault/vault script — unified entry point callable from systemd/cron/Shortcuts.
    _write_vault_script(vault_dir, spec)

    # Seed sources.db with spec-declared sources (locked — never auto-archived).
    from ..pipeline.source_manager import seed as _seed_sources

    _seed_sources(vault_dir, spec)

    # .cursor/cli.json — per-repo override that blanket-allows Shell tool
    # calls in this vault. The vault is its own git repo (see
    # _init_vault_git below), so Cursor's CLI walks cli.json from this
    # directory down to the user's cwd — an override placed at the vault
    # root therefore applies to every command run inside the vault but
    # nowhere else. The intent is to let long unattended cycle runs
    # (``rv generate --resume``) proceed without per-command approval
    # prompts while leaving the user's global Cursor config untouched.
    # Delete ``.cursor/cli.json`` to opt out.
    cursor_cli = vault_dir / ".cursor"
    cursor_cli.mkdir(exist_ok=True)
    cli_json = cursor_cli / "cli.json"
    if not cli_json.exists():
        cli_json.write_text(
            "{\n"
            '  "permissions": {\n'
            '    "allow": [\n'
            '      "Shell(**)"\n'
            "    ],\n"
            '    "deny": []\n'
            "  }\n"
            "}\n",
            encoding="utf-8",
        )

    corpus = spec.vault_corpus_dir
    gitignore = vault_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_render_vault_gitignore(corpus), encoding="utf-8")

    pipeline = vault_dir / "_pipeline"
    pipeline.mkdir(exist_ok=True)
    (pipeline / "cycles").mkdir(exist_ok=True)
    (pipeline / "prompts").mkdir(exist_ok=True)
    (pipeline / "corrections").mkdir(exist_ok=True)

    # Initialize budget-log.md.
    # Header columns must match the row format written by
    # research_framework.pipeline.orchestrator._append_budget_log — a mismatch
    # produces malformed tables that survive across resume runs.
    budget_log = pipeline / "budget-log.md"
    if not budget_log.exists():
        budget_log.write_text(
            "---\n_template_version: 1\n---\n"
            "# Budget Log\n\n"
            "Budget + cycle caps are configured in `settings.yaml` "
            "(`pipeline.max_cycles` / `pipeline.budget_usd`) and overridable per "
            "run via `--max-cycles` / `--max-usd` (spec 061).\n\n"
            "One row per completed cycle. Appends across `--resume` runs.\n\n"
            "| Timestamp | Cycle | Notes Created | Cycle Cost USD | Cumulative USD |\n"
            "|-----------|-------|---------------|----------------|----------------|\n",
            encoding="utf-8",
        )

    # Initialize research-backlog.md
    backlog = pipeline / "research-backlog.md"
    if not backlog.exists():
        backlog.write_text(
            "---\n_template_version: 1\n---\n"
            "# Research Backlog\n\nTopics deferred from scout passes.\n",
            encoding="utf-8",
        )

    # Initialize coverage-targets.json from spec targets. ``display_name`` is
    # carried forward so the per-category classifier in pipeline/coverage.py
    # has the human-readable label to match notes against — without it the
    # classifier would fall back to pure round-robin on the slugified name.
    coverage_data = {
        "last_updated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cycle_number": 0,
        "categories": [
            {
                "name": cat.name,
                "note_type": cat.note_type,
                "target_count": cat.target_count,
                "met_count": 0,
                "required": cat.required,
                "display_name": cat.display_name,
            }
            for cat in spec.coverage_targets.categories
        ],
    }
    (pipeline / "coverage-targets.json").write_text(
        json.dumps(coverage_data, indent=2) + "\n", encoding="utf-8"
    )

    # Write spec-parse.json
    (pipeline / "spec-parse.json").write_text(
        json.dumps(spec.to_dict(), indent=2, default=str) + "\n", encoding="utf-8"
    )

    # .tmpl-versions.json — one per directory containing non-markdown scaffold
    # files. Each maps filename → template_version (integer). Written here so
    # the vault migrator (spec 013) can detect and upgrade generated artefacts.
    (vault_dir / ".tmpl-versions.json").write_text(
        json.dumps(
            {
                "settings.yaml": 1,
                "vault-config.yaml": 1,
                "vault": 1,
                "update_vault.py": 1,
                ".gitignore": 1,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (vault_dir / ".claude" / ".tmpl-versions.json").write_text(
        json.dumps({"settings.json": 1}, indent=2) + "\n", encoding="utf-8"
    )
    (vault_dir / ".cursor" / ".tmpl-versions.json").write_text(
        json.dumps({"cli.json": 1}, indent=2) + "\n", encoding="utf-8"
    )
    (pipeline / ".tmpl-versions.json").write_text(
        json.dumps(
            {
                "coverage-targets.json": 1,
                "spec-parse.json": 1,
                "sources.db": 1,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # Self-containment: copy the source spec + settings.yaml in so the vault
    # carries its own configuration and can be re-run without the generator
    # repo on PATH (once the `research-framework` CLI is installed).
    #
    # A common user pattern is to draft `research.spec.md` inside the bundle
    # directory and then pass the same directory as ``--output``. In that case
    # ``spec_source`` and ``vault_dir/research.spec.md`` resolve to the same
    # file and ``shutil.copy2`` raises SameFileError. Silently skip the copy
    # when source and destination are identical — the file is already where
    # it needs to be.
    if spec_source is not None and spec_source.exists():
        dst = vault_dir / "research.spec.md"
        if spec_source.resolve() != dst.resolve():
            shutil.copy2(spec_source, dst)

    settings_src = (
        settings_source if settings_source is not None else default_settings_path()
    )
    if settings_src.exists():
        dst = vault_dir / "settings.yaml"
        if settings_src.resolve() != dst.resolve():
            if not should_preserve_user_owned_file(vault_dir, "settings.yaml"):
                shutil.copy2(settings_src, dst)

    # Initialize git at the vault root *now* — before any cycle runs.
    # Rationale:
    #   1. Codex CLI's default sandbox refuses to execute in directories
    #      that aren't a trusted git repo. Initialising here means cycle 1
    #      already runs inside a repo Codex will accept, removing a
    #      `--skip-git-repo-check` requirement from the happy path.
    #   2. It matches the "commit per cycle" intent — each cycle can
    #      produce a distinct commit over the initial scaffold baseline,
    #      so rolling back to any cycle is `git reset` instead of
    #      blowing the vault away.
    #   3. If git is not installed or init fails, the vault still works;
    #      the runtime dispatcher's sandbox flags (see
    #      settings.codex.yaml) are the belt-and-suspenders fallback.
    _init_vault_git(vault_dir, spec.name)


def _write_claude_settings(vault_dir: Path) -> None:
    """Write ``.claude/settings.json`` pre-authorising normal vault operations.

    Does not overwrite an existing file so user customisations survive a
    re-scaffold. The JSON is static (no Jinja2 variables needed) so we read
    the template and write it verbatim rather than rendering it.
    """
    settings_json = vault_dir / ".claude" / "settings.json"
    if settings_json.exists():
        return
    template_path = asset_path("templates") / "claude-settings.json.j2"
    settings_json.write_text(
        template_path.read_text(encoding="utf-8"), encoding="utf-8"
    )


def render_vault_shim(vault_dir: Path, spec: SpecConfig) -> str:
    """Render the vault bash shim from the bundled template (spec 023 FR-014)."""
    templates_dir = asset_path("templates")
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    ctx = {"vault_dir": str(vault_dir.resolve()), "spec": spec}
    return env.get_template("vault-script.sh.j2").render(**ctx)


def _write_vault_script(vault_dir: Path, spec: SpecConfig) -> None:
    """Render ``vault`` (the unified entry-point script) and a systemd unit.

    Does not overwrite an existing ``vault`` file so user customisations
    survive a re-scaffold.  The systemd unit is always (re-)written because
    it's a generated artefact that only embeds ``vault_dir`` and ``spec.name``
    — both of which may change on re-scaffold.
    """
    # vault script — skip if already present so user edits are preserved.
    script_path = vault_dir / "vault"
    if not script_path.exists():
        script_path.write_text(render_vault_shim(vault_dir, spec), encoding="utf-8")
        os.chmod(script_path, 0o755)

    templates_dir = asset_path("templates")
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    ctx = {"vault_dir": str(vault_dir.resolve()), "spec": spec}
    # systemd unit — always rendered (contains only generated values).
    systemd_dir = vault_dir / "_pipeline" / "systemd"
    systemd_dir.mkdir(parents=True, exist_ok=True)
    (systemd_dir / "vault-research.service").write_text(
        env.get_template("vault-research.service.j2").render(**ctx),
        encoding="utf-8",
    )
    (systemd_dir / ".tmpl-versions.json").write_text(
        json.dumps({"vault-research.service": 1}, indent=2) + "\n", encoding="utf-8"
    )


def _init_vault_git(vault_dir: Path, spec_name: str) -> None:
    """Initialise a git repo at ``vault_dir`` with an initial scaffold commit.

    Fails silently if git isn't installed or the repo already exists —
    this is a best-effort convenience, not a hard invariant. The .gitignore
    that scoped tracking to ``data_vault/`` was written earlier in
    ``scaffold``; we just commit what's there.
    """
    import subprocess

    if not shutil.which("git"):
        return
    if (vault_dir / ".git").exists():
        return  # Idempotent: re-scaffolding an existing vault doesn't re-init.

    try:
        subprocess.run(
            ["git", "init", "--quiet"],
            cwd=vault_dir,
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["git", "add", "."],
            cwd=vault_dir,
            check=False,
            capture_output=True,
        )
        # Use -c so we don't depend on the user's global git identity
        # being set (CI boxes, fresh machines, etc.).
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=research-framework@local",
                "-c",
                "user.name=research-framework",
                "commit",
                "--quiet",
                "-m",
                f"scaffold: initial vault for '{spec_name}'",
            ],
            cwd=vault_dir,
            check=False,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        # Git failures are non-fatal — vault still works, Codex just
        # needs the sandbox-flag fallback in its settings profile.
        pass


def _discover_scripts_user_owned(vault_dir: Path) -> list[str]:
    from .scripts import _framework_script_basenames, _scripts_src

    scripts_dir = vault_dir / "scripts"
    if not scripts_dir.is_dir():
        return []
    shipped = _framework_script_basenames(_scripts_src())
    out: list[str] = []
    for path in sorted(scripts_dir.glob("*.py")):
        if path.is_file() and path.name not in shipped:
            out.append(f"scripts/{path.name}")
    return out


def write_scaffold_manifest_snapshot(vault_dir: Path) -> None:
    """Persist dist manifest + vault-local script ownership (spec 023 FR-015)."""
    from ..pipeline.scaffold_manifest import default_manifest_path, load_manifest

    manifest = load_manifest(default_manifest_path())
    snapshot = {
        "framework_version": str(_FRAMEWORK_VERSION),
        "captured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": [
            {
                "path": e.path,
                "kind": e.kind,
                "template_version": e.template_version,
                "rendered_sha256": e.rendered_sha256,
                "is_user_owned_after_first_write": e.is_user_owned_after_first_write,
            }
            for e in manifest.entries
        ],
        "scripts_user_owned": _discover_scripts_user_owned(vault_dir),
    }
    out = vault_dir / "_pipeline" / "scaffold-manifest-snapshot.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    from ..pipeline.atomic_write import write_json

    write_json(out, snapshot)


def apply_vault_scaffold_update(vault_dir: Path) -> None:
    """Update apply path for FR-015: merge scripts + record manifest snapshot."""
    from .scripts import copy_scripts

    copy_scripts(vault_dir)
    write_scaffold_manifest_snapshot(vault_dir)
