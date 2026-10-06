"""Parse vault-spec.md files into SpecConfig."""

from __future__ import annotations

from pathlib import Path

import yaml

from ..vault.frontmatter import split_frontmatter
from .schema import SpecConfig, SpecValidationError


def parse(spec_path: Path) -> SpecConfig:
    """Read a YAML-fronted Markdown spec file and return a SpecConfig.

    Raises SpecValidationError if the file is not found, cannot be parsed, or
    has malformed frontmatter. Does NOT run semantic validation — call
    `validator.validate(spec)` after parsing.
    """
    if not spec_path.exists():
        raise SpecValidationError([f"spec file not found: {spec_path}"])

    # Holdout from spec 025 B4 canonical parser migration.
    # Reason: spec parsing must raise SpecValidationError with spec paths, not
    # FrontmatterParseError; delimiter rules differ from vault notes.
    text = spec_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise SpecValidationError(
            [f"spec file {spec_path} missing YAML frontmatter (must start with '---')"]
        )

    # Split at the delimiter LINES. ``text.split("---", 2)`` ended the
    # frontmatter at the first `---` inside a line (a `# -------` comment rule,
    # a `---` in a value) and silently dropped every field below it.
    split = split_frontmatter(text)
    if split is None:
        raise SpecValidationError(
            [f"spec file {spec_path} has malformed frontmatter delimiters"]
        )

    try:
        # The leading newline stands for the opening delimiter line, so the
        # line numbers in a YAML error stay what they were.
        data = yaml.safe_load("\n" + split[0])
    except yaml.YAMLError as e:
        line = getattr(getattr(e, "problem_mark", None), "line", "?")
        raise SpecValidationError(
            [f"YAML parse error in {spec_path} (line {line}): {e}"]
        ) from e

    if not isinstance(data, dict):
        raise SpecValidationError(
            [f"spec frontmatter must be a mapping (got {type(data).__name__})"]
        )

    return SpecConfig.from_dict(data)
