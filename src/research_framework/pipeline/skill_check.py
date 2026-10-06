"""Skill-file YAML preflight + auto-restore.

External agent runtimes (Cursor, Claude Code, Codex, the Superpowers plugin)
discover ``.agents/skills/<name>/SKILL.md`` files automatically and have, in
the past (v0.2.19 bundle), rewritten them on first open — flattening multi-line
strings, injecting ``related: []`` / ``status: draft`` blocks, and breaking the
YAML frontmatter so the cycle's own skill loader silently drops them.

This module gives us two things:

1. ``validate_skills(vault_dir)`` — return a list of broken skill files with
   the YAML error string. Callers decide whether to fail-loud (cycle start)
   or attempt repair (install).
2. ``validate_and_repair_skills(vault_dir)`` — same, but for every broken
   file try to restore it from the wheel's bundled ``.agents/`` copy.
   Returns a structured :class:`SkillCheckResult` so callers can both log it
   and write a diagnostic sidecar.

There is **no silent recovery path**. If a skill ends up broken AND has no
bundled copy to restore from, ``validate_and_repair_skills`` records the file
under ``unrecoverable`` and the caller is expected to fail the cycle rather
than dispatch agents with a broken skill registry. That is the explicit
contrast with the v0.2.19 behaviour, where four mangled SKILL.md files caused
verifier/topic-classifier/source-relevance/cycle-report to silently disappear
from the agent's skill list mid-cycle.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from research_framework._assets import asset_path
from research_framework.vault.frontmatter import split_frontmatter

__all__ = [
    "SkillIssue",
    "SkillCheckResult",
    "validate_skills",
    "validate_and_repair_skills",
]

_LOG = logging.getLogger(__name__)

_SKILLS_RELDIR = Path(".agents") / "skills"


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return ``(frontmatter_yaml, body)`` from a SKILL.md.

    SKILL.md files use the same ``---``-bracketed YAML frontmatter as vault
    notes. If the document doesn't open with ``---`` we treat the whole file
    as body (no frontmatter to validate); callers should still flag this as
    suspicious because every SKILL.md ships with frontmatter.
    """
    if not text.startswith("---"):
        return None, text
    split = split_frontmatter(text)
    if split is None:
        return None, text
    yaml_text, body = split
    # The leading newline stands for the opening delimiter line, so the line
    # numbers in a YAML error are the file's own.
    return "\n" + yaml_text, body


def _parse_skill_yaml(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(parsed_dict, error_string)``. Exactly one is non-None.

    Failure modes:
    - no frontmatter at all → ``("missing YAML frontmatter", None)``
    - YAML parse error → preserve the original yaml error message
    - frontmatter is not a mapping → flagged so loaders downstream don't
      explode on ``data.get(...)`` against a list/string
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"read error: {exc}"
    fm, _ = _split_frontmatter(text)
    if fm is None:
        return None, "missing YAML frontmatter"
    try:
        data = yaml.safe_load(fm)
    except yaml.YAMLError as exc:
        return None, f"invalid YAML: {exc}"
    if not isinstance(data, dict):
        return None, f"frontmatter is not a mapping (got {type(data).__name__})"
    return data, None


@dataclass
class SkillIssue:
    """One broken SKILL.md, with whether repair succeeded."""

    path: Path
    error: str
    repaired_from: Path | None = None
    """Bundled source path used to overwrite ``path``. ``None`` when no
    repair attempt was made or no bundled copy exists."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "error": self.error,
            "repaired_from": str(self.repaired_from) if self.repaired_from else None,
        }


@dataclass
class SkillCheckResult:
    """Aggregate outcome of one ``validate_and_repair_skills`` pass.

    ``ok`` means every SKILL.md parses (possibly after auto-restore). Callers
    that gate on this still need to log ``repaired`` — a silent restore is
    useful telemetry because it usually means an external tool is still
    mangling the files and the user should investigate (Cursor auto-detect,
    Superpowers plugin, etc.).
    """

    scanned: int
    repaired: list[SkillIssue] = field(default_factory=list)
    unrecoverable: list[SkillIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unrecoverable

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "repaired": [i.to_dict() for i in self.repaired],
            "unrecoverable": [i.to_dict() for i in self.unrecoverable],
            "ok": self.ok,
        }


def _iter_skill_files(skills_root: Path) -> list[Path]:
    if not skills_root.is_dir():
        return []
    return sorted(skills_root.glob("*/SKILL.md"))


def validate_skills(vault_dir: Path) -> list[SkillIssue]:
    """Return the list of broken SKILL.md files under ``vault_dir``.

    Read-only — does not attempt any restore. Use :func:`validate_and_repair_skills`
    when you also want auto-recovery from the wheel's bundled copies.
    """
    skills_root = vault_dir / _SKILLS_RELDIR
    issues: list[SkillIssue] = []
    for path in _iter_skill_files(skills_root):
        _data, err = _parse_skill_yaml(path)
        if err:
            issues.append(SkillIssue(path=path, error=err))
    return issues


def _bundled_skills_root() -> Path | None:
    """Locate ``.agents/skills/`` inside the installed wheel (or source tree).

    Returns ``None`` when neither location holds the bundle — should never
    happen in production (force-include guarantees it) but we don't crash on
    it. The caller treats that case as "no auto-restore available".
    """
    try:
        agents_dir = asset_path(".agents")
    except FileNotFoundError:
        return None
    return agents_dir / "skills"


def _restore_from_bundle(broken: Path, bundled_root: Path | None) -> Path | None:
    """Copy the bundled SKILL.md over ``broken`` if a matching skill exists.

    The skill is matched by directory name (``broken.parent.name``) because
    that's the stable identifier the agent CLI uses to find a skill — file
    paths inside the vault may have been moved by the user but the skill
    directory name is part of the agent contract.
    """
    if bundled_root is None:
        return None
    candidate = bundled_root / broken.parent.name / "SKILL.md"
    if not candidate.is_file():
        return None
    # Sanity-check: the bundled copy itself must parse before we trust it.
    _data, err = _parse_skill_yaml(candidate)
    if err:
        _LOG.error(
            "bundled fallback for %s is itself broken (%s); refusing to restore",
            broken.parent.name,
            err,
        )
        return None
    shutil.copyfile(candidate, broken)
    return candidate


def validate_and_repair_skills(vault_dir: Path) -> SkillCheckResult:
    """Validate every SKILL.md, restore broken ones from the wheel, return the result.

    Logs every repair at ``warning`` and every unrecoverable file at ``error``
    so the user sees the problem in the cycle log even before opening the
    diagnostic sidecar.
    """
    skills_root = vault_dir / _SKILLS_RELDIR
    files = _iter_skill_files(skills_root)
    bundled_root = _bundled_skills_root()

    repaired: list[SkillIssue] = []
    unrecoverable: list[SkillIssue] = []

    for path in files:
        _data, err = _parse_skill_yaml(path)
        if not err:
            continue
        restored_from = _restore_from_bundle(path, bundled_root)
        if restored_from is None:
            _LOG.error(
                "SKILL.md unrecoverable: %s — %s (no bundled fallback)", path, err
            )
            unrecoverable.append(SkillIssue(path=path, error=err))
            continue
        _LOG.warning(
            "SKILL.md auto-restored: %s — was %r, copied from bundled %s",
            path,
            err,
            restored_from,
        )
        repaired.append(SkillIssue(path=path, error=err, repaired_from=restored_from))

    return SkillCheckResult(
        scanned=len(files), repaired=repaired, unrecoverable=unrecoverable
    )
