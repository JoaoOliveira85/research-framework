"""Tier 2: every reader of the parsed spec sees fresh data (issue #9).

Each test leaves a stale ``spec-parse.json`` next to a spec that has since
changed, with the mtimes arranged so an mtime comparison would call the cache
current, then asserts the reader reports the spec's data. The loader's own
rules are pinned in ``tests/spec/test_parsed_spec_cache.py``; these tests pin
that the readers actually go through it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from research_framework.cli_inventory import build_inventory
from research_framework.onboard import _step_parse_spec
from research_framework.prune import prune_vault
from research_framework.spec.parsed import spec_parse_path


def _spec(name: str, owner: str = "alice", corpus: str | None = None) -> str:
    vault_block = f"vault:\n  corpus_dir: {corpus}\n" if corpus else ""
    return (
        "---\n"
        f'name: "{name}"\n'
        f'owner: "{owner}"\n'
        'topic: "A small topic for reader tests"\n'
        f"{vault_block}"
        "---\n\nBody.\n"
    )


def _stale_cache(vault: Path, **doc: object) -> None:
    """A cache an mtime check would trust: newer than the spec, wrong hash."""
    path = spec_parse_path(vault)
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps({**doc, "spec_sha256": "0" * 64, "parser_version": 1}),
        encoding="utf-8",
    )
    spec = vault / "research.spec.md"
    older = path.stat().st_mtime - 3600
    os.utime(spec, (older, older))


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    v = tmp_path / "reader-vault"
    (v / "_pipeline").mkdir(parents=True)
    return v


def test_inventory_reports_the_current_spec_not_the_stale_cache(vault: Path) -> None:
    (vault / "data_vault").mkdir()
    (vault / "research.spec.md").write_text(_spec("Fresh Name"), encoding="utf-8")
    _stale_cache(vault, name="Stale Name", owner="x", vault_corpus_dir="data_vault")
    cache_before = spec_parse_path(vault).read_bytes()

    inventory = build_inventory(vault)

    assert inventory["vault_spec"]["name"] == "Fresh Name"
    # inventory is a diagnostic: it must not rewrite the vault's cache
    assert spec_parse_path(vault).read_bytes() == cache_before


def test_prune_resolves_the_corpus_dir_from_the_current_spec(vault: Path) -> None:
    (vault / "research.spec.md").write_text(
        _spec("V", corpus="fresh_corpus"), encoding="utf-8"
    )
    _stale_cache(vault, name="V", vault_corpus_dir="stale_corpus")

    with pytest.raises(ValueError) as excinfo:
        prune_vault(vault, yes=True, force=True)

    assert "fresh_corpus" in str(excinfo.value)
    assert "stale_corpus" not in str(excinfo.value)


def test_corpus_resolver_follows_the_current_spec(vault: Path) -> None:
    from research_framework.vault.corpus import corpus_dir_name

    (vault / "research.spec.md").write_text(
        _spec("V", corpus="fresh_corpus"), encoding="utf-8"
    )
    _stale_cache(vault, name="V", vault_corpus_dir="stale_corpus")

    assert corpus_dir_name(vault) == "fresh_corpus"


def test_onboard_reparses_a_changed_spec_that_looks_older_than_the_cache(
    vault: Path,
) -> None:
    (vault / "data_vault").mkdir()
    spec = vault / "research.spec.md"
    spec.write_text(_spec("V", owner="alice"), encoding="utf-8")
    assert _step_parse_spec(vault).status == "done"

    spec.write_text(_spec("V", owner="bob"), encoding="utf-8")
    cache_mtime = spec_parse_path(vault).stat().st_mtime
    os.utime(spec, (cache_mtime - 3600, cache_mtime - 3600))

    assert _step_parse_spec(vault).status == "done"
    assert json.loads(spec_parse_path(vault).read_text())["owner"] == "bob"


def test_onboard_skips_when_content_is_unchanged_even_if_mtime_is_newer(
    vault: Path,
) -> None:
    (vault / "data_vault").mkdir()
    spec = vault / "research.spec.md"
    spec.write_text(_spec("V"), encoding="utf-8")
    assert _step_parse_spec(vault).status == "done"
    cache_mtime = spec_parse_path(vault).stat().st_mtime
    os.utime(spec, (cache_mtime + 3600, cache_mtime + 3600))

    assert _step_parse_spec(vault).status == "skipped"


def test_onboard_aborts_on_an_invalid_spec(vault: Path) -> None:
    (vault / "research.spec.md").write_text("---\nname: only\n---\n", encoding="utf-8")

    result = _step_parse_spec(vault)

    assert result.status == "aborted"
    assert not spec_parse_path(vault).exists()


def test_parse_spec_verb_stamps_the_cache(vault: Path) -> None:
    import argparse

    from research_framework.cli.vault import _cmd_parse_spec
    from research_framework.spec.parsed import PARSER_VERSION, spec_file_sha256

    (vault / "data_vault").mkdir()
    spec = vault / "research.spec.md"
    spec.write_text(_spec("V"), encoding="utf-8")

    rc = _cmd_parse_spec(argparse.Namespace(vault_path=vault, spec_path=spec))

    doc = json.loads(spec_parse_path(vault).read_text())
    assert rc == 0
    assert doc["spec_sha256"] == spec_file_sha256(spec)
    assert doc["parser_version"] == PARSER_VERSION


def _broken_spec(vault: Path) -> None:
    (vault / "research.spec.md").write_text("---\nname: only\n---\n", encoding="utf-8")


def _primed(vault: Path, **extra: object) -> bytes:
    """A good, stamped cache for a valid spec; returns its bytes."""
    from research_framework.spec.parsed import load_parsed_spec

    (vault / "research.spec.md").write_text(
        _spec("V", corpus="notes"), encoding="utf-8"
    )
    doc = load_parsed_spec(vault, write_cache=True)
    if extra:
        spec_parse_path(vault).write_text(json.dumps({**doc, **extra}))
    return spec_parse_path(vault).read_bytes()


def test_corpus_resolver_keeps_the_declared_folder_when_the_spec_is_invalid(
    vault: Path,
) -> None:
    from research_framework.vault.corpus import corpus_dir_name

    _primed(vault)
    _broken_spec(vault)

    assert corpus_dir_name(vault) == "notes"


def test_corpus_resolver_is_read_only(vault: Path) -> None:
    from research_framework.vault.corpus import corpus_dir_name

    (vault / "research.spec.md").write_text(_spec("V", corpus="notes"))
    corpus_dir_name(vault)

    assert not spec_parse_path(vault).exists()


def test_claims_export_loader_is_read_only(vault: Path) -> None:
    from research_framework.vault.claims_export import _load_spec

    (vault / "research.spec.md").write_text(_spec("V"))
    warnings: list[str] = []

    assert _load_spec(vault, warnings) is not None
    assert not spec_parse_path(vault).exists()


def test_runner_declared_sources_survive_an_invalid_spec(vault: Path) -> None:
    from research_framework.pipeline.runner import _declared_sources

    _primed(vault, data_sources=[{"name": "Web", "type": "external"}])
    _broken_spec(vault)

    assert _declared_sources(vault) == ["Web"]


def test_runner_refreshes_a_stale_cache_on_disk(vault: Path) -> None:
    from research_framework.pipeline.runner import _read_parsed_spec

    (vault / "research.spec.md").write_text(_spec("V", owner="bob"))
    _stale_cache(vault, owner="alice")

    doc, error = _read_parsed_spec(vault)

    assert error is None and doc["owner"] == "bob"
    assert json.loads(spec_parse_path(vault).read_text())["owner"] == "bob"


def test_onboard_stays_strict_when_the_spec_is_invalid_despite_a_cache(
    vault: Path,
) -> None:
    (vault / "data_vault").mkdir()
    _primed(vault)
    _broken_spec(vault)

    assert _step_parse_spec(vault).status == "aborted"


def test_onboard_accepts_a_hand_named_spec_and_records_it(vault: Path) -> None:
    (vault / "data_vault").mkdir()
    (vault / "my-notes-spec.md").write_text(_spec("V"), encoding="utf-8")

    assert _step_parse_spec(vault).status == "done"
    assert json.loads(spec_parse_path(vault).read_text())["spec_file"] == (
        "my-notes-spec.md"
    )
    assert _step_parse_spec(vault).status == "skipped"


def test_regenerate_agents_stays_strict_when_the_spec_is_invalid(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import argparse

    from research_framework.cli.vault import _cmd_regenerate_agents

    _primed(vault)
    _broken_spec(vault)

    rc = _cmd_regenerate_agents(
        argparse.Namespace(vault_path=vault, agent=None, force=True)
    )

    assert rc == 2
    assert "spec-parse.json" in capsys.readouterr().err
