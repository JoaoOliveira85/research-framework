"""Vault inventory: read-only snapshot of a vault's contents.

Exported:
  build_inventory(vault_root: Path) -> dict
  format_text(inv: dict) -> str
  format_json(inv: dict) -> str
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

__all__ = ["build_inventory", "format_text", "format_json"]

# Migrator artefact paths to exclude from user-added detection
_MIGRATOR_ARTEFACTS = frozenset(
    {
        "_pipeline/.migration-plan.json",
        "_pipeline/.migration-log.md",
        "_pipeline/.tmpl-versions.json",
    }
)


def _read_spec_parse(vault_root: Path) -> dict[str, Any]:
    """Read _pipeline/spec-parse.json; return {} on absence/error."""
    sp = vault_root / "_pipeline" / "spec-parse.json"
    if not sp.exists():
        return {}
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _count_migration_log_entries(vault_root: Path) -> int:
    log = vault_root / "_pipeline" / ".migration-log.md"
    if not log.exists():
        return 0
    try:
        text = log.read_text(encoding="utf-8")
        return text.count("## Migration ")
    except OSError:
        return 0


def _build_corpus_block(
    vault_root: Path, corpus_dir: str, manifest_paths: set[str]
) -> dict:
    """Summarise the corpus: count + bytes, plus enumerate _templates/."""
    corpus_path = vault_root / corpus_dir
    if not corpus_path.exists():
        return {"path": corpus_dir, "file_count": 0, "total_bytes": 0, "templates": []}

    file_count = 0
    total_bytes = 0
    for p in corpus_path.rglob("*"):
        if p.is_file():
            file_count += 1
            try:
                total_bytes += p.stat().st_size
            except OSError:
                pass

    # Enumerate _templates/
    templates_dir = corpus_path / "_templates"
    templates: list[dict] = []
    if templates_dir.exists():
        for p in sorted(templates_dir.iterdir()):
            if p.is_file():
                rel = str(p.relative_to(vault_root)).replace("\\", "/")
                in_manifest = rel in manifest_paths
                templates.append(
                    {
                        "name": p.name,
                        "size": p.stat().st_size,
                        "in_manifest": in_manifest,
                        "user_customised": False,  # refined by build_inventory
                    }
                )

    return {
        "path": corpus_dir,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "templates": templates,
    }


def _build_scripts_block(vault_root: Path, manifest_paths: set[str]) -> dict:
    """Enumerate scripts/ — .py and .sh files only."""
    scripts_dir = vault_root / "scripts"
    if not scripts_dir.exists():
        return {"path": "scripts", "framework_shipped": [], "user_added": []}

    framework_shipped: list[dict] = []
    user_added: list[dict] = []
    for p in sorted(scripts_dir.iterdir()):
        if not p.is_file():
            continue
        if p.suffix not in {".py", ".sh"}:
            continue
        rel = str(p.relative_to(vault_root)).replace("\\", "/")
        size = p.stat().st_size
        if rel in manifest_paths:
            framework_shipped.append(
                {"name": p.name, "size": size, "manifest_managed": True}
            )
        else:
            user_added.append({"name": p.name, "size": size})

    return {
        "path": "scripts",
        "framework_shipped": framework_shipped,
        "user_added": user_added,
    }


def _is_agent_definition(path: Path) -> bool:
    """Return True iff the file's frontmatter contains 'type: agent-definition'."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.startswith("---"):
            return False
        end = text.find("\n---", 3)
        if end == -1:
            return False
        frontmatter = text[3:end]
        return "type: agent-definition" in frontmatter
    except OSError:
        return False


def _build_slash_commands_block(
    vault_root: Path,
    manifest_paths: set[str],
    user_owned_paths: set[str],
) -> dict:
    """Enumerate .claude/commands/ — .md files."""
    cmd_dir = vault_root / ".claude" / "commands"
    if not cmd_dir.exists():
        return {"path": ".claude/commands", "framework_seeded": [], "user_added": []}

    framework_seeded: list[dict] = []
    user_added: list[dict] = []
    for p in sorted(cmd_dir.iterdir()):
        if not p.is_file() or p.suffix != ".md":
            continue
        rel = str(p.relative_to(vault_root)).replace("\\", "/")
        name = p.stem
        size = p.stat().st_size
        agent_def = _is_agent_definition(p)
        if rel in manifest_paths:
            framework_seeded.append(
                {
                    "name": name,
                    "size": size,
                    "framework_seeded": True,
                    "user_customised_after_seed": rel in user_owned_paths,
                    "agent_definition": agent_def,
                }
            )
        else:
            user_added.append(
                {
                    "name": name,
                    "size": size,
                    "framework_seeded": False,
                    "agent_definition": agent_def,
                }
            )

    return {
        "path": ".claude/commands",
        "framework_seeded": framework_seeded,
        "user_added": user_added,
    }


def _build_pipeline_state(vault_root: Path, manifest_paths: set[str]) -> dict:
    """Summarise _pipeline/ state."""
    pipeline_dir = vault_root / "_pipeline"
    spec_parse = pipeline_dir / "spec-parse.json"
    spec_parse_present = spec_parse.exists()
    spec_parse_valid = False
    fw_version_in_sp: int | None = None

    if spec_parse_present:
        try:
            data = json.loads(spec_parse.read_text(encoding="utf-8"))
            spec_parse_valid = True
            fw_version_in_sp = data.get("framework_version")
        except (json.JSONDecodeError, OSError):
            pass

    migration_log_entries = _count_migration_log_entries(vault_root)

    # Custom pipeline files = in _pipeline/, not in manifest, not migrator artefacts
    custom_pipeline_files: list[str] = []
    if pipeline_dir.exists():
        for p in sorted(pipeline_dir.rglob("*")):
            if not p.is_file():
                continue
            rel = str(p.relative_to(vault_root)).replace("\\", "/")
            if rel in manifest_paths:
                continue
            if rel in _MIGRATOR_ARTEFACTS:
                continue
            custom_pipeline_files.append(rel)

    return {
        "spec_parse_present": spec_parse_present,
        "spec_parse_valid": spec_parse_valid,
        "framework_version_in_spec_parse": fw_version_in_sp,
        "migration_log_entries": migration_log_entries,
        "custom_pipeline_files": custom_pipeline_files,
    }


def _build_warnings(
    corpus_dir: str,
    scripts_block: dict,
    corpus_block: dict,
) -> list[str]:
    warnings: list[str] = []

    # Heuristic 1: collect_*.py scripts → candidate for 014 collector modules
    for entry in scripts_block["user_added"]:
        name = entry["name"]
        if name.startswith("collect_") and name.endswith(".py"):
            warnings.append(
                f"scripts/{name} detected — candidate for 014 RSS/YouTube/Reddit collector modules"
            )

    # Heuristic 2: many user-added templates
    user_added_templates = [
        t for t in corpus_block["templates"] if not t["in_manifest"]
    ]
    if len(user_added_templates) > 5:
        warnings.append(
            f"{len(user_added_templates)} user-added templates under "
            f"{corpus_dir}/_templates/ — consider promoting common ones to framework"
        )

    return warnings


def build_inventory(vault_root: Path) -> dict:
    """Pure function: returns the inventory dict for *vault_root*.

    Raises ValueError if the path is not a recognisable vault.
    """
    from .pipeline.scaffold_baseline import read_vault_baseline
    from .pipeline.scaffold_diff import compute_plan
    from .pipeline.scaffold_manifest import default_manifest_path, load_manifest

    if not vault_root.exists() or not vault_root.is_dir():
        raise ValueError(f"not a directory: {vault_root}")

    # Read spec-parse.json for vault metadata + corpus_dir
    sp_data = _read_spec_parse(vault_root)
    corpus_dir_name: str = sp_data.get("vault_corpus_dir", "data_vault")

    # Validate it looks like a vault
    if not (vault_root / corpus_dir_name).exists():
        # Try default fallback
        if (vault_root / "data_vault").exists():
            corpus_dir_name = "data_vault"
        else:
            raise ValueError(
                f"not a vault (no {corpus_dir_name}/ directory): {vault_root}"
            )

    # Load manifest
    manifest_path = default_manifest_path()
    manifest = load_manifest(manifest_path)

    manifest_paths: set[str] = {e.path for e in manifest.entries}
    user_owned_paths: set[str] = {
        e.path for e in manifest.entries if e.is_user_owned_after_first_write
    }

    # Baseline + plan for manifest_status counts
    baseline = read_vault_baseline(vault_root, manifest)
    plan = compute_plan(baseline, manifest)

    pending_create = sum(1 for op in plan.operations if op.kind == "create")
    pending_overwrite = sum(1 for op in plan.operations if op.kind == "overwrite")
    matching = sum(1 for op in plan.operations if op.kind == "leave_alone")

    # Build sub-blocks
    corpus_block = _build_corpus_block(vault_root, corpus_dir_name, manifest_paths)

    # Refine user_customised on templates
    for tmpl in corpus_block["templates"]:
        rel_path = f"{corpus_dir_name}/_templates/{tmpl['name']}"
        tmpl["user_customised"] = rel_path in user_owned_paths

    scripts_block = _build_scripts_block(vault_root, manifest_paths)
    slash_commands_block = _build_slash_commands_block(
        vault_root, manifest_paths, user_owned_paths
    )
    pipeline_state = _build_pipeline_state(vault_root, manifest_paths)
    warnings = _build_warnings(corpus_dir_name, scripts_block, corpus_block)

    # vault_spec from spec-parse.json
    vault_spec: dict | None = None
    if sp_data:
        vault_spec = {
            "name": sp_data.get("name"),
            "owner": sp_data.get("owner"),
            "corpus_dir": corpus_dir_name,
        }

    # Pruneable section — paths present on disk that the framework now supersedes
    from .migration.superseded_paths import superseded_paths_present

    pruneable = [
        {"path": p, "superseded_by": m} for p, m in superseded_paths_present(vault_root)
    ]

    return {
        "vault_root": str(vault_root),
        "framework_version": manifest.framework_version,
        "vault_spec": vault_spec,
        "manifest_status": {
            "entries_total": len(manifest.entries),
            "matching": matching,
            "pending_overwrite": pending_overwrite,
            "pending_create": pending_create,
        },
        "corpus": corpus_block,
        "scripts": scripts_block,
        "slash_commands": slash_commands_block,
        "pipeline_state": pipeline_state,
        "warnings": warnings,
        "pruneable": pruneable,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }


def format_json(inv: dict) -> str:
    return json.dumps(inv, indent=2, default=str)


def format_text(inv: dict) -> str:
    lines: list[str] = []
    vault_spec = inv.get("vault_spec") or {}
    vault_name = vault_spec.get("name", inv["vault_root"])
    corpus_dir = vault_spec.get("corpus_dir", "data_vault")
    corpus = inv["corpus"]
    file_count = corpus["file_count"]

    lines.append(f"Vault: {vault_name}  (corpus: {corpus_dir}/ — {file_count} notes)")
    lines.append("─" * 65)

    ms = inv["manifest_status"]
    lines.append(f"Framework manifest entries:        {ms['entries_total']}")
    lines.append(f"  matching disk (LEAVE_ALONE):     {ms['matching']}")
    lines.append(f"  pending overwrite:               {ms['pending_overwrite']}")
    lines.append(f"  missing on disk (pending CREATE):{ms['pending_create']}")
    lines.append("")

    sc = inv["scripts"]
    fw = sc["framework_shipped"]
    ua = sc["user_added"]
    lines.append(f"Scripts in scripts/ ({len(fw) + len(ua)} files):")
    lines.append(f"  framework-shipped:  {len(fw)}")
    lines.append(f"  user-added:         {len(ua)}")
    for entry in ua:
        kb = entry["size"] / 1024
        lines.append(f"    {entry['name']:<40} ({kb:.1f} KB)")
    lines.append("")

    slash = inv["slash_commands"]
    fs = slash["framework_seeded"]
    ua_slash = slash["user_added"]
    lines.append(f"Slash commands in .claude/commands/ ({len(fs) + len(ua_slash)}):")
    lines.append(f"  framework-seeded:   {len(fs)}")
    lines.append(f"  user-added:         {len(ua_slash)}")
    for cmd in ua_slash:
        suffix = " (agent-definition)" if cmd.get("agent_definition") else ""
        lines.append(f"    {cmd['name']}.md{suffix}")
    lines.append("")

    templates = corpus["templates"]
    lines.append(f"Templates in {corpus_dir}/_templates/ ({len(templates)}):")
    fw_tmpl = [t for t in templates if t["in_manifest"]]
    ua_tmpl = [t for t in templates if not t["in_manifest"]]
    lines.append(f"  framework-shipped:  {len(fw_tmpl)}")
    lines.append(f"  user-added:         {len(ua_tmpl)}")
    if ua_tmpl:
        names = ", ".join(t["name"] for t in ua_tmpl)
        lines.append(f"    {names}")
    lines.append("")

    ps = inv["pipeline_state"]
    custom_pf = ps.get("custom_pipeline_files", [])
    if custom_pf:
        lines.append("Custom _pipeline/ artefacts:")
        for cp in custom_pf:
            lines.append(f"  {cp}")
        lines.append("")

    pruneable = inv.get("pruneable", [])
    if pruneable:
        lines.append("Pruneable (framework now supersedes these):")
        for entry in pruneable:
            lines.append(
                f"  {entry['path']:<40} — framework has {entry['superseded_by']}"
            )
        lines.append("")
        lines.append("To remove these:")
        lines.append("  research_framework prune <vault>")
        lines.append("")

    if inv["warnings"]:
        lines.append("Warnings:")
        for w in inv["warnings"]:
            lines.append(f"  - {w}")
        lines.append("")

    lines.append("Run with --format=json for the full machine-readable inventory.")
    return "\n".join(lines)
