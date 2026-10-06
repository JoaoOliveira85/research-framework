"""Integration tests for the hardened ``./vault update`` verb (spec 027).

Tier-3 hermetic tests: local file-URL framework repo, no network, no live
``claude``/``codex``. Exercises the rendered ``vault`` shim from
``templates/vault-script.sh.j2`` once the update verb is wired to
``pipeline.vault_update`` decision helpers.

See ``specs/027-vault-update-hardening/plan.md`` §Test approach.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests._helpers.vault_factory import build_minimal_vault

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git_repo(path: Path, *, message: str = "initial") -> None:
    """Initialize a git repo and commit all present files (framework remote)."""
    if not (path / ".git").exists():
        _run_git("git", "init", "-b", "main", cwd=path)
    _run_git("git", "config", "user.email", "test@example.com", cwd=path)
    _run_git("git", "config", "user.name", "Test", cwd=path)
    _run_git("git", "add", "-A", cwd=path)
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(path),
        capture_output=True,
        text=True,
        check=True,
    )
    if status.stdout.strip():
        _run_git("git", "commit", "-m", message, cwd=path)


def _bootstrap_vault_git(vault: Path) -> None:
    """Track corpus + settings so Principle X commits and dirty checks work."""
    if not (vault / ".git").exists():
        _run_git("git", "init", "-b", "main", cwd=vault)
    _run_git("git", "config", "user.email", "test@example.com", cwd=vault)
    _run_git("git", "config", "user.name", "Test", cwd=vault)
    tracked = vault / "01 - Concepts" / "seed-tracked.md"
    tracked.parent.mkdir(parents=True, exist_ok=True)
    if not tracked.exists():
        tracked.write_text("# tracked seed\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-f", "01 - Concepts/seed-tracked.md", "settings.yaml"],
        cwd=str(vault),
        check=True,
        capture_output=True,
    )
    # The scaffold's .gitignore now un-ignores the spec-058 control files
    # (research.spec.md, _pipeline/{research-backlog.md,coverage-targets.json}).
    # Stage whatever else git can see so the bootstrap commit leaves a CLEAN
    # tree — otherwise the update verb's dirty-tree guard trips. Mirrors what
    # `vault_commit` does in a real vault (`git add -A`).
    _run_git("git", "add", "-A", cwd=vault)
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(vault),
        capture_output=True,
        text=True,
        check=True,
    )
    if status.stdout.strip():
        _run_git("git", "commit", "-m", "vault bootstrap", cwd=vault)


def _ensure_vault_venv(vault: Path) -> Path:
    """Create ``.venv`` and editable-install the worktree package."""
    venv_python = vault / ".venv/bin/python"
    if not venv_python.is_file():
        subprocess.run(
            [sys.executable, "-m", "venv", str(vault / ".venv")],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [str(vault / ".venv/bin/pip"), "install", "-q", "-e", str(REPO_ROOT)],
            check=True,
            capture_output=True,
        )
    return venv_python


def _write_minimal_framework_tree(
    root: Path,
    *,
    version: str,
    install_sh: bool = True,
) -> None:
    """Lay down a minimal pip-installable research-framework source tree."""
    root.mkdir(parents=True, exist_ok=True)
    pyproject = textwrap.dedent(
        f"""\
        [build-system]
        requires = ["hatchling"]
        build-backend = "hatchling.build"

        [project]
        name = "research-framework"
        version = "{version}"
        requires-python = ">=3.11"

        [tool.hatch.build.targets.wheel]
        packages = ["src/research_framework"]
        """
    )
    (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    src_pkg = root / "src" / "research_framework"
    src_pkg.mkdir(parents=True, exist_ok=True)
    (src_pkg / "__init__.py").write_text(
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )
    if install_sh:
        (root / "install.sh").write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail
                VAULT_DIR="${1:-}"
                echo '[install] stub OK'
                if [[ -n "${VAULT_DIR}" && -d "${VAULT_DIR}/01 - Concepts" ]]; then
                  echo "# upgraded" >> "${VAULT_DIR}/01 - Concepts/seed-tracked.md"
                fi
                """
            ),
            encoding="utf-8",
        )
        (root / "install.sh").chmod(0o755)


@dataclass(frozen=True)
class LocalFrameworkRepo:
    """A hermetic local git repo exposed as a ``file://`` URL."""

    root: Path
    file_url: str

    def checkout_version(self, version: str, *, ref: str = "main") -> None:
        _write_minimal_framework_tree(self.root, version=version)
        _run_git("git", "add", "-A", cwd=self.root)
        _run_git("git", "commit", "-m", f"framework {version}", cwd=self.root)
        _run_git("git", "tag", "-f", ref, cwd=self.root)


@pytest.fixture
def local_framework_repo(tmp_path: Path) -> LocalFrameworkRepo:
    """Hermetic file-URL remote mimicking ``RV_GITHUB_REPO``."""
    root = tmp_path / "framework-remote"
    _write_minimal_framework_tree(root, version="0.3.0")
    _init_git_repo(root, message="framework 0.3.0")
    _run_git("git", "tag", "v0.3.0", cwd=root)
    _write_minimal_framework_tree(root, version="0.3.1")
    _run_git("git", "add", "-A", cwd=root)
    _run_git("git", "commit", "-m", "framework 0.3.1", cwd=root)
    _run_git("git", "tag", "v0.3.1", cwd=root)
    file_url = root.resolve().as_uri()
    return LocalFrameworkRepo(root=root, file_url=file_url)


def _render_fresh_vault_shim(vault: Path) -> None:
    from research_framework.generator.scaffold import render_vault_shim
    from research_framework.spec.parser import parse

    spec = parse(vault / "research.spec.md")
    shim = vault / "vault"
    shim.write_text(render_vault_shim(vault, spec), encoding="utf-8")
    shim.chmod(0o755)


def _install_framework_from_repo(
    vault: Path,
    repo: LocalFrameworkRepo,
    *,
    ref: str,
) -> None:
    subprocess.run(
        [
            str(vault / ".venv/bin/pip"),
            "install",
            "-q",
            f"git+{repo.file_url}@{ref}",
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def upgrade_vault(tmp_path: Path, local_framework_repo: LocalFrameworkRepo) -> Path:
    """Fixture vault at framework v0.3.0 with git history and a rendered shim."""
    vault = build_minimal_vault(tmp_path)
    _bootstrap_vault_git(vault)
    _ensure_vault_venv(vault)
    _install_framework_from_repo(vault, local_framework_repo, ref="v0.3.0")
    _render_fresh_vault_shim(vault)
    return vault


def _run_vault_update(
    vault: Path,
    *args: str,
    env: dict[str, str] | None = None,
    bash: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], float]:
    """Run ``./vault update`` with optional env overrides; return proc + elapsed seconds.

    ``bash`` names the interpreter to run the shim with instead of the one its
    shebang resolves to — ``/bin/bash`` is 3.2 on macOS.
    """
    run_env = {**os.environ, **(env or {})}
    # The vault venv carries a *stub* framework (installed for version
    # simulation — see ``_install_framework_from_repo``), which has no
    # ``research_framework.pipeline``. The hardened shim resolves versions via
    # ``from research_framework.pipeline import vault_update``, so it needs the
    # real decision helpers on the subprocess path. ``resolve_local_version``
    # still reads the stub's installed dist metadata (0.3.0), so this supplies
    # only the *code*, never the version. Set it explicitly so the test does not
    # depend on the runner exporting ``PYTHONPATH=src`` — ``build.sh``'s smoke
    # gate (line 165) does not, which is why this regressed only at release time.
    repo_src = str(REPO_ROOT / "src")
    existing_pp = run_env.get("PYTHONPATH", "")
    run_env["PYTHONPATH"] = (
        repo_src + os.pathsep + existing_pp if existing_pp else repo_src
    )
    started = time.perf_counter()
    shim = [bash, str(vault / "vault")] if bash else [str(vault / "vault")]
    proc = subprocess.run(
        [*shim, "update", *args],
        cwd=str(vault),
        capture_output=True,
        text=True,
        env=run_env,
        timeout=30,
    )
    return proc, time.perf_counter() - started


def _update_env(repo: LocalFrameworkRepo, *, ref: str = "v0.3.1") -> dict[str, str]:
    return {
        "RV_GITHUB_REPO": repo.file_url,
        "RV_GITHUB_REF": ref,
    }


def _git_log_oneline(vault: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "log", "--oneline", "--pretty=%s"],
        cwd=str(vault),
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in proc.stdout.splitlines() if line.strip()]


def test_short_circuit_when_already_current(
    upgrade_vault: Path,
    local_framework_repo: LocalFrameworkRepo,
) -> None:
    proc, elapsed = _run_vault_update(
        upgrade_vault,
        env=_update_env(local_framework_repo, ref="v0.3.0"),
    )
    assert proc.returncode == 0
    assert elapsed < 5.0, f"short-circuit took {elapsed:.2f}s (SC-002 limit 5s)"
    assert "Already at" in proc.stdout
    assert "nothing to do" in proc.stdout
    assert "pip upgrade failed" not in proc.stdout + proc.stderr


def test_dirty_tree_refused_without_force(
    upgrade_vault: Path,
    local_framework_repo: LocalFrameworkRepo,
) -> None:
    settings = upgrade_vault / "settings.yaml"
    settings.write_text(settings.read_text() + "# dirty\n", encoding="utf-8")
    proc, elapsed = _run_vault_update(
        upgrade_vault,
        env=_update_env(local_framework_repo, ref="v0.3.1"),
    )
    assert proc.returncode != 0
    assert elapsed < 2.0, f"dirty refusal took {elapsed:.2f}s (SC-003 limit 2s)"
    assert "dirty" in proc.stderr.lower() or "dirty" in proc.stdout.lower()
    assert "framework: upgrade to 0.3.1" not in _git_log_oneline(upgrade_vault)


def test_dirty_tree_proceeds_with_force_flag(
    upgrade_vault: Path,
    local_framework_repo: LocalFrameworkRepo,
) -> None:
    settings = upgrade_vault / "settings.yaml"
    settings.write_text(settings.read_text() + "# dirty\n", encoding="utf-8")
    proc, _elapsed = _run_vault_update(
        upgrade_vault,
        "--force",
        "--auto-confirm",
        env=_update_env(local_framework_repo, ref="v0.3.1"),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    subjects = _git_log_oneline(upgrade_vault)
    assert any("snapshot before update 0.3.0 -> 0.3.1" in s for s in subjects)


def test_pre_snapshot_then_upgrade_topology(
    upgrade_vault: Path,
    local_framework_repo: LocalFrameworkRepo,
) -> None:
    proc, _elapsed = _run_vault_update(
        upgrade_vault,
        "--auto-confirm",
        env=_update_env(local_framework_repo, ref="v0.3.1"),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    subjects = _git_log_oneline(upgrade_vault)
    assert subjects[0] == "framework: upgrade to 0.3.1"
    assert subjects[1] == "framework: snapshot before update 0.3.0 -> 0.3.1"


def test_downgrade_refused_by_default(
    upgrade_vault: Path,
    local_framework_repo: LocalFrameworkRepo,
) -> None:
    _install_framework_from_repo(upgrade_vault, local_framework_repo, ref="v0.3.1")
    refused, _elapsed = _run_vault_update(
        upgrade_vault,
        env=_update_env(local_framework_repo, ref="v0.3.0"),
    )
    assert refused.returncode != 0
    assert (
        "Refusing downgrade" in refused.stderr or "Refusing downgrade" in refused.stdout
    )

    allowed, _elapsed = _run_vault_update(
        upgrade_vault,
        "--auto-confirm",
        env=_update_env(local_framework_repo, ref="v0.3.0"),
    )
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr


def test_health_failure_surfaces_nonzero(
    upgrade_vault: Path,
    local_framework_repo: LocalFrameworkRepo,
) -> None:
    health = upgrade_vault / "scripts" / "vault_health.py"
    health.write_text(
        "#!/usr/bin/env python3\nimport sys\nsys.exit(3)\n", encoding="utf-8"
    )
    health.chmod(0o755)
    # This test induces the failure by replacing the vault's health checker,
    # and `update` now refreshes vault-local scripts/ from the installed
    # package (a stale copy shadows the packaged one at runtime). The two are
    # orthogonal concerns; opt out of the sync so this test keeps asserting the
    # one it is about — that a failing health check surfaces its exit code.
    env = _update_env(local_framework_repo, ref="v0.3.1")
    env["RV_SKIP_SCRIPT_SYNC"] = "1"
    proc, _elapsed = _run_vault_update(upgrade_vault, "--auto-confirm", env=env)
    assert proc.returncode == 3
    assert (
        "health failed" in proc.stderr.lower() or "health failed" in proc.stdout.lower()
    )


def test_user_owned_file_survives_upgrade(
    upgrade_vault: Path,
    local_framework_repo: LocalFrameworkRepo,
) -> None:
    settings = upgrade_vault / "settings.yaml"
    edited = settings.read_bytes() + b"# user-owned edit\n"
    settings.write_bytes(edited)
    proc, _elapsed = _run_vault_update(
        upgrade_vault,
        "--force",
        "--auto-confirm",
        env=_update_env(local_framework_repo, ref="v0.3.1"),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert settings.read_bytes() == edited


@pytest.mark.regression
@pytest.mark.skipif(not Path("/bin/bash").is_file(), reason="/bin/bash not available")
def test_a_ref_that_closes_a_python_string_is_not_executed(
    upgrade_vault: Path,
    local_framework_repo: LocalFrameworkRepo,
    tmp_path: Path,
) -> None:
    """``RV_GITHUB_REF`` was pasted into the Python that decides the update
    (``pinned_ref="${REF}"``). git allows double quotes and parentheses in a
    ref name, so a ref could close the literal and run as code — before the
    downgrade and dirty-tree gates had a say."""
    marker = tmp_path / "EXECUTED"
    ref = 'v0.3.0"+str(open(__import__("os").environ.get("RF_TEST_MARK"),"w"))+"'
    _run_git("git", "tag", ref, "v0.3.0", cwd=local_framework_repo.root)
    env = _update_env(local_framework_repo, ref=ref)
    env["RF_TEST_MARK"] = str(marker)

    proc, _elapsed = _run_vault_update(upgrade_vault, env=env, bash="/bin/bash")

    assert not marker.exists(), "the ref was executed as Python"
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Already at" in proc.stdout
    assert "nothing to do" in proc.stdout


@pytest.mark.regression
@pytest.mark.skipif(not Path("/bin/bash").is_file(), reason="/bin/bash not available")
def test_a_dirty_check_that_fails_is_not_reported_as_a_dirty_tree(
    upgrade_vault: Path,
    local_framework_repo: LocalFrameworkRepo,
) -> None:
    """The guard read *any* non-zero exit of its check as "dirty". A check
    that crashed — here ``git status`` on an unreadable index — told the
    operator to "commit or stash" a tree nobody had looked at."""
    (upgrade_vault / ".git" / "index").write_bytes(b"not an index")

    proc, _elapsed = _run_vault_update(
        upgrade_vault,
        env=_update_env(local_framework_repo, ref="v0.3.1"),
        bash="/bin/bash",
    )
    combined = proc.stdout + proc.stderr

    assert proc.returncode == 2, combined
    assert "Working tree is dirty" not in combined
    assert "could not check the working tree" in combined
    assert "Upgrading framework from" not in combined, "the upgrade went ahead"
