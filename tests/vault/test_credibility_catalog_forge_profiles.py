"""Spec 070 F2/FR3 — forge PROFILE URLs must ground, not just org/repo URLs.

`github.com` shipped as `host_path, min_segments: 2` ("org/repo scoped"), which
is right for citing a repository and wrong for citing a person. A practitioner
note's natural evidence is `github.com/<user>` — one segment — so any vault
whose note type is "a person" lost every practitioner citation to the
"no source default applies" reject.

Bare `github.com/` must still ground nothing: the host on its own is not
evidence of anything.
"""

from __future__ import annotations

import pytest

from research_framework.vault.credibility import Level
from research_framework.vault.credibility_catalog import build_resolved_catalog


@pytest.fixture
def catalog():
    return build_resolved_catalog([])


@pytest.mark.parametrize("host", ["github.com", "gitlab.com", "codeberg.org"])
def test_profile_url_grounds(catalog, host: str) -> None:
    assert catalog.lookup(f"https://{host}/person-d") is Level.CORROBORATED


@pytest.mark.parametrize("host", ["github.com", "gitlab.com", "codeberg.org"])
def test_org_repo_url_still_grounds(catalog, host: str) -> None:
    assert catalog.lookup(f"https://{host}/acme/widget") is Level.CORROBORATED


@pytest.mark.parametrize("host", ["github.com", "gitlab.com", "codeberg.org"])
def test_bare_host_grounds_nothing(catalog, host: str) -> None:
    assert catalog.lookup(f"https://{host}/") is None
    assert catalog.lookup(f"https://{host}") is None


def test_deep_paths_still_ground(catalog) -> None:
    assert (
        catalog.lookup("https://github.com/acme/widget/blob/main/README.md")
        is Level.CORROBORATED
    )


def test_non_profile_forges_keep_org_scoping(catalog) -> None:
    """sourceforge/bitbucket are project hosts, not profile hosts — unchanged."""
    assert catalog.lookup("https://sourceforge.net/someone") is None
    assert catalog.lookup("https://bitbucket.org/someone") is None
    assert (
        catalog.lookup("https://sourceforge.net/projects/thing") is Level.CORROBORATED
    )
