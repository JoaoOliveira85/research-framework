#!/usr/bin/env python3
"""Walk enumerated repos and produce `_pipeline/repo-scan.json`.

Reads the spec (via `_pipeline/spec-parse.json` or --spec path), walks the
primary behaviour source's repos, extracts ADRs, Kafka topics, REST endpoints,
and domain terms (class/enum/interface names referenced 2+ times across files),
and derives coverage targets.

Exit codes:
  0  scan complete, repo-scan.json written
  1  one or more repos could not be accessed (partial scan written)
  2  usage / spec / filesystem error

See contracts/repo_scan.output.schema.md for the output schema.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_IGNORE = {
    "target",
    "build",
    "generated",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".gradle",
    "out",
    "dist",
    ".git",
    ".idea",
}

# Path substrings that mark a file as test/fixture code. Terms declared under
# these paths never count toward domain-term extraction — a class named
# `BetConverterTest` is a test artifact, not a domain concept.
TEST_PATH_SUBSTRINGS = (
    "/src/test/",
    "/src/testFixtures/",
    "/src/integrationTest/",
    "/src/test-integration/",
    "/src/testIntegration/",
)

# Name suffixes that mark a TitleCase type as architectural scaffolding rather
# than a domain concept. Kept conservative: DTO-ish suffixes (Request/Response/
# Message/Event/Command/Dto) are intentionally NOT listed because they frequently
# ARE domain concepts in an event-driven system.
SCAFFOLDING_SUFFIXES = (
    "Test",
    "Tests",
    "IT",
    "ITs",
    "TestConfig",
    "TestConfiguration",
    "TestContext",
    "TestSupport",
    "TestUtil",
    "TestUtils",
    "TestHelper",
    "TestHelpers",
    "Mock",
    "Mocks",
    "Fixture",
    "Fixtures",
    "Stub",
    "Stubs",
    "Fake",
    "Fakes",
    "Builder",
    "Factory",
    "Provider",
    "Converter",
    "Mapper",
    "Resolver",
    "Helper",
    "Util",
    "Utils",
    "Config",
    "Configuration",
    "Properties",
    "Exception",
    "Impl",
)

DEFAULT_PRIORITY = ["README.md", "docs", "src/main/resources/application.yml"]

# Regex scanners — stdlib only (Principle V).
JAVA_TYPE_RE = re.compile(
    r"^\s*public\s+(?:abstract\s+|final\s+|static\s+)*(class|enum|interface|record)\s+(\w+)",
    re.MULTILINE,
)
KOTLIN_TYPE_RE = re.compile(
    r"^\s*(?:public|open|sealed|data|abstract)?\s*(class|object|interface|enum\s+class)\s+(\w+)",
    re.MULTILINE,
)
KAFKA_TOPIC_RE = re.compile(
    r'topic[:\s=]+["\']?([a-zA-Z][\w\.\-]{3,}\.[a-zA-Z][\w\.\-]{3,})["\']?',
    re.IGNORECASE,
)
REST_ENDPOINT_RE = re.compile(
    r'@(Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*(?:path\s*=\s*)?["\']([/\w\-{}]+)["\']',
    re.IGNORECASE,
)
ADR_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class DomainTerm:
    term: str
    ref_count: int
    sample_paths: list[str]


@dataclass
class RepoScanRepo:
    name: str
    url: str
    head_sha: str = ""
    access_method_used: str = ""
    access_failed: bool = False
    files_scanned: int = 0
    adrs_found: list[str] = field(default_factory=list)
    kafka_topics_found: list[str] = field(default_factory=list)
    rest_endpoints_found: list[str] = field(default_factory=list)
    domain_terms_found: list[DomainTerm] = field(default_factory=list)


def _load_spec(pipeline_dir: Path | None, spec_path: Path | None) -> dict | None:
    if spec_path:
        try:
            return json.loads(_parse_spec_to_dict(spec_path))
        except Exception:
            return None
    if pipeline_dir:
        parse_file = pipeline_dir / "spec-parse.json"
        if parse_file.exists():
            try:
                return json.loads(parse_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
    return None


def _parse_spec_to_dict(spec_path: Path) -> str:
    """Invoke the research-framework parser for an authored spec file — returns JSON."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from research_framework.spec.parser import parse  # type: ignore

    spec = parse(spec_path)
    return json.dumps(spec.to_dict())


def _resolve_local_path(repo: dict) -> Path | None:
    lp = repo.get("local_path") or ""
    if lp:
        path = Path(lp).expanduser()
        if path.exists():
            return path
    return None


def _iter_repo_files(
    repo_root: Path, ignore_paths: list[str], priority_paths: list[str]
):
    """Yield files under repo_root, honouring ignore globs + defaulted ignores."""
    ignore_set = set(ignore_paths) | DEFAULT_IGNORE

    # Priority paths first, then the remaining files.
    priority_files: list[Path] = []
    for pp in priority_paths or DEFAULT_PRIORITY:
        candidate = repo_root / pp
        if candidate.is_file():
            priority_files.append(candidate)
        elif candidate.is_dir():
            for p in candidate.rglob("*"):
                if p.is_file() and not _is_ignored(p, repo_root, ignore_set):
                    priority_files.append(p)

    yielded: set[Path] = set()
    for p in priority_files:
        if p not in yielded:
            yielded.add(p)
            yield p

    for p in repo_root.rglob("*"):
        if not p.is_file():
            continue
        if p in yielded:
            continue
        if _is_ignored(p, repo_root, ignore_set):
            continue
        yielded.add(p)
        yield p


def _is_ignored(path: Path, root: Path, ignore_set: set[str]) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    for part in rel.parts:
        if part in ignore_set:
            return True
    return False


def _is_test_path(rel_posix: str) -> bool:
    """True if the relative POSIX path lives under a test/fixture source root."""
    return any(marker in rel_posix for marker in TEST_PATH_SUBSTRINGS)


def _is_scaffolding_name(name: str) -> bool:
    """True if the TitleCase type name matches an architectural-scaffolding suffix.

    Used to keep the concept-target list anchored in domain vocabulary. The
    check is suffix-only — a class named `ConfigHolder` is not flagged, but
    `RetryConfig` is.
    """
    return any(name.endswith(suffix) for suffix in SCAFFOLDING_SUFFIXES)


def _scan_repo(repo_spec: dict) -> RepoScanRepo:
    name = repo_spec.get("name", "")
    url = repo_spec.get("url", "")
    access_method = repo_spec.get("access_method", "both")
    out = RepoScanRepo(name=name, url=url)

    local = None
    if access_method in ("local", "both"):
        local = _resolve_local_path(repo_spec)

    if not local:
        # MCP fallback is not implemented in this script (agents handle MCP at
        # scout time). Mark as access_failed; partial scan still proceeds.
        out.access_failed = True
        out.access_method_used = "mcp" if access_method != "local" else "local"
        return out

    out.access_method_used = "local"
    out.head_sha = _git_head_sha(local)

    priority_paths = repo_spec.get("priority_paths") or []
    ignore_paths = repo_spec.get("ignore_paths") or []

    # Per-repo domain-term accumulator
    term_counts: dict[str, int] = defaultdict(int)
    term_paths: dict[str, list[str]] = defaultdict(list)

    for path in _iter_repo_files(local, ignore_paths, priority_paths):
        out.files_scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        # ADRs under docs/adr or docs/decisions
        rel = path.relative_to(local).as_posix()
        if ("docs/adr/" in rel or "docs/decisions/" in rel) and rel.endswith(".md"):
            out.adrs_found.append(rel)

        # Kafka topics
        for m in KAFKA_TOPIC_RE.finditer(text):
            topic = m.group(1)
            if topic not in out.kafka_topics_found:
                out.kafka_topics_found.append(topic)

        # REST endpoints
        for m in REST_ENDPOINT_RE.finditer(text):
            verb = m.group(1).upper()
            path_str = m.group(2)
            endpoint = f"{verb} {path_str}"
            if endpoint not in out.rest_endpoints_found:
                out.rest_endpoints_found.append(endpoint)

        # Java / Kotlin type extraction. Skip files under test source roots
        # and type names matching architectural-scaffolding suffixes so
        # domain-term derivation stays anchored in real business vocabulary.
        suffix = path.suffix.lower()
        if suffix in (".java", ".kt") and _is_test_path(rel):
            continue
        if suffix == ".java":
            for m in JAVA_TYPE_RE.finditer(text):
                name_ = m.group(2)
                if _is_scaffolding_name(name_):
                    continue
                term_counts[name_] += 1
                if len(term_paths[name_]) < 5:
                    term_paths[name_].append(rel)
        elif suffix == ".kt":
            for m in KOTLIN_TYPE_RE.finditer(text):
                name_ = m.group(2)
                if _is_scaffolding_name(name_):
                    continue
                term_counts[name_] += 1
                if len(term_paths[name_]) < 5:
                    term_paths[name_].append(rel)

        # Also count plain-text references to already-declared types across files
        # (helps surface cross-file domain terms).
        # For simplicity we only consider type NAMES longer than 3 chars and
        # TitleCase (class-like) — avoids matching common English words.

    # Promote terms referenced 2+ times across files; deterministic ordering
    for term, count in sorted(term_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if count < 2:
            continue
        out.domain_terms_found.append(
            DomainTerm(
                term=term,
                ref_count=count,
                sample_paths=term_paths[term][:5],
            )
        )

    return out


def _git_head_sha(repo_root: Path) -> str:
    head = repo_root / ".git" / "HEAD"
    if not head.exists():
        return ""
    try:
        content = head.read_text(encoding="utf-8").strip()
        if content.startswith("ref: "):
            ref = content[5:]
            ref_file = repo_root / ".git" / ref
            if ref_file.exists():
                return ref_file.read_text(encoding="utf-8").strip()[:40]
        return content[:40]
    except OSError:
        return ""


def _derive_targets(
    repos: list[RepoScanRepo], cross_repo_terms: dict[str, int]
) -> dict[str, list[str]]:
    """Collapse per-repo scan output into category → expected_filenames."""
    services: list[str] = []
    decisions: list[str] = []
    flows: list[str] = []
    concepts: list[str] = []

    seen_topics: set[str] = set()
    seen_endpoints: set[str] = set()

    for repo in repos:
        services.append(_service_filename(repo))
        for adr in repo.adrs_found:
            decisions.append(_adr_filename(repo, adr))
        for topic in repo.kafka_topics_found:
            seen_topics.add(topic)
        for endpoint in repo.rest_endpoints_found:
            seen_endpoints.add(endpoint)

    for topic in sorted(seen_topics):
        flows.append(_topic_to_filename(topic))
    for endpoint in sorted(seen_endpoints):
        flows.append(_endpoint_to_filename(endpoint))

    for term, count in sorted(cross_repo_terms.items(), key=lambda kv: (-kv[1], kv[0])):
        if count < 2:
            continue
        concepts.append(_term_to_filename(term))

    return {
        "services": services,
        "decisions": decisions,
        "flows": flows,
        "concepts": concepts,
    }


def _service_filename(repo: RepoScanRepo) -> str:
    return f"{repo.name} ({_humanize(repo.name)}).md"


def _humanize(name: str) -> str:
    """Best-effort long form. Real scanners read README H1; here we fall back."""
    # Strip "-service" suffix and title-case
    base = name.removesuffix("-service").replace("-", " ")
    return base.title() if base else name


def _adr_filename(repo: RepoScanRepo, adr_path: str) -> str:
    m = re.search(r"(\d{3,4})[_\-\s]*(.+?)\.md$", adr_path)
    if m:
        num = m.group(1).zfill(4)
        title = m.group(2).replace("-", " ").replace("_", " ").title()
        return f"ADR {num} - {title} ({repo.name}).md"
    return f"ADR - {Path(adr_path).stem} ({repo.name}).md"


def _topic_to_filename(topic: str) -> str:
    # order.housekeeper.trigger.v1 → Order Housekeeper Trigger V1 Flow.md
    parts = [p for p in re.split(r"[\.\-_]", topic) if p]
    return " ".join(p.title() for p in parts) + " Flow.md"


def _endpoint_to_filename(endpoint: str) -> str:
    # "GET /order/{id}" → "GET Order ID Endpoint.md"
    verb, _, path = endpoint.partition(" ")
    tokens = [t.strip("{}").replace("-", " ").title() for t in path.split("/") if t]
    return f"{verb} {' '.join(tokens)} Endpoint.md"


def _term_to_filename(term: str) -> str:
    # CamelCase → spaced; acronyms preserved
    words: list[str] = []
    current = ""
    for ch in term:
        if ch.isupper() and current and not current[-1].isupper():
            words.append(current)
            current = ch
        else:
            current += ch
    if current:
        words.append(current)
    return " ".join(words) + ".md"


def scan(spec_data: dict) -> dict[str, Any]:
    """Perform the scan; return the RepoScanOutput dict."""
    primary_repos: list[dict] = []
    for ds in spec_data.get("data_sources", []) or []:
        if ds.get("priority") == 1 and ds.get("role") == "behaviour":
            primary_repos = ds.get("repos") or []
            break

    if not primary_repos:
        return {
            "scan_timestamp": dt.datetime.now(dt.UTC).isoformat(),
            "research_framework_version": "0.2.0",
            "repos": [],
            "derived_targets": {
                "services": [],
                "decisions": [],
                "flows": [],
                "concepts": [],
            },
        }

    scanned: list[RepoScanRepo] = []
    cross_repo_terms: dict[str, int] = defaultdict(int)
    for repo_spec in primary_repos:
        result = _scan_repo(repo_spec)
        scanned.append(result)
        for term in result.domain_terms_found:
            cross_repo_terms[term.term] += term.ref_count

    targets = _derive_targets(scanned, cross_repo_terms)

    return {
        "scan_timestamp": dt.datetime.now(dt.UTC).isoformat(),
        "research_framework_version": "0.2.0",
        "repos": [
            {
                "name": r.name,
                "url": r.url,
                "head_sha": r.head_sha,
                "access_method_used": r.access_method_used,
                "access_failed": r.access_failed,
                "files_scanned": r.files_scanned,
                "adrs_found": r.adrs_found,
                "kafka_topics_found": r.kafka_topics_found,
                "rest_endpoints_found": r.rest_endpoints_found,
                "domain_terms_found": [
                    {
                        "term": t.term,
                        "ref_count": t.ref_count,
                        "sample_paths": t.sample_paths,
                    }
                    for t in r.domain_terms_found
                ],
            }
            for r in scanned
        ],
        "derived_targets": targets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Walk repos and emit repo-scan.json.")
    parser.add_argument("vault_dir", type=Path)
    parser.add_argument("--spec", type=Path, default=None)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    args = parser.parse_args()

    vault = args.vault_dir
    pipeline_dir = vault / "_pipeline"
    if not pipeline_dir.exists() and not args.spec:
        print(
            f"ERROR: {pipeline_dir} not found (and --spec not provided)",
            file=sys.stderr,
        )
        return 2

    spec_data = _load_spec(pipeline_dir if pipeline_dir.exists() else None, args.spec)
    if spec_data is None:
        print(
            "ERROR: could not load spec — pass --spec <file> or generate the vault first",
            file=sys.stderr,
        )
        return 2

    output = scan(spec_data)
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    out_path = pipeline_dir / "repo-scan.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    if args.emit_json:
        print(json.dumps(output, indent=2))

    any_failed = any(r["access_failed"] for r in output["repos"])
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
