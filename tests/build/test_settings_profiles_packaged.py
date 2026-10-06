"""Every committed settings profile reaches both distribution surfaces.

``settings.ollama.yaml`` was committed in 1.0.0rc5 (spec 047 v1), named by the
settings loader's own error message as a valid ``default_agent``, and cited
by the docs as the local-model profile — and it was never added to
``pyproject.toml``'s wheel ``force-include`` table or to ``build.sh``'s bundle
copy list. A user installing from a GitHub Release therefore could not pass
``--settings settings.ollama.yaml``: only a source checkout had the file, and
``_assets.asset_path`` falls back to the source tree in dev mode, so every
existing test was green about a profile the release did not ship.

Nothing compared the two lists against the files on disk, so a profile can
drop out of a release without any test noticing. This guard closes that:
it reads the repo root for ``settings*.yaml`` and asserts each one is named
in both places. Owner decision 2026-09-08 (D11): the Ollama profile is
packaged, and the local-model option is always supported.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
BUILD_SH = REPO_ROOT / "build.sh"

# `cp "${ROOT_DIR}/settings.codex.yaml" "${BUNDLE_DIR}/settings.codex.yaml"`
_BUNDLE_COPY_RE = re.compile(r'cp\s+"\$\{ROOT_DIR\}/(settings[^"/]*\.yaml)"')


def _committed_profiles() -> list[str]:
    names = sorted(p.name for p in REPO_ROOT.glob("settings*.yaml"))
    assert names, "no settings*.yaml profile found at the repo root"
    return names


def _wheel_force_included() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    table = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    return {source for source in table if source.startswith("settings")}


def _bundle_copied() -> set[str]:
    return set(_BUNDLE_COPY_RE.findall(BUILD_SH.read_text(encoding="utf-8")))


@pytest.mark.parametrize("profile", _committed_profiles())
def test_profile_is_force_included_in_the_wheel(profile: str) -> None:
    """`research-framework --settings <profile>` must resolve from an
    installed wheel, not only from a source checkout."""
    assert profile in _wheel_force_included(), (
        f"{profile} is committed but missing from pyproject.toml's "
        "[tool.hatch.build.targets.wheel.force-include] table — a release "
        "wheel would not carry it."
    )


@pytest.mark.parametrize("profile", _committed_profiles())
def test_profile_is_copied_into_the_bundle(profile: str) -> None:
    """The install bundle (`build.sh` § 4c) must carry every profile the
    wheel carries, so `./generate.sh --settings <profile>` works in the box."""
    assert profile in _bundle_copied(), (
        f"{profile} is committed but build.sh never copies it into the "
        "bundle — the tarball a user downloads would not carry it."
    )


def test_wheel_and_bundle_profile_lists_agree() -> None:
    """The two lists are maintained by hand in two files; pin them equal."""
    assert _wheel_force_included() == _bundle_copied()
