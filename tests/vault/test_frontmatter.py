"""Tier-1 tests for vault.frontmatter (spec 025 US7 B4, contract § 7)."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from research_framework.vault.frontmatter import (
    FrontmatterParseError,
    append_frontmatter_keys,
    dump_frontmatter,
    parse_frontmatter,
    parse_frontmatter_str,
    split_frontmatter,
)


def test_parse_empty_frontmatter() -> None:
    fm, body = parse_frontmatter_str("---\n---\n# Title\n")
    assert fm == {}
    assert body == "# Title\n"


def test_parse_no_frontmatter() -> None:
    content = "# Title\n\nBody text.\n"
    fm, body = parse_frontmatter_str(content)
    assert fm == {}
    assert body == content


def test_parse_well_formed() -> None:
    fm, body = parse_frontmatter_str("---\ntitle: foo\n---\n# Title\n")
    assert fm == {"title": "foo"}
    assert body == "# Title\n"


def test_parse_missing_closing_delimiter_raises() -> None:
    with pytest.raises(FrontmatterParseError, match="missing closing --- delimiter"):
        parse_frontmatter_str("---\ntitle: foo\n# Title\n")


def test_parse_malformed_yaml_raises() -> None:
    with pytest.raises(FrontmatterParseError, match="YAML parse error") as exc_info:
        parse_frontmatter_str("---\ntitle: [unclosed\n---\nbody\n")
    assert exc_info.value.line_no is not None


def test_parse_unsafe_yaml_rejected() -> None:
    with pytest.raises(FrontmatterParseError, match="unsafe YAML construct"):
        parse_frontmatter_str("---\n!!python/object\n---\nbody\n")


def test_parse_unicode() -> None:
    fm, body = parse_frontmatter_str("---\nkey: \u00e9\n---\nbody\n")
    assert fm == {"key": "\u00e9"}
    assert body == "body\n"


def test_parse_nested_keys() -> None:
    fm, body = parse_frontmatter_str("---\nlevel1:\n  level2: foo\n---\nbody\n")
    assert fm == {"level1": {"level2": "foo"}}
    assert body == "body\n"


def test_parse_multi_doc_yaml() -> None:
    content = "---\nkey1: foo\n---\nkey2: bar\n---\nrest\n"
    fm, body = parse_frontmatter_str(content)
    assert fm == {"key1": "foo"}
    assert body == "key2: bar\n---\nrest\n"


def test_parse_list_frontmatter_rejected() -> None:
    with pytest.raises(
        FrontmatterParseError, match="frontmatter must be a mapping, got list"
    ):
        parse_frontmatter_str("---\n- a\n- b\n---\nbody\n")


def test_dump_parse_roundtrip(tmp_path: Path) -> None:
    cases = [
        ({"title": "Roundtrip", "tags": ["a", "b"]}, "# Body\n\nParagraph.\n"),
        ({}, "no frontmatter body\n"),
        ({"nested": {"x": 1}}, "text\n"),
    ]
    for meta, body in cases:
        rendered = dump_frontmatter(meta, body)
        fm, parsed_body = parse_frontmatter_str(rendered)
        assert fm == meta
        assert parsed_body == body


def test_perf_1mb_file(tmp_path: Path) -> None:
    body = "x" * (1024 * 1024 - 64)
    path = tmp_path / "large.md"
    path.write_text(f"---\ntitle: big\n---\n{body}", encoding="utf-8")
    start = time.perf_counter()
    fm, parsed_body = parse_frontmatter(path)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert fm == {"title": "big"}
    assert len(parsed_body) == len(body)
    assert elapsed_ms < 100


def test_short_circuit_on_no_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "plain.md"
    path.write_text("# No frontmatter\n" + ("z" * 5000), encoding="utf-8")

    with patch(
        "research_framework.vault.frontmatter.parse_frontmatter_str",
        side_effect=AssertionError("parse_frontmatter_str must not run"),
    ):
        fm, body = parse_frontmatter(path)
    assert fm == {}
    assert body.startswith("# No frontmatter")


# ---------------------------------------------------------------------------
# Issue #287: CRLF line endings / UTF-8 BOM silently discarded frontmatter.
# ---------------------------------------------------------------------------


def test_crlf_line_endings_do_not_lose_frontmatter(tmp_path: Path) -> None:
    """A note saved with CRLF line endings used to fail the ``b"---\\n"``
    byte match on the opening delimiter and read as having no frontmatter
    at all — silently, with no parse error."""
    path = tmp_path / "crlf.md"
    path.write_bytes(b"---\r\ntitle: crlf note\r\nrelated: [x]\r\n---\r\nBody.\r\n")

    fm, body = parse_frontmatter(path)

    assert fm == {"title": "crlf note", "related": ["x"]}
    assert "Body." in body


def test_utf8_bom_does_not_lose_frontmatter(tmp_path: Path) -> None:
    """A leading UTF-8 BOM used to shift the first 4 bytes away from
    ``b"---\\n"`` and produce the same silent no-frontmatter result."""
    path = tmp_path / "bom.md"
    path.write_bytes(
        b"\xef\xbb\xbf---\ntitle: bom note\ncoverage_category: x\n---\nBody.\n"
    )

    fm, body = parse_frontmatter(path)

    assert fm == {"title": "bom note", "coverage_category": "x"}
    assert body == "Body.\n"


def test_utf8_bom_with_crlf_does_not_lose_frontmatter(tmp_path: Path) -> None:
    """Both defects compound (a BOM-and-CRLF file from a Windows editor) —
    pinned separately since either alone used to be enough to trigger the
    bug and a fix for only one would still leave this combination broken."""
    path = tmp_path / "bom-crlf.md"
    path.write_bytes(b"\xef\xbb\xbf---\r\ntitle: both\r\n---\r\nBody.\r\n")

    fm, body = parse_frontmatter(path)

    assert fm == {"title": "both"}
    assert "Body." in body


def test_bare_cr_line_endings_do_not_lose_frontmatter(tmp_path: Path) -> None:
    """Legacy classic-Mac ``\\r``-only line endings are the third universal-
    newline case ``Path.read_text()`` already normalizes for every other
    reader in this codebase."""
    path = tmp_path / "cr.md"
    path.write_bytes(b"---\rtitle: cr note\r---\rBody.\r")

    fm, body = parse_frontmatter(path)

    assert fm == {"title": "cr note"}
    assert "Body." in body


# ---------------------------------------------------------------------------
# split_frontmatter: the raw split for readers that must not raise on bad YAML.
# ---------------------------------------------------------------------------


def test_split_returns_the_yaml_text_and_the_body() -> None:
    assert split_frontmatter("---\ntitle: foo\n---\n# Title\n") == (
        "title: foo\n",
        "# Title\n",
    )


@pytest.mark.parametrize(
    "value_line",
    [
        "url: https://example.com/kafka---a-guide",
        'topic: "Kafka --- a guide"',
        "# ---------------------------------------",
        "  --- indented, so part of a block scalar",
    ],
)
def test_split_does_not_end_the_frontmatter_at_dashes_inside_a_line(
    value_line: str,
) -> None:
    """Only a whole `---` line is a delimiter, never a `---` substring."""
    content = f"---\nfirst: 1\n{value_line}\nlast: 2\n---\nbody\n"
    assert split_frontmatter(content) == (
        f"first: 1\n{value_line}\nlast: 2\n",
        "body\n",
    )


def test_split_tolerates_trailing_whitespace_on_the_delimiter_lines() -> None:
    assert split_frontmatter("--- \ntitle: foo\n---\t\nbody\n") == (
        "title: foo\n",
        "body\n",
    )


def test_split_closing_delimiter_may_be_the_last_line() -> None:
    assert split_frontmatter("---\ntitle: foo\n---") == ("title: foo\n", "")


@pytest.mark.parametrize(
    "content",
    [
        "# Title\n\nBody text.\n",
        "---\ntitle: foo\n# never closed\n",
        "----\ntitle: foo\n---\nbody\n",
        "",
    ],
)
def test_split_returns_none_without_a_delimited_block(content: str) -> None:
    assert split_frontmatter(content) is None


# ---------------------------------------------------------------------------
# append_frontmatter_keys: add keys without re-emitting the lines already there.
# ---------------------------------------------------------------------------


def test_append_keeps_every_existing_line() -> None:
    content = "---\n# keep me\nzip: 0123\npublic: no\n---\nBody.\n"

    assert append_frontmatter_keys(content, {"related": [], "status": "draft"}) == (
        "---\n# keep me\nzip: 0123\npublic: no\n"
        "related: []\nstatus: draft\n"
        "---\nBody.\n"
    )


def test_append_after_a_block_scalar_and_a_closing_line_at_eof() -> None:
    content = "---\nsummary: |\n  two\n  lines\n---"

    patched = append_frontmatter_keys(content, {"status": "draft"})

    assert patched == "---\nsummary: |\n  two\n  lines\nstatus: draft\n---"
    assert parse_frontmatter_str(patched) == (
        {"summary": "two\nlines\n", "status": "draft"},
        "",
    )


def test_append_into_an_empty_block() -> None:
    assert append_frontmatter_keys("---\n---\nBody.\n", {"related": []}) == (
        "---\nrelated: []\n---\nBody.\n"
    )


@pytest.mark.parametrize(
    ("content", "additions"),
    [
        ("# Title\n\nBody.\n", {"status": "draft"}),  # no frontmatter block
        ("---\nstatus: final\n---\nBody.\n", {"status": "draft"}),  # key exists
        ("---\n{title: Flow}\n---\nBody.\n", {"status": "draft"}),  # flow mapping
        ("---\ntitle: [unclosed\n---\nBody.\n", {"status": "draft"}),  # malformed
        ("---\ntitle: x\n---\nBody.\n", {}),  # nothing to add
    ],
)
def test_append_returns_none_when_a_line_cannot_simply_be_added(
    content: str, additions: dict
) -> None:
    assert append_frontmatter_keys(content, additions) is None
