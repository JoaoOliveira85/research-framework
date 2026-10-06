"""``research-framework export --claims`` (issue #189, spec 077 exit codes)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.cli import main
from research_framework.vault.frontmatter import dump_frontmatter
from tests._helpers.vault_factory import build_minimal_vault


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    vault = build_minimal_vault(tmp_path, install_fake_agent=False)
    folder = vault / "data_vault" / "01 - Concepts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "alpha.md").write_text(
        dump_frontmatter(
            {
                "title": "Alpha",
                "type": "concept",
                "summary": "Alpha is first.",
                "source_urls": ["https://example.test/a"],
            },
            "# Alpha\n",
        ),
        encoding="utf-8",
    )
    q = vault / "_pipeline" / "quarantine"
    q.mkdir(parents=True)
    (q / "bad.md").write_text(
        dump_frontmatter(
            {"title": "Bad", "type": "concept", "summary": "s", "source_urls": []},
            "# Bad\n",
        ),
        encoding="utf-8",
    )
    return vault


def test_claims_to_stdout_is_json(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["export", "--vault", str(vault), "--claims"])
    assert rc == 0
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["schema_version"] == "1.0"
    assert [c["title"] for c in doc["claims"]] == ["Alpha"]
    assert out.endswith("\n")


def test_out_writes_the_file_and_says_so_on_stderr(
    vault: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "consumer" / "claims.json"
    rc = main(["export", "--vault", str(vault), "--claims", "--out", str(target)])
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert str(target) in captured.err
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert doc["counts"]["claims"] == 1


def test_include_quarantined_reaches_the_exporter(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["export", "--vault", str(vault), "--claims", "--include-quarantined"])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert sorted(c["title"] for c in doc["claims"]) == ["Alpha", "Bad"]
    assert doc["counts"]["quarantined"] == 1


def test_export_does_not_touch_the_vault(vault: Path) -> None:
    """Principle X exemption: the verb produces nothing on disk in the vault."""
    before = sorted(str(p.relative_to(vault)) for p in vault.rglob("*"))
    assert main(["export", "--vault", str(vault), "--claims"]) == 0
    after = sorted(str(p.relative_to(vault)) for p in vault.rglob("*"))
    assert before == after


def test_missing_claims_flag_is_a_usage_error(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["export", "--vault", str(vault)])
    assert rc == 2
    assert "--claims" in capsys.readouterr().err


def test_bad_vault_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["export", "--vault", str(tmp_path / "nope"), "--claims"])
    assert rc == 2
    assert "vault" in capsys.readouterr().err


def test_directory_without_a_corpus_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["export", "--vault", str(tmp_path), "--claims"])
    assert rc == 2
    assert "corpus" in capsys.readouterr().err
