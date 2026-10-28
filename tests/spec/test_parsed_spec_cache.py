"""Tier 1: the one loader for ``_pipeline/spec-parse.json`` (issue #9).

The cache is keyed on the spec file's content hash and the parser version.
File modification times are never consulted, so every staleness case below
forces the mtimes to the opposite of what an mtime comparison would want.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from research_framework.spec import parsed
from research_framework.spec.parsed import (
    PARSER_VERSION,
    ParsedSpecError,
    find_spec_file,
    load_parsed_spec,
    spec_file_sha256,
    spec_parse_path,
)
from research_framework.spec.schema import SpecConfig


def _spec_text(owner: str) -> str:
    return (
        "---\n"
        'name: "Cache Vault"\n'
        f'owner: "{owner}"\n'
        'topic: "A small topic for cache tests"\n'
        "---\n\nBody.\n"
    )


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    v = tmp_path / "cache-vault"
    (v / "_pipeline").mkdir(parents=True)
    (v / "data_vault").mkdir()
    (v / "research.spec.md").write_text(_spec_text("alice"), encoding="utf-8")
    return v


def _set_mtime(path: Path, when: float) -> None:
    os.utime(path, (when, when))


def _cache(vault: Path) -> dict:
    return json.loads(spec_parse_path(vault).read_text(encoding="utf-8"))


def _rewrite_cache(vault: Path, **changes: object) -> None:
    doc = _cache(vault)
    for key, value in changes.items():
        if value is None:
            doc.pop(key, None)
        else:
            doc[key] = value
    spec_parse_path(vault).write_text(json.dumps(doc), encoding="utf-8")


def test_missing_cache_is_parsed_and_stamped(vault: Path) -> None:
    doc = load_parsed_spec(vault, write_cache=True)

    assert doc["owner"] == "alice"
    assert doc["spec_sha256"] == spec_file_sha256(vault / "research.spec.md")
    assert doc["parser_version"] == PARSER_VERSION
    assert doc["spec_file"] == "research.spec.md"
    assert _cache(vault) == doc


def test_current_cache_is_read_not_reparsed(vault: Path) -> None:
    load_parsed_spec(vault, write_cache=True)
    _rewrite_cache(vault, owner="SENTINEL")  # hash + version still match

    assert load_parsed_spec(vault)["owner"] == "SENTINEL"


def test_touched_but_unchanged_spec_is_not_reparsed(vault: Path) -> None:
    load_parsed_spec(vault, write_cache=True)
    _rewrite_cache(vault, owner="SENTINEL")
    spec = vault / "research.spec.md"
    _set_mtime(spec, spec_parse_path(vault).stat().st_mtime + 3600)

    assert load_parsed_spec(vault)["owner"] == "SENTINEL"


def test_changed_spec_with_older_mtime_than_cache_is_reparsed(vault: Path) -> None:
    load_parsed_spec(vault, write_cache=True)
    spec = vault / "research.spec.md"
    spec.write_text(_spec_text("bob"), encoding="utf-8")
    # A restore/checkout can leave the edited spec looking older than the cache.
    _set_mtime(spec, spec_parse_path(vault).stat().st_mtime - 3600)
    assert spec.stat().st_mtime < spec_parse_path(vault).stat().st_mtime

    assert load_parsed_spec(vault, write_cache=True)["owner"] == "bob"
    assert _cache(vault)["owner"] == "bob"


def test_changed_spec_with_unchanged_mtime_is_reparsed(vault: Path) -> None:
    load_parsed_spec(vault, write_cache=True)
    spec = vault / "research.spec.md"
    before = spec.stat().st_mtime
    spec.write_text(_spec_text("bob"), encoding="utf-8")
    _set_mtime(spec, before)

    assert load_parsed_spec(vault)["owner"] == "bob"


def test_cache_without_hash_is_stale(vault: Path) -> None:
    load_parsed_spec(vault, write_cache=True)
    _rewrite_cache(vault, owner="SENTINEL", spec_sha256=None)

    doc = load_parsed_spec(vault)

    assert doc["owner"] == "alice"
    assert doc["spec_sha256"] == spec_file_sha256(vault / "research.spec.md")


@pytest.mark.parametrize("version", [None, 0, 999, "1", "garbage"])
def test_cache_with_missing_or_foreign_version_is_rebuilt(
    vault: Path, version: object
) -> None:
    load_parsed_spec(vault, write_cache=True)
    _rewrite_cache(vault, owner="SENTINEL", parser_version=version)

    doc = load_parsed_spec(vault)

    assert doc["owner"] == "alice"
    assert doc["parser_version"] == PARSER_VERSION


def test_parser_version_bump_rebuilds_cache(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_parsed_spec(vault, write_cache=True)
    _rewrite_cache(vault, owner="SENTINEL")

    monkeypatch.setattr(parsed, "PARSER_VERSION", PARSER_VERSION + 1)
    doc = load_parsed_spec(vault)

    assert doc["owner"] == "alice"
    assert doc["parser_version"] == PARSER_VERSION + 1


def test_corrupt_cache_is_rebuilt(vault: Path) -> None:
    spec_parse_path(vault).write_text("{ not json", encoding="utf-8")

    assert load_parsed_spec(vault)["owner"] == "alice"


def test_without_a_spec_file_the_cache_is_returned_as_is(vault: Path) -> None:
    spec_parse_path(vault).write_text(json.dumps({"name": "hand-made"}))
    (vault / "research.spec.md").unlink()

    assert load_parsed_spec(vault) == {"name": "hand-made"}


def test_no_cache_and_no_spec_raises(vault: Path) -> None:
    (vault / "research.spec.md").unlink()

    with pytest.raises(ParsedSpecError):
        load_parsed_spec(vault)


def test_strict_invalid_spec_raises_instead_of_serving_stale_cache(
    vault: Path,
) -> None:
    load_parsed_spec(vault, write_cache=True)
    (vault / "research.spec.md").write_text("---\nname: only-a-name\n---\n")

    with pytest.raises(ParsedSpecError):
        load_parsed_spec(vault, strict=True)


def test_lenient_invalid_spec_serves_the_last_good_parse_and_warns(
    vault: Path, caplog: pytest.LogCaptureFixture
) -> None:
    load_parsed_spec(vault, write_cache=True)
    last_good = _cache(vault)
    (vault / "research.spec.md").write_text("---\nname: only-a-name\n---\n")

    with caplog.at_level("WARNING", logger=parsed.__name__):
        doc = load_parsed_spec(vault)

    assert doc == last_good
    assert _cache(vault) == last_good  # the good cache is not clobbered
    warning = " ".join(r.getMessage() for r in caplog.records)
    assert "research.spec.md" in warning
    assert "last good parse" in warning
    assert "topic" in warning  # the parse error itself


def test_lenient_invalid_spec_without_any_cache_raises(vault: Path) -> None:
    (vault / "research.spec.md").write_text("---\nname: only-a-name\n---\n")

    with pytest.raises(ParsedSpecError):
        load_parsed_spec(vault)


def test_undecodable_spec_is_a_parsed_spec_error_not_a_unicode_error(
    vault: Path,
) -> None:
    (vault / "research.spec.md").write_bytes(b"---\nname: \xff\xfe\n---\n")

    with pytest.raises(ParsedSpecError):
        load_parsed_spec(vault)


def test_undecodable_spec_serves_the_cache_when_lenient(vault: Path) -> None:
    load_parsed_spec(vault, write_cache=True)
    (vault / "research.spec.md").write_bytes(b"---\nname: \xff\xfe\n---\n")

    assert load_parsed_spec(vault)["owner"] == "alice"


def test_malformed_yaml_spec_is_a_parsed_spec_error(vault: Path) -> None:
    (vault / "research.spec.md").write_text("---\nname: [unclosed\n---\n")

    with pytest.raises(ParsedSpecError):
        load_parsed_spec(vault)


def test_default_leaves_disk_untouched(vault: Path) -> None:
    doc = load_parsed_spec(vault)

    assert doc["owner"] == "alice"
    assert not spec_parse_path(vault).exists()


def test_rebuild_is_atomic_and_leaves_no_temp_files(vault: Path) -> None:
    load_parsed_spec(vault, write_cache=True)

    assert sorted(p.name for p in (vault / "_pipeline").iterdir()) == [
        "spec-parse.json"
    ]


def test_explicit_non_default_spec_is_not_replaced_by_the_default(
    vault: Path,
) -> None:
    other = vault / "other.md"
    other.write_text(_spec_text("carol"), encoding="utf-8")
    doc = parsed.stamp_parsed_spec({"owner": "carol"}, other, vault)
    parsed.write_parsed_spec(vault, doc)

    assert load_parsed_spec(vault)["owner"] == "carol"


def test_find_spec_file_order(tmp_path: Path) -> None:
    v = tmp_path / "v"
    v.mkdir()
    assert find_spec_file(v) is None
    (v / "research.spec.md").write_text("x")
    assert find_spec_file(v).name == "research.spec.md"
    (v / "v-spec.md").write_text("x")
    assert find_spec_file(v).name == "v-spec.md"


def test_find_spec_file_does_not_glob_arbitrary_spec_files(tmp_path: Path) -> None:
    v = tmp_path / "v"
    v.mkdir()
    (v / "stray-spec.md").write_text("x")

    assert find_spec_file(v) is None


def test_find_spec_file_uses_the_resolved_name_for_a_dot_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    v = tmp_path / "dotvault"
    v.mkdir()
    (v / "dotvault-spec.md").write_text("x")
    monkeypatch.chdir(v)

    assert find_spec_file(Path(".")).name == "dotvault-spec.md"


def test_stray_spec_file_cannot_hijack_a_legacy_unstamped_cache(vault: Path) -> None:
    (vault / "research.spec.md").unlink()
    spec_parse_path(vault).write_text(json.dumps({"owner": "legacy"}))
    (vault / "stray-spec.md").write_text(_spec_text("mallory"), encoding="utf-8")

    assert load_parsed_spec(vault)["owner"] == "legacy"


def test_explicit_spec_file_is_used_and_recorded(vault: Path) -> None:
    (vault / "research.spec.md").unlink()
    hand_named = vault / "my-notes-spec.md"
    hand_named.write_text(_spec_text("dana"), encoding="utf-8")

    doc = load_parsed_spec(vault, write_cache=True, spec_file=hand_named)

    assert doc["owner"] == "dana"
    assert doc["spec_file"] == "my-notes-spec.md"
    # later loads find it again through the recorded name, no glob needed
    assert load_parsed_spec(vault)["owner"] == "dana"


def test_spec_edited_during_the_parse_is_not_stamped_as_current(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stamp carries the digest taken BEFORE parsing, so a concurrent edit
    leaves a cache that the next load recognises as stale."""
    from research_framework.spec import simple

    real_load = simple.load
    spec = vault / "research.spec.md"

    def edit_then_parse(path: Path, **kw: object):  # type: ignore[no-untyped-def]
        result = real_load(path, **kw)
        spec.write_text(_spec_text("edited-mid-parse"), encoding="utf-8")
        return result

    monkeypatch.setattr(simple, "load", edit_then_parse)
    load_parsed_spec(vault, write_cache=True)
    monkeypatch.setattr(simple, "load", real_load)

    assert _cache(vault)["owner"] == "alice"  # what the parse saw
    assert load_parsed_spec(vault)["owner"] == "edited-mid-parse"


# Always-present top-level keys of SpecConfig.to_dict() at PARSER_VERSION == 1
# (``forbidden_filename_prefixes`` is emitted only when non-empty). Changing the
# parsed shape means a cache written earlier is wrong about it: bump
# PARSER_VERSION in spec/parsed.py, then update this set and the version below.
_SHAPE_AT_VERSION = (
    1,
    frozenset(
        {
            "access_modes",
            "budget",
            "code_source_url_patterns",
            "coverage_targets",
            "data_sources",
            "jira_project",
            "location",
            "naming_convention",
            "name",
            "note_types",
            "owner",
            "processors",
            "research_mode",
            "scope",
            "search_dimensions",
            "settings",
            "vault_corpus_dir",
        }
    ),
)


def test_parser_version_tracks_the_parsed_shape() -> None:
    spec = SpecConfig.from_dict({"name": "x", "owner": "y"})
    version, keys = _SHAPE_AT_VERSION

    assert PARSER_VERSION == version, "update _SHAPE_AT_VERSION with the bump"
    assert set(spec.to_dict()) == keys, (
        "SpecConfig.to_dict() changed shape: bump PARSER_VERSION "
        "in spec/parsed.py and update _SHAPE_AT_VERSION"
    )
