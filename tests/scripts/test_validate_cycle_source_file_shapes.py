"""v0.2.27 regression tests for ``validate_cycle.py`` source_file matching.

Background (the fifth seam bug in the 0.2.21 → 0.2.26 chain): the user's
cycle-3 scout report was aborted with:

    ERROR: topic source_file not under enumerated repo:
           'acme-corp/backend/oebh-service/README.md' (id=CT-3-004)

The spec lists every repo with both representations of the same on-disk
location:

    - name: oebh-service
      url: https://github.com/acme-corp/oebh-service        # canonical
      local_path: /Users/dev/acme-corp/backend/oebh-service # on-disk

The scout-prompt template renders BOTH to the scout (URL in the heading,
local_path in the access blurb). Naturally, the scout sometimes copied
paths in the URL shape (``acme-corp/oebh-service/...``) and
sometimes in the local-path shape (``acme-corp/backend/oebh-service/...``).
v0.2.26 ``validate_cycle.py`` only knew the URL shape and rejected the
local-path shape with the substring check
``key in source_file`` (which failed because
``"acme-corp/oebh-service"`` is NOT a substring of
``"acme-corp/backend/oebh-service/README.md"``).

v0.2.27 builds repo signatures from BOTH the URL **and** the local_path
tail, matches via contiguous-subsequence on path segments, and accepts
either shape. Truly-wrong-repo paths are still rejected.

These tests lock the new contract at two layers:

1. Unit-level: the new helpers ``_repo_match_signatures`` and
   ``_source_file_matches_repo`` get tested directly so a future refactor
   can't silently regress the matching semantics.
2. Subprocess-level: a vault staged with the user's exact spec shape
   (URL + on-disk-with-backend-segment) gets validated end-to-end against
   a scout report that uses the local-path shape. Pre-fix this was the
   aborting case; post-fix it must return exit 0.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "validate_cycle.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_validate_cycle_module():
    """Load ``scripts/validate_cycle.py`` as a module so we can unit-test the
    new helpers directly. The script isn't on ``sys.path`` (it lives under
    ``scripts/`` rather than ``src/``) so we use the
    ``importlib.util.spec_from_file_location`` incantation rather than
    ``import scripts.validate_cycle``.

    We register the module in ``sys.modules`` before ``exec_module`` runs so
    that ``@dataclass`` (which walks ``sys.modules[cls.__module__]`` while
    deciding whether ``KW_ONLY`` is a type) can find it. Without this,
    decorating any dataclass in the script raises
    ``AttributeError: 'NoneType' object has no attribute '__dict__'``.
    """
    module_name = "validate_cycle_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )


def _stage_users_vault(tmp_path: Path) -> Path:
    """Stage a vault whose spec is shaped exactly like the user's
    ``reference-vault-v4`` spec: every repo has BOTH a GitHub URL and a
    ``local_path`` that includes an extra ``backend/`` wrapper directory.
    """
    vault = tmp_path / "v"
    (vault / "_pipeline" / "cycles").mkdir(parents=True)
    (vault / "data_vault").mkdir()
    spec_parse = {
        "name": "Reference Vault v4 shape",
        "data_sources": [
            {
                "name": "Local Team Service Repositories",
                "type": "internal",
                "priority": 1,
                "role": "behaviour",
                "required": True,
                "repos": [
                    {
                        "name": "oebh-service",
                        "url": "https://github.com/acme-corp/oebh-service",
                        "local_path": "/Users/dev/acme-corp/backend/oebh-service",
                    },
                    {
                        "name": "oms-service",
                        "url": "https://github.com/acme-corp/oms-service",
                        "local_path": "/Users/dev/acme-corp/backend/oms-service",
                    },
                    {
                        "name": "erp-service",
                        "url": "https://github.com/acme-corp/erp-service",
                        "local_path": "/Users/dev/acme-corp/backend/erp-service",
                    },
                ],
            }
        ],
    }
    (vault / "_pipeline" / "spec-parse.json").write_text(json.dumps(spec_parse))
    return vault


def _write_scout(vault: Path, report: dict, name: str = "cycle-001-scout.json") -> Path:
    path = vault / "_pipeline" / "cycles" / name
    path.write_text(json.dumps(report))
    return path


def _minimum_valid_scout(topics: list[dict]) -> dict:
    """A scout report that satisfies every check EXCEPT the one we're
    targeting (source_file ↔ enumerated-repo matching). Used so that a
    failing matching check is the only reason the validator would abort.
    """
    return {
        "schema_version": "2.0",
        "cycle": 1,
        "phase": "scout",
        "timestamp": "2026-05-17T21:00:00Z",
        "dimensions_covered": [
            "technical",
            "organizational",
            "domain",
            "market",
            "temporal",
        ],
        "topics_from_code": topics,
        "intent_from_confluence": [
            {
                "id": "IT-1-001",
                "parent_code_topic_id": topics[0]["id"],
                "source_url": "https://example.atlassian.net/x",
                "intent_summary": "test intent",
                "intent_type": "description",
            }
        ],
        "topics_found": {
            "new": [
                {
                    "title": "Test Topic",
                    "coverage_category": "services",
                    "proposed_filename": "test_topic.md",
                    "source_code_topic_ids": [topics[0]["id"]],
                    "source_intent_ids": ["IT-1-001"],
                }
            ],
            "existing": [],
            "total": 1,
        },
        "proposed_filenames": ["test_topic.md"],
        # H2 (spec-019 / 0.2.28): sources_consulted is now validated
        # against the spec's required sources. The staged spec lists
        # "Local Team Service Repositories" as required, so the report
        # must name it (or the normalized key) here.
        "sources_consulted": ["Local Team Service Repositories"],
        "access_methods_used": {},
        "termination_condition": None,
        "notes_created": [],
        "unresolved_wikilinks": [],
        "budget_consumed_usd": 0.0,
    }


# ---------------------------------------------------------------------------
# Unit tests — _repo_match_signatures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def vc():
    return _load_validate_cycle_module()


def test_signatures_url_only_emits_url_tuple_only(vc) -> None:
    repos = [{"name": "oebh", "url": "https://github.com/acme-corp/oebh-service"}]
    sigs = vc._repo_match_signatures(repos)
    assert ("acme-corp", "oebh-service") in sigs
    assert len(sigs) == 1


def test_signatures_url_plus_local_path_emits_both_shapes(vc) -> None:
    """The user's actual case: URL says ``acme-corp/oebh-service`` but
    on-disk path has an extra ``backend/`` wrapper. Both signatures must
    be emitted so the scout's choice of shape doesn't matter to the
    validator."""
    repos = [
        {
            "name": "oebh-service",
            "url": "https://github.com/acme-corp/oebh-service",
            "local_path": "/Users/dev/acme-corp/backend/oebh-service",
        }
    ]
    sigs = vc._repo_match_signatures(repos)
    assert ("acme-corp", "oebh-service") in sigs
    assert ("acme-corp", "backend", "oebh-service") in sigs


def test_signatures_skip_local_path_when_no_anchor(vc) -> None:
    """If the local_path doesn't contain the URL's first segment (the
    "org") and no repo name to anchor on, the local-path signature is
    omitted — we never invent a key from raw filesystem prefixes."""
    repos = [
        {
            "name": "oebh-service",
            "url": "https://github.com/acme-corp/oebh-service",
            "local_path": "/tmp/checkouts/some-other-place",
        }
    ]
    sigs = vc._repo_match_signatures(repos)
    assert sigs == [("acme-corp", "oebh-service")]


def test_signatures_deduplicate_when_url_and_local_path_agree(vc) -> None:
    repos = [
        {
            "name": "oebh-service",
            "url": "https://github.com/acme-corp/oebh-service",
            "local_path": "/Users/dev/acme-corp/oebh-service",
        }
    ]
    sigs = vc._repo_match_signatures(repos)
    assert sigs == [("acme-corp", "oebh-service")]


# ---------------------------------------------------------------------------
# Unit tests — _source_file_matches_repo
# ---------------------------------------------------------------------------


def test_match_url_shape_source_file(vc) -> None:
    """v0.2.26 already accepted this — make sure v0.2.27 doesn't break it."""
    sigs = [("acme-corp", "oebh-service")]
    assert vc._source_file_matches_repo("acme-corp/oebh-service/README.md", sigs)


def test_match_local_path_shape_source_file_the_fifth_seam_bug_fix(vc) -> None:
    """THE bug: scout emits a path with the local-path-shape extra
    ``backend/`` segment, and v0.2.26 rejected it. v0.2.27 must accept it
    when the local-path signature is present."""
    sigs = [
        ("acme-corp", "oebh-service"),
        ("acme-corp", "backend", "oebh-service"),
    ]
    assert vc._source_file_matches_repo(
        "acme-corp/backend/oebh-service/README.md", sigs
    )


def test_match_file_uri_with_absolute_local_path(vc) -> None:
    """A scout that emits a ``file:///`` URL pointing at the on-disk
    checkout location must still match — used to be supported by the
    "substring in source_file" path and we mustn't lose it."""
    sigs = [
        ("acme-corp", "oebh-service"),
        ("acme-corp", "backend", "oebh-service"),
    ]
    assert vc._source_file_matches_repo(
        "file:///Users/dev/acme-corp/backend/oebh-service/README.md", sigs
    )


def test_reject_wrong_repo_under_known_org(vc) -> None:
    """The whole point of this check: catch the scout hallucinating a
    repo that's not in the enumerated list. ``some-other-service`` under
    the same org should still fail even with the more lenient matcher."""
    sigs = [
        ("acme-corp", "oebh-service"),
        ("acme-corp", "backend", "oebh-service"),
    ]
    assert not vc._source_file_matches_repo(
        "acme-corp/some-other-service/README.md", sigs
    )


def test_reject_completely_foreign_path(vc) -> None:
    sigs = [
        ("acme-corp", "oebh-service"),
        ("acme-corp", "backend", "oebh-service"),
    ]
    assert not vc._source_file_matches_repo(
        "some-other-org/some-other-repo/README.md", sigs
    )


def test_reject_repo_name_alone_without_org_context(vc) -> None:
    """A bare ``oebh-service/README.md`` (no ``acme-corp`` segment)
    must NOT match — otherwise a malicious / hallucinated repo name from
    a third party would slip through."""
    sigs = [
        ("acme-corp", "oebh-service"),
        ("acme-corp", "backend", "oebh-service"),
    ]
    assert not vc._source_file_matches_repo("oebh-service/README.md", sigs)


def test_reject_empty_source_file(vc) -> None:
    sigs = [("acme-corp", "oebh-service")]
    assert not vc._source_file_matches_repo("", sigs)


def test_reject_when_no_signatures_configured(vc) -> None:
    """If the spec yields zero signatures we can't make any claim about
    repo ownership; the caller is expected to skip the check entirely.
    The matcher should still return False (defensive)."""
    assert not vc._source_file_matches_repo("anything/at/all.md", [])


# ---------------------------------------------------------------------------
# End-to-end subprocess test — reproduces the user's cycle-3 abort and
# asserts v0.2.27 lets it through.
# ---------------------------------------------------------------------------


def test_subprocess_scout_with_local_path_shape_source_files_accepted(
    tmp_path: Path,
) -> None:
    """The user's cycle-3 abort, end-to-end:

    Spec has ``url`` (``acme-corp/<repo>``) + ``local_path``
    (``/Users/.../acme-corp/backend/<repo>``). Scout emits
    ``source_file`` with the local-path shape including ``backend/``.
    Pre-v0.2.27 the validator aborted with "not under enumerated repo".
    Post-v0.2.27 the validator accepts it.
    """
    vault = _stage_users_vault(tmp_path)
    topics = [
        {
            "id": "CT-1-001",
            "topic_type": "service",
            "source_file": "acme-corp/backend/oebh-service/README.md",
            "source_snippet": "lines 20-24, 49-57, 68-75",
            "proposed_filename": "order_engine_bets_handler_service.md",
        },
        {
            "id": "CT-1-002",
            "topic_type": "service",
            "source_file": "acme-corp/backend/oms-service/ARCHITECTURE.md",
            "source_snippet": "lines 5-9",
            "proposed_filename": "customer_bet_risk_service.md",
        },
    ]
    report_path = _write_scout(vault, _minimum_valid_scout(topics))
    result = _run(str(report_path), "--vault", str(vault))
    assert result.returncode == 0, (
        "v0.2.27 regression: local-path-shape source_file must validate. "
        f"stdout/stderr:\n{result.stdout}\n{result.stderr}"
    )


def test_subprocess_scout_with_url_shape_source_files_still_accepted(
    tmp_path: Path,
) -> None:
    """Backwards-compat guard: the original URL shape that v0.2.26 already
    accepted must continue to work after the v0.2.27 changes.
    """
    vault = _stage_users_vault(tmp_path)
    topics = [
        {
            "id": "CT-1-001",
            "topic_type": "service",
            "source_file": "acme-corp/oebh-service/README.md",
            "source_snippet": "lines 1-10",
            "proposed_filename": "oebh.md",
        }
    ]
    report_path = _write_scout(vault, _minimum_valid_scout(topics))
    result = _run(str(report_path), "--vault", str(vault))
    assert result.returncode == 0, (
        "v0.2.27 must not regress the URL-shape acceptance that worked "
        f"in v0.2.26. stdout/stderr:\n{result.stdout}\n{result.stderr}"
    )


def test_subprocess_mixed_shape_scout_accepted(tmp_path: Path) -> None:
    """The realistic state of the user's cycle-3 scout: some topics in URL
    shape, some in local-path shape, in a single report. Both must pass.
    """
    vault = _stage_users_vault(tmp_path)
    topics = [
        {
            "id": "CT-1-001",
            "topic_type": "service",
            "source_file": "acme-corp/oms-service/ARCHITECTURE.md",
            "source_snippet": "lines 5-9",
            "proposed_filename": "oms.md",
        },
        {
            "id": "CT-1-002",
            "topic_type": "service",
            "source_file": "acme-corp/backend/oebh-service/README.md",
            "source_snippet": "lines 20-24",
            "proposed_filename": "oebh.md",
        },
    ]
    report_path = _write_scout(vault, _minimum_valid_scout(topics))
    result = _run(str(report_path), "--vault", str(vault))
    assert result.returncode == 0, (
        f"Mixed-shape scout must validate. stdout/stderr:\n{result.stdout}\n{result.stderr}"
    )


def test_subprocess_scout_with_truly_wrong_repo_still_aborts(
    tmp_path: Path,
) -> None:
    """Backwards-compat guard the OTHER way: the validator must STILL
    reject a source_file that doesn't map onto any enumerated repo
    (different org, or hallucinated repo name). v0.2.27's leniency only
    extends to ``url`` ↔ ``local_path`` ambiguity — it must not become a
    no-op.
    """
    vault = _stage_users_vault(tmp_path)
    topics = [
        {
            "id": "CT-1-001",
            "topic_type": "service",
            "source_file": "acme-corp/some-hallucinated-service/README.md",
            "source_snippet": "lines 1-10",
            "proposed_filename": "hallucinated.md",
        }
    ]
    report_path = _write_scout(vault, _minimum_valid_scout(topics))
    result = _run(str(report_path), "--vault", str(vault))
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "not under enumerated repo" in combined
    assert "some-hallucinated-service" in combined
