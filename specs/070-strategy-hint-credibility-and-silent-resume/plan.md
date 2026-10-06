# Implementation plan — spec 070

**Status:** EXECUTED 2026-08-26. Sequenced by what unblocks what, not by severity.
Stage 0 was diagnosed and fixed first as planned; see `tasks.md` §Outcome notes
for where reality diverged from the plan (Stage 0 cause, Stage 1 key shape,
Stage 4 dropped).

## Ordering constraint

**F5 (silent exit 1) comes first and alone.** Every other fix here is verified
by running a cycle, and no cycle can be run until resume works. Fixing F1
without F5 means shipping a credibility change nobody can exercise — which is
exactly the position this spec was written from.

## Stage 0 — F5: make the CLI say why it refuses (blocking)

**Diagnosis: DONE — see `spec.md` §F5 root cause.** Reproduction is reliable:

```bash
.venv/bin/python -m research_framework.cli generate \
  --spec <vault>/research.spec.md --output <vault> \
  --resume --max-usd 12 --max-cycles 3 > out.txt 2> err.txt
echo $?          # 1
wc -c out.txt err.txt   # 0 0
```

Known-good contrast: the same vault ran cycles 4-6 successfully ~40 minutes
earlier with `--resume --cycle 4`. `_pipeline/state.json` is untouched by the
failing invocation, so it aborts before the cycle runner starts. Candidates, in
the order they are cheapest to rule out:

1. an `argparse` / mutually-exclusive-flag path that exits before logging is
   configured (note `--dry-run` + `--resume` already exits 2 — a *different*,
   correctly-reported conflict, which suggests the arg layer does have exit
   paths of its own);
2. a resume precondition — cycle bounds against `spec.max_cycles` (4) versus
   `settings.pipeline.max_cycles` (20) versus `state.cycles_budgeted` (8), the
   vault having already reached cycle 6;
3. an exception swallowed by a bare `except` that returns a status code.

**Deliverable regardless of cause:** a CLI-level guard so that no `sys.exit(n≠0)`
can leave both streams empty. Print what was rejected, where it came from, and
what would make it valid. This guard is worth having even after the specific
cause is found — it is the difference between a five-minute fix and the
half-day this cost.

**Test:** a subprocess test asserting that a deliberately invalid resume
invocation exits non-zero AND writes >0 bytes to stderr. Assert on the stream,
not the message text, so it cannot rot.

## Stage 1 — F1: index a strategy-hint source's own url

`vault/credibility.py::build_credibility_context`, the `for repo in ds.repos`
loop. Add the source's own `url` to the same `defaults` index, keyed through
`normalise_source_id`, when `default_credibility` is set.

Care needed on **key shape**: `normalise_source_id` currently receives repo URLs
and local paths. A `data_sources[].url` is a bare origin (`https://eng.alpha.example/`)
while citations carry full paths (`https://eng.alpha.example/some-post`). If
`normalise_source_id` is exact-match on the full string, indexing the origin
alone will not match any real citation — resolve to host-level matching, and
reuse `credibility_catalog`'s existing `host`/`host_suffix`/`host_path` matcher
rather than inventing a second matching rule (the repo has already legislated
against second copies of a rule).

**Test:** a spec with one `kind: strategy_hint` source declaring
`url: https://example.org/` and `default_credibility: primary`; a note citing
`https://example.org/some/deep/path` resolves to `primary`. Regression test that
a source with `repos` keeps its current behaviour unchanged.

## Stage 2 — F2: ground person-scoped forge URLs

`data/credibility_catalog.yaml`. Either relax `github.com` to `min_segments: 1`
at `tier_2`, or add a sibling profile entry. Decide the same question for
`gitlab.com` and `codeberg.org` in the same change, so the three do not drift.

If the decision is instead "vault override", then `quickstart.md` MUST carry the
recipe, because the current default silently excludes an entire note type and
nothing tells the author.

**Test:** `github.com/<user>` resolves at `tier_2`; `github.com/<org>/<repo>`
still resolves at `tier_2`; bare `github.com/` does not resolve.

## Stage 3 — F3/F4: make the cycle summary tell the truth

Two independent reporting fixes, same stage because they touch the same summary.

**F3** — one line per cycle carrying created, quarantined and net, at one
severity. The current split ("0 note(s) created" at INFO, quarantine count at
WARNING, coverage divergence at WARNING) means the operator has to reassemble
the truth from three places and can reasonably conclude nothing happened.

This is the same defect spec 068 sees from the coverage side: the incremental
expectation counted quarantined notes as created (`expectation 20 (prior 16 + 4
created) != disk recount 18`). Fixing the count in one place should fix both —
confirm before assuming.

**F4** — a skipped required source carries its actual reason. If the reason is
genuinely unrecoverable, emit that explicitly rather than the string
`no reason given`, which reads as a bug in the message rather than an absence
of information.

**Test:** a cycle in which the verifier rejects every written note reports
non-zero written and non-zero quarantined, and does NOT report `0 created` alone.

## Stage 4 — F6: a note count that is not misleading

Not a defect (ADR-0005 alias behaviour is correct), but `find -name '*.md' | wc -l`
over a vault counts alias redirects as notes — 17 files for 9 real notes in the
subject vault, which was misread twice in one session.

A `--counts` output, or a line in the cycle summary, distinguishing real notes
from alias redirects from templates. Cheap, and it prevents an operator from
concluding the pipeline is producing noise when it is producing a correct graph.

## Out of scope

- The relevance classifier deciding *which* sources get searched (spec 069 FR4,
  already split to a follow-up). F4 here is only about reporting the decision,
  not changing it.
- Any change to what the researcher agent cites. The vault's citations were
  honest and correct throughout; every failure in this spec is on the
  framework's side of the line.
