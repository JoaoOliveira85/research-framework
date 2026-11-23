# Contract: the backlog view (`_pipeline/research-backlog.md`)

Rendered from `_pipeline/state/research-backlog.json` on every write and
before any step that reads it. Git-ignored. Read by the scout agent and by
the operator; **never parsed by code** (FR-016).

## Layout

```markdown
# Research Backlog

> Generated from `_pipeline/state/research-backlog.json` — edit that file,
> not this one. A change made here is overwritten on the next write; the
> overwritten text is kept once at `_pipeline/research-backlog.md.overwritten`.

## Follow-on topics (harvest)

- **<title>** — cited by <N> note(s): `<path>`, `<path>`, `<path>` (+<k> more) · first seen cycle <a>, last seen cycle <b> (<n> cycles)

## Notes to update

- **<stem>** — <reason> · as of <date or "unknown"> · <n> prompting source(s)

### Set aside after <N> failed attempts

- **<stem>** — <reason> · as of <date or "unknown"> · <n> prompting source(s) · last failure (cycle <c>): <why>

## Found by discovery

- **<title>** — scope area: <area> · <n> source(s)

## Flagged by the researcher

- **<title>** — <detail> · first seen cycle <a>

## Quarantined notes

- **<stem>** — rewrite the quarantined note (<detail>)
- **<stem>** — retry the refresh; previous content restored (<detail>)

## Added by the operator

- **<title>** — <detail>

## Proposed tangents (advisory)

- **<title>** ⚠️ (<relation> of [[<parent_note>]]) — <detail>

## Carried over from the old backlog

- <the migrated line, verbatim>

## Unmet coverage categories

- `<category>` [<note_type>] — <met>/<target> (required)

_<R> resolved and <D> dropped entries are kept in the JSON file._

<!-- research-backlog-view sha256=<hex> -->
```

## Rules

1. Sections appear in this order (FR-017: harvest, notes to update (spec 087),
   found by discovery (spec 088), researcher, quarantine, operator, proposal, migrated, then coverage). A section with no open entry
   is omitted, heading included. The header, the summary line and the footer
   are always present.
2. Only `open` entries are listed. "Notes to update" lists `update` entries in
   `update_topics()` order (`new_material` first, then oldest `as_of`, missing
   last, then store order); entries at `pipeline.update_max_attempts` failed attempts are
   listed after them under the `### Set aside after <N> failed attempts` sub-heading
   (omitted when none), each with its last failure; every other section is ordered as follows. Within a section, entries are ordered by
   `first_seen_cycle` (nulls last), then store order.
3. A topic entry is listed under the section of its `origin`, except that an
   entry with `citation_count >= 1` is listed under "Follow-on topics"
   whatever its origin — the same evidence rule the planner uses (FR-012).
4. At most three `cited_from` paths are shown, then `(+k more)`.
5. "Unmet coverage categories" is read live from the coverage targets
   (`083`'s `coverage_targets_path`), never from the store (FR-011). If that
   file is missing or unreadable the section is omitted.
6. The last line is the footer: the SHA-256, in lowercase hex, of every byte
   that precedes the footer line. Text ends with a single newline.
7. **Hand-edit detection** (FR-018, `research.md` R4): before rendering, the
   module recomputes the digest of the file on disk. A mismatch, or a file
   with no footer while the store exists, means the file was changed outside
   the module: its current text is copied to
   `_pipeline/research-backlog.md.overwritten` (one copy, replaced each
   time), a `WARNING` names the JSON file and the copy, and the view is
   overwritten. An identical re-render writes nothing.
8. A Markdown backlog with no footer and **no** store is not a view: it is an
   unconverted legacy backlog (FR-020).
