"""Unit tests for ``pipeline.vault_update`` decision helpers (spec 027)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.pipeline.vault_update import (
    Decision,
    compare_versions,
    decide,
    resolve_local_version,
    resolve_target_version,
    snapshot_title,
)


def test_vault_update_module_importable() -> None:
    import research_framework.pipeline.vault_update as vault_update

    assert vault_update is not None


def test_decision_dataclass_fields() -> None:
    decision = Decision(action="noop", message="Already at v0.3.1", exit_code=0)
    assert decision.action == "noop"
    assert decision.message == "Already at v0.3.1"
    assert decision.exit_code == 0


def test_compare_versions_classifies_same_upgrade_downgrade() -> None:
    assert compare_versions("0.3.0", "0.3.0") == "same"
    assert compare_versions("0.3.0", "0.3.1") == "upgrade"
    assert compare_versions("0.3.1", "0.3.0") == "downgrade"


def test_snapshot_title_matches_fr004_label() -> None:
    assert snapshot_title("0.3.0", "0.3.1") == "snapshot before update 0.3.0 -> 0.3.1"


def test_decide_noop_when_local_equals_target() -> None:
    result = decide("0.3.1", "0.3.1")
    assert result.action == "noop"
    assert result.exit_code == 0
    assert "Already at" in result.message
    assert "nothing to do" in result.message


def test_decide_refuses_downgrade_unless_pinned_and_confirmed() -> None:
    refused = decide("0.3.1", "0.3.0")
    assert refused.action == "refuse"
    assert refused.exit_code != 0

    still_refused = decide("0.3.1", "0.3.0", pinned_ref="v0.3.0", confirmed=False)
    assert still_refused.action == "refuse"

    allowed = decide("0.3.1", "0.3.0", pinned_ref="v0.3.0", confirmed=True)
    assert allowed.action == "proceed"
    assert allowed.exit_code == 0


def test_resolve_local_version_from_vault_venv(tmp_path: Path) -> None:
    import subprocess
    import sys

    from tests._helpers.vault_factory import build_minimal_vault

    vault = build_minimal_vault(tmp_path)
    subprocess.run(
        [sys.executable, "-m", "venv", str(vault / ".venv")],
        check=True,
        capture_output=True,
    )
    repo_root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [str(vault / ".venv/bin/pip"), "install", "-q", "-e", str(repo_root)],
        check=True,
        capture_output=True,
    )
    repo_root = Path(__file__).resolve().parents[2]
    import tomllib

    expected = tomllib.loads(
        (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    version = resolve_local_version(vault)
    assert version == expected


def test_resolve_target_version_from_archive_pyproject(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "pyproject.toml").write_text(
        '[project]\nname = "research-framework"\nversion = "0.3.1"\n',
        encoding="utf-8",
    )
    assert resolve_target_version(archive) == "0.3.1"


def test_decide_proceed_on_upgrade() -> None:
    result = decide("0.3.0", "0.3.1")
    assert result.action == "proceed"
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Version ordering is PEP 440, the scheme `pyproject.toml` versions and the
# release tags use (`1.0.0rc11`, `1.0.0.dev3`). Comparing only the digits
# reads the pre-release number as a fourth release component, so the step
# from the last release candidate to the final release looked like a
# downgrade and `./vault update` refused it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("local", "target", "expected"),
    [
        ("1.0.0rc11", "1.0.0", "upgrade"),
        ("1.0.0", "1.0.0rc11", "downgrade"),
        ("1.0.0rc2", "1.0.0rc11", "upgrade"),
        ("1.0.0a2", "1.0.0b1", "upgrade"),
        ("1.0.0b1", "1.0.0rc1", "upgrade"),
        ("1.0.0.dev3", "1.0.0a1", "upgrade"),
        ("1.0.0.dev3", "1.0.0", "upgrade"),
        ("1.0.0rc1.dev2", "1.0.0rc1", "upgrade"),
        ("1.0.0", "1.0.0.post1", "upgrade"),
        ("1.4.0rc1", "1.3.9", "downgrade"),
        ("1.9.0", "1.10.0", "upgrade"),
        ("2!1.0", "3.0", "downgrade"),
        ("1.0.0", "1.0.0+local.1", "upgrade"),
        # Spellings PEP 440 normalises to the same version.
        ("1.0", "1.0.0", "same"),
        ("v1.2.0", "1.2.0", "same"),
        ("1.0.0-rc1", "1.0.0rc1", "same"),
        ("1.0.0RC1", "1.0.0rc1", "same"),
        ("1.0.0c1", "1.0.0rc1", "same"),
        ("1.0.0alpha1", "1.0.0a1", "same"),
        ("1.0.0-1", "1.0.0.post1", "same"),
    ],
)
def test_compare_versions_orders_pep440(local: str, target: str, expected: str) -> None:
    assert compare_versions(local, target) == expected


@pytest.mark.parametrize(
    ("local", "target", "expected"),
    [
        ("build-7", "build-12", "upgrade"),
        ("unknown", "unknown", "same"),
        ("unknown", "1.2.0", "upgrade"),
        ("1.2.0-custom", "1.2.0", "same"),
    ],
)
def test_compare_versions_keeps_digit_ordering_for_non_pep440_strings(
    local: str, target: str, expected: str
) -> None:
    """A string PEP 440 cannot parse must not raise — the update verb would
    exit 2 on a traceback — so both sides fall back to the digit tuples."""
    assert compare_versions(local, target) == expected


def test_decide_proceeds_from_release_candidate_to_final() -> None:
    result = decide("1.0.0rc11", "1.0.0")
    assert result.action == "proceed"
    assert result.exit_code == 0
    assert "Upgrading" in result.message
