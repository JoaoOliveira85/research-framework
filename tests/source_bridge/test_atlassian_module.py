"""Atlassian module contract tests (Tier-2 / spec 060, governed by spec 020).

Cover the module assets at ``src/research_framework/modules/atlassian/``:

1. Manifest parses + validates + declares the atlassian url trigger, the
   mandatory ``authentication.env_vars`` and the two ``source_id_from`` kinds.
2. The extractor honours the spec-020 stdin/stdout JSON contract for both Jira
   and Confluence surfaces, hermetically via ``ATLASSIAN_API_FIXTURE``.
3. URL routing: jira project / browse / JQL → Jira; ``/wiki/spaces`` → Confluence.
4. **Key-leak sentinels**: ``ATLASSIAN_EMAIL`` + ``ATLASSIAN_API_TOKEN`` never
   appear in stdout/stderr/payload; the auth header is base64 (not plaintext).
5. The emitted ``SignalPayload`` validates against ``signal-payload.schema.json``.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from research_framework.pipeline.source_bridge.discovery import parse_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = REPO_ROOT / "src" / "research_framework" / "modules" / "atlassian"

SITE = "example.atlassian.net"
JIRA_PROJECT_URL = f"https://{SITE}/jira/projects/PROJ"
JIRA_BROWSE_URL = f"https://{SITE}/browse/PROJ-123"
JIRA_JQL_URL = f"https://{SITE}/issues/?jql=project%3DPROJ"
CONFLUENCE_URL = f"https://{SITE}/wiki/spaces/ENG"

SENTINEL_EMAIL = "leak-email@example.com"
SENTINEL_TOKEN = "sentinel-token-do-not-leak-98765"

JIRA_FIXTURE = {
    "issues": [
        {
            "key": "PROJ-101",
            "fields": {
                "summary": "Tighten order cohort drift",
                "status": {"name": "In Progress"},
                "updated": "2026-02-10T12:00:00.000+0000",
                "assignee": {"displayName": "Alice Dev"},
            },
        },
        {
            "key": "PROJ-99",
            "fields": {
                "summary": "Add fingerprint variant doc",
                "status": {"name": "Done"},
                "updated": "2026-02-01T09:00:00.000+0000",
                "assignee": None,
            },
        },
    ]
}

CONFLUENCE_FIXTURE = {
    "results": [
        {
            "id": "12345",
            "title": "Cohort Drift Runbook",
            "version": {"number": 7, "when": "2026-02-09T08:00:00.000Z"},
            "_links": {"webui": "/spaces/ENG/pages/12345/Cohort+Drift+Runbook"},
        }
    ]
}


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
    for key in ("ATLASSIAN_API_FIXTURE", "ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN"):
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


# ---------------------------------------------------------------------------
# URL routing (pure function — pins the fail-closed / no-silent-broadening rules)
# ---------------------------------------------------------------------------


def test_parse_source_routing() -> None:
    from research_framework.modules.atlassian.extractor import _parse_source

    # Jira: project / browse → project poll
    assert _parse_source(JIRA_PROJECT_URL) == (
        "jira",
        SITE,
        "project = PROJ ORDER BY updated DESC",
    )
    assert _parse_source(JIRA_BROWSE_URL) == (
        "jira",
        SITE,
        "project = PROJ ORDER BY updated DESC",
    )
    # Jira: an explicit ?jql= wins over the enclosing project (regression: the
    # software/c/projects/.../issues navigator URL used to drop the jql).
    nav = f"https://{SITE}/jira/software/c/projects/PROJ/issues?jql=project%3DPROJ%20AND%20status%3DDone"
    assert _parse_source(nav) == ("jira", SITE, "project=PROJ AND status=Done")
    short = f"https://{SITE}/jira/issues/?jql=assignee%3Dme"
    assert _parse_source(short) == ("jira", SITE, "assignee=me")
    # Confluence: space root → space poll; deep page URL → that page only.
    assert _parse_source(CONFLUENCE_URL) == (
        "confluence",
        SITE,
        'space = "ENG" ORDER BY lastmodified DESC',
    )
    page = f"https://{SITE}/wiki/spaces/DOCS/pages/111/Some+Page"
    assert _parse_source(page) == ("confluence", SITE, "id = 111")
    # Unsupported / unparseable → None (cmd_extract turns this into a loud error).
    assert _parse_source(f"https://{SITE}/jira/dashboards/10000") is None
    assert _parse_source(f"https://{SITE}/wiki/home") is None
    assert _parse_source("https://example.com/jira/projects/PROJ") is None
    assert _parse_source("ftp://x/y") is None


# ---------------------------------------------------------------------------
# Manifest + asset contracts
# ---------------------------------------------------------------------------


def test_manifest_loads_and_declares_identity() -> None:
    raw = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    assert raw["name"] == "atlassian"
    assert raw["entry_point"] == "extractor.py"
    assert raw["authentication"]["env_vars"] == [
        "ATLASSIAN_EMAIL",
        "ATLASSIAN_API_TOKEN",
    ]


def test_manifest_validates_via_discovery_parser() -> None:
    manifest = parse_manifest(_module_path("manifest.yaml"))
    assert manifest.name == "atlassian"
    assert manifest.source_id_from.get("jira_projects") == "url"
    assert manifest.source_id_from.get("confluence_spaces") == "url"
    assert manifest.authentication is not None
    assert manifest.authentication.env_vars == [
        "ATLASSIAN_EMAIL",
        "ATLASSIAN_API_TOKEN",
    ]


def test_manifest_conforms_to_json_schema() -> None:
    pytest.importorskip("jsonschema", reason="jsonschema not installed")
    import jsonschema  # type: ignore

    schema = json.loads(
        (
            REPO_ROOT
            / "specs"
            / "020-code-bridge"
            / "contracts"
            / "manifest.schema.json"
        ).read_text(encoding="utf-8")
    )
    data = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)


def test_manifest_trigger_matches_atlassian_only() -> None:
    import re

    raw = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    patterns = [t["pattern"] for t in raw["triggers"] if t["type"] == "url_pattern"]
    rx = re.compile("|".join(f"(?:{p})" for p in patterns))
    assert rx.search(JIRA_PROJECT_URL)
    assert rx.search(CONFLUENCE_URL)
    assert not rx.search("https://example.com/wiki/spaces/ENG")


def test_assets_ship() -> None:
    template = yaml.safe_load(
        _module_path("sources.yaml.template").read_text(encoding="utf-8")
    )
    assert "jira_projects" in template
    assert "confluence_spaces" in template
    assert _module_path("few-shot.md").read_text(encoding="utf-8").count("```") >= 2
    assert _module_path("README.md").exists()


# ---------------------------------------------------------------------------
# Extractor — Jira surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [JIRA_PROJECT_URL, JIRA_BROWSE_URL, JIRA_JQL_URL])
def test_jira_urls_extract_issues(tmp_path: Path, url: str) -> None:
    fixture = _write(tmp_path, "jira.json", JIRA_FIXTURE)
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": url}, "source_id": url},
            env_extra={"ATLASSIAN_API_FIXTURE": str(fixture)},
        ).stdout
    )
    assert payload["module"] == "atlassian"
    assert payload["verdict"] == "ok"
    assert payload["source_version"].startswith("sha256:")
    obs = " ".join(n["observation"] for n in payload["notable"])
    assert "PROJ-101" in obs
    assert "In Progress" in obs


def test_confluence_url_extracts_pages(tmp_path: Path) -> None:
    fixture = _write(tmp_path, "conf.json", CONFLUENCE_FIXTURE)
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": CONFLUENCE_URL}, "source_id": CONFLUENCE_URL},
            env_extra={"ATLASSIAN_API_FIXTURE": str(fixture)},
        ).stdout
    )
    assert payload["verdict"] == "ok"
    obs = " ".join(n["observation"] for n in payload["notable"])
    assert "Cohort Drift Runbook" in obs
    assert f"https://{SITE}/wiki/spaces/ENG/pages/12345" in obs


def test_combined_fixture_routes_by_family(tmp_path: Path) -> None:
    combined = {"jira": JIRA_FIXTURE, "confluence": CONFLUENCE_FIXTURE}
    fixture = _write(tmp_path, "both.json", combined)
    jira = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": JIRA_PROJECT_URL}, "source_id": JIRA_PROJECT_URL},
            env_extra={"ATLASSIAN_API_FIXTURE": str(fixture)},
        ).stdout
    )
    conf = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": CONFLUENCE_URL}, "source_id": CONFLUENCE_URL},
            env_extra={"ATLASSIAN_API_FIXTURE": str(fixture)},
        ).stdout
    )
    assert "PROJ-101" in " ".join(n["observation"] for n in jira["notable"])
    assert "Cohort Drift" in " ".join(n["observation"] for n in conf["notable"])


def test_get_source_version_matches_extract(tmp_path: Path) -> None:
    fixture = _write(tmp_path, "jira.json", JIRA_FIXTURE)
    env = {"ATLASSIAN_API_FIXTURE": str(fixture)}
    gsv = json.loads(
        _run_extractor(
            "get_source_version", {"source": {"url": JIRA_PROJECT_URL}}, env_extra=env
        ).stdout
    )
    ext = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": JIRA_PROJECT_URL}, "source_id": JIRA_PROJECT_URL},
            env_extra=env,
        ).stdout
    )
    assert gsv["source_version"] == ext["source_version"]


def test_get_source_version_matches_extract_confluence(tmp_path: Path) -> None:
    """Parity must hold for BOTH families — Confluence uses a different identity
    (page id + version) than Jira, so it gets its own regression lock."""
    fixture = _write(tmp_path, "conf.json", CONFLUENCE_FIXTURE)
    env = {"ATLASSIAN_API_FIXTURE": str(fixture)}
    gsv = json.loads(
        _run_extractor(
            "get_source_version", {"source": {"url": CONFLUENCE_URL}}, env_extra=env
        ).stdout
    )
    ext = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": CONFLUENCE_URL}, "source_id": CONFLUENCE_URL},
            env_extra=env,
        ).stdout
    )
    assert gsv["source_version"] == ext["source_version"]
    assert ext["source_version"].startswith("sha256:")


def test_empty_jira_returns_empty_verdict(tmp_path: Path) -> None:
    fixture = _write(tmp_path, "empty.json", {"issues": []})
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": JIRA_PROJECT_URL}, "source_id": JIRA_PROJECT_URL},
            env_extra={"ATLASSIAN_API_FIXTURE": str(fixture)},
        ).stdout
    )
    assert payload["verdict"] == "empty"
    assert payload["notable"] == []


def test_malformed_fixture_returns_error(tmp_path: Path) -> None:
    fixture = _write(tmp_path, "bad.json", "not json <<<")
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": JIRA_PROJECT_URL}, "source_id": JIRA_PROJECT_URL},
            env_extra={"ATLASSIAN_API_FIXTURE": str(fixture)},
        ).stdout
    )
    assert payload["verdict"] == "error"
    assert "malformed ATLASSIAN_API_FIXTURE" in payload["notable"][0]["observation"]


def test_non_atlassian_url_returns_error(tmp_path: Path) -> None:
    fixture = _write(tmp_path, "jira.json", JIRA_FIXTURE)
    url = "https://example.com/jira/projects/PROJ"
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": url}, "source_id": url},
            env_extra={"ATLASSIAN_API_FIXTURE": str(fixture)},
        ).stdout
    )
    assert payload["verdict"] == "error"
    assert "supported atlassian" in payload["notable"][0]["observation"]


def test_unsupported_atlassian_path_returns_error(tmp_path: Path) -> None:
    """A valid site but an unrecognised surface (dashboard) must error loudly,
    not silently default to polling a project/space (spec-020 lock-step)."""
    fixture = _write(tmp_path, "jira.json", JIRA_FIXTURE)
    url = f"https://{SITE}/jira/dashboards/10000"
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": url}, "source_id": url},
            env_extra={"ATLASSIAN_API_FIXTURE": str(fixture)},
        ).stdout
    )
    assert payload["verdict"] == "error"
    assert "supported atlassian" in payload["notable"][0]["observation"]


def test_missing_credentials_without_fixture_errors() -> None:
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": JIRA_PROJECT_URL}, "source_id": JIRA_PROJECT_URL},
        ).stdout
    )
    assert payload["verdict"] == "error"
    obs = payload["notable"][0]["observation"]
    assert "ATLASSIAN_EMAIL" in obs and "ATLASSIAN_API_TOKEN" in obs


def _jira_fixture_n(n: int) -> dict:
    return {
        "issues": [
            {
                "key": f"PROJ-{i}",
                "fields": {
                    "summary": f"Issue {i}",
                    "status": {"name": "Open"},
                    "updated": "2026-01-01T00:00:00.000+0000",
                },
            }
            for i in range(n)
        ]
    }


def test_truncated_boundary(tmp_path: Path) -> None:
    from research_framework.modules.atlassian.extractor import MAX_ITEMS

    at_max = _write(tmp_path, "max.json", _jira_fixture_n(MAX_ITEMS))
    over = _write(tmp_path, "over.json", _jira_fixture_n(MAX_ITEMS + 1))
    p_max = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": JIRA_PROJECT_URL}, "source_id": JIRA_PROJECT_URL},
            env_extra={"ATLASSIAN_API_FIXTURE": str(at_max)},
        ).stdout
    )
    p_over = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": JIRA_PROJECT_URL}, "source_id": JIRA_PROJECT_URL},
            env_extra={"ATLASSIAN_API_FIXTURE": str(over)},
        ).stdout
    )
    assert p_max["truncated"] is False
    assert p_over["truncated"] is True


# ---------------------------------------------------------------------------
# Jira search endpoint (rc5 regression — Atlassian retired GET /search → 410)
# ---------------------------------------------------------------------------


def test_jira_search_request_targets_new_jql_endpoint() -> None:
    """Jira Cloud retired GET ``/rest/api/3/search`` (HTTP 410 Gone, 2025).
    The request builder must target POST ``/rest/api/3/search/jql`` with a
    JSON body carrying the JQL, the fetch limit, and an explicit field list."""
    from research_framework.modules.atlassian.extractor import (
        _FETCH_LIMIT,
        _jira_search_request,
    )

    url, body = _jira_search_request("example.atlassian.net", "project = PROJ")
    assert url == "https://example.atlassian.net/rest/api/3/search/jql"
    assert "/rest/api/3/search?" not in url  # deprecated GET form is gone
    assert body["jql"] == "project = PROJ"
    assert body["maxResults"] == _FETCH_LIMIT
    assert isinstance(body["fields"], list)
    assert {"summary", "status", "updated"} <= set(body["fields"])


def test_jira_fetch_posts_to_search_jql(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end (network mocked, in-process): the Jira fetch path issues a
    POST to ``/rest/api/3/search/jql`` with a JSON body — not the retired GET
    ``/rest/api/3/search`` that now returns 410 on real Atlassian Cloud."""
    import urllib.request

    from research_framework.modules.atlassian import extractor as ex

    monkeypatch.setenv("ATLASSIAN_EMAIL", "u@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
    monkeypatch.delenv("ATLASSIAN_API_FIXTURE", raising=False)

    captured: dict[str, object] = {}

    class _Resp:
        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *_a: object) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "issues": [
                        {
                            "key": "PROJ-1",
                            "fields": {
                                "summary": "x",
                                "updated": "2026-01-01T00:00:00.000+0000",
                            },
                        }
                    ]
                }
            ).encode("utf-8")

    def _fake_urlopen(req: urllib.request.Request, timeout: float | None = None):
        captured["method"] = req.get_method()
        captured["url"] = req.full_url
        captured["body"] = req.data
        captured["content_type"] = req.get_header("Content-type")
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    items, err = ex._fetch(
        "jira", "example.atlassian.net", "project = PROJ ORDER BY updated DESC"
    )
    assert err is None
    assert items and items[0]["key"] == "PROJ-1"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.atlassian.net/rest/api/3/search/jql"
    assert captured["content_type"] == "application/json"
    body = json.loads(captured["body"].decode("utf-8"))  # type: ignore[union-attr]
    assert body["jql"] == "project = PROJ ORDER BY updated DESC"
    assert {"summary", "status", "updated"} <= set(body["fields"])


# ---------------------------------------------------------------------------
# Key-leak sentinels
# ---------------------------------------------------------------------------


def test_credentials_never_leak_in_output(tmp_path: Path) -> None:
    fixture = _write(tmp_path, "jira.json", JIRA_FIXTURE)
    result = _run_extractor(
        "extract",
        {"source": {"url": JIRA_PROJECT_URL}, "source_id": JIRA_PROJECT_URL},
        env_extra={
            "ATLASSIAN_API_FIXTURE": str(fixture),
            "ATLASSIAN_EMAIL": SENTINEL_EMAIL,
            "ATLASSIAN_API_TOKEN": SENTINEL_TOKEN,
        },
    )
    assert result.returncode == 0
    b64 = base64.b64encode(f"{SENTINEL_EMAIL}:{SENTINEL_TOKEN}".encode()).decode()
    for blob in (result.stdout, result.stderr):
        assert SENTINEL_TOKEN not in blob
        assert SENTINEL_EMAIL not in blob
        assert b64 not in blob


def test_credentials_never_leak_on_error_path(tmp_path: Path) -> None:
    """Creds present + a forced error (malformed fixture, so still hermetic) must
    not echo the email/token/base64 into the error payload or stderr."""
    fixture = _write(tmp_path, "bad.json", "not json <<<")
    result = _run_extractor(
        "extract",
        {"source": {"url": JIRA_PROJECT_URL}, "source_id": JIRA_PROJECT_URL},
        env_extra={
            "ATLASSIAN_API_FIXTURE": str(fixture),
            "ATLASSIAN_EMAIL": SENTINEL_EMAIL,
            "ATLASSIAN_API_TOKEN": SENTINEL_TOKEN,
        },
    )
    assert json.loads(result.stdout)["verdict"] == "error"
    b64 = base64.b64encode(f"{SENTINEL_EMAIL}:{SENTINEL_TOKEN}".encode()).decode()
    for blob in (result.stdout, result.stderr):
        assert SENTINEL_TOKEN not in blob
        assert SENTINEL_EMAIL not in blob
        assert b64 not in blob


def test_auth_header_is_base64_not_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_framework.modules.atlassian.extractor import _auth_header

    monkeypatch.setenv("ATLASSIAN_EMAIL", SENTINEL_EMAIL)
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", SENTINEL_TOKEN)
    header = _auth_header()
    assert header is not None
    assert header.startswith("Basic ")
    assert SENTINEL_TOKEN not in header  # encoded, not plaintext
    decoded = base64.b64decode(header.split(" ", 1)[1]).decode()
    assert decoded == f"{SENTINEL_EMAIL}:{SENTINEL_TOKEN}"


# ---------------------------------------------------------------------------
# Signal payload conforms to spec-020 schema
# ---------------------------------------------------------------------------


def test_payload_validates_against_signal_schema(tmp_path: Path) -> None:
    pytest.importorskip("jsonschema", reason="jsonschema not installed")
    import jsonschema  # type: ignore

    schema = json.loads(
        (
            REPO_ROOT
            / "specs"
            / "020-code-bridge"
            / "contracts"
            / "signal-payload.schema.json"
        ).read_text(encoding="utf-8")
    )
    fixture = _write(tmp_path, "jira.json", JIRA_FIXTURE)
    payload = json.loads(
        _run_extractor(
            "extract",
            {"source": {"url": JIRA_PROJECT_URL}, "source_id": JIRA_PROJECT_URL},
            env_extra={"ATLASSIAN_API_FIXTURE": str(fixture)},
        ).stdout
    )
    jsonschema.validate(payload, schema)


def test_parse_source_decodes_the_jql_exactly_once() -> None:
    """``parse_qs`` already percent-decodes; a second ``unquote_plus`` turned the
    literal ``+`` of ``C++`` into spaces and silently changed the query."""
    from research_framework.modules.atlassian.extractor import _parse_source

    url = f"https://{SITE}/issues/?jql=text%20~%20%22C%2B%2B%22%20AND%20summary%20~%20%22100%25%22"
    assert _parse_source(url) == ("jira", SITE, 'text ~ "C++" AND summary ~ "100%"')
