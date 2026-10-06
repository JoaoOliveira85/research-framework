# The archived spec corpus

These folders are **history, not description**. They record how the system
got here. Nothing in this directory describes how anything works today, and
nothing here should be planned against.

They arrived by `git mv`, so `git log --follow` still reaches every earlier
revision, every folder keeps its original `NNN-kebab-name`, and every
citation elsewhere in the repo is fixable by inserting one path segment.
Nothing was deleted. Their numbers stay allocated forever
([`../README.md` § The numbering rule](../README.md#the-numbering-rule)).

## The rule that put a folder here

A spec is archived when it is one of the following **and** no tracked file
outside `specs/` opens a file inside it:

1. **Tombstoned or superseded** — its own Status header says
   `superseded(by …)`, or its `spec.md` carries the `# tombstoned` banner.
   The banners are bidirectional: the superseding spec names it back.
2. **A pre-format problem statement** — the 0.2.x-era specs (004–008), which
   predate the spec-kit template and are prose descriptions of a problem
   rather than numbered requirements. All shipped; nothing in them is a live
   contract.
3. **A 015x consolidation draft** — spec 015 split into `015a`–`015h`
   mid-flight, and ADR-0009 then subsumed the consolidation. `015f` stayed
   active because `src/research_framework/processors/_common.py` reads its
   `contracts/raw-item.schema.json`.
4. **A vault-instance plan** — a spec written to produce one particular
   vault, not a framework capability.
5. **A refactor diary** — a record of a code-motion pass, with no behaviour
   contract of its own.

The "no tracked file outside `specs/` opens a file inside it" half of the
rule is why `013-vault-migrator` (superseded) and `017-vault-quality-fix`
(a vault-instance spec) are still in the active corpus: tests load their
`contracts/` files by path. Archiving those means moving the reference too,
which is a code change, not a corpus change — see the "Deliberately left out"
note in the PR that created this directory.

That half is now **enforced**, not stated:
`tests/docs/test_spec_index_completeness.py::test_no_tracked_file_outside_specs_opens_a_file_in_the_archive`
walks the tracked tree for a string literal naming this directory as a path
(prose in a comment or a docstring is fine; a `Path` component or a written-out
`specs/_archive/...` is not). It was written because the rule had exactly one
violation and nothing said so: `015g-pipeline-orchestrator-command/contracts/
pipeline-state.schema.json` described `_pipeline/pipeline-state.json`, a file
the runner writes today, and `tests/contracts/test_json_schema_validation.py`
opened it here. The schema moved to `specs/075-pipeline-runner/contracts/` —
075 supersedes 015g as the runner's owning document (#295).

## What is here, and where its subject lives now

| Category | Folders | Where the subject lives now |
| --- | --- | --- |
| Tombstoned / superseded | `010-flow-separation`, `011-llm-routing`, `012-multi-vault`, `014-reusable-collectors`, `015-pipeline-consolidation`, `015g-pipeline-orchestrator-command`, `031-git-boundary`, `034-runtime-consolidation`, `046-vault-specialities-plugin-model`, `047-backend-agnostic-agent-layer` | Each folder's own Status header names its successor. The two that owned trunk behaviour — `015g` (the seven-phase runner) and `034` (dispatch) — are replaced by `075-pipeline-runner` and `078-dispatch-surface`. |
| Pre-format problem statements | `004-python-pipeline`, `005-adaptive-sources`, `006-vault-audit`, `007-autonomous-vault-settings`, `008-vault-script` | `008`'s subject (the `./vault` script) is now specified in `077-cli-contract`. The rest shipped into the pipeline and are described by ARCHITECTURE.md. |
| 015x consolidation drafts | `015a-corpus-folder-name`, `015b-vault-inventory`, `015c-vault-onboarding`, `015d-note-types-first-class`, `015e-agent-definitions-as-templates`, `015h-retire-vault-local-scripts` | ADR-0009 (`docs/adr/0009-collectors-vs-modules-reconciliation.md`). `015d`'s note-type taxonomy is now specified in `079-note-format`. |
| Refactor diaries | `025-simplify-pass`, `049-cycle-helpers-split` | The code they moved. `025`'s contracts are still cited by `028-dispatch-telemetry`, which is where the dispatch-telemetry contract now lives. |

## Guards

`tests/spec/test_acceptance_coverage_guard.py` skips anything under this
directory, matched on the `_archive` path segment rather than a folder
allowlist — a guard that had to be told each new archived name would fail
open the first time someone forgot. `tests/docs/test_spec_status_headers.py`
and `tests/docs/test_shipped_tasks_are_a_ledger.py` glob `specs/*/spec.md`
non-recursively, so they never saw this directory in the first place.

`tests/docs/test_spec_index_completeness.py` requires every folder here to
appear in [`../README.md`](../README.md)'s Archived table.
