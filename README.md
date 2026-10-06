# research-framework

Turn a one-page topic description into a living knowledge vault that cites its
sources and keeps itself current. You describe what you want to learn in a
spec; research-framework runs an autonomous research loop that scouts public
sources, writes cross-linked Markdown notes citing the primary sources, and
validates every claim with scripts before anything ships. The result is a
plain-Markdown vault (Obsidian-friendly, git-backed) you query in plain
English through `./vault ask`, with answers that cite both the vault's notes
and the original sources. It runs locally against the LLM CLIs you already
use — no SaaS, no lock-in.

---

## About this project

I built this to keep my own knowledge vaults current, and as a hands-on way to
learn how far AI coding agents can carry a real, long-running codebase. The
code was written by AI agents under my direction; I'm sharing it because it
may be useful to others.

- **Tools** — [Cursor](https://cursor.com) and
  [Claude Code](https://claude.com/claude-code), with Claude models from
  Sonnet 4.6 up to Fable 5.1.
- **Guard rails** — a spec-driven workflow
  ([spec-kit](https://github.com/github/spec-kit)) with a written constitution
  and a spec per feature, a large test suite, a mandatory smoke gate and a
  guard battery. They are what keep agent-written code honest.
- **History** — this repository starts at v1.0.0, its first public release.
  It was recreated from a private development repository with personal and
  workplace details removed; the private versions (0.1.0 – 1.2.0) are
  summarised in [`CHANGELOG.md`](./CHANGELOG.md#before-the-public-release).

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the system design and
[`CONTRIBUTING.md`](./CONTRIBUTING.md) for the development workflow.

---

## Quick start

### Install (development)

```bash
git clone https://github.com/JoaoOliveira85/research-framework.git
cd research-framework
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install -e ".[reports]"   # optional: fpdf2 PDF rendering for audit-report.md
pytest -m "not e2e"           # the fast local loop (count: docs/testing-strategy.md TL;DR)
```

### Install (end users)

There is no PyPI publication (spec 041 is a v2.0.0 candidate on the
roadmap). Install from GitHub Releases — the bundle tarball carries
`install.sh`, scripts, templates, every settings profile and the example
spec:

```bash
# Current stable is v1.0.0 (2026-10-06); check the Releases page for newer
curl -L https://github.com/JoaoOliveira85/research-framework/releases/download/v1.0.0/research-framework-1.0.0.tar.gz \
  | tar -xzf - -C /tmp
cd /tmp/research-framework-1.0.0
./install.sh ~/vaults/my-vault          # scaffolds + installs the framework
```

See [`docs/RELEASE.md`](./docs/RELEASE.md) for the full install / upgrade
flow. `./vault update` re-scaffolds framework-owned files (spec 027); the
caveat is that
user-owned files such as `settings.yaml` are never rewritten by an update
(RELEASE.md § Migration notes).

### Build your first vault

1. **Write a spec.** Use the `vault-spec` skill for a guided dialogue, or
   start from the tracked example:
   - `examples/research.spec.md` — the simple format (with
     `examples/settings.yml` beside it)
   - `examples/detailed-vault-spec.md` — a book-scale detailed-format
     spec; the detailed format is what the `vault-spec` skill produces
2. **Generate the vault:**
   ```bash
   research-framework generate --spec my-vault-spec.md --output ~/vaults/my-vault
   ```
3. **Use it:**
   ```bash
   cd ~/vaults/my-vault
   ./vault research              # add more notes
   ./vault ask "what is X?"      # query it
   ./vault audit                 # check freshness + quality
   ```

---

## What you get

A vault is a folder. Inside it:

```text
my-vault/
├── research.spec.md       # YOUR input — what the vault should cover
├── data_vault/            # The actual knowledge, organised by note type
│   ├── 01 - Concepts/     # (or whatever your spec declares)
│   ├── 02 - Companies/
│   ├── _index.md          # Auto-rebuilt route to everything
│   └── ...
├── _pipeline/             # Pipeline state (sources DB, cycle reports, etc.)
├── _templates/            # The note shape this vault enforces
├── modules/               # Pluggable source extractors (shipped: code, github, atlassian, oreilly, reddit, rss, youtube)
├── AGENTS.md              # How agents should query this vault
├── CLAUDE.md              # Claude Code workspace rules
└── vault                  # Uniform script: research / ask / audit / status / digest …
```

Every note in `data_vault/` is plain Markdown with frontmatter:

- A summary you can read in 5 seconds.
- A body that answers the type-specific questions ("What is this thing? What
  problem does it solve? What are the alternatives? What are the
  trade-offs?").
- `[[wikilinks]]` to every related concept — Obsidian's graph view lets you
  see the topology at a glance.
- `source_urls` in frontmatter pointing at the **primary external sources**
  the note was synthesised from.

When you (or an agent) query the vault:

- `./vault ask "How does CRDT conflict resolution differ from CAP-bounded eventual consistency?"`
  → returns an answer grounded in your vault's notes, with **both** Tier 1
  (vault wikilinks) AND Tier 2 (original source URLs) cited distinctly. If
  the vault doesn't know, it triggers a focused mini-cycle to find out —
  then re-answers.
- `./vault write "5-page brief on the embedded firmware security landscape"`
  → *listed by the shim, not runnable today*: the verb execs a
  `scripts/generate_doc.py` that does not ship (spec 077 D2 / T001 decides
  whether to build it or delete the verb). The `/write` prompt it would use
  is rendered in `docs/prompts/`.
- `./vault research`
  → runs the next research cycle. Discovers new topics, refreshes stale
  notes, fills coverage gaps, never duplicates.
- `./vault audit`
  → runs the validators + an LLM-assisted source-relevance check, produces
  a markdown report.

The vault is consumable by humans (open it in Obsidian, browse the graph,
read notes directly) AND by agents (Claude Code reads `AGENTS.md` + the
index files, then drills in via wikilinks). Same content, two interfaces.

---

## Why this exists

**The 30-second pitch**: I kept running into knowledge needs that don't
fit "go read this one book" — staying current in a fast-moving field,
keeping a deep engineering reference, tracking the context around a domain.
Each one required continuously synthesising hundreds of evolving sources
into something I could *query*, not just *re-read*.

The first attempts (Notion databases, bookmark piles, ad-hoc Claude
sessions, hand-written notes) all failed for the same reasons:

1. **They didn't answer questions** — they accumulated sources I'd have to
   re-read to get a specific answer.
2. **They had no quality discipline** — claims were ungrounded, citations
   inconsistent, "draft" notes lingered forever.
3. **They drifted** — the world moved, the notes didn't.
4. **They couldn't be trusted** when an LLM read them — confident prose
   with no grounded sources is worse than no notes at all.

research-framework is the answer: an opinionated factory that produces
knowledge vaults with the same rigor a competent human researcher would
apply, *enforced by scripts not by trust*. Verifier rejection rates,
two-tier citation, stub detection, source preflight, dynamic coverage
expansion — all of it is enforced at the gate level, not requested.

---

## What makes it different

A non-exhaustive list of design decisions that distinguish this from
"another RAG tool" or "another note-taking system":

### Validation is enforced by scripts, not by agent self-judgment

Every phase transition has a script that decides go / no-go. An agent
saying "the notes look good" is not validation; `validate_vault.py`
returning exit code 0 is validation. This rules out the failure mode where
an agent generates 50 stub notes, declares the vault done, and you discover
months later that nothing is actually grounded.

### Two-tier citation is non-negotiable

Constitution Principle IX: every answer cites BOTH the vault notes it drew
from AND the original external sources those notes were built from. An
independent verifier agent rejects any output that lacks either tier. The
mechanism is built so the verifier *cannot* pass output that bypasses the
vault — even a well-meaning LLM that "knows the answer" gets rejected and
re-prompted. **You get answers, not vibes.**

### Stub-as-Fuel: the loop refuses to declare done while gaps exist

If the vault has stub notes, orphan wikilinks, or unresolved backlog items,
the next research cycle uses them as PROMPTS for what to learn next. The
loop terminates cleanly only when scouts find no new topics, the backlog
is empty, no stubs remain, AND coverage targets are met. Cap a run at a
budget if you must (it'll exit with a punch-list for `--resume`) — but it
won't fake completion.

### Domain-agnostic by construction

Whether your vault is about Java microservices, embedded firmware, ML
research, legal case law, or gardening — the framework produces
the same quality of work. The spec file is the *only* source of domain
knowledge. We don't bake "tech" assumptions into the prompts or templates;
when we accidentally do, we rip them out the moment we notice. (See
constitution amendment 1.3.2 for the painful detail.)

### Every change to a vault is a git commit

Constitution Principle X: every framework operation that mutates a vault
auto-commits to git. Research cycles run on a dedicated
`research/<timestamp>` branch with per-cycle commits, a completed run lands
on `main` and leaves the checkout there (spec 072), framework upgrades commit
directly on `main`, and `./vault ask` commits its output. Bad runs are one
`git revert` away.

### Single LLM dispatch surface

Every LLM call in the framework flows through one file (`scripts/agent_call.py` — spec 078).
That file knows which model to use, which runtime (claude / codex / API /
local), what tier, what budget. Cost tracking, hard caps, audit logs — all
single-point. You can swap from Claude to Codex to a local model without
changing anything outside that file. The framework is vendor-agnostic at
the architecture level; the configuration just decides what backend to use.

### Offline-first; no cloud lock-in

Constitution Principle V: research-framework MUST be fully operable
offline. No telemetry. No phone-home dependencies. Your vault is your
content; it never leaves your disk unless YOU explicitly push it. The
framework runs entirely against local files + the LLM CLIs you've
authenticated separately.

### Sources have value ratings, not just URLs

`_pipeline/sources.db` tracks per-cycle yield for every source. Sources
that consistently produce useful, well-cited notes earn rating points;
sources that produce nothing get marked for archival. Spec-declared
sources are locked (never auto-archived); auto-discovered sources can
deprecate. The vault knows which of its sources are paying their keep.

### Designed for multiple LLM backends

Stage-by-stage you can choose tier (`basic` / `normal` / `flagship`) and
vendor. Scout runs on cheap Haiku-equivalent; note-writing runs on
sonnet; final verification runs on flagship. The cost/quality knob is
explicit in `settings.yaml`, not buried in the prompt code.

### Sequenced on purpose — quality first, then an unattended operator surface, then contracts

The quality measurement harness (spec 022) shipped before the feature waves
so every release could be checked against it. The current ordering — make
the weekly pipeline run unattended (v1.1.0) before giving sibling repos a
contract to build against (v1.2.0) — is in `docs/ROADMAP.md`
§ Sequencing decisions. A local / self-hosted model path is always
supported: `settings.ollama.yaml` and `settings.opencode.yaml` ship in every
release, and what a local model can *complete* is tracked in spec 065.

---

## Symbiotic with `assistant-framework`

Long-horizon plan: the three "flows" (research / maintenance / query)
become deployment-time separable services that compose.

- **research-framework** (this repo) is the FACTORY — takes a spec,
  produces / refreshes a vault. Can serve N vaults.
- **The vault** is the ARTIFACT — plain Markdown, portable, self-contained.
  Lives in git. Queryable via `./vault ask` without research-framework being
  present.
- **`assistant-framework`** (sibling project, separate repo) is the QUERY +
  WORKFLOW layer — routes user queries, picks the right vault(s), composes
  multi-vault answers, surfaces them to humans / agents / MCP clients.

The contract surface between the three is **flat files** (the vault is the
contract) plus the stable `./vault` subprocess interface. No in-process
coupling. Specs 023 and 036 carry the architectural detail; the
sequencing is `docs/ROADMAP.md` v1.2.0.

This shapes decisions we make NOW (no premature `VaultHandle` abstraction;
no daemon mode; vault state always under vault root) — even though the
formal split is still ahead: spec 023 shipped Phase 1
(`refresh-sources`, `regenerate-shim`, atomic writes); Phase 2
(`VaultHandle`, multi-vault — #43) and the contract spec 036 (#52) are
roadmap v1.2.0.

---

## Per-vault scripts

Every generated vault ships with a uniform `./vault` script (this is what
`assistant-framework` and other downstream consumers call):

```bash
./vault research              # next research cycle(s) — forwards to `generate --resume`; --log-level {debug,info,warning,error}
./vault health                # deterministic health check (fast, no LLM); warns on untracked control files (spec 058)
./vault audit                 # deterministic audit -> _pipeline/audit-report.md (--full's LLM half is an unwired placeholder: SKIP)
./vault ask                   # open Claude in the vault dir; /ask <question> answers with two-tier citations
./vault write "topic"         # LISTED, NOT RUNNABLE — its backing script does not ship (spec 077 D2 / T001)
./vault update                # pip upgrade + re-run install.sh; refreshes vault-local scripts (spec 027)
./vault coverage              # coverage target status
./vault reindex               # rebuild index files
./vault sync                  # commit + push vault notes to git
./vault refresh-sources       # re-run collectors against active sources (spec 023 Phase 1)
./vault regenerate-shim       # re-render this script from its template (spec 023 Phase 1)
./vault status                # live cycle progress, read-only (spec 048 v1.1)
./vault digest --last-week    # deterministic cross-cycle roll-up, LLM-free (spec 035)
./vault acceptance            # framework-generic acceptance gates → _pipeline/acceptance/ (spec 063)
./vault wikilinks [--fix]     # acronym-wikilink sweep (spec 067)
./vault re-grade              # re-grade quarantined notes against the credibility catalog (spec 066; alias: regrade)
./vault maintain              # NOT RUNNABLE — exits 1 naming the missing spec-023-Phase-2 script
./vault help
```

That is the 18-verb surface spec 077 FR-008 pins. Its FR-011 requires a
verb whose backing script is absent to say so and exit non-zero:
`maintain` does; `write` execs the missing file and fails less legibly,
which is 077 T001 (ship the script or delete the verb). The
`research-framework` console script has 21 verbs of its own (077 FR-004).

Schedule a weekly digest with cron or launchd (explicit opt-in — the verb never auto-runs):

```bash
(cd ~/vaults/<vault> && ./vault digest --last-week)
```

Every cycle writes a Tier-6 audit file at `<vault>/_pipeline/cycles/cycle-NNN/bridge.log`
capturing extractor-subprocess stderr verbatim (spec 048 — `tail -f` it live).

Per-vault validators are also callable standalone:

```bash
python scripts/validate_vault.py ~/vaults/my-vault
python scripts/check_template_compliance.py ~/vaults/my-vault
python scripts/check_acronym_links.py ~/vaults/my-vault
python scripts/vault_metrics.py ~/vaults/my-vault
python scripts/vault_audit.py ~/vaults/my-vault          # deterministic
python scripts/vault_audit.py ~/vaults/my-vault --full   # + LLM checks: not wired yet, reports SKIP
```

---

## Building a release bundle

```bash
bash build.sh
# → build/wheel/research_framework-<version>-py3-none-any.whl
# → build/bundle/research-framework-<version>/
# → build/research-framework-<version>.tar.gz
```

The tarball is the shipping artefact. Its contents are documented in
[dist-templates/README.md](./dist-templates/README.md). The smoke gate
in `build.sh` is mandatory — there is no `--skip-smoke` flag (see
[ADR-0007](./docs/adr/0007-smoke-gate-is-mandatory.md)).

---

## Testing

```bash
pytest -m "not e2e"   # fast local loop (unit + integration + contract + tier-2/3/4 + smoke) — ~6-7 min
pytest                # full sweep including tier-5/6 cycle e2e (per ADR-0008) — ~12 min
pytest -m e2e         # only tier-5/6 e2e — ~7 min
python scripts/guards/run_all.py   # guard battery — portability + every corpus guard, one summary
ruff check .          # lint baseline — must be clean (zero errors)
ruff format --check . # format baseline — separate gate, also must be clean
bash build.sh         # smoke gate (hard); mandatory on pipeline-touching changes
bash build.sh --quality  # smoke gate + spec-022 quality harness (3 fixtures + 3 metric families + regression diff)
```

The test count lives in exactly one place — the `<!-- test-count: … -->`
marker in [`docs/testing-strategy.md`](./docs/testing-strategy.md)'s TL;DR —
and `tests/docs/test_one_source_per_fact.py` fails the suite when it drifts
from a live `pytest --collect-only -q`. **Seven-tier pyramid** per ADR-0008
(unit / schema / integration / component / cycle e2e / multi-cycle e2e /
smoke gate); ruff baseline at zero errors. The mandatory smoke gate
(ADR-0007), the guard battery (`python scripts/guards/run_all.py`) and the
spec-022 quality gate (`build.sh --quality`) together protect against
correctness regressions, doc drift and quality drift. They run in CI only
on version tags and by hand — the local run is the merge gate
(`CONTRIBUTING.md` § 1).

Constitution principle III (TDD,
NON-NEGOTIABLE) applies — write tests alongside any new script. Tier
guidance + anti-patterns are in [`docs/testing-strategy.md`](./docs/testing-strategy.md).

---

## Onboarding (for contributors and agents)

Read in order (about 1 hour total):

1. [`.specify/memory/constitution.md`](./.specify/memory/constitution.md) — the inviolables
2. [`ARCHITECTURE.md`](./ARCHITECTURE.md) — system design
3. [`CONTRIBUTING.md`](./CONTRIBUTING.md) — spec-kit workflow, TDD discipline, doc taxonomy
4. [`docs/testing-strategy.md`](./docs/testing-strategy.md) — the test pyramid
5. [`docs/ROADMAP.md`](./docs/ROADMAP.md) — what ships next, in what order, and why
6. [`docs/adr/README.md`](./docs/adr/README.md) — durable decisions index

After that, you're current.

---

## Reference documents

- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — system design (read first if you're new)
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — spec-kit workflow, TDD discipline, doc taxonomy
- `specs/` — every feature spec, active ones at the top level and finished ones under `specs/_archive/`; [`specs/README.md`](./specs/README.md) is the guarded index with each spec's Status
- `docs/adr/` — cross-cutting architectural decisions
- [`docs/ROADMAP.md`](./docs/ROADMAP.md) — shipped registry, the next two releases as ordered tiers, and the Deferred table
- [`docs/RELEASE.md`](./docs/RELEASE.md) — maintainer release process + user install/update
- [`docs/TODO.md`](./docs/TODO.md) — scratchpad for un-triaged ideas (often empty)
- [`docs/testing-strategy.md`](./docs/testing-strategy.md) — the seven-tier test pyramid (ADR-0008) + tier decision flow
- [`dist-templates/README.md`](./dist-templates/README.md) — end-user bundle documentation
- [`.specify/memory/constitution.md`](./.specify/memory/constitution.md) — immutable project constraints (v1.6.0)
- [`CHANGELOG.md`](./CHANGELOG.md) — release-by-release notes (current stable: **1.0.0**)
- Example spec: [`examples/research.spec.md`](./examples/research.spec.md) (+ [`examples/settings.yml`](./examples/settings.yml)); [`examples/detailed-vault-spec.md`](./examples/detailed-vault-spec.md) is a detailed-format example

---

## Specs at a glance

[`specs/README.md`](./specs/README.md) — one row per spec with its Status,
guarded by `tests/docs/test_spec_index_completeness.py` so it cannot drift.

---

> *"The next massive software failure will probably not come from a missing
> line of code. It will come from a missing sentence."* — César Soto Valero
>
> The vault is the missing sentences.
