"""Global ``--log-level`` flag and TTY-aware default resolution.

Contract: ``specs/048-observability-v1/contracts/log-level-flag.contract.md``.
Authority: spec 048 FR-004 + FR-005.

Two public functions:

``add_log_level_arg(parser)``
    Registers ``--log-level {debug,info,warning,error}`` on the supplied
    argparse parser. Stores the (lowercased) value in
    ``args.log_level`` or ``None`` when the flag is absent.

``resolve(value, *, verb_default=None)``
    Returns the ``logging`` level constant for the supplied value.
    When ``value`` is ``None``, falls back to the verb's own declared
    default if it has one (issue #241 — the ``pipeline`` verbs run
    headless by design), otherwise to a TTY-aware default (``INFO``
    when ``sys.stdout.isatty()`` is true, ``WARNING`` when not).
    Raises ``ValueError`` for any value outside the allowed set.

The module is pure stdlib (Principle V — no new runtime deps).
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Literal

LogLevelStr = Literal["debug", "info", "warning", "error"]

_ALLOWED_VALUES: tuple[str, ...] = ("debug", "info", "warning", "error")

_LEVEL_MAP: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def add_log_level_arg(parser: argparse.ArgumentParser) -> None:
    """Register the global ``--log-level`` flag on ``parser``.

    Must be called BEFORE ``parser.add_subparsers(...)`` so the flag is
    available on every subcommand without re-declaration.

    The choices are case-insensitive on the parser side (we lowercase
    in a ``type=`` callable) so ``--log-level INFO`` and
    ``--log-level info`` are equivalent.
    """
    parser.add_argument(
        "--log-level",
        dest="log_level",
        type=str.lower,
        choices=_ALLOWED_VALUES,
        default=None,
        metavar="{debug,info,warning,error}",
        help=(
            "Logger verbosity. Defaults to INFO on an interactive TTY and "
            "WARNING when stdout is piped/redirected (per FR-005) — except "
            "the `pipeline` verbs, which default to INFO either way because "
            "they are built to run unattended."
        ),
    )


def _detect_default_level() -> int:
    """Return ``INFO`` on interactive TTYs, ``WARNING`` otherwise (FR-005)."""
    return logging.INFO if sys.stdout.isatty() else logging.WARNING


def resolve(value: str | None, *, verb_default: str | None = None) -> int:
    """Return the ``logging`` level constant for ``value``.

    ``None``  → ``verb_default`` if the verb declared one, else the TTY-aware
                default (FR-005).
    ``str``   → case-insensitive lookup in ``_LEVEL_MAP``.
    other     → ``ValueError`` (FR-004 / contract § Error mode).

    ``verb_default`` exists for issue #241. FR-005's TTY test is a good proxy
    for "is a human watching" everywhere except the one place it matters most:
    an autonomous pipeline runs from cron/launchd/systemd, never on a TTY, so
    the mode the framework is built for was the mode in which it narrated
    nothing. A verb that is *expected* to run headless says so here rather
    than the default being loosened for every verb. An explicit flag still
    wins, and the value is validated on the same path as any other.
    """
    if value is None:
        if verb_default is not None:
            return resolve(verb_default)
        return _detect_default_level()
    if not isinstance(value, str):
        raise ValueError(
            f"log level must be a string or None, got {type(value).__name__}"
        )
    normalized = value.lower()
    if normalized not in _LEVEL_MAP:
        raise ValueError(
            f"invalid log level {value!r}; expected one of {_ALLOWED_VALUES}"
        )
    return _LEVEL_MAP[normalized]


__all__ = ["LogLevelStr", "add_log_level_arg", "resolve"]
