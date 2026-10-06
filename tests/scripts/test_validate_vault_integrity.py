"""Spec 062 FR2/FR3 — validate_vault duplicate + dead-acronym classes.

Exercises ``scripts/validate_vault.py`` as a subprocess (its canonical entry):
  - the duplicate-note class fails an ` N.md`/content-dup vault (exit 1);
  - the dead-acronym-link class returns clean on a vault whose titles imply
    the acronym (a ``[[OECDH]]`` ``related`` entry is NOT "file not found").
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate_vault.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )


def _valid_note(vault: Path, stem: str, title: str, *, related: str = "[]") -> None:
    data = vault / "data_vault"
    data.mkdir(parents=True, exist_ok=True)
    body = ("lorem ipsum dolor sit amet " * 50).strip()
    (data / f"{stem}.md").write_text(
        "---\n"
        f"title: {title}\n"
        "type: concept\n"
        "summary: a short summary\n"
        "tags: [x]\n"
        "source_urls: [https://example.com]\n"
        f"related: {related}\n"
        "created: 2026-01-01\n"
        "updated: 2026-01-01\n"
        f"---\n{body}\n",
        encoding="utf-8",
    )


def test_os_sibling_duplicate_fails(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    _valid_note(vault, "Risk", "Risk")
    # Forge an OS-style numbered sibling.
    (vault / "data_vault" / "Risk 2.md").write_text(
        (vault / "data_vault" / "Risk.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    result = _run(str(vault))
    assert result.returncode == 1
    assert "duplicate" in result.stdout.lower()


def test_dead_acronym_link_resolves_via_title_map(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    _valid_note(
        vault,
        "order-engine-customer-data-handler",
        "Order Engine Customer Data Handler",
    )
    # A note referencing the acronym in `related`. The title-derived map
    # (OECDH → the full-title stem) makes this resolvable, not a dead link.
    _valid_note(vault, "risk-register", "Risk Register", related="[OECDH]")
    result = _run(str(vault))
    assert "[[OECDH]] — file not found" not in result.stdout, result.stdout
    assert result.returncode == 0, f"stdout={result.stdout}"


def test_ambiguous_acronym_emits_warning(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    _valid_note(vault, "shared-processing-and-control", "Shared Processing And Control")
    _valid_note(vault, "system-process-control", "System Process Control")
    result = _run(str(vault))
    # Both yield "SPC" → ambiguous → WARN, not a wrong link.
    assert "SPC" in result.stdout and "ambiguous" in result.stdout.lower()


def _load_validate_vault_module():
    import importlib.util

    name = "_validate_vault_under_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclass introspection needs the module registered
    spec.loader.exec_module(mod)
    return mod


def test_acronym_map_parity_with_pipeline(tmp_path: Path) -> None:
    """Spec 067 C1-b: the standalone ``scripts/validate_vault.py`` acronym map
    agrees with ``pipeline/wikilinks.build_acronym_map`` on the same vault —
    single-expansion-only mapping with the same ``ambiguous`` set."""
    from research_framework.pipeline.wikilinks import build_acronym_map

    vault = tmp_path / "v"
    # A single-claim acronym (OECDH) + an ambiguous one (SPC).
    _valid_note(
        vault,
        "order-engine-customer-data-handler",
        "Order Engine Customer Data Handler",
    )
    _valid_note(vault, "shared-processing-and-control", "Shared Processing And Control")
    _valid_note(vault, "system-process-control", "System Process Control")

    pipeline_map, pipeline_ambig = build_acronym_map(vault)
    vv = _load_validate_vault_module()
    script_map, script_ambig = vv._build_acronym_map(vault)

    assert pipeline_map == script_map
    assert sorted(pipeline_ambig) == sorted(script_ambig)
    assert "SPC" in pipeline_ambig and "SPC" not in pipeline_map
    assert pipeline_map.get("OECDH") == "order-engine-customer-data-handler"


def test_acronym_map_parity_when_the_acronym_is_a_real_note(tmp_path: Path) -> None:
    """An acronym that is itself a note's file name is on neither map, whether
    one note claims it (CAP) or two do (SPC) — ``[[CAP]]`` already resolves."""
    from research_framework.pipeline.wikilinks import build_acronym_map

    vault = tmp_path / "v"
    _valid_note(vault, "cap", "CAP Theorem")
    _valid_note(vault, "cache-aside-pattern", "Cache-Aside Pattern")
    _valid_note(vault, "spc", "SPC Charts")
    _valid_note(vault, "shared-processing-and-control", "Shared Processing And Control")
    _valid_note(vault, "system-process-control", "System Process Control")

    pipeline_map, pipeline_ambig = build_acronym_map(vault)
    vv = _load_validate_vault_module()
    script_map, script_ambig = vv._build_acronym_map(vault)

    assert pipeline_map == script_map
    assert sorted(pipeline_ambig) == sorted(script_ambig)
    assert "CAP" not in script_map
    assert "SPC" not in script_ambig
