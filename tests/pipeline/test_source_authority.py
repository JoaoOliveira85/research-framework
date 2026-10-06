"""Tests for src/research_framework/pipeline/source_authority.py (spec 053 T006/D4).

The resolver replaces regex URL-guessing with a deterministic
`citation → source_id → owning data_source → role` lookup, reusing spec-020
`walk_modules` + `load_module_sources`.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from research_framework.pipeline.source_authority import (
    build_source_role_index,
    derive_trunk_dict,
    resolve_role,
)
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    RepoEnumeration,
    ScopeConfig,
    SpecConfig,
)
from tests._helpers.fake_module import write_fake_preflight


def _spec(data_sources: list[DataSourceConfig]) -> SpecConfig:
    return SpecConfig(
        name="s",
        location=Path("/tmp/s"),
        owner="o",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[NoteTypeConfig(name="concept", description="d", folder="f")],
        data_sources=data_sources,
        search_dimensions=["domain"],
        coverage_targets=CoverageTargets(
            categories=[CoverageCategory(name="c", note_type="concept", target_count=1)]
        ),
        budget=BudgetConfig(),
    )


def _write_module(
    vault_dir: Path,
    name: str,
    *,
    kinds: dict[str, list[dict]],
    source_id_from: dict[str, str] | None = None,
) -> None:
    mod = vault_dir / "modules" / name
    mod.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": "0.1.0",
        "description": f"{name} module",
        "triggers": [],
        "entry_point": "extractor.py",
        "schema_examples": "{}",
        "preflight": {"entry_point": "preflight.py"},
    }
    if source_id_from:
        manifest["source_id_from"] = source_id_from
    (mod / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (mod / "sources.yaml").write_text(yaml.safe_dump(kinds), encoding="utf-8")
    write_fake_preflight(mod)


class TestCodeRepoOwnership:
    def test_repo_url_and_local_path_resolve_to_owning_role(
        self, tmp_path: Path
    ) -> None:
        spec = _spec(
            [
                DataSourceConfig(
                    name="GitHub repos",
                    type="internal",
                    priority=1,
                    role="behaviour",
                    repos=[
                        RepoEnumeration(
                            name="OEHK",
                            url="https://github.com/acme-corp/oehk-service",
                            local_path="/Users/me/src/oehk-service",
                        )
                    ],
                ),
                DataSourceConfig(
                    name="Confluence", type="external", priority=2, role="intent"
                ),
            ]
        )
        index = build_source_role_index(spec, tmp_path)
        assert (
            resolve_role("https://github.com/acme-corp/oehk-service", index)
            == "behaviour"
        )
        assert resolve_role("/Users/me/src/oehk-service", index) == "behaviour"

    def test_deep_code_path_resolves_via_repo_signature(self, tmp_path: Path) -> None:
        """A citation pointing *inside* a repo (deep path) resolves to the
        repo's owning role by segment-containment, not just exact source_id —
        this is what preserves the pre-053 `^https://github.com/` behaviour."""
        spec = _spec(
            [
                DataSourceConfig(
                    name="GitHub repos",
                    type="internal",
                    priority=1,
                    role="behaviour",
                    repos=[
                        RepoEnumeration(
                            name="OEHK",
                            url="https://github.com/acme-corp/oehk-service",
                        )
                    ],
                )
            ]
        )
        index = build_source_role_index(spec, tmp_path)
        # github deep path and a local clone path both contain the (org, repo)
        # signature → both resolve to the repo's role.
        assert (
            resolve_role("https://github.com/acme-corp/oehk-service/src/app.py", index)
            == "behaviour"
        )
        assert (
            resolve_role("file:///srv/acme-corp/oehk-service/application.yml", index)
            == "behaviour"
        )

    def test_path_in_a_different_repo_does_not_resolve(self, tmp_path: Path) -> None:
        spec = _spec(
            [
                DataSourceConfig(
                    name="GitHub repos",
                    type="internal",
                    priority=1,
                    role="behaviour",
                    repos=[
                        RepoEnumeration(
                            name="OEHK",
                            url="https://github.com/acme-corp/oehk-service",
                        )
                    ],
                )
            ]
        )
        index = build_source_role_index(spec, tmp_path)
        assert (
            resolve_role("https://github.com/acme-corp/some-other-service/x.py", index)
            is None
        )

    def test_unknown_citation_resolves_to_none(self, tmp_path: Path) -> None:
        spec = _spec(
            [
                DataSourceConfig(
                    name="GitHub repos",
                    type="internal",
                    priority=1,
                    role="behaviour",
                    repos=[
                        RepoEnumeration(name="X", url="https://github.com/acme-corp/x")
                    ],
                )
            ]
        )
        index = build_source_role_index(spec, tmp_path)
        assert resolve_role("https://example.com/unrelated", index) is None


class TestDeriveTrunkDict:
    def test_unique_minimum_priority(self) -> None:
        ds = [
            {"name": "GitHub", "priority": 1, "role": "behaviour"},
            {"name": "Confluence", "priority": 2, "role": "intent"},
        ]
        assert derive_trunk_dict(ds)["name"] == "GitHub"

    def test_tie_returns_none(self) -> None:
        ds = [
            {"name": "A", "priority": 1, "role": "behaviour"},
            {"name": "B", "priority": 1, "role": "intent"},
        ]
        assert derive_trunk_dict(ds) is None

    def test_empty_returns_none(self) -> None:
        assert derive_trunk_dict([]) is None


class TestModuleOwnership:
    def test_module_source_id_inherits_matching_data_source_role(
        self, tmp_path: Path
    ) -> None:
        """A module's enumerated source_ids inherit the role of the spec
        data_source whose name slugifies to the module name (Reddit→reddit)."""
        _write_module(
            tmp_path,
            "reddit",
            kinds={"posts": [{"url": "https://reddit.com/r/ml/abc"}]},
            source_id_from={"posts": "url"},
        )
        spec = _spec(
            [
                DataSourceConfig(
                    name="Journals", type="external", priority=1, role="domain"
                ),
                DataSourceConfig(
                    name="Reddit", type="external", priority=3, role="domain"
                ),
            ]
        )
        index = build_source_role_index(spec, tmp_path)
        assert resolve_role("https://reddit.com/r/ml/abc", index) == "domain"

    def test_module_without_matching_data_source_is_unmapped(
        self, tmp_path: Path
    ) -> None:
        _write_module(
            tmp_path,
            "hackernews",
            kinds={"posts": [{"url": "https://news.ycombinator.com/item?id=1"}]},
            source_id_from={"posts": "url"},
        )
        # spec has no data_source named hackernews
        spec = _spec(
            [
                DataSourceConfig(
                    name="GitHub repos", type="internal", priority=1, role="behaviour"
                )
            ]
        )
        index = build_source_role_index(spec, tmp_path)
        assert resolve_role("https://news.ycombinator.com/item?id=1", index) is None

    def test_slug_collision_first_data_source_wins(self, tmp_path: Path) -> None:
        """Two data_sources slugifying to the same module name: first declared wins."""
        _write_module(
            tmp_path,
            "reddit",
            kinds={"posts": [{"url": "https://reddit.com/r/test/post"}]},
            source_id_from={"posts": "url"},
        )
        spec = _spec(
            [
                DataSourceConfig(
                    name="Reddit", type="external", priority=1, role="domain"
                ),
                DataSourceConfig(
                    name="reddit", type="external", priority=3, role="intent"
                ),
            ]
        )
        index = build_source_role_index(spec, tmp_path)
        assert resolve_role("https://reddit.com/r/test/post", index) == "domain"
