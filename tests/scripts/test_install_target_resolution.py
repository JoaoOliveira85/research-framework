"""FR-001/002/003 — TARGET resolution and source-vs-target split (spec 039 US1).

The F2 bug: ``install.sh`` ignored ``$1``/``${VAULT_DIR}`` and always operated on
``ROOT_DIR``. These tests lock precedence, in-place default, and the wheel-source
vs vault-target write split.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parents[2] / "dist-templates" / "install.sh"
RESEARCH_SPEC = (
    Path(__file__).resolve().parents[2] / "dist-templates" / "research.spec.md"
)


def _bash_available() -> bool:
    return shutil.which("bash") is not None


def _extract_function_block(install_sh_text: str, fn_name: str) -> str:
    lines = install_sh_text.splitlines()
    out: list[str] = []
    in_fn = False
    depth = 0
    for line in lines:
        if not in_fn and line.startswith(f"{fn_name}()"):
            in_fn = True
        if in_fn:
            out.append(line)
            depth += line.count("{") - line.count("}")
            if depth == 0 and "{" in "\n".join(out):
                break
    assert out, f"{fn_name}() not found in install.sh"
    return "\n".join(out)


def _extract_target_resolution_block(text: str) -> str:
    """Return the TARGET-resolution block from install.sh."""
    lines = text.splitlines()
    out: list[str] = []
    capture = False
    for line in lines:
        if line.startswith('TARGET="${POSITIONAL_TARGET'):
            capture = True
        if capture:
            out.append(line)
            if line.startswith('cd "${TARGET}"'):
                break
    assert out, "TARGET resolution block missing"
    return "\n".join(out)


@pytest.mark.skipif(not _bash_available(), reason="bash not available")
class TestTargetPrecedence:
    def test_positional_arg_wins_over_vault_dir(self, tmp_path: Path) -> None:
        pos = tmp_path / "positional"
        env_dir = tmp_path / "env-vault"
        pos.mkdir()
        env_dir.mkdir()
        block = _extract_target_resolution_block(INSTALL_SH.read_text(encoding="utf-8"))
        harness = tmp_path / "harness.sh"
        harness.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                set -euo pipefail
                ROOT_DIR="{tmp_path / "bundle"}"
                mkdir -p "$ROOT_DIR"
                VAULT_DIR="{env_dir}"
                POSITIONAL_TARGET="{pos}"
                {block}
                echo "TARGET=$TARGET"
                """
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            ["bash", str(harness)], capture_output=True, text=True, timeout=15
        )
        assert proc.returncode == 0, proc.stderr
        assert (
            f"TARGET={pos.resolve()}" in proc.stdout or f"TARGET={pos}" in proc.stdout
        )

    def test_vault_dir_wins_when_no_positional(self, tmp_path: Path) -> None:
        root = tmp_path / "bundle"
        vault = tmp_path / "my-vault"
        root.mkdir()
        vault.mkdir()
        block = _extract_target_resolution_block(INSTALL_SH.read_text(encoding="utf-8"))
        harness = tmp_path / "harness.sh"
        harness.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                set -euo pipefail
                ROOT_DIR="{root}"
                VAULT_DIR="{vault}"
                POSITIONAL_TARGET=""
                {block}
                echo "TARGET=$TARGET"
                """
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            ["bash", str(harness)], capture_output=True, text=True, timeout=15
        )
        assert proc.returncode == 0, proc.stderr
        assert str(vault.resolve()) in proc.stdout

    def test_root_dir_default_in_place(self, tmp_path: Path) -> None:
        root = tmp_path / "bundle"
        root.mkdir()
        block = _extract_target_resolution_block(INSTALL_SH.read_text(encoding="utf-8"))
        harness = tmp_path / "harness.sh"
        harness.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                set -euo pipefail
                ROOT_DIR="{root}"
                unset VAULT_DIR
                POSITIONAL_TARGET=""
                {block}
                echo "TARGET=$TARGET"
                """
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            ["bash", str(harness)], capture_output=True, text=True, timeout=15
        )
        assert proc.returncode == 0, proc.stderr
        assert str(root.resolve()) in proc.stdout

    def test_mkdir_p_creates_absent_target(self, tmp_path: Path) -> None:
        root = tmp_path / "bundle"
        target = tmp_path / "new-vault"
        root.mkdir()
        block = _extract_target_resolution_block(INSTALL_SH.read_text(encoding="utf-8"))
        harness = tmp_path / "harness.sh"
        harness.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                set -euo pipefail
                ROOT_DIR="{root}"
                POSITIONAL_TARGET="{target}"
                {block}
                test -d "{target}"
                """
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            ["bash", str(harness)], capture_output=True, text=True, timeout=15
        )
        assert proc.returncode == 0, proc.stderr
        assert target.is_dir()


class TestTargetWiring:
    def test_install_sh_cd_targets_target_not_root_only(self) -> None:
        text = INSTALL_SH.read_text(encoding="utf-8")
        assert 'cd "${TARGET}"' in text, "install must cd into TARGET after resolution"
        idx_target = text.find('TARGET="${')
        idx_cd = text.find('cd "${TARGET}"')
        assert idx_target < idx_cd, "TARGET must be resolved before cd"

    def test_venv_dir_under_target(self) -> None:
        text = INSTALL_SH.read_text(encoding="utf-8")
        assert 'VENV_DIR="${TARGET}/.venv"' in text

    def test_wheel_glob_stays_on_root_dir(self) -> None:
        text = INSTALL_SH.read_text(encoding="utf-8")
        assert 'ls "${ROOT_DIR}"/research_framework-*.whl' in text

    def test_in_place_info_line_present(self) -> None:
        text = INSTALL_SH.read_text(encoding="utf-8")
        assert "installing in place at" in text


@pytest.mark.skipif(not _bash_available(), reason="bash not available")
@pytest.mark.slow
class TestF2SourceVsTargetSplit:
    """End-to-end: wheel sourced from ROOT_DIR, venv written to TARGET."""

    def test_venv_lands_under_target_bundle_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = tmp_path / "bundle"
        target = tmp_path / "vault-target"
        bundle.mkdir()
        target.mkdir()

        # Minimal fake wheel (pip needs a valid wheel — use real one if present)
        real_wheels = list(
            (Path(__file__).resolve().parents[2] / "dist").glob(
                "research_framework-*.whl"
            )
        )
        if not real_wheels:
            real_wheels = list(
                Path(__file__).resolve().parents[2].glob("research_framework-*.whl")
            )
        if not real_wheels:
            pytest.skip("no research_framework wheel available for slow e2e")

        shutil.copy(real_wheels[0], bundle / real_wheels[0].name)
        # install.sh resolves the wheel relative to its OWN dir (ROOT_DIR), not
        # cwd — so the bundle must be a self-contained "distribution": copy the
        # script in beside the wheel and run THAT copy. Running the repo's
        # dist-templates/install.sh would look for the wheel next to itself
        # (where none exists) and abort, which is exactly how a stray dist/
        # wheel used to make this test fail instead of skip.
        bundle_install_sh = bundle / "install.sh"
        shutil.copy(INSTALL_SH, bundle_install_sh)

        env = os.environ.copy()
        env.update(
            {
                "RV_INSTALL_LOG": "0",
                "RV_NONINTERACTIVE": "1",
                "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
            }
        )
        proc = subprocess.run(
            [
                "bash",
                str(bundle_install_sh),
                str(target),
                "--non-interactive",
                "--accept-path",
                str(target),
            ],
            cwd=str(bundle),
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert (target / ".venv").is_dir(), "venv must land under TARGET"
        assert (
            not (bundle / ".venv").exists() or bundle.resolve() == target.resolve()
        ), "bundle ROOT_DIR must not receive .venv when TARGET differs"
        # Bundle scaffold must remain untouched (no research.spec.md written to bundle)
        if bundle.resolve() != target.resolve():
            assert (
                not (bundle / "research.spec.md").exists()
                or not (bundle / "research.spec.md").stat().st_size
            )
