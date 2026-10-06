#!/usr/bin/env python3
"""Generate dist-templates/scaffold-manifest.json from the current generator.

Uses the real Jinja2 templates to render a minimal dummy spec into a temp
directory, then walks the output to produce the authoritative list of scaffold
files with their normalised SHA-256 hashes and template versions.

CLI:
    python scripts/build_scaffold_manifest.py [--output <path>]
"""

# ruff: noqa: E402  (imports after sys.path.insert below are intentional)

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# Allow running from repo root without install
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from research_framework._assets import asset_path
from research_framework.generator.scaffold import scaffold
from research_framework.generator.templates import render_all
from research_framework.pipeline.template_drift import read_template_version
from research_framework.spec.simple import load as load_spec

_SAMPLE_SPEC = REPO_ROOT / "tests" / "fixtures" / "sample-spec.md"
_DIST = REPO_ROOT / "dist-templates"

# Canonical vault_dir substituted when rendering templates that embed the path.
# Using the spec's location field makes vault-script and systemd-service
# byte-stable across manifest rebuilds regardless of which temp dir was used.
_CANONICAL_VAULT_DIR = "/tmp/research_framework-test-vault"

# Files whose rendered content is never stable across runs (SQLite side files)
# and should be excluded from the manifest.
_EXCLUDE_PATHS: frozenset[str] = frozenset(
    {
        "_pipeline/sources.db-shm",
        "_pipeline/sources.db-wal",
    }
)

_SUFFIX_TO_KIND = {
    ".md": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".sh": "shell",
    ".py": "python",
}

# Files generated without a standard extension that we know the kind for.
_NAME_TO_KIND: dict[str, str] = {
    "vault": "shell",
}

# Files the migrator creates on first write but never upgrades thereafter.
# Includes: user-configured files, path-specific scripts, pipeline-managed files,
# and .tmpl-versions.json files (managed by the migrator's VERSION_STAMP mechanism
# and cannot self-reference their own version).
_USER_OWNED_PATTERNS: tuple[str, ...] = (
    "data_vault/",
    "_templates/",  # user-owned templates including concept.md and CHANGELOG.md
    "vault",  # path-specific shell script
    "_pipeline/systemd/vault-research.service",  # path-specific systemd unit
    "_pipeline/coverage-targets.json",  # contains runtime timestamps
    "_pipeline/spec-parse.json",  # per-vault parsed spec; framework MUST NOT overwrite
    "_pipeline/sources.db",  # SQLite database (user data)
    "_pipeline/budget-log.md",  # append-only user log
    "_pipeline/research-backlog.md",  # user-managed backlog
    "settings.yaml",  # user vault configuration
    "vault-config.yaml",  # user vault configuration
    "update_vault.py",  # user-managed update script
    ".claude/settings.json",  # user-managed Claude settings
    ".claude/commands/ask.md",  # per-vault curator agent
    ".claude/commands/research.md",  # per-vault research agent
    ".claude/commands/write.md",  # per-vault writer agent
    ".claude/commands/scout.md",  # per-vault scout agent
    ".claude/commands/verify.md",  # per-vault verifier agent
    ".claude/commands/report.md",  # per-vault reporter agent
    ".claude/commands/extract.md",  # per-vault extractor agent
    ".claude/commands/pipeline.md",  # per-vault pipeline agent
    ".cursor/cli.json",  # user-managed Cursor settings
)

# File names that are always user-owned regardless of directory
_USER_OWNED_NAMES: frozenset[str] = frozenset(
    {
        ".tmpl-versions.json",  # managed by migrator VERSION_STAMP, cannot self-reference
    }
)


def _kind(rel: Path) -> str:
    suffix = rel.suffix.lower()
    if suffix in _SUFFIX_TO_KIND:
        return _SUFFIX_TO_KIND[suffix]
    if rel.name in _NAME_TO_KIND:
        return _NAME_TO_KIND[rel.name]
    return "other"


def _is_user_owned(rel: str) -> bool:
    if Path(rel).name in _USER_OWNED_NAMES:
        return True
    return any(
        rel.startswith(pat) or rel == pat.rstrip("/") for pat in _USER_OWNED_PATTERNS
    )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return "unknown"


_FIXED_TIMESTAMP = "2000-01-01T00:00:00Z"
_TIMESTAMP_KEYS = ("last_updated", "generated_at", "created_at", "updated_at")


def _fix_timestamps(vault_dir: Path) -> None:
    """Replace timestamp fields in generated JSON files with a fixed value.

    Some files (e.g. coverage-targets.json) embed datetime.now() at generation
    time. Replacing with a fixed sentinel before hashing makes the manifest
    byte-stable across runs.
    """
    for p in vault_dir.rglob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        changed = False
        for key in _TIMESTAMP_KEYS:
            if key in data and isinstance(data[key], str):
                data[key] = _FIXED_TIMESTAMP
                changed = True
        if changed:
            p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _re_render_with_canonical_vault_dir(vault_dir: Path, spec) -> None:  # type: ignore[no-untyped-def]
    """Re-render templates that embed vault_dir with a fixed canonical path.

    vault-script.sh.j2 and vault-research.service.j2 embed the absolute vault
    path at render time. Without this step, manifest SHA256s differ between
    runs because tempdir paths differ.
    """
    templates_dir = asset_path("templates")
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    ctx = {"vault_dir": _CANONICAL_VAULT_DIR, "spec": spec}
    (vault_dir / "vault").write_text(
        env.get_template("vault-script.sh.j2").render(**ctx), encoding="utf-8"
    )
    (vault_dir / "_pipeline" / "systemd" / "vault-research.service").write_text(
        env.get_template("vault-research.service.j2").render(**ctx), encoding="utf-8"
    )


def _scaffold_files(vault_dir: Path) -> list[tuple[str, Path]]:
    """Return (vault-relative-path, absolute-path) for every scaffold file."""
    results = []
    for p in sorted(vault_dir.rglob("*")):
        if p.is_dir():
            continue
        rel = p.relative_to(vault_dir)
        rel_str = rel.as_posix()
        if rel_str.startswith(".git/") or rel_str in _EXCLUDE_PATHS:
            continue
        results.append((rel_str, p))
    return results


def build_manifest(output: Path) -> None:
    spec = load_spec(_SAMPLE_SPEC)

    with tempfile.TemporaryDirectory(prefix="rvault-manifest-") as tmp:
        vault_dir = Path(tmp) / "vault"
        vault_dir.mkdir()

        scaffold(spec, vault_dir)
        render_all(spec, vault_dir)
        _re_render_with_canonical_vault_dir(vault_dir, spec)
        _fix_timestamps(vault_dir)

        entries = []
        for rel_str, abs_path in _scaffold_files(vault_dir):
            raw = abs_path.read_bytes()
            file_kind = _kind(Path(rel_str))
            sha = _sha256(raw)

            tv = read_template_version(abs_path)
            if tv is None:
                tv = 1

            entries.append(
                {
                    "path": rel_str,
                    "kind": file_kind,
                    "template_version": tv,
                    "rendered_sha256": sha,
                    "is_user_owned_after_first_write": _is_user_owned(rel_str),
                }
            )

    entries.sort(key=lambda e: e["path"])

    manifest = {
        "framework_version": 1,
        "generator_commit": _git_head(),
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "entries": entries,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(entries)} entries to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=_DIST / "scaffold-manifest.json",
        help="Output path for the manifest (default: dist-templates/scaffold-manifest.json)",
    )
    args = parser.parse_args()
    build_manifest(args.output)


if __name__ == "__main__":
    main()
