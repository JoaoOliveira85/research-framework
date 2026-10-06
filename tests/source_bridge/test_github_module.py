"""GitHub module contract tests (Tier-2 / spec 060, governed by spec 020).

Cover the SHIPPED module assets at ``src/research_framework/modules/github/``:

1. Manifest parses + validates + declares the expected github url_pattern
   trigger and ``source_id_from`` mapping.
2. The extractor honours the spec-020 stdin/stdout JSON contract for both
   ``extract`` and ``get_source_version``, hermetically — via ``GH_FIXTURE``
   (data injection, no subprocess) and via ``GH_BIN`` (a fake ``gh`` binary so
   the real subprocess path is exercised without the network).
3. Surface routing (pulls / issues / releases) is derived from the URL; the
   ``issues`` surface drops pull-requests; truncation boundary is correct.
4. The emitted ``SignalPayload`` validates against ``signal-payload.schema.json``.
5. **Regression**: the trigger registry routes ``github.com/...`` URLs to the
   ``github`` module, and the ``code`` module no longer claims remote URLs.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from research_framework.pipeline.source_bridge.discovery import (
    build_trigger_registry,
    parse_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULES_ROOT = REPO_ROOT / "src" / "research_framework" / "modules"
MODULE_DIR = MODULES_ROOT / "github"

REPO_URL = "https://github.com/openai/openai-python"
RELEASES_URL = f"{REPO_URL}/releases"
PULLS_URL = f"{REPO_URL}/pulls"
ISSUES_URL = f"{REPO_URL}/issues"

RELEASES_FIXTURE = [
    {
        "tag_name": "v1.2.0",
        "name": "1.2.0",
        "html_url": "https://github.com/openai/openai-python/releases/tag/v1.2.0",
        "published_at": "2026-02-01T00:00:00Z",
    },
    {
        "tag_name": "v1.1.0",
        "name": "1.1.0",
        "html_url": "https://github.com/openai/openai-python/releases/tag/v1.1.0",
        "published_at": "2026-01-01T00:00:00Z",
    },
]

PULLS_FIXTURE = [
    {
        "number": 42,
        "title": "Add streaming support",
        "html_url": "https://github.com/openai/openai-python/pull/42",
        "state": "open",
        "updated_at": "2026-02-10T00:00:00Z",
        "user": {"login": "alice"},
    }
]

# The /issues endpoint returns PRs too (they carry a `pull_request` key) — the
# extractor must drop those so the `issues` surface is genuinely issues-only.
ISSUES_FIXTURE = [
    {
        "number": 7,
        "title": "Docs typo",
        "html_url": "https://github.com/openai/openai-python/issues/7",
        "state": "closed",
        "updated_at": "2026-02-05T00:00:00Z",
        "user": {"login": "bob"},
    },
    {
        "number": 42,
        "title": "Add streaming support",
        "html_url": "https://github.com/openai/openai-python/pull/42",
        "state": "open",
        "updated_at": "2026-02-10T00:00:00Z",
        "user": {"login": "alice"},
        "pull_request": {"url": "https://api.github.com/.../pulls/42"},
    },
]


def _module_path(name: str) -> Path:
    return MODULE_DIR / name


def _write(tmp_path: Path, name: str, data: object) -> Path:
    path = tmp_path / name
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _run_extractor(
    command: str,
    payload: dict,
    *,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in ("GH_FIXTURE", "GH_BIN"):
        env.pop(key, None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(_module_path("extractor.py")), command],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
        check=False,
    )


def _write_fake_gh(
    tmp_path: Path,
    *,
    api_stdout: str = "[]",
    api_exit: int = 0,
    auth_exit: int = 0,
) -> Path:
    """Create an executable fake ``gh`` so the real subprocess path is hermetic.

    On an ``api`` call the fake records its argv to ``<script>.argv`` so tests
    can assert the extractor built the right ``gh api`` endpoint (surface
    routing) rather than trusting any-JSON-array-means-pass.
    """
    script = tmp_path / "fake_gh.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, pathlib\n"
        "args = sys.argv[1:]\n"
        "if args[:1] == ['auth']:\n"
        f"    sys.exit({auth_exit})\n"
        "if args[:1] == ['api']:\n"
        "    pathlib.Path(__file__ + '.argv').write_text(chr(10).join(args))\n"
        f"    sys.stdout.write({api_stdout!r})\n"
        f"    sys.exit({api_exit})\n"
        "sys.exit(3)\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR)
    return script


# ---------------------------------------------------------------------------
# Manifest + asset contracts
# ---------------------------------------------------------------------------


def test_manifest_loads_and_declares_github_identity() -> None:
    raw = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    assert raw["name"] == "github"
    assert raw["entry_point"] == "extractor.py"
    assert raw["schema_examples"] == "few-shot.md"
    assert raw["authentication"] == "none"  # session auth, no env key


def test_manifest_validates_via_discovery_parser() -> None:
    manifest = parse_manifest(_module_path("manifest.yaml"))
    assert manifest.name == "github"
    assert manifest.entry_point == "extractor.py"
    assert manifest.source_id_from.get("github_sources") == "url"


def test_manifest_conforms_to_json_schema() -> None:
    pytest.importorskip("jsonschema", reason="jsonschema not installed")
    import jsonschema  # type: ignore

    schema_path = (
        REPO_ROOT / "specs" / "020-code-bridge" / "contracts" / "manifest.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    data = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)


def test_manifest_url_trigger_matches_github_not_others() -> None:
    import re

    raw = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    patterns = [t["pattern"] for t in raw["triggers"] if t["type"] == "url_pattern"]
    assert len(patterns) >= 1
    rx = re.compile("|".join(f"(?:{p})" for p in patterns))
    assert rx.search(REPO_URL)
    assert rx.search(PULLS_URL)
    assert rx.search(ISSUES_URL)
    assert rx.search(RELEASES_URL)
    assert not rx.search("https://gitlab.com/org/repo")
    assert not rx.search("https://example.com/openai/openai-python")
    # Tightened (spec-020 amendment): file/tree browse URLs are NOT claimed —
    # they would otherwise silently poll releases.
    assert not rx.search("https://github.com/openai/openai-python/blob/main/x.py")
    assert not rx.search("https://github.com/openai/openai-python/tree/main")


def test_assets_ship_with_module() -> None:
    template = _module_path("sources.yaml.template")
    raw = yaml.safe_load(template.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    entries = raw.get("github_sources", [])
    assert 4 <= len(entries) <= 8
    assert all("github.com" in e["url"] for e in entries)
    assert _module_path("few-shot.md").read_text(encoding="utf-8").count("```") >= 2
    assert _module_path("README.md").exists()


# ---------------------------------------------------------------------------
# Extractor — GH_FIXTURE (hermetic data injection)
# ---------------------------------------------------------------------------


def test_extract_releases_emits_valid_signal(tmp_path: Path) -> None:
    fixture = _write(tmp_path, "rel.json", {"releases": RELEASES_FIXTURE})
    result = _run_extractor(
        "extract",
        {"source": {"url": RELEASES_URL}, "source_id": RELEASES_URL},
        env_extra={"GH_FIXTURE": str(fixture)},
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["module"] == "github"
    assert payload["source_id"] == RELEASES_URL
    assert payload["verdict"] == "ok"
    assert payload["facts"] == {}
    assert payload["source_version"].startswith("sha256:")
    assert payload["extracted_at"].endswith("Z")
    obs = " ".join(n["observation"] for n in payload["notable"])
    assert "v1.2.0" in obs and "release" in obs.lower()


def test_get_source_version_matches_extract(tmp_path: Path) -> None:
    """The cache-probe version MUST equal the version `extract` emits."""
    fixture = _write(tmp_path, "rel.json", {"releases": RELEASES_FIXTURE})
    env = {"GH_FIXTURE": str(fixture)}
    gsv = json.loads(
        _run_extractor(
            "get_source_version", {"source": {"url": RELEASES_URL}}, env_extra=env
        ).stdout
    )
    ext = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": RELEASES_URL}, "source_id": RELEASES_URL},
            env_extra=env,
        ).stdout
    )
    assert gsv["source_version"].startswith("sha256:")
    assert gsv["source_version"] == ext["source_version"]


def test_get_source_version_issues_matches_extract_after_pr_drop(
    tmp_path: Path,
) -> None:
    """Regression: get_source_version applies the same issues→drop-PR
    normalization as extract, so their versions agree (Arm B finding #1)."""
    fixture = _write(tmp_path, "iss.json", {"issues": ISSUES_FIXTURE})
    env = {"GH_FIXTURE": str(fixture)}
    gsv = json.loads(
        _run_extractor(
            "get_source_version", {"source": {"url": ISSUES_URL}}, env_extra=env
        ).stdout
    )
    ext = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": ISSUES_URL}, "source_id": ISSUES_URL},
            env_extra=env,
        ).stdout
    )
    assert gsv["source_version"] == ext["source_version"]


def test_surface_routing_pulls(tmp_path: Path) -> None:
    fixture = _write(
        tmp_path,
        "all.json",
        {"releases": RELEASES_FIXTURE, "pulls": PULLS_FIXTURE},
    )
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": PULLS_URL}, "source_id": PULLS_URL},
            env_extra={"GH_FIXTURE": str(fixture)},
        ).stdout
    )
    assert payload["verdict"] == "ok"
    obs = " ".join(n["observation"] for n in payload["notable"])
    assert "PR #42" in obs
    assert "by alice" in obs


def test_issues_surface_drops_pull_requests(tmp_path: Path) -> None:
    fixture = _write(tmp_path, "iss.json", {"issues": ISSUES_FIXTURE})
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": ISSUES_URL}, "source_id": ISSUES_URL},
            env_extra={"GH_FIXTURE": str(fixture)},
        ).stdout
    )
    assert payload["verdict"] == "ok"
    obs = " ".join(n["observation"] for n in payload["notable"])
    assert "Issue #7" in obs
    assert "#42" not in obs  # the PR masquerading as an issue is dropped


def test_empty_fixture_returns_empty_verdict(tmp_path: Path) -> None:
    fixture = _write(tmp_path, "empty.json", {"releases": []})
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": RELEASES_URL}, "source_id": RELEASES_URL},
            env_extra={"GH_FIXTURE": str(fixture)},
        ).stdout
    )
    assert payload["verdict"] == "empty"
    assert payload["notable"] == []


def test_malformed_fixture_returns_error(tmp_path: Path) -> None:
    fixture = _write(tmp_path, "bad.json", "not json <<<")
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": RELEASES_URL}, "source_id": RELEASES_URL},
            env_extra={"GH_FIXTURE": str(fixture)},
        ).stdout
    )
    assert payload["verdict"] == "error"
    assert "malformed GH_FIXTURE" in payload["notable"][0]["observation"]


def test_non_github_url_returns_error(tmp_path: Path) -> None:
    fixture = _write(tmp_path, "rel.json", {"releases": RELEASES_FIXTURE})
    url = "https://example.com/openai/openai-python"
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": url}, "source_id": url},
            env_extra={"GH_FIXTURE": str(fixture)},
        ).stdout
    )
    assert payload["verdict"] == "error"
    assert "github.com" in payload["notable"][0]["observation"]


def test_missing_url_returns_error() -> None:
    payload = json.loads(
        _run_extractor("extract", {"source": {}, "source_id": "x"}).stdout
    )
    assert payload["verdict"] == "error"


def test_unsupported_surface_url_returns_error(tmp_path: Path) -> None:
    """A /blob file URL must error, not silently poll releases (Arm B #3)."""
    fixture = _write(tmp_path, "rel.json", {"releases": RELEASES_FIXTURE})
    url = f"{REPO_URL}/blob/main/setup.py"
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": url}, "source_id": url},
            env_extra={"GH_FIXTURE": str(fixture)},
        ).stdout
    )
    assert payload["verdict"] == "error"
    assert "github.com" in payload["notable"][0]["observation"]


def test_fixture_missing_surface_key_returns_error(tmp_path: Path) -> None:
    """A typo'd surface key must fail closed, not return empty (Arm B #4)."""
    fixture = _write(tmp_path, "rel.json", {"releases": RELEASES_FIXTURE})
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": PULLS_URL}, "source_id": PULLS_URL},
            env_extra={"GH_FIXTURE": str(fixture)},
        ).stdout
    )
    assert payload["verdict"] == "error"
    assert "pulls" in payload["notable"][0]["observation"]


def _releases_fixture_n(n: int) -> dict:
    return {
        "releases": [
            {
                "tag_name": f"v0.{i}.0",
                "name": f"0.{i}.0",
                "html_url": f"https://github.com/o/r/releases/tag/v0.{i}.0",
                "published_at": "2026-01-01T00:00:00Z",
            }
            for i in range(n)
        ]
    }


def test_truncated_false_at_exactly_max(tmp_path: Path) -> None:
    from research_framework.modules.github.extractor import MAX_ITEMS

    fixture = _write(tmp_path, "max.json", _releases_fixture_n(MAX_ITEMS))
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": RELEASES_URL}, "source_id": RELEASES_URL},
            env_extra={"GH_FIXTURE": str(fixture)},
        ).stdout
    )
    assert payload["verdict"] == "ok"
    assert payload["truncated"] is False


def test_truncated_true_when_over_max(tmp_path: Path) -> None:
    from research_framework.modules.github.extractor import MAX_ITEMS

    fixture = _write(tmp_path, "over.json", _releases_fixture_n(MAX_ITEMS + 1))
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": RELEASES_URL}, "source_id": RELEASES_URL},
            env_extra={"GH_FIXTURE": str(fixture)},
        ).stdout
    )
    assert payload["verdict"] == "ok"
    assert payload["truncated"] is True


# ---------------------------------------------------------------------------
# Extractor — GH_BIN (real subprocess path, fake gh binary)
# ---------------------------------------------------------------------------


def test_extract_via_fake_gh_bin(tmp_path: Path) -> None:
    fake_gh = _write_fake_gh(tmp_path, api_stdout=json.dumps(RELEASES_FIXTURE))
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": RELEASES_URL}, "source_id": RELEASES_URL},
            env_extra={"GH_BIN": str(fake_gh)},
        ).stdout
    )
    assert payload["verdict"] == "ok"
    assert payload["notable"]
    # The real subprocess path ran AND built the right surface endpoint.
    recorded = (tmp_path / "fake_gh.py.argv").read_text(encoding="utf-8")
    assert "repos/openai/openai-python/releases" in recorded


def test_fake_gh_bin_routes_pulls_endpoint(tmp_path: Path) -> None:
    fake_gh = _write_fake_gh(tmp_path, api_stdout=json.dumps(PULLS_FIXTURE))
    json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": PULLS_URL}, "source_id": PULLS_URL},
            env_extra={"GH_BIN": str(fake_gh)},
        ).stdout
    )
    recorded = (tmp_path / "fake_gh.py.argv").read_text(encoding="utf-8")
    assert "repos/openai/openai-python/pulls" in recorded


def test_gh_nonzero_exit_returns_error(tmp_path: Path) -> None:
    fake_gh = _write_fake_gh(tmp_path, api_stdout="boom", api_exit=1)
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": RELEASES_URL}, "source_id": RELEASES_URL},
            env_extra={"GH_BIN": str(fake_gh)},
        ).stdout
    )
    assert payload["verdict"] == "error"
    assert "gh api exited" in payload["notable"][0]["observation"]


def test_gh_binary_missing_returns_error(tmp_path: Path) -> None:
    missing = tmp_path / "definitely-not-gh"
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": RELEASES_URL}, "source_id": RELEASES_URL},
            env_extra={"GH_BIN": str(missing)},
        ).stdout
    )
    assert payload["verdict"] == "error"
    assert "gh" in payload["notable"][0]["observation"].lower()


# ---------------------------------------------------------------------------
# Signal payload conforms to spec-020 schema
# ---------------------------------------------------------------------------


def test_payload_validates_against_signal_schema(tmp_path: Path) -> None:
    pytest.importorskip("jsonschema", reason="jsonschema not installed")
    import jsonschema  # type: ignore

    schema_path = (
        REPO_ROOT
        / "specs"
        / "020-code-bridge"
        / "contracts"
        / "signal-payload.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    fixture = _write(tmp_path, "rel.json", {"releases": RELEASES_FIXTURE})
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": RELEASES_URL}, "source_id": RELEASES_URL},
            env_extra={"GH_FIXTURE": str(fixture)},
        ).stdout
    )
    jsonschema.validate(payload, schema)


# ---------------------------------------------------------------------------
# Regression: code/github trigger boundary (spec-020 amendment 2026-06-08)
# ---------------------------------------------------------------------------


def test_github_url_routes_to_github_not_code() -> None:
    code = parse_manifest(MODULES_ROOT / "code" / "manifest.yaml")
    github = parse_manifest(MODULES_ROOT / "github" / "manifest.yaml")
    # Discovery orders "code" before "github" (lexicographic). The registry is
    # first-match-wins, so this is the realistic ordering that would have let
    # the old `code` url_pattern shadow the github module.
    registry = build_trigger_registry([code, github])
    assert registry.match(PULLS_URL)[0] == "github"
    assert registry.match(REPO_URL)[0] == "github"


def test_code_manifest_has_no_remote_url_trigger() -> None:
    code = parse_manifest(MODULES_ROOT / "code" / "manifest.yaml")
    url_triggers = [t for t in code.triggers if t.get("type") == "url_pattern"]
    assert url_triggers == [], (
        "code module must NOT claim remote URLs — those route to `github` "
        "(spec-020 amendment, Session 2026-06-08)"
    )
