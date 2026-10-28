"""Layer 1 rebuild — regenerates _index.md, _concepts.md, _graph.md from Layer 2.

Every link these files carry is ``[[stem|Title]]``: the target is the note's file
stem (what the validator and Obsidian resolve), the label is its title. The file
names, ``##`` headings and section structure are unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from research_framework.pipeline.wikilinks import _resolve_titlecase_stem
from research_framework.vault.corpus import corpus_dir
from research_framework.vault.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter,
)

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

# Framework documents that sit beside the notes when the corpus is the vault
# root (``vault.corpus_dir: "."``); they have no front matter and are not notes.
_ROOT_DOCS = frozenset({"AGENTS.md", "CLAUDE.md", "README.md", "CONTRIBUTING.md"})


def _parse_frontmatter(path: Path) -> tuple[dict | None, str]:
    """Return ``(frontmatter, body)``.

    ``frontmatter`` is ``{}`` for a readable note with none (or with malformed
    YAML) and ``None`` only when the file cannot be read at all. A note without
    front matter is still a note: it is listed under its file stem instead of
    dropping out of the indexes.
    """
    try:
        fm, body = parse_frontmatter(path)
    except UnicodeDecodeError:
        # Not UTF-8: skip it like any other unreadable note rather than abort
        # the whole rebuild.
        return None, ""
    except (OSError, FrontmatterParseError):
        try:
            return {}, path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None, ""
    return fm or {}, body


def _is_note_path(data_vault: Path, path: Path) -> bool:
    rel = path.relative_to(data_vault)
    parts = rel.parts
    if "_templates" in parts:
        return False
    if path.name in ("_index.md", "_concepts.md", "_graph.md"):
        return False
    return True


def _is_unfielded_non_note(rel: Path) -> bool:
    """Whether a front-matter-less file is tooling rather than a note.

    Only consulted for files with no front matter: with the corpus at the vault
    root, ``_pipeline/`` reports, hidden folders and the framework's own root
    documents are all markdown without front matter and must not be indexed.
    """
    if any(p.startswith(("_", ".")) for p in rel.parts):
        return True
    return len(rel.parts) == 1 and rel.name in _ROOT_DOCS


@dataclass
class _Note:
    rel: str  # posix path under the corpus, no suffix: "01 - Concepts/Foo"
    stem: str
    title: str
    summary: str
    folder: str
    category: str
    ntype: str
    links: set[str] = field(default_factory=set)  # raw targets, as written
    link: str = ""  # how the Layer-1 files link to this note


def _display(title: str) -> str:
    """A title safe to use as the label of a wikilink."""
    return " ".join(title.replace("|", "/").replace("[", "(").replace("]", ")").split())


def _load_notes(data_vault: Path) -> list[_Note]:
    """Every note under *data_vault*, in path order, each with its rendered link."""
    notes: list[_Note] = []
    for path in sorted(data_vault.rglob("*.md")):
        if not _is_note_path(data_vault, path):
            continue
        fm, body = _parse_frontmatter(path)
        if fm is None:
            continue
        rel_path = path.relative_to(data_vault)
        if not fm and _is_unfielded_non_note(rel_path):
            continue
        title = str(fm.get("title", path.stem))
        notes.append(
            _Note(
                rel=rel_path.with_suffix("").as_posix(),
                stem=path.stem,
                title=title,
                summary=_truncate_summary(str(fm.get("summary", ""))),
                folder=path.parent.name,
                category=str(fm.get("coverage_category", "") or "").strip() or title,
                ntype=str(fm.get("type", "unknown")),
                links=_outgoing_links(fm, body),
            )
        )
    stem_count: dict[str, int] = {}
    for n in notes:
        stem_count[n.stem.lower()] = stem_count.get(n.stem.lower(), 0) + 1
    for n in notes:
        # Two notes can share a stem in different folders; the path keeps the
        # link unambiguous (the validator accepts ``Folder/Note``).
        target = n.stem if stem_count[n.stem.lower()] == 1 else n.rel
        label = _display(n.title)
        n.link = f"[[{target}]]" if label == target else f"[[{target}|{label}]]"
    return notes


class _Resolver:
    """Map a wikilink target, as a note wrote it, to the note it points at.

    Follows the validator's lookup (``scripts/validate_vault.py::
    _related_target_resolves``): relative path, then file stem — case-insensitive,
    with space to ``_``/``-`` variants via ``wikilinks._resolve_titlecase_stem`` —
    and finally the note title, because notes also link by title.
    """

    def __init__(self, notes: list[_Note]) -> None:
        self._by_path: dict[str, _Note] = {}
        self._by_stem: dict[str, _Note] = {}
        self._by_title: dict[str, _Note] = {}
        for n in notes:  # path order: the first claimant of a name wins
            self._by_path.setdefault(n.rel.lower(), n)
            self._by_stem.setdefault(n.stem.lower(), n)
            self._by_title.setdefault(n.title.strip().lower(), n)

    def resolve(self, raw: str) -> _Note | None:
        target = raw.split("|", 1)[0].split("#", 1)[0].strip()
        if not target:
            return None
        lower = target.lower()
        if lower in self._by_path:
            return self._by_path[lower]
        stem = _resolve_titlecase_stem(lower.rsplit("/", 1)[-1], set(self._by_stem))
        if stem is not None:
            return self._by_stem[stem]
        return self._by_title.get(lower)

    def edges(self, note: _Note) -> list[_Note]:
        """The notes *note* links to: resolved, deduplicated, sorted by title."""
        found: dict[str, _Note] = {}
        for raw in note.links:
            hit = self.resolve(raw)
            if hit is not None:
                found[hit.rel] = hit
        return sorted(found.values(), key=lambda n: (n.title.lower(), n.rel))


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
    inbound links are present with a count of ``0``. A link counts toward the
    note it resolves to (by file stem, relative path or title); one that
    resolves to no note is ignored.
    """
    data_vault = corpus_dir(vault_dir)
    if not data_vault.is_dir():
        return {}

    notes = _load_notes(data_vault)
    resolver = _Resolver(notes)
    counts: dict[str, int] = dict.fromkeys((n.title for n in notes), 0)
    for note in notes:
        for dst in resolver.edges(note):
            counts[dst.title] += 1
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

    notes = _load_notes(data_vault)
    resolver = _Resolver(notes)
    notes_by_folder: dict[str, list[_Note]] = {}
    notes_by_category: dict[str, list[_Note]] = {}
    type_counts: dict[str, int] = {}
    for n in notes:
        notes_by_folder.setdefault(n.folder, []).append(n)
        notes_by_category.setdefault(n.category, []).append(n)
        type_counts[n.ntype] = type_counts.get(n.ntype, 0) + 1

    def by_title(group: list[_Note]) -> list[_Note]:
        return sorted(group, key=lambda n: (n.title.lower(), n.rel))

    # _index.md — grouped by folder; omit empty groups
    index_lines = [f"# Index — {vault_dir.name}", ""]
    for folder in sorted(notes_by_folder.keys()):
        index_lines.append(f"## {folder}")
        index_lines.append("")
        for n in by_title(notes_by_folder[folder]):
            index_lines.append(
                f"- {n.link} — {n.summary}" if n.summary else f"- {n.link}"
            )
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
    for cat in sorted(notes_by_category.keys(), key=str.lower):
        concept_lines.append(f"## {cat}")
        concept_lines.append("")
        for n in by_title(notes_by_category[cat]):
            concept_lines.append(f"- {n.link}")
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
    # (which reads the same edges) and O(n^2) noise in a large vault. A note
    # with no outgoing links renders with no targets, honestly. A target that
    # resolves to no note is not an edge: writing it out would put a dead link
    # in the index.
    graph_lines = [f"# Graph — {vault_dir.name}", ""]
    for n in sorted(notes, key=lambda n: (n.title, n.rel)):
        graph_lines.append(f"## {n.title}")
        graph_lines.append("")
        targets = resolver.edges(n)
        for dst in targets:
            graph_lines.append(f"- {dst.link}")
        if targets:
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
