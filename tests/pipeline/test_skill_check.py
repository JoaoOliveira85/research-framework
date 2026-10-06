"""Tests for the .agents/skills/*/SKILL.md preflight + auto-restore."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from research_framework.pipeline import skill_check


def _write_skill(root: Path, name: str, text: str) -> Path:
    p = root / ".agents" / "skills" / name / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _valid_skill(name: str) -> str:
    return dedent(
        f"""\
        ---
        name: {name}
        description: Test skill {name}.
        ---

        # {name}

        Body.
        """
    )


def _broken_skill_with_bad_yaml() -> str:
    # The v0.2.19 cycle-6 corruption shape: a key with an unquoted ``::``
    # block scalar separator inside a single-line value — yaml refuses the
    # frontmatter outright.
    return dedent(
        """\
        ---
        name: verifier
        description: Verifier skill
        meta:
          title: Servlet Authentication Architecture :: Spring Security
        ---

        # verifier
        """
    )


def test_validate_skills_flags_broken_files(tmp_path: Path) -> None:
    _write_skill(tmp_path, "ok-skill", _valid_skill("ok-skill"))
    _write_skill(tmp_path, "verifier", _broken_skill_with_bad_yaml())

    issues = skill_check.validate_skills(tmp_path)
    paths = {i.path.parent.name for i in issues}
    assert paths == {"verifier"}
    assert "invalid YAML" in issues[0].error or "expected key" in issues[0].error


def test_validate_skills_accepts_clean_vault(tmp_path: Path) -> None:
    _write_skill(tmp_path, "alpha", _valid_skill("alpha"))
    _write_skill(tmp_path, "beta", _valid_skill("beta"))
    assert skill_check.validate_skills(tmp_path) == []


def test_validate_skills_empty_dir_is_noop(tmp_path: Path) -> None:
    assert skill_check.validate_skills(tmp_path) == []


def test_validate_and_repair_restores_from_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_root = tmp_path / "_bundle" / "skills"
    bundle_skill = bundle_root / "verifier" / "SKILL.md"
    bundle_skill.parent.mkdir(parents=True)
    bundle_skill.write_text(_valid_skill("verifier"), encoding="utf-8")
    monkeypatch.setattr(skill_check, "_bundled_skills_root", lambda: bundle_root)

    vault = tmp_path / "vault"
    broken = _write_skill(vault, "verifier", _broken_skill_with_bad_yaml())

    result = skill_check.validate_and_repair_skills(vault)
    assert result.ok
    assert len(result.repaired) == 1
    assert result.repaired[0].path == broken
    # After repair the on-disk file should match the bundled source.
    assert broken.read_text(encoding="utf-8") == _valid_skill("verifier")


def _skill_with_dashes_in_its_description() -> str:
    return (
        "---\n"
        "name: verifier\n"
        'description: "Verify every claim --- strictly, the vault owner\'s way."\n'
        "---\n"
        "\n"
        "# verifier\n"
    )


def test_a_skill_with_dashes_in_a_value_is_not_overwritten_from_the_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `---` inside a value is not the closing delimiter.

    The preflight split on the first `---` substring, which left the quoted
    description above unterminated: "invalid YAML", and the owner's edited
    SKILL.md was replaced by the bundled copy.
    """
    bundle_root = tmp_path / "_bundle" / "skills"
    bundle_skill = bundle_root / "verifier" / "SKILL.md"
    bundle_skill.parent.mkdir(parents=True)
    bundle_skill.write_text(_valid_skill("verifier"), encoding="utf-8")
    monkeypatch.setattr(skill_check, "_bundled_skills_root", lambda: bundle_root)

    vault = tmp_path / "vault"
    edited = _write_skill(vault, "verifier", _skill_with_dashes_in_its_description())

    result = skill_check.validate_and_repair_skills(vault)

    assert result.repaired == []
    assert result.ok
    assert edited.read_text(encoding="utf-8") == (
        _skill_with_dashes_in_its_description()
    )


def test_broken_yaml_below_dashes_in_a_value_is_still_flagged(tmp_path: Path) -> None:
    """The other half of the same cut: everything below it went unchecked."""
    _write_skill(
        tmp_path,
        "verifier",
        "---\n"
        "name: verifier\n"
        "description: Verify every claim --- strictly\n"
        "meta:\n"
        "  title: Servlet Authentication Architecture :: Spring Security\n"
        "---\n"
        "\n"
        "# verifier\n",
    )

    issues = skill_check.validate_skills(tmp_path)

    assert [i.path.parent.name for i in issues] == ["verifier"]
    # The YAML mark still names the file's own line (5: the `title` line).
    assert "invalid YAML" in issues[0].error
    assert "line 5" in issues[0].error


def test_validate_and_repair_reports_unrecoverable_when_no_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(skill_check, "_bundled_skills_root", lambda: None)
    vault = tmp_path / "vault"
    _write_skill(vault, "verifier", _broken_skill_with_bad_yaml())

    result = skill_check.validate_and_repair_skills(vault)
    assert not result.ok
    assert len(result.unrecoverable) == 1


def test_validate_and_repair_skips_when_bundle_itself_is_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_root = tmp_path / "_bundle" / "skills"
    (bundle_root / "verifier").mkdir(parents=True)
    (bundle_root / "verifier" / "SKILL.md").write_text(
        _broken_skill_with_bad_yaml(), encoding="utf-8"
    )
    monkeypatch.setattr(skill_check, "_bundled_skills_root", lambda: bundle_root)

    vault = tmp_path / "vault"
    _write_skill(vault, "verifier", _broken_skill_with_bad_yaml())

    result = skill_check.validate_and_repair_skills(vault)
    # Bundle copy is itself unusable → fall through to unrecoverable.
    assert not result.ok
    assert not result.repaired
