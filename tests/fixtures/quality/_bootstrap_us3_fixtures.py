"""One-shot bootstrap for spec-022 US3 quality fixtures (T044–T054).

Regenerates the committed quality fixtures. Spec 026 US3 / SC-006: this is a
DRY RUN by default — it only prints which fixtures it *would* rewrite. Pass
``--force`` to actually mutate the tracked tree (with a ``y/N`` confirm on a
TTY). This stops an accidental ``python _bootstrap_us3_fixtures.py`` from
silently dirtying the source-of-truth fixtures.

Run from repo root:
  python tests/fixtures/quality/_bootstrap_us3_fixtures.py            # dry run
  python tests/fixtures/quality/_bootstrap_us3_fixtures.py --force    # rewrite
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

from tests._helpers.vault_factory import build_quality_fixture

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "quality"

TIMESTAMP_FMT = "2026-05-17T00:00:{cycle:02d}Z"


def _note_body(
    *,
    note_type: str,
    title: str,
    category: str,
    cycle: int,
    sections: list[str],
) -> str:
    fm = {
        "type": note_type,
        "template_version": "1.0.0",
        "coverage_category": category,
        "summary": f"Synthetic {note_type} note for quality harness fixture ({title}).",
        "related": [],
        "source_urls": [f"https://synthetic.test/quality/{category}/{cycle}"],
        "lifecycle": {"created_at_cycle": cycle},
    }
    import yaml

    lines = [
        "---",
        yaml.safe_dump(fm, sort_keys=False).rstrip(),
        "---",
        "",
        f"# {title}",
    ]
    for sec in sections:
        lines += ["", f"## {sec}", "", f"Lorem ipsum placeholder for {sec} in {title}."]
    return "\n".join(lines) + "\n"


def _scout_report(
    *,
    cycle: int,
    topics_new: list[dict],
    topics_from_code: list[dict],
    sources_consulted: list[str] | dict,
    missing_sources: list[str] | None = None,
) -> dict:
    proposed = [
        t.get("proposed_filename") or f"{t['title'].lower().replace(' ', '-')}.md"
        for t in topics_new
    ]
    report = {
        "schema_version": "2.0",
        "cycle": cycle,
        "phase": "scout",
        "timestamp": TIMESTAMP_FMT.format(cycle=cycle),
        "dimensions_covered": ["technical", "organizational", "domain"],
        "topics_from_code": topics_from_code,
        "intent_from_confluence": [],
        "topics_found": {"new": topics_new, "existing": [], "total": len(topics_new)},
        "proposed_filenames": proposed,
        "sources_consulted": sources_consulted,
        "access_methods_used": {"synthetic": "local"},
        "termination_condition": None,
        "notes_created": [],
        "unresolved_wikilinks": [],
        "budget_consumed_usd": 0.0,
    }
    if missing_sources:
        report["missing_sources"] = missing_sources
        report["gap_substitution_attempted"] = True
    return report


def _code_topic(
    cycle: int, idx: int, *, topic_type: str, title: str, category: str
) -> tuple[dict, dict]:
    slug = title.lower().replace(" ", "-")
    code_id = f"CT-{cycle}-{idx:03d}"
    code_row = {
        "id": code_id,
        "topic_type": topic_type,
        "source_file": f"synthetic/acme/{slug}/README.md",
        "source_snippet": "lines 1-40",
        "proposed_filename": f"{slug}.md",
    }
    new_row = {
        "title": title,
        "coverage_category": category,
        "proposed_filename": f"{slug}.md",
        "discovery": "code-derived",
        "source_code_topic_ids": [code_id],
    }
    return code_row, new_row


def _tech_lite_scout(cycle: int) -> dict:
    pairs = [
        ("service", "Synthetic Order Service", "services"),
        ("service", "Synthetic Payment Service", "services"),
        ("service", "Synthetic Inventory Service", "services"),
        ("service", "Synthetic Notification Service", "services"),
        ("service", "Synthetic Audit Service", "services"),
        ("flow", "Synthetic Checkout Flow", "flows"),
        ("flow", "Synthetic Refund Flow", "flows"),
        ("flow", "Synthetic Settlement Flow", "flows"),
        ("concept", "Synthetic Idempotency Keys", "concepts"),
        ("concept", "Synthetic Saga Orchestration", "concepts"),
        ("concept", "Synthetic Circuit Breaker", "concepts"),
        ("concept", "Synthetic Event Sourcing", "concepts"),
        ("decision", "Synthetic ADR Retry Policy", "decisions"),
        ("decision", "Synthetic ADR Database Choice", "decisions"),
        ("service", "Synthetic Gateway Service", "services"),
        ("concept", "Synthetic Hexagonal Ports", "concepts"),
        ("flow", "Synthetic Webhook Flow", "flows"),
        ("service", "Synthetic Ledger Service", "services"),
    ]
    code_rows, new_rows = [], []
    for i, (tt, title, cat) in enumerate(pairs, start=1):
        c, n = _code_topic(cycle, i, topic_type=tt, title=title, category=cat)
        code_rows.append(c)
        new_rows.append(n)
    return _scout_report(
        cycle=cycle,
        topics_new=new_rows,
        topics_from_code=code_rows,
        sources_consulted=["payment-repo", "order-repo"],
    )


def _source_poor_scout(cycle: int) -> dict:
    """Single-category topics to trip SG-002 when many categories are unfilled."""
    new_rows = [
        {
            "title": f"Gap topic {i} cycle {cycle}",
            "coverage_category": "concepts",
            "proposed_filename": f"gap-topic-{i}-c{cycle}.md",
            "discovery": "gap-substitution",
            "substitution_for": "missing-external-corpus",
        }
        for i in range(1, 18)
    ]
    code_rows = [
        {
            "id": f"CT-{cycle}-{i:03d}",
            "topic_type": "concept",
            "source_file": f"synthetic/gap/topic-{i}.md",
            "source_snippet": "lines 1-5",
            "proposed_filename": row["proposed_filename"],
        }
        for i, row in enumerate(new_rows, start=1)
    ]
    return _scout_report(
        cycle=cycle,
        topics_new=new_rows,
        topics_from_code=code_rows,
        sources_consulted={
            "only-wiki": {"searched": True, "results_count": 0, "pages_read": 0}
        },
        missing_sources=["arxiv-corpus", "oreilly-shelf", "youtube-channel"],
    )


def _source_rich_scout(cycle: int) -> dict:
    categories = [
        ("services", "service", "Curated Service Note"),
        ("flows", "flow", "Curated Flow Note"),
        ("concepts", "concept", "Curated Concept Note"),
        ("decisions", "decision", "Curated Decision Note"),
        ("integrations", "service", "Curated Integration Note"),
    ]
    new_rows, code_rows = [], []
    idx = 0
    for cat, tt, prefix in categories:
        for n in range(1, 4):
            idx += 1
            title = f"{prefix} {n} c{cycle}"
            c, row = _code_topic(cycle, idx, topic_type=tt, title=title, category=cat)
            row["discovery"] = "source-rich"
            code_rows.append(c)
            new_rows.append(row)
    return _scout_report(
        cycle=cycle,
        topics_new=new_rows,
        topics_from_code=code_rows,
        sources_consulted=[
            "official-docs",
            "oreilly-shelf",
            "arxiv-feed",
            "github-org",
            "confluence-space",
        ],
    )


def _note_writer_payload(
    fixture: str,
    cycle: int,
    *,
    reject_fraction: float = 0.0,
) -> dict:
    if fixture == "tech-lite":
        scout = _tech_lite_scout(cycle)
    elif fixture == "source-poor":
        scout = _source_poor_scout(cycle)
    else:
        scout = _source_rich_scout(cycle)

    notes = []
    for row in scout["topics_found"]["new"]:
        cat = row["coverage_category"]
        title = row["title"]
        slug = row["proposed_filename"].replace(".md", "")
        nt = "concept"
        if cat == "services":
            nt, folder, sections = (
                "service",
                "01 - Services",
                ["Overview", "API Surface", "Dependencies", "Related"],
            )
        elif cat == "flows":
            nt, folder, sections = (
                "flow",
                "02 - Flows",
                ["Overview", "Trigger", "Steps", "Failure Modes", "Related"],
            )
        elif cat == "decisions":
            nt, folder, sections = (
                "decision",
                "04 - Decisions",
                ["Context", "Decision", "Consequences", "Related"],
            )
        elif cat == "integrations":
            nt, folder, sections = (
                "service",
                "01 - Services",
                ["Overview", "API Surface", "Dependencies", "Related"],
            )
        else:
            folder, sections = (
                "03 - Concepts",
                ["Overview", "Mechanism", "Trade-offs", "Related"],
            )

        notes.append(
            {
                "relative_path": f"data_vault/{folder}/{slug}.md",
                "body": _note_body(
                    note_type=nt,
                    title=title,
                    category=cat,
                    cycle=cycle,
                    sections=sections,
                ),
            }
        )
    return {
        "batch_topics": [
            {
                "title": r["title"],
                "category": r["coverage_category"],
                "discovery": r.get("discovery"),
            }
            for r in scout["topics_found"]["new"]
        ],
        "notes": notes,
        "verifier_reject_indices": (
            [2, 7] if reject_fraction > 0 and fixture == "source-poor" else []
        ),
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_templates(dst: Path) -> None:
    templates = {
        "service.md": textwrap.dedent(
            """\
            # {{ title }}

            ## Overview

            ## API Surface

            ## Dependencies

            ## Related
            """
        ),
        "flow.md": textwrap.dedent(
            """\
            # {{ title }}

            ## Overview

            ## Trigger

            ## Steps

            ## Failure Modes

            ## Related
            """
        ),
        "concept.md": textwrap.dedent(
            """\
            # {{ title }}

            ## Overview

            ## Mechanism

            ## Trade-offs

            ## Related
            """
        ),
        "decision.md": textwrap.dedent(
            """\
            # {{ title }}

            ## Context

            ## Decision

            ## Consequences

            ## Related
            """
        ),
    }
    dst.mkdir(parents=True, exist_ok=True)
    for name, body in templates.items():
        (dst / name).write_text(body, encoding="utf-8")


def _write_fake_agent_tree(fixture: str, src: Path) -> None:
    resp = src / "fake_agent_responses"
    for stage in ("scout", "note_writer", "verifier", "narrator", "probe_retrieval"):
        (resp / stage).mkdir(parents=True, exist_ok=True)

    if fixture == "tech-lite":
        _write_json(resp / "scout" / "happy.json", _tech_lite_scout(1))
        _write_json(resp / "scout" / "code_derived.json", _tech_lite_scout(1))
    elif fixture == "source-poor":
        _write_json(resp / "scout" / "happy.json", _source_poor_scout(1))
        _write_json(resp / "scout" / "sg002_fail.json", _source_poor_scout(1))
    else:
        _write_json(resp / "scout" / "happy.json", _source_rich_scout(1))

    for cycle in (1, 2, 3):
        _write_json(
            resp / "note_writer" / f"cycle_{cycle:03d}.json",
            _note_writer_payload(fixture, cycle),
        )

    _write_json(resp / "note_writer" / "happy.json", _note_writer_payload(fixture, 1))
    if fixture == "source-poor":
        _write_json(
            resp / "note_writer" / "substitution.json",
            _note_writer_payload(fixture, 1, reject_fraction=0.15),
        )

    scenarios_root = ROOT / "tests" / "_helpers" / "fake_agent_scenarios"
    for name in ("accept.json", "reject.json", "malformed_json.json"):
        src_v = scenarios_root / "verifier" / name
        if src_v.is_file():
            (resp / "verifier" / name).write_text(
                src_v.read_text(encoding="utf-8"), encoding="utf-8"
            )
    (resp / "narrator" / "happy.json").write_text(
        (scenarios_root / "narrator" / "happy.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (resp / "probe_retrieval" / "happy.json").write_text(
        (scenarios_root / "probe_retrieval" / "happy.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )


TECH_LITE_SPEC = textwrap.dedent(
    """\
    ---
    name: tech-lite-quality-fixture
    owner: research-framework-tests
    location: PLACEHOLDER
    scope:
      domain: >-
        Small Java payment-gateway microservice domain for the spec-022 quality
        harness. Exercises code-derived topic discovery (FR-011).
      organization: Synthetic fixture — not a production vault
      boundaries:
        - Spring Boot services under synthetic/acme/* repos
        - Kafka flows and ADR decisions
        - Shared platform concepts (idempotency, sagas, circuit breakers)
      out_of_scope:
        - Production credentials or real customer data
        - Non-Java stacks
    note_types:
      - name: service
        description: Microservice boundary and responsibilities
        folder: "01 - Services"
        required_sections: ["Overview", "API Surface", "Dependencies", "Related"]
        min_word_count: 80
        template_version: "1.0.0"
      - name: flow
        description: End-to-end messaging or HTTP flow
        folder: "02 - Flows"
        required_sections: ["Overview", "Trigger", "Steps", "Failure Modes", "Related"]
        min_word_count: 80
        template_version: "1.0.0"
      - name: concept
        description: Reusable engineering concept
        folder: "03 - Concepts"
        required_sections: ["Overview", "Mechanism", "Trade-offs", "Related"]
        min_word_count: 80
        template_version: "1.0.0"
      - name: decision
        description: Architecture decision record
        folder: "04 - Decisions"
        required_sections: ["Context", "Decision", "Consequences", "Related"]
        min_word_count: 80
        template_version: "1.0.0"
    data_sources:
      - name: payment-repo
        type: code
        description: Synthetic payment service repository
        priority: 1
        required: true
      - name: order-repo
        type: code
        description: Synthetic order service repository
        priority: 1
        required: true
    search_dimensions: [technical, organizational]
    coverage_targets:
      categories:
        - name: services
          note_type: service
          target_count: 6
          met_count: 0
          priority: 95
        - name: flows
          note_type: flow
          target_count: 4
          met_count: 0
          priority: 90
        - name: concepts
          note_type: concept
          target_count: 5
          met_count: 0
          priority: 85
        - name: decisions
          note_type: decision
          target_count: 3
          met_count: 0
          priority: 80
    budget:
      max_usd: 25.0
      max_cycles: 3
    max_cycles: 3
    ---

    # tech-lite quality fixture

    Synthetic Java microservice domain for harness regression tests.
    """
)

SOURCE_POOR_SPEC = textwrap.dedent(
    """\
    ---
    name: source-poor-quality-fixture
    owner: research-framework-tests
    location: PLACEHOLDER
    scope:
      domain: >-
        Deliberately under-resourced research spec to exercise gap-pursuit and
        SG-002 diversity gate behaviour (FR-011 gap-pursuit-substitution).
      organization: Synthetic fixture
      boundaries:
        - One reachable wiki source
        - Many ambitious coverage categories
      out_of_scope:
        - Paid corpora without credentials
    note_types:
      - name: concept
        description: Concept note
        folder: "01 - Concepts"
        required_sections: ["Overview", "Mechanism", "Trade-offs", "Related"]
        min_word_count: 60
        template_version: "1.0.0"
      - name: service
        description: Service note
        folder: "02 - Services"
        required_sections: ["Overview", "API Surface", "Dependencies", "Related"]
        min_word_count: 60
        template_version: "1.0.0"
      - name: flow
        description: Flow note
        folder: "03 - Flows"
        required_sections: ["Overview", "Trigger", "Steps", "Failure Modes", "Related"]
        min_word_count: 60
        template_version: "1.0.0"
      - name: decision
        description: Decision note
        folder: "04 - Decisions"
        required_sections: ["Context", "Decision", "Consequences", "Related"]
        min_word_count: 60
        template_version: "1.0.0"
    data_sources:
      - name: only-wiki
        type: external
        description: Single weak wiki source
        priority: 1
        required: true
    search_dimensions: [technical]
    coverage_targets:
      categories:
        - name: concepts
          note_type: concept
          target_count: 12
          met_count: 0
          priority: 95
        - name: services
          note_type: service
          target_count: 10
          met_count: 0
          priority: 90
        - name: flows
          note_type: flow
          target_count: 8
          met_count: 0
          priority: 85
        - name: decisions
          note_type: decision
          target_count: 6
          met_count: 0
          priority: 80
        - name: integrations
          note_type: service
          target_count: 5
          met_count: 0
          priority: 75
    budget:
      max_usd: 10.0
      max_cycles: 3
    max_cycles: 3
    ---

    # source-poor quality fixture
    """
)

SOURCE_RICH_SPEC = textwrap.dedent(
    """\
    ---
    name: source-rich-quality-fixture
    owner: research-framework-tests
    location: PLACEHOLDER
    scope:
      domain: >-
        Curated high-quality sources with comfortable coverage targets for
        source-quality-pruning regression (FR-011).
      organization: Synthetic fixture
      boundaries:
        - Official docs, papers, and org repos
      out_of_scope:
        - Low-signal scraper feeds
    note_types:
      - name: service
        description: Service note
        folder: "01 - Services"
        required_sections: ["Overview", "API Surface", "Dependencies", "Related"]
        min_word_count: 60
        template_version: "1.0.0"
      - name: flow
        description: Flow note
        folder: "02 - Flows"
        required_sections: ["Overview", "Trigger", "Steps", "Failure Modes", "Related"]
        min_word_count: 60
        template_version: "1.0.0"
      - name: concept
        description: Concept note
        folder: "03 - Concepts"
        required_sections: ["Overview", "Mechanism", "Trade-offs", "Related"]
        min_word_count: 60
        template_version: "1.0.0"
      - name: decision
        description: Decision note
        folder: "04 - Decisions"
        required_sections: ["Context", "Decision", "Consequences", "Related"]
        min_word_count: 60
        template_version: "1.0.0"
    data_sources:
      - name: official-docs
        type: external
        description: Curated official documentation
        priority: 1
        required: true
      - name: oreilly-shelf
        type: external
        description: Curated O'Reilly excerpts
        priority: 1
        required: true
      - name: arxiv-feed
        type: external
        description: Curated arXiv feed
        priority: 2
        required: true
      - name: github-org
        type: code
        description: Curated GitHub organization
        priority: 1
        required: true
      - name: confluence-space
        type: external
        description: Curated Confluence space
        priority: 2
        required: true
    search_dimensions: [technical, organizational, domain]
    coverage_targets:
      categories:
        - name: services
          note_type: service
          target_count: 4
          met_count: 0
          priority: 95
        - name: flows
          note_type: flow
          target_count: 3
          met_count: 0
          priority: 90
        - name: concepts
          note_type: concept
          target_count: 3
          met_count: 0
          priority: 85
        - name: decisions
          note_type: decision
          target_count: 2
          met_count: 0
          priority: 80
        - name: integrations
          note_type: service
          target_count: 2
          met_count: 0
          priority: 75
    budget:
      max_usd: 40.0
      max_cycles: 3
    max_cycles: 3
    ---

    # source-rich quality fixture
    """
)

FIXTURE_META = {
    "tech-lite": (TECH_LITE_SPEC, 18),
    "source-poor": (SOURCE_POOR_SPEC, 17),
    "source-rich": (SOURCE_RICH_SPEC, 20),
}


def _settings_yaml(vault_dir: Path) -> str:
    responses = (vault_dir / "fake_agent_responses").resolve()
    return textwrap.dedent(
        f"""\
        pipeline:
          gates:
            cg_003_warn_pct: 30
            cg_003_fail_pct: 60
          note_writer_batch_size: 6
          max_batches_per_cycle: 10
        cycle:
          runner:
            fake_agent_responses_dir: "{responses}"
            max_cycles: 3
        budget:
          max_cycles: 3
        default_executor:
          runtime: claude
          model: sonnet
          timeout_s: 60
        stages:
          verifier:
            enabled: true
        """
    )


def bootstrap_fixture(name: str) -> None:
    spec_yaml, note_target = FIXTURE_META[name]
    vault = FIXTURES / name
    src = vault / ".fixture-src"
    if src.exists():
        import shutil

        shutil.rmtree(src)
    src.mkdir(parents=True)
    _write_templates(src / "_templates")
    _write_fake_agent_tree(name, src)
    spec_path = src / "research.spec.md"
    spec_text = spec_yaml.replace("PLACEHOLDER", str(vault.resolve()))
    spec_path.write_text(spec_text, encoding="utf-8")

    build_quality_fixture(
        name,
        vault,
        spec_yaml=spec_text,
        note_count_target=note_target,
        fake_agent_responses_src=src / "fake_agent_responses",
    )
    (vault / "settings.yaml").write_text(_settings_yaml(vault), encoding="utf-8")
    (vault / ".gitignore").write_text(
        "# Quality harness fixture (spec 022): commit inputs; ignore cycle churn.\n"
        "_pipeline/cycles/\n"
        "_pipeline/prompts/\n"
        "_pipeline/quality/\n"
        ".quality-settings.tmp.yaml\n",
        encoding="utf-8",
    )
    from research_framework.spec.parser import parse

    spec = parse(vault / "research.spec.md")
    (vault / "coverage-targets.json").write_text(
        json.dumps(spec.coverage_targets.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"bootstrapped {name} at {vault}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="_bootstrap_us3_fixtures",
        description=(
            "Regenerate the committed spec-022 quality fixtures. Default is a "
            "DRY RUN; pass --force to mutate the tracked tree (spec 026 SC-006)."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Actually rewrite the tracked fixtures (otherwise this is a dry run).",
    )
    args = parser.parse_args(argv)

    targets = {name: FIXTURES / name for name in FIXTURE_META}
    if not args.force:
        print("[bootstrap] DRY RUN — no files written. Would regenerate:")
        for name, path in targets.items():
            print(f"  - {name}: {path}")
        print("[bootstrap] re-run with --force to mutate the tracked fixture tree.")
        return 0

    if sys.stdin.isatty():
        reply = (
            input(
                f"About to OVERWRITE {len(targets)} committed quality fixtures "
                f"under {FIXTURES}. Continue? [y/N] "
            )
            .strip()
            .lower()
        )
        if reply not in {"y", "yes"}:
            print("[bootstrap] aborted — no files written.")
            return 1

    for name in FIXTURE_META:
        bootstrap_fixture(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
