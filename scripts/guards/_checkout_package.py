"""Shared check: ``research_framework`` must come from THIS checkout (issue #2).

Running ``python scripts/guards/<guard>.py`` puts ``scripts/guards/`` on
``sys.path[0]`` — not ``src/`` — so a guard's ``import research_framework``
resolves through site-packages or an editable finder: a stale install or a
sibling worktree wins, and the guard reports findings about *that* tree.
Guards that import the package call :func:`require_checkout_package` first,
so the answer is either "about this checkout" or an explicit failure.

Resolved with ``importlib.util.find_spec`` (no import) so a wrong-tree
package is rejected before any of its code runs.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

#: Exit status for "the environment is wrong"; ``1`` stays "the guard found a defect".
EXIT_WRONG_PACKAGE = 2


def package_location_problem(
    repo_root: Path,
    package: str = "research_framework",
    *,
    origin: Path | None = None,
) -> str | None:
    """Return a message if ``package`` is not under ``<repo_root>/src``, else ``None``.

    ``origin`` overrides the resolved location (tests; no real second install).
    """
    expected = repo_root.resolve() / "src"
    if origin is None:
        spec = importlib.util.find_spec(package)
        if spec is None or not spec.origin or spec.origin == "namespace":
            return (
                f"{package} is not importable, expected {expected}; "
                "reinstall with pip install -e ."
            )
        origin = Path(spec.origin)
    resolved = origin.resolve()
    if resolved.is_relative_to(expected):
        return None
    return (
        f"imported {package} from {resolved.parent}, expected {expected}; "
        "reinstall with pip install -e ."
    )


def require_checkout_package(
    repo_root: Path,
    package: str = "research_framework",
    *,
    origin: Path | None = None,
) -> None:
    """Exit :data:`EXIT_WRONG_PACKAGE` with an explicit message on a wrong location."""
    problem = package_location_problem(repo_root, package, origin=origin)
    if problem is not None:
        print(f"[guards] ERROR: {problem}", file=sys.stderr)
        raise SystemExit(EXIT_WRONG_PACKAGE)
