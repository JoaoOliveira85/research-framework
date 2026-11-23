"""The scripts an AGENT runs directly work under a bare interpreter.

The note-writer, scout and verifier agents run the vault's validation scripts
with whatever ``python`` is first on their PATH, and that interpreter may have no
usable ``research_framework`` install (a rehearsal found
``validate_vault.py`` dying on ``No module named 'research_framework.vault'``).
On ``main`` these scripts needed nothing from the package, and they must go on
working that way: a module-top import of the package is a regression. Here the
package is made unimportable by a stub that raises, ahead of the real one on
``PYTHONPATH``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from research_framework.vault import note_currency

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

# What the vault-facing prompts, README and skills tell an agent to run.
AGENT_FACING = (
    "validate_vault.py",  # templates/README.md.j2, CLAUDE.md
    "check_template_compliance.py",  # templates/README.md.j2
    "check_acronym_links.py",  # templates/README.md.j2
    "vault_metrics.py",  # templates/README.md.j2
    "vault_health.py",  # dfs prompt: --check-template-version
    "raw_capture.py",  # dfs prompt: before adding any URL to source_urls
    "validate_cycle.py",  # the cycle's own gate
)
# Needs the package by design (it parses a spec with the framework's parser);
# its failure must say so, in words, not with a traceback.
NEEDS_THE_PACKAGE = ("validate_spec.py",)


@pytest.fixture
def broken_package(tmp_path: Path) -> dict[str, str]:
    stub = tmp_path / "stub" / "research_framework"
    stub.mkdir(parents=True)
    (stub / "__init__.py").write_text(
        'raise ImportError("simulated: no usable research_framework install")\n'
    )
    env = {**os.environ, "PYTHONPATH": str(stub.parent)}
    return env


def _run(script: str, env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def test_the_stub_really_hides_the_package(broken_package: dict[str, str]) -> None:
    probe = subprocess.run(
        [sys.executable, "-c", "import research_framework"],
        capture_output=True,
        text=True,
        env=broken_package,
        check=False,
    )
    assert probe.returncode != 0 and "simulated" in probe.stderr


@pytest.mark.parametrize("script", AGENT_FACING)
def test_an_agent_facing_script_does_not_die_on_the_import(
    script: str, broken_package: dict[str, str]
) -> None:
    result = _run(script, broken_package, "--help")

    assert result.returncode == 0, result.stderr[-600:]
    assert "usage" in result.stdout.lower()
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("script", NEEDS_THE_PACKAGE)
def test_a_script_that_needs_the_package_says_so_instead_of_a_traceback(
    script: str, broken_package: dict[str, str]
) -> None:
    result = _run(script, broken_package, "--help")

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "research_framework" in result.stderr


def test_validate_vault_still_validates_under_a_bare_interpreter(
    tmp_path: Path, broken_package: dict[str, str]
) -> None:
    vault = tmp_path / "v"
    notes = vault / "data_vault" / "01 - Concepts"
    notes.mkdir(parents=True)
    body = ("lorem ipsum dolor sit amet " * 50).strip()
    (notes / "Stamped.md").write_text(
        "---\ntitle: Stamped\ntype: concept\nsummary: s\ntags: [x]\n"
        "source_urls: [https://example.com]\nrelated: []\ncreated: 2026-01-01\n"
        f"updated: 2026-01-01\nas_of: 2026-01-01\ncurrency: current\n---\n{body}\n",
        encoding="utf-8",
    )
    (notes / "Unstamped.md").write_text(
        (notes / "Stamped.md")
        .read_text()
        .replace("title: Stamped", "title: Unstamped")
        .replace("as_of: 2026-01-01\ncurrency: current\n", ""),
        encoding="utf-8",
    )

    result = _run("validate_vault.py", broken_package, str(vault))

    # the same two fields the package declares are required, bare or not
    stdout = result.stdout
    assert "as_of: required field missing" in stdout
    assert "currency: required field missing" in stdout
    # only the unstamped note is flagged
    flagged = [ln for ln in stdout.splitlines() if ln.startswith("FAIL")]
    assert flagged and all("Unstamped.md" in ln for ln in flagged)
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("script", ["validate_vault.py"])
def test_the_local_fallback_names_equal_the_declaration(script: str) -> None:
    text = (SCRIPTS / script).read_text(encoding="utf-8")
    fallback = dict(
        re.findall(r'^    (AS_OF_FIELD|CURRENCY_FIELD) = "([a-z_]+)"$', text, re.M)
    )
    assert fallback == {
        "AS_OF_FIELD": note_currency.AS_OF_FIELD,
        "CURRENCY_FIELD": note_currency.CURRENCY_FIELD,
    }
