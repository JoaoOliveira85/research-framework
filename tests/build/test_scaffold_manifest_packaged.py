"""The wheel must carry `dist-templates/scaffold-manifest.json` (issue #34).

`default_manifest_path` can only fall back to the packaged copy if
`pyproject.toml`'s `force-include` table actually puts the file inside
`research_framework/_data/`. A source checkout resolves through the walk-up
path, so every checkout test stays green even when the release wheel lacks it —
this guard compares the committed manifest against the force-include table.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
MANIFEST = "dist-templates/scaffold-manifest.json"
PACKAGED = "src/research_framework/_data/dist-templates/scaffold-manifest.json"


def _force_include() -> dict[str, str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]


def test_the_manifest_is_committed() -> None:
    assert (REPO_ROOT / MANIFEST).is_file(), (
        "dist-templates/scaffold-manifest.json is the migrator's source of "
        "truth; scripts/build_scaffold_manifest.py regenerates it."
    )


def test_the_manifest_is_force_included_under_the_package() -> None:
    table = _force_include()
    assert table.get(MANIFEST) == PACKAGED, (
        "The wheel would not carry the scaffold manifest, so an installed "
        "vault's `regenerate-shim --force` cannot resolve it (issue #34)."
    )
