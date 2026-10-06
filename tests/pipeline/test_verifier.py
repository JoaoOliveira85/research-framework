"""Tests for the verifier stage wiring (verdict parsing and dispatch)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent.parent / "fixtures"
ACCEPT_VERDICT = {"verdict": "accept", "violations": [], "suggested_fix": None}
REJECT_VERDICT = {
    "verdict": "reject",
    "violations": [
        {
            "rule_id": "IX-tier2-missing",
            "location": "note:Alpha.md",
            "message": "No source_urls entry",
        }
    ],
    "suggested_fix": "Add at least one source URL",
}


def _make_note(vault: Path, rel_path: str) -> Path:
    """Create a minimal note at vault / rel_path with YAML frontmatter."""
    note = vault / rel_path
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\ntitle: Alpha\ntype: concept\nsummary: A test concept.\n---\n\nBody text.\n",
        encoding="utf-8",
    )
    return note


def _make_scripts_dir(tmp_path: Path) -> Path:
    """Create a minimal scripts directory so verifier can find agent_call.py."""
    scripts = tmp_path / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "agent_call.py").write_text("# stub\n")
    return scripts


def _subprocess_mock(verdict: dict | None, *, write_output: bool = True):
    """A mock ``popen_session`` whose agent writes the verdict to --output-file."""

    def _fake_run(cmd, **kwargs):
        if write_output and verdict is not None and "--output-file" in cmd:
            idx = cmd.index("--output-file")
            Path(cmd[idx + 1]).write_text(json.dumps(verdict))
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    return _fake_run


# ---------------------------------------------------------------------------
# T013 — failing tests
# ---------------------------------------------------------------------------


def test_accept_stamps_verified(tmp_path: Path) -> None:
    """accept verdict → verifier_status: verified in frontmatter."""
    from research_framework.pipeline.verifier import run_verifier_stage

    note_rel = "data_vault/01 - Concepts/Alpha.md"
    note_file = _make_note(tmp_path, note_rel)
    scripts_dir = _make_scripts_dir(tmp_path)

    report = {"notes_created": [note_rel], "notes_updated": []}

    with patch(
        "research_framework.pipeline.verifier.popen_session",
        side_effect=_subprocess_mock(ACCEPT_VERDICT),
    ):
        run_verifier_stage(tmp_path, 1, report, scripts_dir=scripts_dir)

    fm = yaml.safe_load(note_file.read_text().split("---")[1])
    assert fm.get("verifier_status") == "verified"
    assert not fm.get("verifier_notes")

    manifest = tmp_path / "_pipeline" / "cycles" / "cycle-001-verifier.json"
    assert manifest.exists()


def test_reject_stamps_rejected_with_notes(tmp_path: Path) -> None:
    """reject verdict → verifier_status: rejected + verifier_notes list."""
    from research_framework.pipeline.verifier import run_verifier_stage

    note_rel = "data_vault/01 - Concepts/Alpha.md"
    note_file = _make_note(tmp_path, note_rel)
    scripts_dir = _make_scripts_dir(tmp_path)

    report = {"notes_created": [note_rel], "notes_updated": []}

    with patch(
        "research_framework.pipeline.verifier.popen_session",
        side_effect=_subprocess_mock(REJECT_VERDICT),
    ):
        run_verifier_stage(tmp_path, 1, report, scripts_dir=scripts_dir)

    fm = yaml.safe_load(note_file.read_text().split("---")[1])
    assert fm.get("verifier_status") == "rejected"
    assert isinstance(fm.get("verifier_notes"), list)
    assert len(fm["verifier_notes"]) >= 1


def test_timeout_stamps_pending(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """TimeoutExpired → verifier_status: pending, no exception raised."""
    import logging

    from research_framework.pipeline.verifier import run_verifier_stage

    note_rel = "data_vault/01 - Concepts/Alpha.md"
    note_file = _make_note(tmp_path, note_rel)
    scripts_dir = _make_scripts_dir(tmp_path)

    report = {"notes_created": [note_rel], "notes_updated": []}

    def _timeout(*args, **kwargs):
        proc = MagicMock()
        proc.wait.side_effect = subprocess.TimeoutExpired("agent_call.py", 30)
        return proc

    with caplog.at_level(
        logging.WARNING, logger="research_framework.pipeline.verifier"
    ):
        with patch(
            "research_framework.pipeline.verifier.popen_session", side_effect=_timeout
        ):
            run_verifier_stage(
                tmp_path, 1, report, scripts_dir=scripts_dir
            )  # must not raise

    fm = yaml.safe_load(note_file.read_text().split("---")[1])
    assert fm.get("verifier_status") == "pending"

    assert any("timed out" in record.message for record in caplog.records)


def test_parse_error_stamps_pending(tmp_path: Path) -> None:
    """Bad JSON from agent_call → verifier_status: pending, no exception."""
    from research_framework.pipeline.verifier import run_verifier_stage

    note_rel = "data_vault/01 - Concepts/Alpha.md"
    note_file = _make_note(tmp_path, note_rel)
    scripts_dir = _make_scripts_dir(tmp_path)

    report = {"notes_created": [note_rel], "notes_updated": []}

    def _bad_json(cmd, **kwargs):
        if "--output-file" in cmd:
            idx = cmd.index("--output-file")
            Path(cmd[idx + 1]).write_text("not-json")
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with patch(
        "research_framework.pipeline.verifier.popen_session", side_effect=_bad_json
    ):
        run_verifier_stage(tmp_path, 1, report, scripts_dir=scripts_dir)

    fm = yaml.safe_load(note_file.read_text().split("---")[1])
    assert fm.get("verifier_status") == "pending"


def test_null_violations_do_not_abort_the_stage(tmp_path: Path) -> None:
    """``"violations": null`` is valid JSON an agent can emit. Iterating it
    raised TypeError out of ``run_verifier_stage``, so every later note went
    unverified and no manifest was written for the cycle."""
    from research_framework.pipeline.verifier import run_verifier_stage

    first = "data_vault/01 - Concepts/Alpha.md"
    second = "data_vault/01 - Concepts/Beta.md"
    _make_note(tmp_path, first)
    second_file = _make_note(tmp_path, second)
    scripts_dir = _make_scripts_dir(tmp_path)
    verdicts = iter(
        [
            {"verdict": "reject", "violations": None, "suggested_fix": None},
            ACCEPT_VERDICT,
        ]
    )

    def _fake_run(cmd, **kwargs):
        idx = cmd.index("--output-file")
        Path(cmd[idx + 1]).write_text(json.dumps(next(verdicts)))
        mock = MagicMock()
        mock.returncode = 0
        return mock

    report = {"notes_created": [first, second], "notes_updated": []}
    with patch(
        "research_framework.pipeline.verifier.popen_session", side_effect=_fake_run
    ):
        summary = run_verifier_stage(tmp_path, 1, report, scripts_dir=scripts_dir)

    assert [v.status for v in summary.verdicts] == ["rejected", "verified"]
    fm = yaml.safe_load(second_file.read_text().split("---")[1])
    assert fm.get("verifier_status") == "verified"
    assert (tmp_path / "_pipeline" / "cycles" / "cycle-001-verifier.json").is_file()


@pytest.mark.parametrize(
    "frontmatter",
    [
        pytest.param('title: "Alpha\nsummary: an open quote\n', id="yaml-error"),
        pytest.param("- a list\n- not a mapping\n", id="not-a-mapping"),
    ],
)
def test_unparseable_frontmatter_does_not_abort_the_stage(
    tmp_path: Path, frontmatter: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A note whose frontmatter does not parse cannot be stamped. Loading it
    raised out of ``run_verifier_stage``, so every later note went unverified
    and no manifest was written for the cycle."""
    from research_framework.pipeline.verifier import run_verifier_stage

    first = "data_vault/01 - Concepts/Alpha.md"
    second = "data_vault/01 - Concepts/Beta.md"
    broken = "---\n" + frontmatter + "---\n\nBody text.\n"
    first_file = _make_note(tmp_path, first)
    first_file.write_text(broken, encoding="utf-8")
    second_file = _make_note(tmp_path, second)
    scripts_dir = _make_scripts_dir(tmp_path)

    report = {"notes_created": [first, second], "notes_updated": []}
    with (
        patch(
            "research_framework.pipeline.verifier.popen_session",
            side_effect=_subprocess_mock(ACCEPT_VERDICT),
        ),
        caplog.at_level("WARNING", logger="research_framework.pipeline.verifier"),
    ):
        summary = run_verifier_stage(tmp_path, 1, report, scripts_dir=scripts_dir)

    assert [v.note_path for v in summary.verdicts] == [first, second]
    assert first_file.read_text(encoding="utf-8") == broken
    assert any(first in r.getMessage() for r in caplog.records)
    fm = yaml.safe_load(second_file.read_text().split("---")[1])
    assert fm.get("verifier_status") == "verified"
    assert (tmp_path / "_pipeline" / "cycles" / "cycle-001-verifier.json").is_file()


def test_unreadable_note_does_not_abort_the_stage(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A note that is not UTF-8 cannot be read, let alone verified. Reading it
    raised ``UnicodeDecodeError`` out of ``run_verifier_stage``, so every later
    note went unverified and no manifest was written for the cycle."""
    from research_framework.pipeline.verifier import run_verifier_stage

    first = "data_vault/01 - Concepts/Alpha.md"
    second = "data_vault/01 - Concepts/Beta.md"
    latin1 = b"---\ntitle: caf\xe9\n---\n\nBody text.\n"
    first_file = _make_note(tmp_path, first)
    first_file.write_bytes(latin1)
    second_file = _make_note(tmp_path, second)
    scripts_dir = _make_scripts_dir(tmp_path)
    calls: list[list[str]] = []
    fake = _subprocess_mock(ACCEPT_VERDICT)

    def _counting_run(cmd, **kwargs):
        calls.append(cmd)
        return fake(cmd, **kwargs)

    report = {"notes_created": [first, second], "notes_updated": []}
    with (
        patch(
            "research_framework.pipeline.verifier.popen_session",
            side_effect=_counting_run,
        ),
        caplog.at_level("WARNING", logger="research_framework.pipeline.verifier"),
    ):
        summary = run_verifier_stage(tmp_path, 1, report, scripts_dir=scripts_dir)

    assert [(v.note_path, v.status) for v in summary.verdicts] == [
        (first, "pending"),
        (second, "verified"),
    ]
    assert len(calls) == 1, "no agent is dispatched for a note that cannot be read"
    assert first_file.read_bytes() == latin1
    assert any(first in r.getMessage() for r in caplog.records)
    fm = yaml.safe_load(second_file.read_text().split("---")[1])
    assert fm.get("verifier_status") == "verified"
    assert (tmp_path / "_pipeline" / "cycles" / "cycle-001-verifier.json").is_file()


def test_disabled_skips_all_notes(tmp_path: Path) -> None:
    """verifier.enabled: false → zero subprocess calls, no frontmatter change, no manifest."""
    from research_framework.pipeline.verifier import run_verifier_stage

    settings_path = FIXTURES / "settings" / "verifier-disabled.yaml"
    settings = yaml.safe_load(settings_path.read_text())

    note_rel = "data_vault/01 - Concepts/Alpha.md"
    note_file = _make_note(tmp_path, note_rel)
    original_text = note_file.read_text()
    scripts_dir = _make_scripts_dir(tmp_path)

    report = {"notes_created": [note_rel], "notes_updated": []}

    call_count = [0]

    def _counting_run(*args, **kwargs):
        call_count[0] += 1
        mock = MagicMock()
        mock.returncode = 0
        return mock

    with patch(
        "research_framework.pipeline.verifier.popen_session", side_effect=_counting_run
    ):
        run_verifier_stage(
            tmp_path, 1, report, scripts_dir=scripts_dir, settings=settings
        )

    assert call_count[0] == 0, "subprocess must not be called when verifier is disabled"
    assert note_file.read_text() == original_text, "note must not be modified"

    manifest = tmp_path / "_pipeline" / "cycles" / "cycle-001-verifier.json"
    assert not manifest.exists()


def test_manifest_written(tmp_path: Path) -> None:
    """2 created + 1 updated → manifest has 3 verdict entries."""
    from research_framework.pipeline.verifier import run_verifier_stage

    notes = [
        "data_vault/01 - Concepts/Alpha.md",
        "data_vault/01 - Concepts/Beta.md",
        "data_vault/01 - Concepts/Gamma.md",
    ]
    for n in notes:
        _make_note(tmp_path, n)
    scripts_dir = _make_scripts_dir(tmp_path)

    report = {
        "notes_created": notes[:2],
        "notes_updated": notes[2:],
    }

    with patch(
        "research_framework.pipeline.verifier.popen_session",
        side_effect=_subprocess_mock(ACCEPT_VERDICT),
    ):
        run_verifier_stage(tmp_path, 1, report, scripts_dir=scripts_dir)

    manifest = tmp_path / "_pipeline" / "cycles" / "cycle-001-verifier.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    assert len(data["verdicts"]) == 3


def test_frontmatter_write_is_atomic(tmp_path: Path) -> None:
    """After run_verifier_stage, note file exists at original path (no leftover .tmp)."""
    from research_framework.pipeline.verifier import run_verifier_stage

    note_rel = "data_vault/01 - Concepts/Alpha.md"
    note_file = _make_note(tmp_path, note_rel)
    scripts_dir = _make_scripts_dir(tmp_path)

    report = {"notes_created": [note_rel], "notes_updated": []}

    with patch(
        "research_framework.pipeline.verifier.popen_session",
        side_effect=_subprocess_mock(ACCEPT_VERDICT),
    ):
        run_verifier_stage(tmp_path, 1, report, scripts_dir=scripts_dir)

    assert note_file.exists(), "note file must exist at its original path"
    tmp_file = note_file.with_suffix(".tmp")
    assert not tmp_file.exists(), ".tmp file must be cleaned up (renamed to final)"


def test_notes_updated_also_verified(tmp_path: Path) -> None:
    """notes_updated entries are also passed to agent_call and stamped."""
    from research_framework.pipeline.verifier import run_verifier_stage

    note_rel = "data_vault/01 - Concepts/Gamma.md"
    note_file = _make_note(tmp_path, note_rel)
    scripts_dir = _make_scripts_dir(tmp_path)

    report = {"notes_created": [], "notes_updated": [note_rel]}

    calls = []

    def _tracking_mock(cmd, **kwargs):
        calls.append(list(cmd))
        if "--output-file" in cmd:
            idx = cmd.index("--output-file")
            Path(cmd[idx + 1]).write_text(json.dumps(ACCEPT_VERDICT))
        mock = MagicMock()
        mock.returncode = 0
        return mock

    with patch(
        "research_framework.pipeline.verifier.popen_session",
        side_effect=_tracking_mock,
    ):
        run_verifier_stage(tmp_path, 1, report, scripts_dir=scripts_dir)

    # agent_call must have been called
    assert len(calls) >= 1, "agent_call.py must be called for notes_updated"

    fm = yaml.safe_load(note_file.read_text().split("---")[1])
    assert fm.get("verifier_status") == "verified"


# ---------------------------------------------------------------------------
# Spec 055 — credibility shape validation (deterministic, no LLM)
# ---------------------------------------------------------------------------


def _credibility_spec(tmp_path: Path) -> None:
    spec_text = """---
name: cred-vault
owner: test
location: /tmp/v
scope:
  domain: d
  organization: o
note_types:
  - name: concept
    description: c
    folder: "03 - Concepts"
    authoritative_role: domain
data_sources:
  - name: HN
    type: external
    role: domain
    priority: 2
    default_credibility: commentary
search_dimensions: [domain]
coverage_targets:
  categories:
    - name: concepts
      note_type: concept
      target_count: 1
budget:
  max_usd: 1.0
  max_cycles: 1
---
"""
    (tmp_path / "research.spec.md").write_text(spec_text, encoding="utf-8")


def test_credibility_wellformed_passes(tmp_path: Path) -> None:
    from research_framework.spec.parser import parse
    from research_framework.vault.credibility import (
        build_credibility_context,
        validate_credibility_shape,
    )

    _credibility_spec(tmp_path)
    spec = parse(tmp_path / "research.spec.md")
    ctx = build_credibility_context(spec, tmp_path)
    ctx.role_index.exact["https://news.ycombinator.com/item?id=1"] = "domain"
    fm = {
        "type": "concept",
        "source_urls": [
            {
                "url": "https://news.ycombinator.com/item?id=1",
                "credibility": "commentary",
                "coi": False,
            }
        ],
    }
    assert validate_credibility_shape(fm, ctx, location="note:data_vault/foo.md") == []


def test_credibility_unresolved_fails(tmp_path: Path) -> None:
    from research_framework.spec.parser import parse
    from research_framework.vault.credibility import (
        build_credibility_context,
        validate_credibility_shape,
    )

    _credibility_spec(tmp_path)
    spec = parse(tmp_path / "research.spec.md")
    ctx = build_credibility_context(spec, tmp_path)
    fm = {
        "type": "concept",
        "source_urls": [{"url": "https://unknown.example/x"}],
    }
    violations = validate_credibility_shape(fm, ctx, location="note:data_vault/foo.md")
    assert len(violations) == 1
    assert violations[0]["rule_id"] == "IX-credibility-unresolved"


def test_credibility_bad_enum_fails(tmp_path: Path) -> None:
    from research_framework.spec.parser import parse
    from research_framework.vault.credibility import (
        build_credibility_context,
        validate_credibility_shape,
    )

    _credibility_spec(tmp_path)
    spec = parse(tmp_path / "research.spec.md")
    ctx = build_credibility_context(spec, tmp_path)
    fm = {
        "type": "concept",
        "source_urls": [{"url": "https://a.example/1", "credibility": "tier-99"}],
    }
    violations = validate_credibility_shape(fm, ctx, location="note:data_vault/foo.md")
    assert any(v["rule_id"] == "IX-credibility-malformed" for v in violations)


def test_coi_non_boolean_fails(tmp_path: Path) -> None:
    from research_framework.spec.parser import parse
    from research_framework.vault.credibility import (
        build_credibility_context,
        validate_credibility_shape,
    )

    _credibility_spec(tmp_path)
    spec = parse(tmp_path / "research.spec.md")
    ctx = build_credibility_context(spec, tmp_path)
    fm = {
        "type": "concept",
        "source_urls": [
            {
                "url": "https://a.example/1",
                "credibility": "commentary",
                "coi": "maybe",
            }
        ],
    }
    violations = validate_credibility_shape(fm, ctx, location="note:data_vault/foo.md")
    assert any(v["rule_id"] == "IX-credibility-malformed" for v in violations)


# ---------------------------------------------------------------------------
# Spec 067 FR3 — deterministic wikilink title-corruption gate (no LLM)
# ---------------------------------------------------------------------------


def _cap_vault(tmp_path: Path) -> Path:
    """A vault where ``cache-aside pattern`` claims acronym ``CAP`` and a sibling
    ``CAP Theorem`` note exists — the rc7 corruption shape."""
    data = tmp_path / "data_vault"
    data.mkdir(parents=True, exist_ok=True)
    (data / "cache-aside-pattern.md").write_text(
        "---\ntitle: Cache-Aside Pattern\ntype: concept\n---\nBody.\n",
        encoding="utf-8",
    )
    return data


def test_wikilink_title_corruption_rejected(tmp_path: Path) -> None:
    """C3-a: a note whose first body link renames its own title → rejected."""
    from research_framework.pipeline.verifier import deterministic_wikilink_violations

    data = _cap_vault(tmp_path)
    note_rel = "data_vault/cap-theorem.md"
    note_text = (
        "---\ntitle: CAP Theorem\ntype: concept\n---\n"
        "The [[CAP]] Theorem is about distributed systems.\n"
    )
    (data / "cap-theorem.md").write_text(note_text, encoding="utf-8")
    violations = deterministic_wikilink_violations(tmp_path, note_rel, note_text)
    assert len(violations) == 1
    assert violations[0]["rule_id"] == "IX-wikilink-title-corruption"


def test_wikilink_title_corruption_run_verifier_rejects(tmp_path: Path) -> None:
    """C3-a (end-to-end): run_verifier_stage marks the corrupting note rejected
    even when the LLM verifier would have accepted it."""
    from research_framework.pipeline.verifier import run_verifier_stage

    data = _cap_vault(tmp_path)
    note_text = (
        "---\ntitle: CAP Theorem\ntype: concept\n---\n"
        "The [[CAP]] Theorem is about distributed systems.\n"
    )
    (data / "cap-theorem.md").write_text(note_text, encoding="utf-8")
    scripts_dir = _make_scripts_dir(tmp_path)
    report = {"notes_created": ["data_vault/cap-theorem.md"], "notes_updated": []}
    with patch(
        "research_framework.pipeline.verifier.popen_session",
        _subprocess_mock(ACCEPT_VERDICT),
    ):
        summary = run_verifier_stage(tmp_path, 1, report, scripts_dir=scripts_dir)
    verdict = summary.verdicts[0]
    assert verdict.status == "rejected"
    assert any(
        v["rule_id"] == "IX-wikilink-title-corruption" for v in verdict.violations
    )


def test_wikilink_legit_different_concept_not_rejected(tmp_path: Path) -> None:
    """C3-b: a note whose first body link is a legitimately different concept is
    NOT flagged."""
    from research_framework.pipeline.verifier import deterministic_wikilink_violations

    data = _cap_vault(tmp_path)
    note_rel = "data_vault/cap-theorem.md"
    note_text = (
        "---\ntitle: CAP Theorem\ntype: concept\n---\n"
        "It constrains [[consistency]] under partitions.\n"
    )
    (data / "cap-theorem.md").write_text(note_text, encoding="utf-8")
    violations = deterministic_wikilink_violations(tmp_path, note_rel, note_text)
    assert violations == []
