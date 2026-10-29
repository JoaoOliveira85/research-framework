"""The scaffold manifest reaches the wheel (issue #34).

Same shape as the D11 settings-profile guard: ``_assets`` falls back to the
source tree, so only a check of the packaging table notices a missing file.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = "dist-templates/scaffold-manifest.json"
TARGET = "src/research_framework/_data/dist-templates/scaffold-manifest.json"


def test_manifest_is_force_included_in_the_wheel() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    table = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert table.get(SOURCE) == TARGET
    assert (REPO_ROOT / SOURCE).is_file()
