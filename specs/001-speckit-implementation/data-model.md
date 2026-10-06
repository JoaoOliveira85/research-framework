# Data Model: Speckit v0.1 — Knowledge Vault Generator

**Branch**: `001-speckit-implementation` | **Date**: 2026-04-16
**Phase**: 1 — Design

All entities are Python dataclasses (`src/speckit/spec/schema.py`). No ORM, no database.
Serialized to/from JSON for inter-phase communication.

---

## Core Entities

### SpecConfig

The parsed, validated vault specification. Drives all generation decisions in Phases 1–3.
This is the central entity — everything downstream reads from it.

```python
@dataclass
class SpecConfig:
    name: str                          # Vault name (e.g., "Acme Corp Codebase Vault")
    location: Path                     # Target directory for generated vault
    owner: str                         # Vault owner (person or team)
    scope: ScopeConfig
    note_types: list[NoteTypeConfig]
    data_sources: list[DataSourceConfig]
    search_dimensions: list[str]       # Must contain "domain" and "market"
    coverage_targets: CoverageTargets
    budget: BudgetConfig
    max_cycles: int = 5                # Max Phase 2 research cycles
    naming_convention: str = "full_name"  # or "slug"
    jira_project: str | None = None    # enables Jira targets in Condition B
    access_modes: list[str] = field(default_factory=list)  # e.g., ["claude-code", "mcp"]
```

**Validation rules** (enforced by `validator.py`):
- `name` MUST be non-empty string
- `location` MUST be a valid path (need not exist — generator creates it)
- `owner` MUST be non-empty string
- `search_dimensions` MUST include both `"domain"` and `"market"`
- `note_types` MUST have at least one entry
- `data_sources` MUST have at least one entry
- `coverage_targets` MUST have at least one target category

**Serialization**: `_pipeline/spec-parse.json` — written by Phase 0, read by Phases 1–3.

---

### ScopeConfig

Describes the domain and boundaries of the vault. Used in template rendering to generate
a correctly scoped `CLAUDE.md` and scout prompts.

```python
@dataclass
class ScopeConfig:
    domain: str
    organization: str
    boundaries: list[str] # What's in scope, one item per bullet
    out_of_scope: list[str]  # What's explicitly excluded
    contextual_questions: list[str]  # "why/how/who" questions that all notes should answer
```

---

### NoteTypeConfig

Defines a note type in the vault. Used to generate `_templates/{type}.md` and to configure
validation in `check_template_compliance.py`.

```python
@dataclass
class NoteTypeConfig:
    name: str              # e.g., "concept", "service", "team"
    description: str       # What this type captures
    folder: str            # e.g., "01 - Concepts", "02 - Services"
    required_sections: list[str]  # Section headings that MUST be present
    contextual_questions: list[str]  # Type-specific why/how/who questions
    min_word_count: int = 200      # 0 for MOC/index types
```

**State transitions**: None — note types are static configuration.

---

### DataSourceConfig

A source of information for research agents. Used to validate that Condition B sub-
condition "all required sources consulted at least once" is met.

```python
@dataclass
class DataSourceConfig:
    name: str              # e.g., "Confluence", "Jira", "GitHub Acme Corp"
    type: str              # "internal" | "external"
    description: str       # What it contains
    required: bool = True  # If True, must appear in at least one cycle scout report
    access_method: str = ""  # e.g., "MCP", "web", "CLI"
```

---

### CoverageTargets

Tracks required vs. met note counts per category. Written to `coverage-targets.json` at
Phase 1 from spec. Updated after every DFS cycle. Phase 3 MUST NOT begin until all targets
are met.

```python
@dataclass
class CoverageTargets:
    categories: list[CoverageCategory]
    last_updated: str = ""  # ISO 8601 timestamp
    cycle_number: int = 0   # Which cycle last updated this
```

```python
@dataclass
class CoverageCategory:
    name: str           # e.g., "concepts", "services", "team-structures"
    note_type: str      # Matches NoteTypeConfig.name
    target_count: int   # Required number of notes
    met_count: int = 0  # Current count (updated after each DFS)
    required: bool = True
```

**Computed properties**:
- `is_met` → `met_count >= target_count`
- `gap` → `max(0, target_count - met_count)`

**Serialization**: `{vault}/_pipeline/coverage-targets.json`

```json
{
  "last_updated": "2026-04-16T14:30:00Z",
  "cycle_number": 2,
  "categories": [
    {
      "name": "concepts",
      "note_type": "concept",
      "target_count": 40,
      "met_count": 31,
      "required": true
    }
  ]
}
```

---

### BudgetConfig

Controls Phase 2 spending caps. Enforced by `orchestrator.py` before each cycle.

```python
@dataclass
class BudgetConfig:
    max_usd: float         # Total budget cap for Phase 2
    max_cycles: int        # Redundant with SpecConfig.max_cycles; kept here for locality
    warn_at_pct: float = 0.8  # Warn when 80% of budget consumed
```

---

### CycleReport

Output of each BFS or DFS pass. Written by the `claude` CLI agent, validated by
`validate_cycle.py`. Not a Python dataclass — a JSON schema validated at runtime.

```python
# JSON schema (validated by validate_cycle.py)
{
  "cycle": int,                     # Cycle number (1-indexed)
  "phase": "scout" | "research",
  "timestamp": "ISO-8601",
  "dimensions_covered": list[str],  # Must include all 5 for scouts
  "new_topics": list[str],          # Empty → Condition B sub-condition satisfied
  "proposed_filenames": list[str],  # Must be non-overlapping with existing notes
  "sources_consulted": list[str],   # Must include at least one external source
  "termination_condition": "A" | "B" | "C" | null,  # null = CONTINUE
  "notes_created": list[str],       # Filenames of notes written (DFS only)
  "unresolved_wikilinks": list[str], # Detected unresolved links
  "budget_consumed_usd": float
}
```

**Validation rules** (enforced by `validate_cycle.py`):
- `dimensions_covered` MUST include all 5 dimensions for `phase == "scout"`
- `proposed_filenames` MUST NOT collide with existing vault filenames
- `sources_consulted` MUST include at least one source with `DataSourceConfig.type == "external"`
- Exit code 0 → CONTINUE; exit code 1 → TERMINATE (structural); exit code 2 → abort

---

### VaultNote

A single Markdown note with YAML frontmatter. Validated by `validate_vault.py` and
`check_template_compliance.py`. Not a Python dataclass — parsed at runtime from disk.

**Required frontmatter fields**:

```yaml
---
title: string                 # Must match filename
type: concept|service|team|...  # Must match a NoteTypeConfig.name
summary: string               # ≤ 120 chars, specific (not "A note about X")
tags: list[str]               # At least one tag
source_urls: list[str]        # At least one URL
related: list[str]            # Wikilinks to related notes
created: ISO-8601 date
updated: ISO-8601 date
---
```

**Validation rules** (enforced by `validate_vault.py`):
- All required frontmatter fields MUST be present
- `summary` MUST be ≤ 120 characters
- `source_urls` MUST have at least one entry (empty list → fail)
- All entries in `related` MUST resolve to existing vault files (wikilink check)
- Word count MUST be ≥ `NoteTypeConfig.min_word_count` for the note's type
- All acronyms MUST be wikilinked on first occurrence in body (checked by
  `check_acronym_links.py`)
- Section headings MUST match `NoteTypeConfig.required_sections` (checked by
  `check_template_compliance.py`)

---

## Entity Relationships

```
SpecConfig
├── ScopeConfig (1:1)
├── NoteTypeConfig[] (1:many)
│   └── required_sections[] → validates VaultNote section headings
├── DataSourceConfig[] (1:many)
│   └── required=True → validates CycleReport.sources_consulted
├── CoverageTargets (1:1)
│   └── CoverageCategory[] (1:many)
│       └── note_type → maps to NoteTypeConfig.name
└── BudgetConfig (1:1)

CycleReport
└── proposed_filenames[] → checked against existing VaultNote filenames

VaultNote
├── type → validated against NoteTypeConfig.name
└── related[] → validated as existing VaultNote filenames (wikilinks)
```

---

## State Transitions

### Vault Lifecycle

```
[Spec file] → Phase 0 → SpecConfig
SpecConfig  → Phase 1 → [Vault directory + scripts + templates + coverage-targets.json]
[Vault]     → Phase 2 → [Research cycles: scout → validate → DFS → validate → repeat]
              (until Condition A/B/C AND all coverage targets met)
[Vault]     → Phase 3 → [Layer 1 rebuilt + git init + phase1-report.md]
```

### Coverage Target State

```
UNMET (met_count < target_count)
  → After DFS: update met_count
  → If met_count >= target_count: MET
MET
  → Stable (count can only increase)
ALL_MET
  → Phase 3 gate unlocks
```

### Cycle Termination State

```
CONTINUE (exit 0)  → next cycle starts
TERMINATE (exit 1) → check ALL coverage targets
  → if all met: Phase 3 proceeds
  → if any unmet: targeted Phase 2 re-entry (NOT Phase 3)
ABORT (exit 2)     → stop; fix structural problem; do not proceed
```

Note: TERMINATE from `validate_cycle.py` is NOT the same as "Phase 2 complete".
These are different conditions. (See constitution principle II.)
