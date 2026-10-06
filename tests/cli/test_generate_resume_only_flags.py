"""Issue #286: --approve/--approve-all/--reject/--force-budget are resume-only.

``generate`` advertises these four flags in its help (they live on the single
subparser that also serves ``--resume``, per spec 033), but ``_cmd_generate``
only ever reads them from inside the ``--resume`` branch (delegated to
``_resume`` / ``cli/budget_resume.py``). Pass any of them to a fresh
``generate`` invocation and they used to be silently accepted no-ops — no
error, no warning, nothing approved or rejected because nothing has paused
yet. This pins the fix: refuse loudly (exit 2) instead, the same way the
neighbouring ``--dry-run``/``--resume`` mutual-exclusion check already does.
"""

from __future__ import annotations

import pytest

from research_framework.cli._parser import build_parser
from research_framework.cli.research_generate import _cmd_generate


@pytest.mark.parametrize(
    "extra_argv,expected_flag",
    [
        (["--approve", "research"], "--approve"),
        (["--approve-all"], "--approve-all"),
        (["--reject", "research"], "--reject"),
        (["--force-budget"], "--force-budget"),
    ],
)
def test_resume_only_flag_without_resume_exits_2(
    extra_argv: list[str],
    expected_flag: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = build_parser().parse_args(["generate", "--spec", "x", *extra_argv])
    assert args.resume is False

    rc = _cmd_generate(args)

    assert rc == 2
    err = capsys.readouterr().err
    assert expected_flag in err
    assert "--resume" in err


def test_multiple_resume_only_flags_are_all_named(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = build_parser().parse_args(
        ["generate", "--spec", "x", "--approve-all", "--force-budget"]
    )

    rc = _cmd_generate(args)

    assert rc == 2
    err = capsys.readouterr().err
    assert "--approve-all" in err
    assert "--force-budget" in err


def test_resume_only_flags_absent_does_not_trip_the_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity check: a plain ``generate --spec x`` (no resume-only flags, no
    ``--resume``) must not be rejected by this guard — it should fall through
    to the normal Phase 0 flow. Stub ``load_spec`` to fail fast right after
    the guard so this stays a unit test of the guard alone."""
    import research_framework.cli.research_generate as rg

    def _boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("reached phase 0 — guard did not fire, as expected")

    monkeypatch.setattr(rg, "load_spec", _boom, raising=True)
    args = build_parser().parse_args(["generate", "--spec", "x"])

    with pytest.raises(RuntimeError, match="reached phase 0"):
        _cmd_generate(args)


def test_resume_with_approve_flag_is_not_blocked_by_the_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With --resume, these flags are exactly what they're for — the guard
    must not fire, and control must reach ``_resume`` as before."""
    import research_framework.cli.research_generate as rg

    called: dict[str, object] = {}

    def _fake_resume(args: object) -> int:
        called["args"] = args
        return 0

    monkeypatch.setattr(rg, "_resume", _fake_resume, raising=True)
    args = build_parser().parse_args(
        ["generate", "--spec", "x", "--resume", "--approve", "research"]
    )

    rc = _cmd_generate(args)

    assert rc == 0
    assert called["args"] is args


@pytest.mark.parametrize(
    "extra_argv,expected_flag",
    [
        (["--settings", "settings.yaml"], "--settings"),
        (["--prepopulate", "old/_pipeline"], "--prepopulate"),
        (["--skip-gate"], "--skip-gate"),
    ],
)
def test_fresh_only_flag_with_resume_exits_2_without_resuming(
    extra_argv: list[str],
    expected_flag: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The reverse of #286: these three shape Phase 1 (the settings baked into
    the vault, the files copied into it, the pytest gate), which ``--resume``
    skips. ``_cmd_generate`` dispatched to ``_resume`` before reading them, so
    they were silently ignored."""
    import research_framework.cli.research_generate as rg

    resumed: list[object] = []
    monkeypatch.setattr(rg, "_resume", lambda a: resumed.append(a) or 0)
    args = build_parser().parse_args(
        ["generate", "--spec", "x", "--resume", *extra_argv]
    )

    rc = _cmd_generate(args)

    assert rc == 2
    assert resumed == [], "the run must not start with a flag it ignores"
    err = capsys.readouterr().err
    assert expected_flag in err
    assert "--resume" in err
