"""Copy the scripts bundle into a generated vault."""

from __future__ import annotations

import shutil
from pathlib import Path

from .._assets import asset_path

#: Files kept in ``scripts/`` for maintainer auditability (a completed
#: one-shot migration's own docstring says it's "committed for auditability
#: of the migration but is NOT intended for routine re-execution") but that
#: have no business in a generated vault or a release bundle — a fresh vault
#: never had the pre-migration shape the script exists to fix (issue #288).
#: This is deliberately a small, named allowlist, not an underscore-prefix
#: convention: ``__init__.py`` is a leading-underscore name this package
#: still needs shipped.
_MAINTAINER_ONLY: frozenset[str] = frozenset({"_migrate_prints_spec048.py"})


def _scripts_src() -> Path:
    """Resolve the bundled ``scripts/`` directory (packaged or dev)."""
    return asset_path("scripts")


def _framework_script_basenames(src: Path) -> set[str]:
    return {
        p.name for p in src.iterdir() if p.is_file() and p.name not in _MAINTAINER_ONLY
    }


def copy_scripts(vault_dir: Path, src: Path | None = None) -> None:
    """Merge framework scripts into ``{vault_dir}/scripts/`` (never rmtree).

    Vault-local collectors not shipped by the framework are preserved byte-for-byte.
    """
    source = src or _scripts_src()
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"scripts source directory not found: {source}")

    dest = vault_dir / "scripts"
    dest.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_file() and item.name not in _MAINTAINER_ONLY:
            shutil.copy2(item, dest / item.name)

    for sh in dest.glob("*.sh"):
        sh.chmod(sh.stat().st_mode | 0o755)

    shipped = _framework_script_basenames(source)
    dest_files = {p.name for p in dest.iterdir() if p.is_file()}
    missing = shipped - dest_files
    if missing:
        raise RuntimeError(f"scripts copy incomplete; missing: {sorted(missing)}")
