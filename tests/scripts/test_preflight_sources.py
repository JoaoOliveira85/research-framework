"""RED tests for scripts/preflight_sources.py (T067 / US5) — T071 turns these green."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "preflight_sources.py"


def _require_script() -> Path:
    assert SCRIPT.is_file(), (
        "T071: expected scripts/preflight_sources.py at "
        f"{SCRIPT} — add the CLI wrapper that calls pipeline.preflight.check_all"
    )
    return SCRIPT


def _run(
    args: list[str], *, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    _require_script()
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_preflight_script_exists() -> None:
    _require_script()


def test_pass_exits_zero_writes_preflight_json(tmp_path: Path) -> None:
    vault = _minimal_local_only_vault(tmp_path)
    proc = _run(["--vault", str(vault)])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = vault / "_pipeline" / "preflight.json"
    assert out.is_file(), "CLI must write _pipeline/preflight.json"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload.get("overall_status") == "pass"
    assert payload.get("schema_version") == "1"


def test_warn_exits_zero(tmp_path: Path) -> None:
    vault = _vault_with_unreachable_enrichment_only(tmp_path)
    proc = _run(["--vault", str(vault)])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(
        (vault / "_pipeline" / "preflight.json").read_text(encoding="utf-8")
    )
    assert payload["overall_status"] == "warn"


def test_fail_exits_one(tmp_path: Path) -> None:
    vault = _vault_with_bad_required_local(tmp_path)
    proc = _run(["--vault", str(vault)])
    assert proc.returncode == 1, proc.stdout + proc.stderr


def test_json_flag_prints_schema_shape_to_stdout(tmp_path: Path) -> None:
    vault = _minimal_local_only_vault(tmp_path)
    proc = _run(["--vault", str(vault), "--json"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["schema_version"] == "1"
    assert "overall_status" in payload
    assert "sources" in payload


def test_structural_error_exits_two_missing_vault_flag() -> None:
    _require_script()
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_structural_error_exits_two_missing_research_spec(tmp_path: Path) -> None:
    vault = tmp_path / "empty-vault"
    (vault / "_pipeline").mkdir(parents=True)
    proc = _run(["--vault", str(vault)])
    assert proc.returncode == 2, proc.stdout + proc.stderr


def _minimal_local_only_vault(parent: Path) -> Path:
    """Synthetic vault + spec: one reachable local_repo-style source; no network."""
    vault = parent / "v-local"
    pipeline = vault / "_pipeline"
    pipeline.mkdir(parents=True)
    repo = vault / "src"
    repo.mkdir(parents=True)
    (vault / "research.spec.md").write_text(
        "\n".join(
            [
                "---",
                'name: "LocalOnly"',
                "location: ./",
                "owner: t",
                "settings: {}",
                "---",
                "",
                "## Scope",
                "domain: d",
                "organization: o",
                "",
                "## Note Types",
                "- name: concept",
                "  description: d",
                '  folder: "01 - Concepts"',
                "",
                "## Data Sources",
                "- name: code",
                "  type: internal",
                "  role: behaviour",
                "  required: true",
                "  access_method: local",
                "  repos:",
                f'    - name: r\n      url: ""\n      local_path: "{repo.as_posix()}"',
                "",
                "## Search Dimensions",
                "dimensions: []",
                "",
                "## Coverage Targets",
                "categories: []",
                "",
                "## Budget",
                "max_usd: 1",
                "max_cycles: 1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return vault


def _vault_with_bad_required_local(parent: Path) -> Path:
    vault = parent / "v-bad"
    pipeline = vault / "_pipeline"
    pipeline.mkdir(parents=True)
    (vault / "research.spec.md").write_text(
        "\n".join(
            [
                "---",
                'name: "BadLocal"',
                "location: ./",
                "owner: t",
                "settings: {}",
                "---",
                "",
                "## Scope",
                "domain: d",
                "organization: o",
                "",
                "## Note Types",
                "- name: concept",
                "  description: d",
                '  folder: "01 - Concepts"',
                "",
                "## Data Sources",
                "- name: code",
                "  type: internal",
                "  role: behaviour",
                "  required: true",
                "  access_method: local",
                "  repos:",
                '    - name: r\n      url: ""\n      local_path: "/no/such/path/for-preflight-test"',
                "",
                "## Search Dimensions",
                "dimensions: []",
                "",
                "## Coverage Targets",
                "categories: []",
                "",
                "## Budget",
                "max_usd: 1",
                "max_cycles: 1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return vault


def _vault_with_unreachable_enrichment_only(parent: Path) -> Path:
    """Required local ok; optional RSS URL will 404 under real check_all (or env mock)."""
    vault = parent / "v-warn"
    pipeline = vault / "_pipeline"
    pipeline.mkdir(parents=True)
    repo = vault / "src"
    repo.mkdir(parents=True)
    (vault / "research.spec.md").write_text(
        "\n".join(
            [
                "---",
                'name: "WarnCase"',
                "location: ./",
                "owner: t",
                "settings: {}",
                "---",
                "",
                "## Scope",
                "domain: d",
                "organization: o",
                "",
                "## Note Types",
                "- name: concept",
                "  description: d",
                '  folder: "01 - Concepts"',
                "",
                "## Data Sources",
                "- name: code",
                "  type: internal",
                "  role: behaviour",
                "  required: true",
                "  access_method: local",
                "  repos:",
                f'    - name: r\n      url: ""\n      local_path: "{repo.as_posix()}"',
                "- name: feed",
                "  type: external",
                "  role: domain",
                "  required: false",
                "  access_method: rss",
                "  repos:",
                '    - name: u\n      url: "https://example.invalid/preflight-t067-warn.xml"\n      local_path: ""',
                "",
                "## Search Dimensions",
                "dimensions: []",
                "",
                "## Coverage Targets",
                "categories: []",
                "",
                "## Budget",
                "max_usd: 1",
                "max_cycles: 1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return vault
