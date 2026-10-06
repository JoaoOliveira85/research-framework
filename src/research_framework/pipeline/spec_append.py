"""Query-driven spec append (spec 073).

A vault's ``research.spec.md`` is the only durable statement of what the vault
researches and which sources it trusts. Every path in the framework reads it;
nothing writes it. That is right for the spec-as-contract and wrong for the case
this module exists for: a query needed a topic and a source the spec did not
declare, the research happened, and the spec never learned either.

Since spec 070 that is worse than a gap — an uncatalogued domain is a quarantine
reason, so a query that pulls a good new source *creates future quarantines*
unless a human remembers to declare it.

Three rules shape everything here:

**Append only, into a managed region.** Regenerating a spec from a model's
understanding risks silently dropping a boundary, an ``out_of_scope`` line or a
credibility tier that was argued over once. Nothing above
``<!-- framework:discovered:begin -->`` is ever read for meaning or rewritten;
the prefix and suffix are carried through byte-for-byte.

**Appending is not adopting.** A discovered source does not become a
``data_source`` and a discovered topic does not become a coverage target. The
append is a *record*; promotion stays a human edit. Auto-adopting would let one
query silently widen what the vault trusts — the exact drift this design avoids,
and worse than the gap because nobody would read it.

**A discovered source is ``unassessed``.** Nobody has judged it, so spec 070's
verifier goes on quarantining notes that cite it. That is the correct outcome:
an unvetted source should not silently earn a tier. What changes is that the
operator can now *see* which unvetted source caused a quarantine instead of
reverse-engineering it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

__all__ = [
    "BEGIN_MARKER",
    "END_MARKER",
    "Discovery",
    "SpecRegionError",
    "append_discovery",
    "declared_hosts",
    "render_entry",
    "split_region",
    "topic_slug",
]

BEGIN_MARKER = "<!-- framework:discovered:begin -->"
END_MARKER = "<!-- framework:discovered:end -->"

_REGION_HEADER = """## Discovered by query

Appended automatically when a query needed ground the spec did not declare.
Nothing above this marker is ever modified. Promote an entry into the spec
proper by moving it and deleting it here.
"""


class SpecRegionError(Exception):
    """The managed region is malformed and must not be silently rewritten.

    The operator's edits are the point of this design, so a region we cannot
    parse is refused rather than reconstructed — reconstructing it is precisely
    the drift the append-only rule exists to prevent.
    """


@dataclass(frozen=True)
class DiscoveredSource:
    url: str
    note: str = ""


@dataclass(frozen=True)
class Discovery:
    """One query's worth of newly-discovered ground."""

    asked: str
    sources: list[DiscoveredSource] = field(default_factory=list)
    topic: str | None = None

    def label(self) -> str:
        """Short heading label — the topic when there is one, else the question."""
        text = (self.topic or self.asked).strip()
        return text if len(text) <= 60 else text[:57].rstrip() + "…"


def topic_slug(text: str) -> str:
    """Normalised key for idempotence. Case/punctuation/spacing insensitive."""
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _host(url: str) -> str:
    from research_framework.vault.credibility import source_host

    return source_host(url)


def declared_hosts(spec: object) -> set[str]:
    """Every host the spec already declares, across all locator shapes.

    Mirrors what ``build_credibility_context`` indexes, so "undeclared" here
    means the same thing it means to the credibility resolver.
    """
    hosts: set[str] = set()
    for ds in getattr(spec, "data_sources", []) or []:
        for locator in (
            getattr(ds, "url", "") or "",
            *(getattr(ds, "urls", []) or []),
        ):
            h = _host(locator)
            if h:
                hosts.add(h)
        for repo in getattr(ds, "repos", []) or []:
            h = _host(getattr(repo, "url", "") or "")
            if h:
                hosts.add(h)
    return hosts


def split_region(text: str) -> tuple[str, str, str]:
    """Return ``(prefix, region_body, suffix)``.

    ``region_body`` excludes the markers. When no region exists the body is
    empty and the suffix is empty, so a caller can always rebuild by
    concatenation — which is how the "nothing above is modified" promise is
    kept structurally rather than by assertion.
    """
    begins = text.count(BEGIN_MARKER)
    ends = text.count(END_MARKER)
    if begins == 0 and ends == 0:
        return text, "", ""
    if begins != 1 or ends != 1:
        raise SpecRegionError(
            f"expected exactly one managed region, found {begins} begin- and "
            f"{ends} end-marker(s). Fix the file by hand; refusing to guess."
        )
    b = text.index(BEGIN_MARKER)
    e = text.index(END_MARKER)
    if e < b:
        raise SpecRegionError(
            "managed region end-marker precedes its begin-marker. Fix the file "
            "by hand; refusing to guess."
        )
    return text[:b], text[b + len(BEGIN_MARKER) : e], text[e + len(END_MARKER) :]


def render_entry(discovery: Discovery, *, today: str) -> str:
    """Render one entry block. Sources are recorded ``unassessed`` — see §4."""
    lines = [f"### {today} — {discovery.label()}", ""]
    lines.append(f'- **asked:** "{discovery.asked.strip()}"')
    if discovery.sources:
        lines.append("- **sources used:**")
        for src in discovery.sources:
            tail = f" — {src.note.strip()}" if src.note.strip() else ""
            lines.append(f"  - `{src.url.strip()}` — unassessed{tail}")
    if discovery.topic:
        lines.append(f"- **topic:** {discovery.topic.strip()}")
    return "\n".join(lines) + "\n"


def _entry_keys(region_body: str) -> tuple[set[str], set[str]]:
    """``(source_hosts, topic_slugs)`` already recorded in the region."""
    hosts = {h for h in (_host(u) for u in re.findall(r"`([^`]+)`", region_body)) if h}
    topics = {
        topic_slug(m)
        for m in re.findall(r"^\s*-\s+\*\*topic:\*\*\s*(.+)$", region_body, re.M)
    }
    return hosts, topics


def _asked_already(region_body: str, asked: str) -> bool:
    recorded = re.findall(r'^\s*-\s+\*\*asked:\*\*\s*"(.*)"\s*$', region_body, re.M)
    return topic_slug(asked) in {topic_slug(a) for a in recorded}


def append_discovery(
    spec_path: Path,
    discovery: Discovery,
    *,
    today: str | None = None,
) -> bool:
    """Record ``discovery`` in ``spec_path``'s managed region. True if changed.

    Idempotent by design (§5): re-asking the same question does not grow the
    file, and a source or topic already recorded is not recorded twice. The
    region is created on first use and recreated if the operator deletes it.

    Raises :class:`SpecRegionError` on a malformed region rather than repairing
    it, because the operator's hand-edits are the thing being protected.
    """
    today = today or datetime.now(UTC).strftime("%Y-%m-%d")
    text = spec_path.read_text(encoding="utf-8")
    prefix, body, suffix = split_region(text)

    if _asked_already(body, discovery.asked):
        return False

    known_hosts, known_topics = _entry_keys(body)
    new_sources = [
        s for s in discovery.sources if _host(s.url) and _host(s.url) not in known_hosts
    ]
    topic_is_new = bool(discovery.topic) and topic_slug(discovery.topic) not in (
        known_topics
    )
    if not new_sources and not topic_is_new:
        # Nothing this query found is new ground; the question alone is not
        # worth a record (§2 — `asked` is provenance, not a reason).
        return False

    entry = render_entry(
        Discovery(
            asked=discovery.asked,
            sources=new_sources,
            topic=discovery.topic if topic_is_new else None,
        ),
        today=today,
    )

    if not body.strip():
        new_body = "\n" + _REGION_HEADER + "\n" + entry
    else:
        new_body = body.rstrip("\n") + "\n\n" + entry

    rebuilt = (
        prefix.rstrip("\n")
        + "\n\n"
        + BEGIN_MARKER
        + new_body
        + END_MARKER
        + (suffix if suffix.startswith("\n") else "\n" + suffix if suffix else "\n")
    )

    from research_framework.pipeline.atomic_write import write_text

    write_text(spec_path, rebuilt)
    return True


def cited_hosts_for_cycle(vault_dir: Path, cycle_num: int) -> list[DiscoveredSource]:
    """Sources cited by the notes a cycle created, in first-seen order.

    Reads the cycle's own research report and then the notes' frontmatter, which
    is where citations actually live — the report records filenames, not URLs.
    Best-effort throughout: a missing or malformed artifact yields fewer
    discoveries, never an exception, because this runs at the tail of a cycle
    that has already done its real work.
    """
    import json

    from research_framework.vault.corpus import corpus_dir
    from research_framework.vault.credibility import (
        citation_url,
        iter_source_url_entries,
    )
    from research_framework.vault.frontmatter import parse_frontmatter

    report = vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_num:03d}-research.json"
    try:
        created = json.loads(report.read_text(encoding="utf-8")).get("notes_created")
    except (OSError, json.JSONDecodeError, AttributeError):
        return []
    if not isinstance(created, list):
        return []

    out: list[DiscoveredSource] = []
    seen: set[str] = set()
    for rel in created:
        note = vault_dir / str(rel)
        if not note.is_file():
            matches = list(corpus_dir(vault_dir).rglob(Path(str(rel)).name))
            if not matches:
                continue
            note = matches[0]
        try:
            fm, _body = parse_frontmatter(note)
        except Exception:  # pragma: no cover - defensive; never fail a cycle
            continue
        for entry in iter_source_url_entries(fm or {}):
            url = citation_url(entry)
            host = _host(url or "")
            if host and host not in seen:
                seen.add(host)
                out.append(
                    DiscoveredSource(url=url or "", note=f"cited by {note.name}")
                )
    return out


def _coverage_target_slugs(coverage_targets: object) -> set[str]:
    """Every slug an existing coverage_target already declares.

    Spec 073 §2: a `topic` is appended only when "a query asked for an area
    no coverage_target covers" — checked here by comparing ``topic_slug``
    against each category's name, display name, and expected note titles
    (``expected_filenames``), the same normalisation ``_entry_keys`` already
    uses for the managed region's own idempotence.
    """
    slugs: set[str] = set()
    for cat in getattr(coverage_targets, "categories", None) or []:
        for label in (getattr(cat, "name", ""), getattr(cat, "display_name", "")):
            if label:
                slugs.add(topic_slug(label))
        for filename in getattr(cat, "expected_filenames", None) or []:
            slugs.add(topic_slug(Path(filename).stem))
    return slugs


def record_query_discoveries(
    vault_dir: Path,
    spec: object,
    cycle_num: int,
    target_topics: list[str] | None,
) -> bool:
    """Spec 073 hook: record what a QUERY-driven cycle found. True if written.

    Fires only when ``target_topics`` were supplied — i.e. the cycle was driven
    by a question rather than the backlog. That is the conservative reading of
    the spec's open question ("only interactive queries, or full runs too?"):
    a full pipeline run already records its sources in the cycle report, and
    widening this to every run is a decision for the operator, not for the
    implementation.

    Best-effort: a failure here must never change the cycle's exit code, since
    the research it describes has already succeeded.
    """
    if not target_topics:
        return False
    spec_path = vault_dir / "research.spec.md"
    if not spec_path.is_file():
        return False

    known = declared_hosts(spec)
    undeclared = [
        s
        for s in cited_hosts_for_cycle(vault_dir, cycle_num)
        if _host(s.url) not in known
    ]
    # `asked` is provenance — the full question — regardless of coverage;
    # `new_topic` is what actually earns a `- **topic:**` line (§2).
    asked = ", ".join(t.strip() for t in target_topics if t.strip())
    covered = _coverage_target_slugs(getattr(spec, "coverage_targets", None))
    new_topic = ", ".join(
        t.strip() for t in target_topics if t.strip() and topic_slug(t) not in covered
    )
    if not undeclared and not new_topic:
        return False
    return append_discovery(
        spec_path,
        Discovery(asked=asked, sources=undeclared, topic=new_topic or None),
    )
