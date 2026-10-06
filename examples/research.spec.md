---
# =============================================================================
# Example research.spec.md — DETAILED FORMAT (recommended)
# =============================================================================
#
# This is the shape the `vault-spec` skill generates by default and the shape
# the framework's downstream stages (scout, note-writer, verifier, validator)
# are tuned for.
#
# The simple format (which used to live here pre-0.2.32) is now opt-in only
# and limited to throwaway one-shot vaults. The detailed format below is what
# produces the kind of vault you can actually query a year later.
#
# Domain chosen for this example: macro photography on analog film. It's
# deliberately niche, deliberately non-technical, deliberately not about
# software. The framework is domain-agnostic by construction (constitution
# 1.3.2 expansion of "Not opinionated about domain"; NB: distinct from the
# post-1.4.0 Principle X, which is the auto-commit invariant) — any subject
# with reachable sources and a clear scope works.
#
# Replace every value below with whatever your vault is actually about. Keep
# the keys, structure, and field semantics.
#
# Validate after editing:
#   python scripts/validate_spec.py --strict path/to/research.spec.md
#
# Generate:
#   research-framework generate --spec path/to/research.spec.md --output ~/Documents/<your-vault>
# =============================================================================

name: Macro Photography on Analog Film
location: /Users/jdoe/Documents/macro-film-vault
owner: jdoe

# ---------------------------------------------------------------------------
# scope — what is and isn't in this vault.
#
# Fail closed: the scout uses `boundaries` + `out_of_scope` as the literal
# include/exclude rules for proposing new topics. Vague boundaries here
# produce a sprawling vault that grows where you didn't intend.
# ---------------------------------------------------------------------------
scope:
  domain: "Macro photography on 35mm and medium-format analog film — the optical, exposure, and process techniques that shift from digital workflows when shooting at or above 1:1 magnification on film."
  organization: "Personal reference vault — used between shoots to choose gear, between developing rolls to debug exposures, and before buying gear to compare options."
  boundaries:
    - "Bellows, extension tubes, and reversed-lens setups on 35mm SLRs"
    - "Bellows and extension on 6×6 and 6×7 medium-format bodies"
    - "Exposure math at macro magnifications — bellows factor, effective aperture, diffraction limits"
    - "Reciprocity failure for popular B&W and colour negative stocks"
    - "Focus stacking workflows where the stacking happens post-scan"
    - "Flash vs. continuous light for high-magnification work"
    - "Film stocks evaluated specifically against macro use cases (grain, latitude, reciprocity behaviour)"
    - "Development tweaks for thin negatives caused by macro under-exposure"
  out_of_scope:
    - "Digital-sensor macro workflows (separate concern; different exposure model)"
    - "Studio product photography — different lighting + post-production constraints"
    - "Wildlife and nature photography that isn't macro-magnification"
    - "Gear reviews disconnected from technique — this is reference, not editorial"
    - "Personal trip planning or location-specific notes (vault is about technique, not memories)"
  contextual_questions:
    - "What is this technique precisely and what magnification range does it apply to?"
    - "What changes mathematically vs. shooting at infinity or at normal-portrait distances?"
    - "What does it look like in practice — what exposure, what aperture, what film?"
    - "What are the failure modes and how do you recognise them on the developed negative?"
    - "What's the canonical alternative and when would you reach for it instead?"

# ---------------------------------------------------------------------------
# note_types — the structural taxonomy for this vault.
#
# Each note_type drives:
#   - the folder it lands in
#   - the required_sections the note-writer must produce
#   - the contextual_questions that shape the writer's prompt
#   - the min_word_count enforced by the validator
#
# Pick types that map cleanly onto how YOU think about the subject. Five to
# eight is the sweet spot for most domains; a dozen is fine for deep ones;
# fifteen+ usually means you're conflating taxonomy with content and should
# rethink.
# ---------------------------------------------------------------------------
note_types:
  - name: concept
    description: "Foundational ideas — optical, physical, or photographic principles that hold regardless of specific gear"
    folder: "01 - Concepts"
    required_sections: ["Overview", "Why It Matters at Macro", "Math / Mechanics", "Trade-offs", "Related"]
    contextual_questions:
      - "What is this concept precisely?"
      - "How does it manifest differently at macro magnifications vs. normal distances?"
      - "What's the mathematical or physical relationship behind it?"
    min_word_count: 200

  - name: technique
    description: "A practical workflow you actually execute — exposure calculation, focus stacking, reversing a lens, etc."
    folder: "02 - Techniques"
    required_sections: ["Overview", "When to Use", "Step-by-step", "Common Failure Modes", "Alternatives"]
    contextual_questions:
      - "What does the photographer actually do, in order?"
      - "What inputs/measurements do you need before starting?"
      - "Where does this technique typically go wrong on film?"
    min_word_count: 250

  - name: gear
    description: "Specific hardware — a bellows, extension-tube set, lens, body, light, flash trigger — evaluated against its macro-on-film use case"
    folder: "03 - Gear"
    required_sections: ["Overview", "What It Is", "Use Case Fit", "Pros / Cons for Macro Film", "Alternatives"]
    contextual_questions:
      - "What is this piece of gear and what category is it in?"
      - "What macro-film use case does it serve best?"
      - "What's the next-step-up and the cheaper substitute?"
    min_word_count: 200

  - name: film-stock
    description: "A specific film stock evaluated against macro use — grain, reciprocity, latitude, dev behaviour"
    folder: "04 - Film Stocks"
    required_sections: ["Overview", "Reciprocity Behaviour", "Grain & Resolution", "Macro Suitability", "Push / Pull Notes"]
    contextual_questions:
      - "What's the reciprocity curve for this stock at the long exposures macro often demands?"
      - "How does grain hold up at 1:1 enlargement of the negative?"
      - "Is there a developer or dev tweak that suits this stock specifically?"
    min_word_count: 200

  - name: process
    description: "Darkroom or scanning processes — developer choices, dev time adjustments, scan workflows, post-stack alignment"
    folder: "05 - Processes"
    required_sections: ["Overview", "When to Use", "Process Steps", "Quality Checks", "Pitfalls"]
    contextual_questions:
      - "What stage of the workflow does this belong to?"
      - "What signal tells you the process worked? What signal tells you it didn't?"
    min_word_count: 200

  - name: source
    description: "A pointer to an external authoritative reference — book, paper, manufacturer manual, deeply-cited forum thread"
    folder: "06 - Sources"
    required_sections: ["Overview", "What's Useful Here", "Citation"]
    contextual_questions:
      - "Who wrote this and what are their credentials in this niche?"
      - "Which notes in this vault should cite this source?"
    min_word_count: 100

  - name: moc
    description: "Map of Content — entry-point index notes for each major area"
    folder: "00 - MOC"
    required_sections: ["Overview", "Index"]
    contextual_questions:
      - "What does this map cover and what are the headline notes a reader should start with?"
    min_word_count: 0

# ---------------------------------------------------------------------------
# data_sources — the universe the scout is allowed to consult.
#
# Each entry is a contract: name, type (internal/external), what the source
# contains, whether it's required, and how the pipeline accesses it. The
# scout will NOT propose topics from sources that aren't listed here. If a
# source goes stale or 404s during a cycle, validation surfaces it — see
# `validate_cycle.py`.
# ---------------------------------------------------------------------------
data_sources:
  - name: "Photrio (analog photography forum)"
    type: external
    description: "Long-form forum threads on analog technique. Strong for empirical reciprocity data and developer tweaks. Use for community-validated practice, not as a primary citation."
    required: true
    access_method: "web fetch"

  - name: "35mmc"
    type: external
    description: "Independent film-photography publication. Strong for stock comparisons and technique walkthroughs."
    required: false
    access_method: "web fetch"

  - name: "Manufacturer datasheets"
    type: external
    description: "Official film datasheets from Kodak, Ilford, FujiFilm, Foma, Adox. Authoritative for reciprocity curves, ISO ratings, dev times. MUST be the primary citation on any film-stock note."
    required: true
    access_method: "web fetch"

  - name: "Books — canonical references"
    type: external
    description: "Adams' The Negative; Lefkowitz's The Manual of Close-up Photography; Shaw's Closeups in Nature. Cite as Tier-2 sources via their bibliographic entry in the Sources folder."
    required: false
    access_method: "manual / bibliographic citation"

  - name: "Wikipedia"
    type: external
    description: "First-pass reference for optical concepts (bellows factor, diffraction, focal length) and to find primary-source citations to follow. Never the sole citation on a concept note."
    required: false
    access_method: "web fetch"

# ---------------------------------------------------------------------------
# search_dimensions — the axes the scout uses to vary topic generation.
#
# The framework ships five default dimensions. You typically don't change
# this; you change which ones are emphasised via the spec's narrative scope.
# ---------------------------------------------------------------------------
search_dimensions: ["technical", "organizational", "domain", "market", "temporal"]

# ---------------------------------------------------------------------------
# coverage_targets — what "done" looks like.
#
# The Phase 3 gate compares actual note counts per note_type against the
# target_count below. Targets that are `required: true` MUST be met for
# the vault to exit Phase 3. Use `required: false` for nice-to-haves the
# vault can ship without (typically MOCs).
#
# Sizing guidance:
#   small ~40-80 notes      • toy vault, single weekend's research
#   medium ~150-300 notes   • genuinely useful daily reference
#   large ~500-1000 notes   • encyclopaedic coverage of a niche
#   book-scale ~1500-2500   • supports writing one or more books from it
# ---------------------------------------------------------------------------
coverage_targets:
  categories:
    - name: concepts
      note_type: concept
      target_count: 25
      met_count: 0
      required: true
    - name: techniques
      note_type: technique
      target_count: 40
      met_count: 0
      required: true
    - name: gear
      note_type: gear
      target_count: 40
      met_count: 0
      required: true
    - name: film-stocks
      note_type: film-stock
      target_count: 30
      met_count: 0
      required: true
    - name: processes
      note_type: process
      target_count: 20
      met_count: 0
      required: true
    - name: sources
      note_type: source
      target_count: 25
      met_count: 0
      required: true
    - name: mocs
      note_type: moc
      target_count: 6
      met_count: 0
      required: false

# ---------------------------------------------------------------------------
# budget — hard spend cap + warning threshold.
#
# Single source of truth for cost guardrails. The pipeline will refuse to
# start a new cycle once `cumulative_cost_usd >= max_usd`. `max_cycles` is
# a safety net for run-away cycle loops. `warn_at_pct` triggers a non-fatal
# warning when crossed; the run still continues until `max_usd` is hit.
# ---------------------------------------------------------------------------
budget:
  max_usd: 15.0
  max_cycles: 6
  warn_at_pct: 0.8

# ---------------------------------------------------------------------------
# Pipeline knobs.
# ---------------------------------------------------------------------------
max_cycles: 6
naming_convention: full_name
access_modes: ["claude-code", "obsidian"]
---

# Macro Photography on Analog Film — Specification

Everything below the frontmatter is freeform narrative the parser ignores. Use
it to capture context that helps future-you remember why this vault exists and
how to think about additions to it.

## Why this vault exists

The digital-only assumption baked into most macro tutorials silently breaks
the moment you mount a bellows on a Hasselblad. Reciprocity failure alone
adds 1–3 stops of compensation that nobody is going to remind you about at
2× magnification with a 30-second exposure. This vault collects the math, the
techniques, and the gear comparisons that actually generalise to film, with
every quantitative claim backed by a manufacturer datasheet or a working
photographer's documented results.

## What I expect to query it for

- "What's the effective aperture and reciprocity-corrected exposure for shooting
  Provia 100F at 1.5× with bellows extension at meter-indicated f/16?"
- "Which mid-range bellows on Pentax 67 still finds focus past 1:1 without
  vignetting?"
- "What developer tweak compensates for the thin negatives I get when I forget
  to add bellows factor?"

## What it should NOT become

A gear-acquisition rabbit hole. The boundaries above are deliberate: gear
notes exist only to compare options for a defined macro-film use case. If a
note ends up reading like a YouTube review, the verifier should reject it.

## Generation command

```bash
research-framework generate \
  --spec examples/research.spec.md \
  --output ~/Documents/macro-film-vault
```

Check progress between cycles:

```bash
research-framework coverage --vault ~/Documents/macro-film-vault
```

Resume after a budget top-up (edit `budget.max_usd` first):

```bash
research-framework generate \
  --spec examples/research.spec.md \
  --output ~/Documents/macro-film-vault \
  --resume
```
