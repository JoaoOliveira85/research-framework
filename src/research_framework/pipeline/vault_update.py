"""Pure decision helpers for the hardened ``./vault update`` verb (spec 027).

Version resolution, ordering checks, and pre-flight guard outcomes live here so
integration tests can exercise the policy without driving network I/O. The bash
``update`` verb in ``templates/vault-script.sh.j2`` delegates to these helpers
via the vault venv Python.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_LOG = logging.getLogger(__name__)

__all__ = (
    "Decision",
    "compare_versions",
    "decide",
    "is_user_owned",
    "resolve_local_version",
    "resolve_target_version",
    "snapshot_title",
)

VersionRelation = Literal["same", "upgrade", "downgrade"]


@dataclass(frozen=True)
class Decision:
    """Outcome of the update pre-flight decision tree."""

    action: str
    message: str
    exit_code: int


def _parse_version(version: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", version)
    return tuple(int(part) for part in parts) if parts else (0,)


# PEP 440's version grammar (its Appendix B regex), anchored. Hand-rolled
# because `packaging` is not a declared dependency of this project and the
# update verb runs inside the vault venv, which only has what we declare.
_PEP440 = re.compile(
    r"""
    ^\s*v?
    (?:(?P<epoch>[0-9]+)!)?
    (?P<release>[0-9]+(?:\.[0-9]+)*)
    (?:[-_.]?(?P<pre_l>alpha|a|beta|b|preview|pre|c|rc)[-_.]?(?P<pre_n>[0-9]+)?)?
    (?P<post>
        -(?P<post_n1>[0-9]+)
        | [-_.]?(?:post|rev|r)[-_.]?(?P<post_n2>[0-9]+)?
    )?
    (?P<dev>[-_.]?dev[-_.]?(?P<dev_n>[0-9]+)?)?
    (?:\+(?P<local>[a-z0-9]+(?:[-_.][a-z0-9]+)*))?
    \s*$
    """,
    re.VERBOSE | re.IGNORECASE | re.ASCII,
)
_PRE_RANK = {
    "a": 0,
    "alpha": 0,
    "b": 1,
    "beta": 1,
    "c": 2,
    "rc": 2,
    "pre": 2,
    "preview": 2,
}
_DEV_ONLY = (-1, 0)  # 1.0.dev1 sorts before 1.0a1
_FINAL = (3, 0)  # 1.0 sorts after 1.0rc1

_Pep440Key = tuple[
    int,
    tuple[int, ...],
    tuple[int, int],
    tuple[int, int],
    tuple[int, int],
    tuple[tuple[int, int, str], ...],
]


def _pep440_key(version: str) -> _Pep440Key | None:
    """Return a key that sorts *version* the way PEP 440 does.

    ``None`` when the string is not a PEP 440 version. The segments compare in
    the order epoch, release, pre, post, dev, local; an absent pre-release
    sorts after any present one (``1.0rc1 < 1.0``), an absent post-release
    before (``1.0 < 1.0.post1``), an absent dev-release after
    (``1.0.dev1 < 1.0``).
    """
    match = _PEP440.match(version)
    if match is None:
        return None
    release = [int(part) for part in match["release"].split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()  # 1.0 == 1.0.0
    has_post = match["post"] is not None
    has_dev = match["dev"] is not None
    if match["pre_l"] is not None:
        pre = (_PRE_RANK[match["pre_l"].lower()], int(match["pre_n"] or 0))
    elif has_dev and not has_post:
        pre = _DEV_ONLY
    else:
        pre = _FINAL
    post_number = int(match["post_n1"] or match["post_n2"] or 0)
    local = tuple(
        (1, int(part), "") if part.isdigit() else (0, 0, part)
        for part in re.split(r"[-_.]", (match["local"] or "").lower())
        if part
    )
    return (
        int(match["epoch"] or 0),
        tuple(release),
        pre,
        (1, post_number) if has_post else (0, 0),
        (0, int(match["dev_n"] or 0)) if has_dev else (1, 0),
        local,
    )


def compare_versions(local: str, target: str) -> VersionRelation:
    """Classify *target* relative to *local* by PEP 440 ordering.

    PEP 440 is the scheme ``pyproject.toml`` and the release tags use
    (``1.0.0rc11``). Comparing only the digits read the pre-release number as
    a fourth release component, so ``1.0.0rc11`` -> ``1.0.0`` was classified a
    downgrade and the update verb refused the step from the last release
    candidate to the final release.

    When either string is not a PEP 440 version both sides fall back to the
    digit tuples: this function must not raise (the verb would exit on a
    traceback), and a like-for-like comparison is better than none.
    """
    local_key: tuple[object, ...] | None = _pep440_key(local)
    target_key: tuple[object, ...] | None = _pep440_key(target)
    if local_key is None or target_key is None:
        local_key, target_key = _parse_version(local), _parse_version(target)
    if local_key == target_key:
        return "same"
    if target_key > local_key:
        return "upgrade"
    return "downgrade"


def snapshot_title(old: str, new: str) -> str:
    """Return the FR-004 pre-snapshot commit subject body (without ``framework:``)."""
    return f"snapshot before update {old} -> {new}"


def decide(
    local: str,
    target: str,
    *,
    force: bool = False,
    pinned_ref: str | None = None,
    confirmed: bool = False,
) -> Decision:
    """Encode FR-002 short-circuit and FR-012 downgrade refusal.

    ``force`` does two things, and it is worth being explicit about both: it
    overrides the dirty-working-tree guard (enforced by the verb, not here),
    AND it defeats the same-version short-circuit below.

    The second was missing until 2026-08-27. Without it, an operator running an
    unreleased build could not refresh a vault's `scripts/` or `_templates/` at
    all: the archive and the vault reported the same version string, `decide`
    returned ``noop``, and the verb exited 0 having changed nothing. That is the
    worst combination — a stale bundle and a success exit code. It does NOT
    wave through an unconfirmed downgrade; that guard is separate and still
    applies.
    """
    relation = compare_versions(local, target)
    if relation == "same":
        if force:
            return Decision(
                action="proceed",
                message=(
                    f"Already at v{target}; --force re-installing the bundle anyway"
                ),
                exit_code=0,
            )
        return Decision(
            action="noop",
            message=f"Already at v{target}, nothing to do",
            exit_code=0,
        )
    if relation == "downgrade":
        if not pinned_ref or not confirmed:
            return Decision(
                action="refuse",
                message=(
                    f"Refusing downgrade v{local} → v{target}. "
                    "Set RV_GITHUB_REF and confirm to proceed."
                ),
                exit_code=2,
            )
    return Decision(
        action="proceed",
        message=f"Upgrading v{local} → v{target}",
        exit_code=0,
    )


# The maintainer's dev-setup script and the end-user installer are both named
# `install.sh`. This token appears only in the former.
_MAINTAINER_MARKER = "pip install -e"


def resolve_installer(archive: Path) -> Path | None:
    """Return the END-USER installer inside a fetched framework archive.

    Two archive shapes reach the update verb and they disagree about where the
    installer lives:

    - **git archive of the repo** (what ``RV_GITHUB_REF`` fetches): the root
      ``install.sh`` is the *maintainer* dev-setup script — it ignores its
      arguments and runs ``pip install -e ".[dev]"``. Run from a vault (which
      is where ``./vault update`` executes), that tries to pip-install the
      operator's vault and fails with "does not appear to be a Python project".
      The real installer is at ``dist-templates/install.sh``.
    - **release tarball**: only the end-user installer ships, at the root.

    Before this existed the verb always took the root path, so on a git-archive
    source it ran the wrong script and vault-local ``scripts/`` and
    ``_templates/`` were never refreshed — on any update, version bump or not.

    Returns ``None`` when only the maintainer script is present; the caller
    warns that scaffolding was not refreshed rather than running it.
    """
    dist = archive / "dist-templates" / "install.sh"
    if dist.is_file():
        return dist
    root = archive / "install.sh"
    if root.is_file():
        try:
            if _MAINTAINER_MARKER not in root.read_text(encoding="utf-8"):
                return root
        except OSError:  # pragma: no cover - defensive
            return None
    return None


def sync_vault_scripts(vault: Path, *, source: Path | None = None) -> list[str]:
    """Refresh vault-local ``scripts/`` from the installed package. Returns the
    basenames actually changed.

    ``_helpers/script_runner._resolve_script`` prefers the VAULT copy and only
    falls back to the packaged one when the vault file is missing — so a stale
    vault script silently shadows a fixed packaged copy, and a fix shipped in
    the wheel never runs. All five vaults validated on 2026-08-27 were in that
    state: branch build installed, released-rc11 `validate_cycle.py` on disk.

    The update verb cannot get this from ``install.sh``: that installer needs a
    built wheel beside it (release-tarball layout), and a ``RV_GITHUB_REF`` git
    archive has none, so it exits before syncing. Copying from the package that
    pip just installed is simpler and strictly more correct — it is the code
    that will actually run.

    Only overwrites basenames the package ships; operator-added scripts are left
    alone, and nothing is ever deleted. Best-effort by design: scripts are a
    regenerable artifact and must never fail an upgrade.
    """
    if os.environ.get("RV_SKIP_SCRIPT_SYNC"):
        # Escape hatch for an operator who deliberately maintains a customised
        # vault-local script. Off by default: leaving a stale copy in place is
        # how a shipped fix silently fails to run.
        _LOG.info("RV_SKIP_SCRIPT_SYNC set — leaving vault scripts/ untouched")
        return []
    if source is None:
        try:
            from research_framework._assets import asset_path

            source = asset_path("scripts")
        except (FileNotFoundError, ImportError):  # pragma: no cover - defensive
            return []
    if not source.is_dir():
        return []

    dest_dir = vault / "scripts"
    changed: list[str] = []
    for src_file in sorted(source.glob("*.py")):
        dest = dest_dir / src_file.name
        try:
            body = src_file.read_bytes()
            if dest.is_file() and dest.read_bytes() == body:
                continue
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest)
            changed.append(src_file.name)
        except OSError as exc:  # pragma: no cover - advisory
            _LOG.warning("could not refresh vault script %s: %s", src_file.name, exc)
    return changed


def resolve_local_version(vault: Path) -> str:
    """Read the installed ``research-framework`` version from the vault venv."""
    venv_python = vault / ".venv" / "bin" / "python"
    if not venv_python.is_file():
        raise FileNotFoundError(f"vault venv not found at {vault / '.venv'}")
    proc = subprocess.run(
        [
            str(venv_python),
            "-c",
            "import importlib.metadata as m; print(m.version('research-framework'))",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        proc = subprocess.run(
            [
                str(venv_python),
                "-c",
                "import research_framework; print(research_framework.__version__)",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    version = proc.stdout.strip()
    if not version:
        raise RuntimeError("failed to resolve local framework version")
    return version


def resolve_target_version(archive_or_ref: Path) -> str:
    """Parse ``pyproject.toml::version`` from a fetched archive directory."""
    root = archive_or_ref
    pyproject = root if root.is_file() else root / "pyproject.toml"
    if not pyproject.is_file():
        raise FileNotFoundError(f"pyproject.toml not found under {archive_or_ref}")
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def is_user_owned(manifest: object, rel_path: str) -> bool:
    """Return whether *rel_path* is protected after first write (FR-006).

    Accepts a :class:`~research_framework.pipeline.scaffold_manifest.ScaffoldManifest`
    or a snapshot ``dict`` with an ``entries`` list (vault-local copy).
    Unknown paths default to ``False`` (framework-managed).
    """
    normalized = rel_path.replace("\\", "/").lstrip("/")
    entries: tuple[object, ...] | list[object]
    if isinstance(manifest, Mapping):
        raw = manifest.get("entries", ())
        entries = raw if isinstance(raw, list) else ()
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            if str(entry.get("path", "")) == normalized:
                return bool(entry.get("is_user_owned_after_first_write", False))
        return False
    entries = getattr(manifest, "entries", ())
    for entry in entries:
        path = getattr(entry, "path", None)
        if path == normalized:
            return bool(getattr(entry, "is_user_owned_after_first_write", False))
    return False
