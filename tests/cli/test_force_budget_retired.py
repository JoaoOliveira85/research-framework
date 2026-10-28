"""Issue #14: ``--force-budget`` is retired; raise the cap instead.

Every verb rejects the flag with exit 2 and a message that names what to
raise. The rejection lives in ``cli.main`` so it covers verbs that never
declared the flag, not just ``generate``.
"""

from __future__ import annotations

import pytest

from research_framework.cli import main


@pytest.mark.parametrize(
    "argv",
    [
        ["generate", "--spec", "x", "--resume", "--force-budget"],
        ["generate", "--force-budget=1"],
        ["coverage", "--vault", "v", "--force-budget"],
        ["cycle", "--force-budget"],
    ],
)
def test_force_budget_rejected_by_every_verb(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == 2
    err = capsys.readouterr().err
    assert "--force-budget" in err
    for target in (
        "--max-usd",
        "limits.cycle_budget_usd",
        "limits.codex_token_budget",
        "limits.cycle_wallclock_budget_minutes",
    ):
        assert target in err


def test_force_budget_not_in_generate_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["generate", "--help"])
    assert "force-budget" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["--force-budget", "generate"],
        ["pause", "show", "--vault", "v", "--force-budget"],
        ["status", "--vault", "v", "--force-budget"],
    ],
)
def test_force_budget_rejected_before_subcommand_and_on_unrelated_verbs(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == 2
    assert "limits.cycle_budget_usd" in capsys.readouterr().err


def test_force_budget_after_double_dash_is_a_value_not_the_flag() -> None:
    from research_framework.cli import _retired_force_budget

    assert _retired_force_budget(["generate", "--", "--force-budget"]) is False
    assert _retired_force_budget(["generate", "--force-budget", "--"]) is True
