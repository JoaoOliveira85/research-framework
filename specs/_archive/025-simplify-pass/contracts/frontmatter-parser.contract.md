# Contract: `vault.frontmatter` Canonical Parser (B4)

**Owner**: Spec 025 US7 B4.
**Status**: pinned at spec 025 plan time (2026-05-21).

This contract pins the canonical frontmatter-parser API that
replaces the 12+ scattered parsers in the codebase. The goal is
consistency: every metric, validator, and downstream consumer
that reads a vault note's frontmatter goes through ONE parser
that handles the edge cases identically.

---

## § 1 — Public API

```python
# vault/frontmatter.py

def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown file at *path*.

    Returns (frontmatter_dict, body_markdown). If the file has no
    frontmatter (no leading `---` block), returns ({}, file_content).

    Raises FrontmatterParseError on malformed frontmatter.
    """


def parse_frontmatter_str(content: str) -> tuple[dict[str, Any], str]:
    """Same as parse_frontmatter but accepts in-memory content
    (no file I/O). Convenient for tests."""


def dump_frontmatter(
    frontmatter: dict[str, Any],
    body: str,
    *,
    sort_keys: bool = False,
) -> str:
    """Reverse operation: build a markdown string with YAML frontmatter.

    If `frontmatter` is empty, returns body unchanged (no `---` block).
    If non-empty, returns `---\\n{yaml.dump(frontmatter)}---\\n{body}`.

    `sort_keys=False` (default) preserves insertion order — matches
    PyYAML's default behaviour on Python 3.11+ (dicts are insertion-
    ordered).
    """


class FrontmatterParseError(Exception):
    """Raised when YAML frontmatter is malformed."""

    def __init__(
        self,
        message: str,
        *,
        path: Path | None = None,
        line_no: int | None = None,
    ):
        self.path = path
        self.line_no = line_no
        super().__init__(message)
```

---

## § 2 — Format recognised

A markdown file has frontmatter IF AND ONLY IF:

1. The file content starts with the literal line `---\n` (three
   hyphens followed by a newline, no leading whitespace).
2. A subsequent line consists of exactly `---\n` (the closing
   delimiter).
3. The text between the two delimiters parses as valid YAML.

If condition 1 is false, the file has no frontmatter; the parser
returns `({}, full_content)`.

If condition 1 is true but condition 2 is false (no closing
delimiter found before EOF), the parser raises
`FrontmatterParseError("missing closing --- delimiter")`.

If conditions 1 + 2 are true but condition 3 is false (YAML
parse error), the parser raises
`FrontmatterParseError(f"YAML parse error: {yaml_err}")` with
`line_no` set to the YAML error's reported line + 1 (offset by
1 for the opening `---` line).

---

## § 3 — Edge cases and exact behaviour

| Input shape | Output |
|-------------|--------|
| `"---\n---\n# Title\n..."` (empty frontmatter, present delimiters) | `({}, "# Title\n...")`. |
| `"# Title\n..."` (no frontmatter at all) | `({}, "# Title\n...")`. |
| `"---\ntitle: foo\n---\n# Title\n..."` | `({"title": "foo"}, "# Title\n...")`. |
| `"---\ntitle: foo\n# Title\n..."` (missing closing delimiter) | `FrontmatterParseError("missing closing --- delimiter")`. |
| `"---\ntitle: [unclosed\n---\n..."` (YAML error) | `FrontmatterParseError("YAML parse error: ...")`. |
| `"---\ntitle: foo\n---\nbody1\n---\nbody2\n..."` (extra `---` in body) | `({"title": "foo"}, "body1\n---\nbody2\n...")`. The first `---\n` after the opening fence closes frontmatter; subsequent `---` in the body are preserved. |
| `"---\n---\n"` (empty frontmatter, empty body, file ends after closing delimiter) | `({}, "")`. |
| `""` (empty file) | `({}, "")`. |
| `"---\n!!python/object\n---\n..."` (unsafe YAML tag) | `FrontmatterParseError("unsafe YAML construct")`. The parser uses `yaml.safe_load`, which rejects custom tags. |
| Unicode keys / values (`"---\nkey: \\u00e9\\n---\\n..."`) | Parsed and preserved as Python `str` objects. |
| Nested keys (`"---\nlevel1:\\n  level2: foo\\n---\\n..."`) | `({"level1": {"level2": "foo"}}, ...)`. Nested dicts preserved. |
| Multi-document YAML (`"---\nkey1: foo\\n---\\nkey2: bar\\n---\\n..."`, three delimiters) | First `---` opens, second `---` closes frontmatter; remaining body retains the third `---` literally. Parser does NOT support YAML multi-doc semantics. |
| Frontmatter is a YAML list (e.g. `"---\n- a\n- b\n---\n..."`) | `FrontmatterParseError("frontmatter must be a mapping, got list")`. The parser rejects non-dict top-level frontmatter. |

---

## § 4 — Symmetry invariant

For any well-formed input string `s` produced by `dump_frontmatter`:

```python
fm, body = parse_frontmatter_str(s)
s_roundtrip = dump_frontmatter(fm, body)
parse_frontmatter_str(s_roundtrip) == (fm, body)
```

This roundtrip property MUST hold modulo whitespace
normalisation (e.g. trailing newlines on the body, YAML
serialisation choices like quoting). Specifically:

- Whitespace ambiguities: `dump_frontmatter` always ends with a
  single `\n` on the body's final non-empty line.
- Key ordering: insertion order preserved in `parse`; output by
  `dump` in insertion order unless `sort_keys=True`.
- Multi-line string values: parsed as `str`; dumped using PyYAML's
  default style (may be `|`- or `>`-folded depending on content).
  Roundtrip equality holds at the `dict[str, Any]` level even if
  the YAML serialisation byte-shape changes.

The roundtrip is tested in
`tests/vault/test_frontmatter.py::test_dump_parse_roundtrip` for
each fixture file.

---

## § 5 — Performance contract

- `parse_frontmatter` MUST handle a 1 MB markdown file in
  < 100 ms on a recent Mac. (Currently the vault has no files
  near this size; the cap is set for headroom.)
- `parse_frontmatter` MUST NOT load the entire file content if
  the file has no frontmatter — short-circuit on the first
  non-`---\n` line. (Implementation: read first 4 bytes; if not
  `---\n`, return `({}, full_read)`.)
- No regex-of-the-whole-file approaches. Use line-by-line
  scanning to find the closing delimiter.

---

## § 6 — Migration target

Pre-refactor: the codebase has 12+ frontmatter parsers, each with
slightly different edge-case handling. Inventory at v0.2.33 (to
be enumerated precisely during `/speckit.tasks`):

| Site (approximate) | Current pattern | Migration plan |
|--------------------|-----------------|----------------|
| `processors/note_validator.py` | inline `yaml.safe_load` after `---` split | Replace with `parse_frontmatter` |
| `processors/wikilinks.py` | regex + `yaml.safe_load` | Replace |
| `processors/coverage.py` | inline | Replace |
| `processors/quality_report.py` | inline | Replace |
| `pipeline/orchestrator.py` | inline | Replace |
| `pipeline/scout.py` | inline | Replace |
| `pipeline/research_plan.py` | inline | Replace |
| `pipeline/source_manager.py` | inline (one of two patterns) | Replace |
| `tests/_helpers/vault_factory.py` | inline | Replace |
| ... (4+ more enumerated during tasks) | various | Replace or document as holdout |

**Migration target (FR-010 + SC-007)**: ≥ 8 of the ≥ 12 sites
migrate. Holdouts get inline comments:

```python
# Holdout from spec 025 B4 canonical parser migration.
# Reason: this site needs to detect malformed frontmatter
# without raising (it's part of the schema-drift report). The
# canonical parser raises FrontmatterParseError; this site needs
# the soft-fail behaviour.
fm = _parse_frontmatter_soft_fail(path)
```

Each holdout's reason MUST be specific and verifiable (not "this
is complex").

---

## § 7 — Test coverage

Spec 025 ships these tests for the contract:

| Test | Assertion |
|------|-----------|
| `tests/vault/test_frontmatter.py::test_parse_empty_frontmatter` | `({}, "# Title")`-style cases. |
| `tests/vault/test_frontmatter.py::test_parse_no_frontmatter` | Files without leading `---` return `({}, full_content)`. |
| `tests/vault/test_frontmatter.py::test_parse_well_formed` | Standard happy-path inputs. |
| `tests/vault/test_frontmatter.py::test_parse_missing_closing_delimiter_raises` | Raises `FrontmatterParseError`. |
| `tests/vault/test_frontmatter.py::test_parse_malformed_yaml_raises` | Raises with `line_no` set. |
| `tests/vault/test_frontmatter.py::test_parse_unsafe_yaml_rejected` | Custom tags raise. |
| `tests/vault/test_frontmatter.py::test_parse_unicode` | Unicode keys/values preserved. |
| `tests/vault/test_frontmatter.py::test_parse_nested_keys` | Nested dicts preserved. |
| `tests/vault/test_frontmatter.py::test_parse_multi_doc_yaml` | Only first `---` block parsed as frontmatter; rest preserved in body. |
| `tests/vault/test_frontmatter.py::test_parse_list_frontmatter_rejected` | Non-dict top-level raises. |
| `tests/vault/test_frontmatter.py::test_dump_parse_roundtrip` | Symmetry invariant § 4. |
| `tests/vault/test_frontmatter.py::test_perf_1mb_file` | < 100 ms for 1 MB input. |
| `tests/vault/test_frontmatter.py::test_short_circuit_on_no_frontmatter` | Verify no full-file read for non-frontmatter files. |

All tests are tier-1 (unit) per ADR-0008 — pure function tests
with temp-file fixtures.
