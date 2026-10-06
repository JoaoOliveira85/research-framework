"""Every reader of a note's frontmatter ends it at the closing `---` LINE.

The readers below each carried their own `text.split("---", 2)`, which ends
the frontmatter at the first `---` substring. A slug URL such as
`https://example.com/kafka---a-guide` in `source_urls` is enough to cut it
there: the keys below the URL read as absent and the rest of the frontmatter
lands in the body. The canonical parser (`vault/frontmatter.py`) never did
this; these are the holdouts that cannot use it — they must not raise on
malformed YAML, or they ship into vaults as standalone scripts.

The readers that feed a writer have their own regression tests next to that
writer (`vault_health.py`, `fix_acronym_links.py`, the SKILL.md preflight).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from research_framework.generator.templates import render_all
from research_framework.pipeline import (
    branch_retention,
    gates_step,
    preflight,
    probes,
    stubs,
    vault_commit,
)
from research_framework.spec.parser import parse

REPO_ROOT = Path(__file__).resolve().parents[2]

_NOTE = (
    "---\n"
    "source_urls:\n"
    "- https://example.com/kafka---a-guide\n"
    "title: Kafka\n"
    "type: concept\n"
    "summary: The log.\n"
    "---\n"
    "\n"
    "Body.\n"
)


def _load_script(name: str):
    """Load a standalone ``scripts/<name>.py`` as a module."""
    spec = importlib.util.spec_from_file_location(
        f"_reader_{name}", REPO_ROOT / "scripts" / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered first: a script's @dataclass looks its module up by name.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _stubs(note: Path) -> tuple[object, str]:
    fm, body = stubs._split_frontmatter(note.read_text(encoding="utf-8"))
    return fm.get("title"), body


def _probes(note: Path) -> tuple[object, str]:
    fm_block, body = probes._split_frontmatter(note.read_text(encoding="utf-8"))
    return probes._fm_value(fm_block, "title"), body


def _check_template_compliance(note: Path) -> tuple[object, str]:
    fm, body = _load_script("check_template_compliance")._parse_frontmatter(note)
    return (fm or {}).get("title"), body


def _check_acronym_links(note: Path) -> tuple[object, str]:
    fm, body = _load_script("check_acronym_links")._parse_frontmatter(note)
    return (fm or {}).get("title"), body


@pytest.mark.parametrize(
    "read",
    [_stubs, _probes, _check_template_compliance, _check_acronym_links],
    ids=lambda read: read.__name__.lstrip("_"),
)
def test_dashes_inside_a_value_do_not_end_the_frontmatter(
    read: Callable[[Path], tuple[object, str]], tmp_path: Path
) -> None:
    note = tmp_path / "kafka.md"
    note.write_text(_NOTE, encoding="utf-8")

    title, body = read(note)

    assert title == "Kafka"
    assert body.strip() == "Body."


# A settings file opening with YAML's `---` document marker, then the comment
# rules the bundled `settings.yaml` is full of.
_SETTINGS = (
    "---\n"
    "# ---------------------------------------------------------------------------\n"
    "# Commit invariant\n"
    "# ---------------------------------------------------------------------------\n"
    "vault_commit:\n"
    "  enabled: false\n"
)

_SPEC_BODY = (
    "## Scope\ndomain: d\norganization: o\n\n"
    '## Note Types\n- name: concept\n  description: d\n  folder: "01 - Concepts"\n\n'
    "## {data_sources}\n- name: main-repo\n  type: internal\n  role: behaviour\n"
    "  required: false\n  access_method: local\n\n"
    "## Search Dimensions\ndimensions: []\n\n"
    "## Coverage Targets\ncategories: []\n\n"
    "## Budget\nmax_usd: 1\nmax_cycles: 1\n"
)


def _note(tmp_path: Path) -> Path:
    note = tmp_path / "kafka.md"
    note.write_text(_NOTE, encoding="utf-8")
    return note


def _settings_vault(tmp_path: Path) -> Path:
    (tmp_path / "settings.yaml").write_text(_SETTINGS, encoding="utf-8")
    return tmp_path


def _spec_owner(tmp_path: Path, data_sources_heading: str) -> object:
    spec = tmp_path / "research.spec.md"
    spec.write_text(
        "---\n"
        "name: Kafka\n"
        "description: https://example.com/kafka---a-guide\n"
        "location: ./\n"
        "owner: Kafka\n"
        "settings: {}\n"
        "---\n" + _SPEC_BODY.format(data_sources=data_sources_heading),
        encoding="utf-8",
    )
    return preflight.load_spec_for_preflight(spec, tmp_path).owner


def _sg005_gate(tmp_path: Path) -> object:
    return (gates_step._sg005_frontmatter_dict(_note(tmp_path)) or {}).get("title")


def _vault_metrics(tmp_path: Path) -> object:
    fm, _body = _load_script("vault_metrics")._parse_frontmatter(_note(tmp_path))
    return (fm or {}).get("title")


def _check_code_source_coverage(tmp_path: Path) -> object:
    return (
        _load_script("check_code_source_coverage")
        ._parse_frontmatter(_NOTE)
        .get("title")
    )


def _check_intent_drift(tmp_path: Path) -> object:
    fm, _body = _load_script("check_intent_drift")._parse_frontmatter(_NOTE)
    return fm.get("title")


def _vault_commit_settings(tmp_path: Path) -> object:
    return vault_commit._load_settings(_settings_vault(tmp_path))["enabled"]


def _branch_retention_settings(tmp_path: Path) -> object:
    data = branch_retention._read_settings_document(_settings_vault(tmp_path))
    return (data.get("vault_commit") or {}).get("enabled")


def _preflight_split_spec(tmp_path: Path) -> object:
    return _spec_owner(tmp_path, "Data Sources")


def _preflight_fallback(tmp_path: Path) -> object:
    """A heading the split-spec branch misses: the detailed parser rejects the
    file, and the fallback below it splits the frontmatter itself."""
    return _spec_owner(tmp_path, "data sources")


@pytest.mark.parametrize(
    ("read", "expected"),
    [
        (_sg005_gate, "Kafka"),
        (_vault_metrics, "Kafka"),
        (_check_code_source_coverage, "Kafka"),
        (_check_intent_drift, "Kafka"),
        (_vault_commit_settings, False),
        (_branch_retention_settings, False),
        (_preflight_split_spec, "Kafka"),
        (_preflight_fallback, "Kafka"),
    ],
    ids=lambda value: value.__name__.lstrip("_") if callable(value) else None,
)
def test_dashes_inside_a_line_do_not_hide_the_keys_below_them(
    read: Callable[[Path], object], expected: object, tmp_path: Path
) -> None:
    """The read-only holdouts that still split on the first `---` substring.

    Notes lost `title`/`summary` below a slug URL (SG-005 failed a complete
    note). A settings file opening with the `---` document marker ended at its
    first `# ----` comment rule, so `vault_commit.enabled: false` and the
    retention rules read as unset. A spec lost `owner` below a dashed value.
    """
    assert read(tmp_path) == expected


def test_generated_update_script_indexes_a_note_with_dashes_in_a_value(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """`update_vault.py reindex` reads each note's title, type and summary.

    Cut at the slug URL, the note was indexed under its file name with no
    summary and left out of `_concepts.md`.
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    render_all(parse(sample_spec_path), vault)
    concepts = vault / "data_vault" / "01 - Concepts"
    concepts.mkdir(parents=True)
    (concepts / "kafka.md").write_text(_NOTE, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(vault / "update_vault.py"), "reindex"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    entry = "- [[Kafka]] — The log."
    assert entry in (vault / "_index.md").read_text(encoding="utf-8")
    assert entry in (vault / "_concepts.md").read_text(encoding="utf-8")
