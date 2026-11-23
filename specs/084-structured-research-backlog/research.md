# Research: The research backlog as structured state (084)

Phase 0 of the plan. The spec's § Evidence and § Clarifications carry the
reader/writer inventory and the owner decisions; this file records the
design decisions the plan adds on top, each as decision → rationale →
alternatives. Code citations are against `bc39eae`; `083` citations are
against its spec draft at `105519f` (branch `083-durable-state-layout`).

## R1 — Where the module lives and how writers reach it

**Decision**: one module, `src/research_framework/pipeline/backlog.py`. It
exposes typed *observations* (`observe_topic`, `observe_quarantine`,
`resolve_quarantine`, `resolve_covered`) and one transaction primitive
(`update(vault, writer, fn)`), not a writable entry list. Writers never
hold a mutable entry; the module applies an observation under FR-007's
field-ownership rule.

**Rationale**: FR-007 ("a writer changes only the fields it owns") is only
enforceable if the writer cannot reach the other fields. An API that hands
out dicts turns the ownership rule back into a convention, which is the
condition the spec exists to end. The vault-local `scripts/topic_harvest.py`
and `scripts/topic_propose.py` already import `research_framework`
(`pipeline.atomic_write`), so calling the module adds no import path.

**Alternatives**: (a) a `Backlog` dataclass passed around and saved by the
caller — rejected, ownership is unenforced; (b) moving harvest/propose into
`src/` — larger, and out of scope (`003` owns those stages).

## R2 — The store's path comes from `083`'s layout module

**Decision**: the module obtains `state/research-backlog.json` and
`state/research-backlog.pre-migration.md` from `083` FR-004's layout module
and registers both in `083` FR-002's state set. It spells only the view's
and the overwritten copy's paths (they are not state).

**Rationale**: `083` FR-004/FR-005 make a second spelling of a state path a
guard failure. Owner decision Q1 orders `084` after `083`, so the module
exists when this lands.

**Alternatives**: spelling the path locally until `083` lands — moot under
Q1.

## R3 — Conversion is a step in `083`'s ordered migration, not a lazy side effect

**Decision**: the Markdown-to-JSON conversion is the second step of `083`
FR-018's ordered update-time migration (after `083`'s layout move), run by
`./vault update` and by `083`'s stand-alone migration command, with
`--dry-run`. It lands as its own `framework:` commit containing the new
store, the archive, and the removal of `_pipeline/research-backlog.md` from
the git index (`git rm --cached`; the file stays on disk and becomes the
view). This **revises** the spec's first-draft clarification "lazily, on the
module's first access" — FR-020 is amended accordingly.

**Rationale**: three constraints the lazy design breaks, all found while
planning:

1. `083` FR-015 — a command that writes state refuses (exit 2, naming the
   migration command) when state sits at a legacy path, and MUST NOT read
   the legacy path as a fallback. A lazy conversion inside a cycle is
   exactly that fallback.
2. Constitution III — a new vault-mutating operation takes `--dry-run` and
   is exercised on a fixture first. A conversion hidden in the first harvest
   has no dry run.
3. `083` FR-019's note — once the `.md` is a view it must leave the git
   index, or git keeps tracking it despite the ignore rule. Only a migration
   step that commits can do that cleanly; a cycle commit (`git add -A`)
   would instead record the deletion amid research output.

The draft's argument for lazy conversion ("the cycle's vault-local scripts
call the module first") no longer holds: under `083` FR-015 an unconverted
vault never reaches a cycle.

**Alternatives**: lazy conversion with a one-off commit from inside the
module — rejected for (1)–(3).

**Unconverted detection**: a vault is unconverted when the store is absent
and `_pipeline/research-backlog.md` exists without the view's footer
(R4). The module adds that predicate to `083`'s "is this vault migrated"
check; state writers then refuse through `083`'s existing path.

## R4 — Hand-edit detection: a digest footer in the view itself

**Decision**: the view ends with
`<!-- research-backlog-view sha256=<hex> -->`, the SHA-256 of every byte
above that line. Before rendering, the module recomputes the digest of the
current view; a mismatch, or a missing footer while the store exists, is a
hand edit (FR-018).

**Rationale**: self-contained. It needs no second file under `_pipeline/`
(scratch that `git clean` could remove while the view survives, producing a
false "hand edit"), no git, and no clock. A stale vault-local script writing
the old grammar fails the same check, which is the edge case the spec
names.

**Alternatives**: (a) mtime comparison — breaks on checkout and copy;
(b) a sidecar hash file — two files that can disagree.

## R5 — Detecting an operator's status change without a shadow file

**Decision**: each entry carries `status_by` and `status_written` — the
status value the module last wrote. On load, `status != status_written`
means someone outside the module changed it, and the module records
`status_by: operator` and `status_written: <status>` on its next write.
Writers move status only from `open`, and never on an entry whose
`status_by` is `operator` (FR-007/FR-008).

**Rationale**: the concrete hazard is an operator *reopening* a topic whose
note exists but is thin; FR-009's auto-resolve would close it again on the
next harvest. "Writers only move from `open`" alone does not stop that,
because the reopened entry *is* open. The in-entry shadow detects the
reopen with no git and no extra file. An operator who adds an entry by hand
has no `status_written`, which reads the same way: operator-owned.

**Alternatives**: comparing against `git show HEAD:` — needs git, and is
wrong for an edit committed by the operator; asking operators to set
`status_by` by hand — a rule nobody remembers.

## R6 — Identity: topic ids are origin-independent

**Decision**: `id` is `topic:<key>` for every topic origin and
`quarantine:<stem>` for pointers, where `<key>` is the title with internal
whitespace collapsed to single spaces, stripped and case-folded
(`" ".join(t.split()).casefold()`). The spec's FR-004 is amended from
"origin and key" to this.

**Rationale**: with origin in the id, an operator's topic "X" and the
harvest's later sighting of "X" are two entries, the planner queues one or
both, and the propose stage dedupes against neither consistently.
Origin-independent ids make them one entry whose `origin` records who saw it
first and whose observation fields record what the harvest saw since.

**Alternatives**: NFKC normalisation — no live title needs it, and it
silently merges distinct titles; keeping origin in the id — rejected above.

## R7 — What the planner queues: evidence, not origin

**Decision**: the planner queues an open, non-excluded entry when it is
operator-owned (`origin: operator`, or `status_by: operator` and open) **or**
it carries `citation_count ≥ 1` (it has been seen as a cited missing
wikilink). It does not queue an entry whose only evidence is a researcher
flag or a proposal. Score is the existing orphan formula over
`citation_count` (absent ⇒ 0). FR-012 is reworded to this.

**Rationale**: owner decision Q3 (harvest + operator, not researcher) stated
in terms of origin breaks on R6's merged entries: a topic first flagged by
the researcher and cited a cycle later has `origin: researcher` but is
exactly what today's planner queues (it matches `— cited by N` in a later
block). Keying on the citation evidence reproduces today's behaviour for
harvest topics exactly and adds Q3's operator entries.

**Alternatives**: queue by `origin` only — wrong for merged entries.

## R8 — The migration grammar

**Decision**: the converter recognises, inside and outside blocks:

| Line | Becomes |
| --- | --- |
| `- **T** — cited by N note(s): samples` (in a harvest block for cycle C) | topic entry; `first_seen_cycle` = min C, `last_seen_cycle` = max C, `seen_cycles` = number of blocks, `citation_count` and `cited_from` from the latest block |
| the same bullet outside any block | topic entry, `origin: operator`, its `citation_count` kept (today's planner reads it) |
| `- **T** — flagged by researcher` | topic entry, `origin: researcher` unless an earlier line created it |
| `- **T** ⚠️? (rel of [[P]]) — j` (propose block) | topic entry, `origin: proposal`, `relation`, `parent_note`, `scope_warn`, `detail` |
| `- [ ] rewrite quarantined note: S (…)` / `- [ ] retry refresh of S — …` (± `<!-- stem:S -->`) | quarantine entry `quarantine:S`, `kind` and `detail` from the **last** occurrence; duplicates collapse |
| seed boilerplate, block markers, block headings and their fixed prose lines, `` - `cat` [type] — m/n `` gap lines | not carried (counted in the INFO line) |
| any other non-blank line | `migrated` entry, `detail` = the line verbatim, id `migrated:<NNNN>` in file order |

A bullet opened with `- **` and no closing `**` on its line is joined with
the following lines until the closing `**` (at most 3 lines) before
matching — the wrapped-title shape found in 7 of 11 live vaults.

**Rationale**: these are every shape found in the eleven live backlogs
(spec § Evidence); "migrated verbatim" is the no-loss floor for anything
else, and the archive (FR-022) is the floor under that.

## R9 — The scout prompt and the prompt corpus

**Decision**: `templates/prompts/scout-prompt.md.j2` item 4 is rewritten to
describe the view's sections (FR-017 order), and the committed prompt corpus
is regenerated with `scripts/render_prompt_corpus.py`
(`tests/docs/test_prompt_corpus_is_current.py` fails otherwise). The two
fixtures that carry a rendered `scout-prompt.md` are re-rendered.

## R10 — No new ADR

**Decision**: the plan commits to no new ADR. "Durable control state is
structured; its Markdown is a rendered view, never parsed back" is decided
here for one file. `_pipeline/propose-rejects.md` has the same shape
(hand-editable Markdown parsed back by
`orchestrator._persistent_reject_titles`) and is now state under `083`; if
it is converted the same way, that second instance is the point to write
the pattern down as an ADR (rule of three is not needed for a format rule,
but one instance is not yet a pattern).

## R11 — Concurrency

**Decision**: none beyond atomic replace. The module re-reads the store
inside every `update` and writes with `atomic_write`, so a crash cannot
truncate it (F8), but two processes mutating one vault at once can still
lose one update. No vault lock exists today and the runner and the
orchestrator already assume one process per vault (spec § Assumptions).
