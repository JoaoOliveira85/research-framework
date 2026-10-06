"""Regression test for B.3 — `local_path`-backed repos auto-bypass URL pattern check.

Pre-0.7.0 a user who declared an off-pattern repo URL (e.g.
``file:///Users/x/src/foo`` or even just a custom git host) had to also
add the matching prefix to ``code_source_url_patterns`` or the spec
would fail validation. This was the most common feeds-vault revival
footgun — the user had a perfectly valid ``local_path`` declared, and
the framework refused to load the spec because it never thought to
look at it.

The fix: if ``repo.local_path`` resolves on disk, the URL pattern check
is skipped for that repo (the user has physically "vouched" for the
source). All other code-first invariants still apply.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.spec.schema import SpecValidationError
from research_framework.spec.validator import validate

# Reuse the established test factory rather than reinventing it; the
# `_code_first_spec` helper sits in test_validator.py.
from tests.spec.test_validator import _code_first_spec


def _spec_with_offpattern_url(
    repo_url: str,
    repo_local_path: str = "",
    extra_patterns: list[str] | None = None,
):
    spec = _code_first_spec()
    primary = spec.data_sources[0]
    primary.repos[0].url = repo_url
    primary.repos[0].local_path = repo_local_path
    if extra_patterns is not None:
        spec.code_source_url_patterns = list(extra_patterns)
    return spec


def test_offpattern_url_with_resolving_local_path_is_accepted(
    tmp_path: Path,
) -> None:
    real_repo = tmp_path / "src" / "foo"
    real_repo.mkdir(parents=True)
    spec = _spec_with_offpattern_url(
        repo_url="https://internal.example.invalid/team/foo",
        repo_local_path=str(real_repo),
        extra_patterns=[r"^https?://github\.com/"],
    )
    # Must not raise — local_path resolves, so the URL pattern is bypassed.
    validate(spec)


def test_offpattern_url_without_local_path_still_fails() -> None:
    spec = _spec_with_offpattern_url(
        repo_url="https://internal.example.invalid/team/foo",
        repo_local_path="",
        extra_patterns=[r"^https?://github\.com/"],
    )
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("does not match any allowed pattern" in m for m in exc.value.messages)


def test_offpattern_url_with_missing_local_path_still_fails(
    tmp_path: Path,
) -> None:
    spec = _spec_with_offpattern_url(
        repo_url="https://internal.example.invalid/team/foo",
        repo_local_path=str(tmp_path / "does-not-exist"),
        extra_patterns=[r"^https?://github\.com/"],
    )
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("does not match any allowed pattern" in m for m in exc.value.messages)


def test_tilde_local_path_is_expanded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "src" / "x"
    target.mkdir(parents=True)
    spec = _spec_with_offpattern_url(
        repo_url="https://internal.example.invalid/team/x",
        repo_local_path="~/src/x",
        extra_patterns=[r"^https?://github\.com/"],
    )
    validate(spec)  # no raise


def test_file_url_still_accepted_without_local_path() -> None:
    """Default pattern set already accepts `file://`; that path must keep working."""
    spec = _spec_with_offpattern_url(
        repo_url="file:///some/random/path",
        repo_local_path="",
        # No extra_patterns override → DEFAULTS apply (which include `^file://`).
        extra_patterns=None,
    )
    validate(spec)  # no raise
