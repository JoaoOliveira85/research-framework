import json
import os
import subprocess
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from research_framework._assets import asset_path
from research_framework.generator.scaffold import render_vault_shim
from research_framework.spec.schema import SpecConfig
from tests._helpers.vault_factory import build_minimal_vault


def _legacy_render(vault_dir: Path, spec: SpecConfig) -> str:
    templates_dir = asset_path("templates")
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    ctx = {"vault_dir": str(vault_dir.resolve()), "spec": spec}
    return env.get_template("vault-script.sh.j2").render(**ctx)


def _spec(vault: Path) -> SpecConfig:
    raw = json.loads((vault / "_pipeline/spec-parse.json").read_text(encoding="utf-8"))
    return SpecConfig.from_dict(raw)


def test_render_vault_shim_matches_legacy_scaffold_output(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    spec = _spec(vault)
    assert render_vault_shim(vault, spec) == _legacy_render(vault, spec)


def test_render_vault_shim_vault_dir_is_resolved_absolute(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    spec = _spec(vault)
    assert str(vault.resolve()) in render_vault_shim(vault, spec)


# ---------------------------------------------------------------------------
# Execution-level regression coverage for the vault shim's CLI-dispatch verbs.
#
# These verbs shell out via ``exec "${RV[@]}" <verb> ...`` where ``RV`` is a
# bash *array* holding the interpreter + module invocation. Two bugs shipped
# in 1.0.0rc10 that a render/lint-only check could not catch:
#
#   1. ``RV`` was a plain string quoted as ``exec "${RV}"``, so bash tried to
#      exec one literal filename equal to "<python> -m research_framework.cli"
#      and every verb died with exit 127 ("No such file or directory").
#   2. ``research`` pointed ``--spec`` at ``settings.yaml`` (the settings
#      profile), not ``research.spec.md`` (the spec), so generate failed with
#      "missing YAML frontmatter".
#
# We stub ``.venv/bin/python`` with a script that echoes its argv so the verbs
# reach the exec without a real framework install, then assert the argv the
# shim actually forwards.
# ---------------------------------------------------------------------------


def _install_argv_echo_python(vault: Path) -> None:
    """Write a fake ``.venv/bin/python`` that prints each argv item on a line."""
    venv_bin = vault / ".venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    stub = venv_bin / "python"
    stub.write_text(
        '#!/usr/bin/env bash\nfor a in "$@"; do printf "%s\\n" "$a"; done\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)


def _run_verb(vault: Path, verb: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["./vault", verb],
        cwd=vault,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )


@pytest.fixture()
def shim_vault(tmp_path: Path) -> Path:
    vault = build_minimal_vault(tmp_path)
    (vault / "vault").write_text(render_vault_shim(vault, _spec(vault)))
    os.chmod(vault / "vault", 0o755)
    _install_argv_echo_python(vault)
    return vault


def test_shim_research_forwards_split_argv_and_spec_path(shim_vault: Path) -> None:
    """research must not die at exit 127 and must target research.spec.md."""
    proc = _run_verb(shim_vault, "research")
    assert proc.returncode == 0, proc.stderr
    argv = proc.stdout.splitlines()
    # Word-splitting (bug 1): the interpreter invocation reaches the stub as
    # separate tokens, not one literal filename.
    assert argv[:3] == ["-m", "research_framework.cli", "generate"]
    # Correct spec path (bug 2): --spec points at research.spec.md.
    assert "--spec" in argv
    spec_arg = argv[argv.index("--spec") + 1]
    assert spec_arg == str(shim_vault.resolve() / "research.spec.md")
    assert not spec_arg.endswith("settings.yaml")
    assert "--resume" in argv


def test_shim_coverage_forwards_split_argv(shim_vault: Path) -> None:
    proc = _run_verb(shim_vault, "coverage")
    assert proc.returncode == 0, proc.stderr
    argv = proc.stdout.splitlines()
    assert argv[:3] == ["-m", "research_framework.cli", "coverage"]
    assert argv[3:5] == ["--vault", str(shim_vault.resolve())]


def test_shim_reindex_forwards_split_argv(shim_vault: Path) -> None:
    proc = _run_verb(shim_vault, "reindex")
    assert proc.returncode == 0, proc.stderr
    argv = proc.stdout.splitlines()
    assert argv[:3] == ["-m", "research_framework.cli", "reindex"]
    assert argv[3:5] == ["--vault", str(shim_vault.resolve())]


def test_shim_export_forwards_split_argv(shim_vault: Path) -> None:
    """Issue #189: `./vault export --claims` reaches the argparse verb intact."""
    proc = subprocess.run(
        ["./vault", "export", "--claims"],
        cwd=shim_vault,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 0, proc.stderr
    argv = proc.stdout.splitlines()
    assert argv[:3] == ["-m", "research_framework.cli", "export"]
    assert argv[3:5] == ["--vault", str(shim_vault.resolve())]
    assert argv[5:] == ["--claims"]
