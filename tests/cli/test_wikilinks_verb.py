"""Spec 067 FR4/FR5 — ``vault wikilinks`` sweep verb (contracts V-a..V-e)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from research_framework.cli._parser import build_parser
from research_framework.cli.wikilinks import cmd_wikilinks


def _note(vault: Path, stem: str, title: str, *, body: str = "", **extra) -> Path:
    data = vault / "data_vault"
    data.mkdir(parents=True, exist_ok=True)
    fm = [f"title: {title}", "type: concept"]
    for k, v in extra.items():
        fm.append(f"{k}: {v}")
    p = data / f"{stem}.md"
    p.write_text(
        "---\n" + "\n".join(fm) + "\n---\n" + (body or "Body.\n"), encoding="utf-8"
    )
    return p


def _build_corrupted_vault(tmp_path: Path) -> Path:
    """An already-corrupted rc7-shape vault: a ``CAP Theorem`` note whose body
    links its own title to the sibling ``cache-aside pattern`` expansion, plus a
    stale ``cap.md`` alias stub pointing at the sibling."""
    vault = tmp_path / "v"
    _note(vault, "cache-aside-pattern", "Cache-Aside Pattern")
    _note(
        vault,
        "cap-theorem",
        "CAP Theorem",
        body="The [[CAP]] Theorem says you can't have all three.\n",
    )
    return vault


def _args(
    vault: Path, *, fix: bool = False, as_json: bool = False
) -> argparse.Namespace:
    return argparse.Namespace(vault=vault, fix=fix, json=as_json)


def test_dry_run_writes_nothing(tmp_path: Path, capsys) -> None:
    """V-a: dry-run reports actions and writes nothing."""
    vault = _build_corrupted_vault(tmp_path)
    cap = vault / "data_vault" / "cap-theorem.md"
    before = cap.read_text(encoding="utf-8")
    rc = cmd_wikilinks(_args(vault, fix=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "plaintext_body_link" in out
    assert cap.read_text(encoding="utf-8") == before  # unchanged


def test_fix_repairs_body_link(tmp_path: Path) -> None:
    """V-b: --fix de-links the self-title-corrupting body wikilink."""
    vault = _build_corrupted_vault(tmp_path)
    cap = vault / "data_vault" / "cap-theorem.md"
    rc = cmd_wikilinks(_args(vault, fix=True))
    assert rc == 0
    text = cap.read_text(encoding="utf-8")
    assert "[[cache-aside-pattern]]" not in text
    assert "The CAP Theorem says" in text


def test_fix_reverse_maps_fully_expanded_self_acronym_link(tmp_path: Path) -> None:
    """V-b (rc7 retroactive-heal): the corruption that actually shipped in
    reference-vault-rc7 was the acronym already *expanded in full* — ``The CAP Theorem``
    rewritten to ``The [[cache-aside pattern]] Theorem``. The sweep must reverse-map
    a bare ``[[phrase]]`` whose derived acronym IS the note's own title acronym back
    to the plain acronym, even though the link points at a real sibling note (so the
    all-caps ``[[CAP]]`` path never sees it)."""
    vault = tmp_path / "v"
    _note(vault, "cache-aside pattern", "Cache-Aside Pattern")
    _note(
        vault,
        "cap-theorem",
        "CAP Theorem",
        body=(
            "The [[cache-aside pattern]] Theorem, proven by Brewer, states three.\n\n"
            "PACELC extends [[cache-aside pattern]]: even without a partition.\n"
        ),
    )
    cap = vault / "data_vault" / "cap-theorem.md"
    rc = cmd_wikilinks(_args(vault, fix=True))
    assert rc == 0
    text = cap.read_text(encoding="utf-8")
    assert "[[cache-aside pattern]]" not in text
    assert "The CAP Theorem, proven by Brewer" in text
    assert "PACELC extends CAP:" in text


def test_fix_keeps_aliased_self_acronym_link(tmp_path: Path) -> None:
    """An explicitly *aliased* link (``[[cache-aside pattern|...]]``) is an author
    display choice — the reverse-map heal only touches bare links, never an alias."""
    vault = tmp_path / "v"
    _note(vault, "cache-aside pattern", "Cache-Aside Pattern")
    _note(
        vault,
        "cap-theorem",
        "CAP Theorem",
        body="See the [[cache-aside pattern|caching strategy]] for details.\n",
    )
    cap = vault / "data_vault" / "cap-theorem.md"
    cmd_wikilinks(_args(vault, fix=True))
    text = cap.read_text(encoding="utf-8")
    assert "[[cache-aside pattern|caching strategy]]" in text


def test_fix_is_idempotent(tmp_path: Path, capsys) -> None:
    """V-c: a second --fix run reports zero actions."""
    vault = _build_corrupted_vault(tmp_path)
    cmd_wikilinks(_args(vault, fix=True))
    capsys.readouterr()
    rc = cmd_wikilinks(_args(vault, fix=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "no actions needed" in out


def test_json_emits_action_records(tmp_path: Path, capsys) -> None:
    """V-d: --json emits a well-formed SweepActionRecord[]."""
    vault = _build_corrupted_vault(tmp_path)
    rc = cmd_wikilinks(_args(vault, fix=False, as_json=True))
    assert rc == 0
    records = json.loads(capsys.readouterr().out)
    assert isinstance(records, list)
    assert records, "expected at least one action on the corrupted vault"
    for r in records:
        assert set(r) >= {"action", "path", "detail"}
        assert r["action"] in {
            "plaintext_body_link",
            "repoint_stub",
            "delete_stub",
            "noop",
        }


def test_ambiguous_stub_deleted(tmp_path: Path) -> None:
    """V-b (stub branch): an ambiguous alias stub is deleted under --fix."""
    vault = tmp_path / "v"
    data = vault / "data_vault"
    _note(vault, "shared-processing-and-control", "Shared Processing And Control")
    _note(vault, "system-process-control", "System Process Control")
    stub = data / "spc.md"
    stub.write_text(
        "---\ntitle: SPC\nnote_type: alias\nredirect_to: system-process-control\n"
        "verifier_status: exempt\n---\nSee [[system-process-control]].\n",
        encoding="utf-8",
    )
    cmd_wikilinks(_args(vault, fix=True))
    assert not stub.exists()


def test_parser_registers_wikilinks_verb() -> None:
    """V-e (parser): the ``wikilinks`` subcommand is wired with the sweep handler."""
    parser = build_parser()
    ns = parser.parse_args(["wikilinks", "--vault", "/tmp/v", "--fix", "--json"])
    assert ns.func is cmd_wikilinks
    assert ns.fix is True and ns.json is True


def test_shim_routes_wikilinks() -> None:
    """V-e (shim): the rendered vault shim dispatches ``wikilinks)`` to the CLI."""
    template = (
        Path(__file__).resolve().parents[2] / "templates" / "vault-script.sh.j2"
    ).read_text(encoding="utf-8")
    assert "wikilinks)" in template
    assert '-m research_framework.cli wikilinks --vault "${VAULT_DIR}" "$@"' in template
