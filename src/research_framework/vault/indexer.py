"""Layer 1 rebuild — regenerates _index.md, _concepts.md, _graph.md from Layer 2."""

from __future__ import annotations

import re
from pathlib import Path

from research_framework.vault.corpus import corpus_dir
from research_framework.vault.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter,
)

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _parse_frontmatter(path: Path) -> tuple[dict | None, str]:
    try:
        fm, body = parse_frontmatter(path)
    except UnicodeDecodeError:
        # Not UTF-8: skip it like any other unparseable note rather than abort
        # the whole rebuild.
        return None, ""
    except (OSError, FrontmatterParseError):
        try:
            return None, path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None, ""
    if not fm:
        return None, body
    return fm, body


def _is_note_path(data_vault: Path, path: Path) -> bool:
    rel = path.relative_to(data_vault)
    parts = rel.parts
    if "_templates" in parts:
        return False
    if path.name in ("_index.md", "_concepts.md", "_graph.md"):
        return False
    return True


def _truncate_summary(text: str, limit: int = 120) -> str:
    t = text.replace("\n", " ").strip()
    if len(t) <= limit:
        return t
    return t[:limit]


def _normalize_link_label(raw: str) -> str:
    s = raw.strip()
    if s.startswith("[[") and s.endswith("]]"):
        s = s[2:-2].strip()
    return s.strip()


def _outgoing_links(fm: dict, body: str) -> set[str]:
    """Every wikilink target a note points to.

    Body ``[[wikilinks]]`` plus ``related:`` frontmatter targets, normalized.
    Shared by :func:`rebuild_all` (graph emission) and
    :func:`inbound_link_counts` (spec 051 FR3) so both see the same edges.
    """
    links: set[str] = set()
    for m in _WIKILINK_RE.findall(body):
        lbl = _normalize_link_label(m)
        if lbl:
            links.add(lbl)
    related = fm.get("related") or []
    if isinstance(related, list):
        for target in related:
            lbl = _normalize_link_label(str(target))
            if lbl:
                links.add(lbl)
    return links


def inbound_link_counts(vault_dir: Path) -> dict[str, int]:
    """Map each note title to its number of inbound wikilinks.

    Read-only: walks ``vault_dir/data_vault`` and inverts the same outgoing-link
    graph :func:`rebuild_all` builds (via :func:`_outgoing_links`), without
    writing any Layer-1 index. Used by the spec-051 stub classifier to protect
    heavily-linked graph anchors from deletion.

    Returns ``{title: inbound_count}`` for every note — anchors with zero
    inbound links are present with a count of ``0``. Links whose label is not a
    note title are ignored.
    """
    data_vault = corpus_dir(vault_dir)
    if not data_vault.is_dir():
        return {}

    outgoing: dict[str, set[str]] = {}
    for note in sorted(data_vault.rglob("*.md")):
        if not _is_note_path(data_vault, note):
            continue
        fm, body = _parse_frontmatter(note)
        if fm is None:
            continue
        title = str(fm.get("title", note.stem))
        outgoing[title] = _outgoing_links(fm, body)

    counts: dict[str, int] = dict.fromkeys(outgoing, 0)
    for targets in outgoing.values():
        for dst in targets:
            if dst in counts:
                counts[dst] += 1
    return counts


def migrate_root_indexes(vault_dir: Path) -> bool:
    """Move legacy ``_index.md`` / ``_concepts.md`` / ``_graph.md`` from vault root
    into ``data_vault/``, merging under ``## Migrated from vault root`` when needed.

    Idempotent: does nothing when no root-level index files exist.
    """
    data_vault = corpus_dir(vault_dir)
    data_vault.mkdir(parents=True, exist_ok=True)
    any_moved = False
    for name in ("_index.md", "_concepts.md", "_graph.md"):
        root = vault_dir / name
        if not root.is_file():
            continue
        dest = data_vault / name
        root_txt = root.read_text(encoding="utf-8")
        root.unlink()
        any_moved = True
        if dest.exists():
            prev = dest.read_text(encoding="utf-8").rstrip()
            dest.write_text(
                prev + "\n\n## Migrated from vault root\n\n" + root_txt,
                encoding="utf-8",
            )
        else:
            dest.write_text(root_txt, encoding="utf-8")
    return any_moved


def _pull_root_index_stubs(vault_dir: Path) -> dict[str, str]:
    """Return the contents of root-level index files (if present).

    Used by :func:`rebuild_all` so generated indexes can incorporate legacy root
    files without leaving stale copies at the vault root. The files are NOT
    removed here: :func:`rebuild_all` unlinks them only after the new indexes
    holding their content are written, so a failed rebuild loses nothing.
    """
    pulled: dict[str, str] = {}
    for name in ("_index.md", "_concepts.md", "_graph.md"):
        root = vault_dir / name
        if root.is_file():
            pulled[name] = root.read_text(encoding="utf-8")
    return pulled


def rebuild_all(vault_dir: Path) -> dict[str, Path]:
    """Rebuild Layer 1 indexes under ``vault_dir / \"data_vault\"``.

    Writes ``_index.md``, ``_concepts.md``, and ``_graph.md`` with deterministic
    ordering. Appends content from any legacy root-level index files (removed
    during this run) under ``## Migrated from vault root``.

    Returns a map ``{\"index\", \"concepts\", \"graph\"} -> Path``.
    """
    data_vault = corpus_dir(vault_dir)
    data_vault.mkdir(parents=True, exist_ok=True)
    # A corpus_dir of "." makes the vault root the corpus. The index files
    # there are then the ones this function wrote last time, not legacy copies
    # to migrate: pulling them appended the previous index to every rebuild.
    if data_vault.resolve() == vault_dir.resolve():
        pulled: dict[str, str] = {}
    else:
        pulled = _pull_root_index_stubs(vault_dir)

    notes_by_folder: dict[str, list[tuple[str, str, Path, str]]] = {}
    by_title: dict[str, str] = {}
    coverage_to_titles: dict[str, list[str]] = {}
    outgoing: dict[str, set[str]] = {}
    type_counts: dict[str, int] = {}

    for note in sorted(data_vault.rglob("*.md")):
        if not _is_note_path(data_vault, note):
            continue
        fm, body = _parse_frontmatter(note)
        if fm is None:
            continue
        title = str(fm.get("title", note.stem))
        summary = _truncate_summary(str(fm.get("summary", "")))
        folder = note.parent.name
        cat = str(fm.get("coverage_category", "") or "").strip() or title
        notes_by_folder.setdefault(folder, []).append((title, summary, note, cat))
        by_title[title] = title
        coverage_to_titles.setdefault(cat, []).append(title)

        ntype = str(fm.get("type", "unknown"))
        type_counts[ntype] = type_counts.get(ntype, 0) + 1

        outgoing[title] = _outgoing_links(fm, body)

    all_titles_sorted = sorted(by_title.keys())

    # _index.md — grouped by folder; omit empty groups
    index_lines = [f"# Index — {vault_dir.name}", ""]
    for folder in sorted(notes_by_folder.keys()):
        entries = sorted(notes_by_folder[folder], key=lambda t: t[0].lower())
        if not entries:
            continue
        index_lines.append(f"## {folder}")
        index_lines.append("")
        for title, summary, _, _ in entries:
            index_lines.append(f"- [[{title}]] — {summary}")
        index_lines.append("")
    index_body = "\n".join(index_lines).rstrip() + "\n"
    if "_index.md" in pulled:
        index_body = (
            index_body.rstrip()
            + "\n\n## Migrated from vault root\n\n"
            + pulled["_index.md"].rstrip()
            + "\n"
        )

    # _concepts.md — one section per coverage_category
    concept_lines = [f"# Concepts — {vault_dir.name}", ""]
    for cat in sorted(coverage_to_titles.keys(), key=str.lower):
        concept_lines.append(f"## {cat}")
        concept_lines.append("")
        for t in sorted(set(coverage_to_titles[cat]), key=str.lower):
            concept_lines.append(f"- [[{t}]]")
        concept_lines.append("")
    concepts_body = "\n".join(concept_lines).rstrip() + "\n"
    if "_concepts.md" in pulled:
        concepts_body = (
            concepts_body.rstrip()
            + "\n\n## Migrated from vault root\n\n"
            + pulled["_concepts.md"].rstrip()
            + "\n"
        )

    # _graph.md — per-note link list.
    #
    # Issue #287: this used to fall back to "targets = every other note in
    # the vault" whenever a note's real outgoing set was empty, so a note
    # with zero outgoing links rendered an edge to ALL of them instead — the
    # opposite of the truth, disagreeing with :func:`inbound_link_counts`
    # (which reads the same :func:`_outgoing_links` edges and is documented
    # to agree with this emission), and O(n^2) noise in a large vault. A note
    # with no outgoing links now renders with no targets, honestly.
    graph_lines = [f"# Graph — {vault_dir.name}", ""]
    for title in all_titles_sorted:
        graph_lines.append(f"## {title}")
        graph_lines.append("")
        targets = sorted(outgoing.get(title, set()), key=str.lower)
        for dst in targets:
            graph_lines.append(f"- [[{dst}]]")
        graph_lines.append("")
    graph_body = "\n".join(graph_lines).rstrip() + "\n"
    if "_graph.md" in pulled:
        graph_body = (
            graph_body.rstrip()
            + "\n\n## Migrated from vault root\n\n"
            + pulled["_graph.md"].rstrip()
            + "\n"
        )

    idx_path = data_vault / "_index.md"
    con_path = data_vault / "_concepts.md"
    gra_path = data_vault / "_graph.md"
    idx_path.write_text(index_body, encoding="utf-8", newline="\n")
    con_path.write_text(concepts_body, encoding="utf-8", newline="\n")
    gra_path.write_text(graph_body, encoding="utf-8", newline="\n")
    for name in pulled:
        root = vault_dir / name
        # Never the file just written (a corpus_dir of "." makes them one).
        if root.resolve() != (data_vault / name).resolve():
            root.unlink(missing_ok=True)

    # Update AGENTS.md topic index section (unchanged behaviour vs legacy rebuild)
    agents_file = vault_dir / "AGENTS.md"
    if agents_file.exists():
        text = agents_file.read_text(encoding="utf-8")
        topic_lines = [
            "## Topic Index",
            "",
            *[f"- {ntype}: {count}" for ntype, count in sorted(type_counts.items())],
            "",
        ]
        topic_block = "\n".join(topic_lines)
        if "## Topic Index" in text:
            before, _, rest = text.partition("## Topic Index")
            _, _, after = rest.partition("## ")
            if after:
                new_text = before + topic_block + "## " + after
            else:
                new_text = before + topic_block
            agents_file.write_text(new_text, encoding="utf-8")
        else:
            agents_file.write_text(text + "\n" + topic_block, encoding="utf-8")

    return {"index": idx_path, "concepts": con_path, "graph": gra_path}


def rebuild(vault_dir: Path) -> None:
    """Rebuild Layer 1 files from current Layer 2 state (full rebuild).

    Deprecated: use :func:`rebuild_all` — this wrapper keeps the historical
    ``rebuild(vault_dir) -> None`` entrypoint used by the CLI.
    """
    rebuild_all(vault_dir)
