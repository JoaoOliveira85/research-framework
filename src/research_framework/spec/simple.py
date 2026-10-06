"""Simplified user-facing spec format (`research.spec.md`) + expander.

The goal of this module is to give non-technical users a *small* YAML surface
they can write by hand (or be walked through by the `vault-spec` agent skill)
that expands into a full-fat `SpecConfig`. The expander fills in sensible
defaults based on `growth_mode` (throwaway/incremental/big-bang) so users never
have to think about cycle budgets, coverage targets, or note-type templates on
the first pass.

This is the minimum spec — auto-expands everything you don't declare. The
detailed format in ``parser.py`` is the explicit spec — declare every field you
care about; the simple format is sugar over that.

Relationship to the detailed format in `parser.py`:

- `parser.parse()` reads the fully-declared spec with `data_sources`,
  `note_types`, `coverage_targets`, etc. — the format power users and the
  code-first feature use.
- `simple.parse_simple()` reads the friendly format with only `topic`, `scope`,
  `growth_mode`, and optional `sources` / `acceptance`. The expander generates
  the detailed fields.
- `load()` (at module bottom) auto-detects which variant a given `.md` file is
  and routes to the right parser.

The simple format lives in YAML frontmatter of a Markdown file, exactly like
the detailed format — so `research.spec.md` files are consistent for users.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..vault.frontmatter import split_frontmatter
from .schema import (
    RESEARCH_MODES,
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
    SpecValidationError,
)

# Growth modes drive the default budget/cycle/coverage shape of the expanded
# spec. Users pick one; they never set the knobs directly unless they care.
GROWTH_MODES = ("throwaway", "incremental", "big-bang")


@dataclass(frozen=True)
class GrowthDefaults:
    """Default budget/cycle/coverage values for a given growth mode.

    Values are deliberately conservative — a user can always override them via
    `settings:` in their simple spec.
    """

    max_cycles: int
    budget_usd: float
    # target_count applied to every generated coverage category (one per
    # `scope.include` entry). If a user writes 3 include items under
    # `incremental`, they get 3 categories × 8 = 24 notes as a coverage target.
    coverage_target_per_include: int
    # Minimum total notes — if scope.include is empty we still want the vault
    # to aim somewhere. Used only when the expander has to synthesise a single
    # catch-all coverage category.
    coverage_target_floor: int


GROWTH_DEFAULTS: dict[str, GrowthDefaults] = {
    "throwaway": GrowthDefaults(
        max_cycles=2,
        budget_usd=2.0,
        coverage_target_per_include=2,
        coverage_target_floor=3,
    ),
    "incremental": GrowthDefaults(
        max_cycles=3,
        budget_usd=10.0,
        coverage_target_per_include=5,
        coverage_target_floor=8,
    ),
    "big-bang": GrowthDefaults(
        max_cycles=6,
        budget_usd=25.0,
        coverage_target_per_include=10,
        coverage_target_floor=20,
    ),
}


@dataclass
class SimpleSpec:
    """The friendly user-facing spec.

    Only `name`, `owner`, and `topic` are strictly required; `scope.include`
    is strongly recommended (without it the expander uses a single catch-all
    coverage category). All other fields have sensible defaults.
    """

    name: str
    owner: str
    topic: str
    goal: str = ""
    problem: str = ""
    scope_include: list[str] = field(default_factory=list)
    scope_exclude: list[str] = field(default_factory=list)
    growth_mode: str = "incremental"
    research_mode: str = "bootstrap"
    # `sources` kept as raw dicts here so parse_simple stays a thin YAML
    # reader. The expander is where they become DataSourceConfig objects.
    sources: list[dict[str, Any]] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    # Optional corpus folder name declared via `vault.corpus_dir` in the YAML.
    # Defaults to "data_vault" — the historical name — so existing vaults that
    # omit the field are unaffected.
    vault_corpus_dir: str = "data_vault"
    # Optional note-type declarations. Each entry is either a plain string
    # (short form → auto-named folder) or a mapping (long form → passed through
    # to NoteTypeConfig directly). When empty (the default), the expander uses
    # the historical `concept` + `source` defaults so existing vaults are
    # unaffected. Raw dicts/strings stored here; the expander converts them.
    note_types: list[str | dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "owner": self.owner,
            "topic": self.topic,
            "goal": self.goal,
            "problem": self.problem,
            "scope": {
                "include": list(self.scope_include),
                "exclude": list(self.scope_exclude),
            },
            "growth_mode": self.growth_mode,
            "research_mode": self.research_mode,
            "sources": [dict(s) for s in self.sources],
            "acceptance": list(self.acceptance),
            "settings": dict(self.settings),
            "vault": {"corpus_dir": self.vault_corpus_dir},
            "note_types": list(self.note_types),
        }


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_simple(spec_path: Path) -> SimpleSpec:
    """Read a `research.spec.md` file and return a SimpleSpec.

    Raises SpecValidationError with field-level messages if required fields
    (`name`, `owner`, `topic`) are missing, if `growth_mode` / `research_mode`
    are invalid, or if the frontmatter is malformed.

    Does NOT expand to a SpecConfig — call `expand()` separately so callers
    can inspect the simple spec (e.g. the `vault-spec` skill shows it back to
    the user before committing).
    """
    if not spec_path.exists():
        raise SpecValidationError([f"spec file not found: {spec_path}"])

    text = spec_path.read_text(encoding="utf-8")
    data = _read_frontmatter(text, spec_path)
    return _simple_spec_from_dict(data, spec_path)


def _read_frontmatter(text: str, spec_path: Path) -> dict[str, Any]:
    """Extract the YAML frontmatter block from a Markdown file."""
    if not text.startswith("---"):
        raise SpecValidationError(
            [f"spec file {spec_path} missing YAML frontmatter (must start with '---')"]
        )
    # Split at the delimiter LINES. ``text.split("---", 2)`` ended the
    # frontmatter at the first `---` inside a line (a `# -------` comment rule,
    # a `---` in a value) and silently dropped every field below it.
    split = split_frontmatter(text)
    if split is None:
        raise SpecValidationError(
            [f"spec file {spec_path} has malformed frontmatter delimiters"]
        )
    try:
        # The leading newline stands for the opening delimiter line, so the
        # line numbers in a YAML error stay what they were.
        data = yaml.safe_load("\n" + split[0])
    except yaml.YAMLError as e:
        line = getattr(getattr(e, "problem_mark", None), "line", "?")
        raise SpecValidationError(
            [f"YAML parse error in {spec_path} (line {line}): {e}"]
        ) from e
    if not isinstance(data, dict):
        raise SpecValidationError(
            [f"spec frontmatter must be a mapping (got {type(data).__name__})"]
        )
    return data


def _simple_spec_from_dict(d: dict[str, Any], spec_path: Path) -> SimpleSpec:
    errors: list[str] = []

    name = str(d.get("name", "")).strip()
    # `owner` is a soft field — the `vault-spec` skill often doesn't surface it
    # to non-technical users and the information rarely changes the generated
    # vault's shape. Default to the current shell user so a spec authored by
    # someone who skipped this field still validates and runs. Power users can
    # set it explicitly in the detailed format.
    owner = str(d.get("owner", "") or "").strip() or os.environ.get("USER", "unknown")
    topic = str(d.get("topic", "")).strip()
    if not name:
        errors.append(f"{spec_path}: missing required field 'name'")
    if not topic:
        errors.append(f"{spec_path}: missing required field 'topic'")

    growth_mode = str(d.get("growth_mode", "incremental"))
    if growth_mode not in GROWTH_MODES:
        errors.append(
            f"{spec_path}: growth_mode '{growth_mode}' is invalid "
            f"(must be one of {list(GROWTH_MODES)})"
        )
    research_mode = str(d.get("research_mode", "bootstrap"))
    if research_mode not in RESEARCH_MODES:
        errors.append(
            f"{spec_path}: research_mode '{research_mode}' is invalid "
            f"(must be one of {list(RESEARCH_MODES)})"
        )

    scope_raw = d.get("scope") or {}
    if not isinstance(scope_raw, dict):
        errors.append(
            f"{spec_path}: scope must be a mapping with 'include'/'exclude' lists"
        )
        scope_raw = {}

    sources_raw = d.get("sources") or []
    if not isinstance(sources_raw, list):
        errors.append(f"{spec_path}: sources must be a list")
        sources_raw = []
    sources: list[dict[str, Any]] = []
    for i, s in enumerate(sources_raw):
        # The `vault-spec` skill and the example file both advertise
        # plain-string sources (``- Wikipedia``, ``- https://…``) as a valid
        # shorthand. Agents tend to emit them too. We accept both shapes here
        # and coerce the string form into a minimal ``{name: ...}`` mapping so
        # the downstream expander always sees a uniform structure.
        if isinstance(s, str):
            text = s.strip()
            if not text:
                errors.append(f"{spec_path}: sources[{i}] is empty")
                continue
            entry: dict[str, Any] = {"name": text}
            # A bare URL is most usefully described as such; split it out so
            # the expander can surface it in `description` and downstream
            # source_urls checks can pick it up.
            if re.match(r"^https?://", text):
                entry["description"] = text
            sources.append(entry)
            continue
        if not isinstance(s, dict):
            errors.append(
                f"{spec_path}: sources[{i}] must be a mapping or a plain "
                f"string (got {type(s).__name__})"
            )
            continue
        if not str(s.get("name", "")).strip():
            errors.append(f"{spec_path}: sources[{i}] missing 'name'")
        sources.append(dict(s))

    settings = d.get("settings") or {}
    if not isinstance(settings, dict):
        errors.append(f"{spec_path}: settings must be a mapping")
        settings = {}

    # User-friendly shortcuts that the `vault-spec` skill's YAML template
    # advertises as top-level fields. Fold them into `settings` so the
    # expander only needs one code path. Explicit `settings.*` values win
    # on conflict — we never clobber power-user intent.
    top_level_budget = d.get("budget_usd", None)
    if top_level_budget is not None:
        budget_block = settings.setdefault("budget", {})
        if isinstance(budget_block, dict) and "max_usd" not in budget_block:
            try:
                budget_block["max_usd"] = float(top_level_budget)
            except (TypeError, ValueError):
                errors.append(
                    f"{spec_path}: budget_usd must be a number (got "
                    f"{top_level_budget!r})"
                )
    top_level_model = d.get("model", None)
    if top_level_model is not None:
        executor_block = settings.setdefault("default_executor", {})
        if isinstance(executor_block, dict) and "model" not in executor_block:
            executor_block["model"] = str(top_level_model)

    # vault.corpus_dir — optional; defaults to "data_vault".
    vault_block = d.get("vault") or {}
    if not isinstance(vault_block, dict):
        errors.append(f"{spec_path}: vault must be a mapping")
        vault_block = {}
    vault_corpus_dir = vault_block.get("corpus_dir", "data_vault")
    if not isinstance(vault_corpus_dir, str):
        vault_corpus_dir = str(vault_corpus_dir)
    vault_corpus_dir = vault_corpus_dir.strip()
    _FORBIDDEN_CORPUS_DIRS = {
        "_pipeline",
        "_templates",
        ".claude",
        ".cursor",
        "raw_data",
        ".git",
    }
    if not vault_corpus_dir:
        errors.append(f"{spec_path}: vault.corpus_dir must be a non-empty string")
    elif ".." in vault_corpus_dir.split("/"):
        errors.append(
            f"{spec_path}: vault.corpus_dir must not contain '..': {vault_corpus_dir!r}"
        )
    elif vault_corpus_dir.startswith("/"):
        errors.append(
            f"{spec_path}: vault.corpus_dir must not be an absolute path: "
            f"{vault_corpus_dir!r}"
        )
    elif vault_corpus_dir in _FORBIDDEN_CORPUS_DIRS:
        errors.append(
            f"{spec_path}: vault.corpus_dir conflicts with a framework-managed "
            f"folder: {vault_corpus_dir!r}"
        )

    # note_types — optional list of str or mapping.
    note_types_raw = d.get("note_types") or []
    if not isinstance(note_types_raw, list):
        errors.append(f"{spec_path}: note_types must be a list")
        note_types_raw = []
    note_types: list[str | dict[str, Any]] = []
    _seen_nt_names: set[str] = set()
    _VALID_NT_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")
    for i, entry in enumerate(note_types_raw):
        if isinstance(entry, str):
            nt_name = entry.strip()
            if not nt_name:
                errors.append(f"{spec_path}: note_types[{i}] is an empty string")
                continue
            if not _VALID_NT_NAME_RE.match(nt_name):
                errors.append(
                    f"{spec_path}: note_types[{i}] name {nt_name!r} is invalid "
                    f"(must start with a letter; only letters, digits, '-', '_' allowed)"
                )
                continue
            if nt_name in _seen_nt_names:
                errors.append(
                    f"{spec_path}: note_types[{i}] duplicate name {nt_name!r}"
                )
                continue
            _seen_nt_names.add(nt_name)
            note_types.append(nt_name)
        elif isinstance(entry, dict):
            nt_name = str(entry.get("name", "")).strip()
            if not nt_name:
                errors.append(f"{spec_path}: note_types[{i}] mapping is missing 'name'")
                continue
            if not _VALID_NT_NAME_RE.match(nt_name):
                errors.append(
                    f"{spec_path}: note_types[{i}] name {nt_name!r} is invalid "
                    f"(must start with a letter; only letters, digits, '-', '_' allowed)"
                )
                continue
            if nt_name in _seen_nt_names:
                errors.append(
                    f"{spec_path}: note_types[{i}] duplicate name {nt_name!r}"
                )
                continue
            _seen_nt_names.add(nt_name)
            note_types.append(dict(entry))
        else:
            errors.append(
                f"{spec_path}: note_types[{i}] must be a string or a mapping "
                f"(got {type(entry).__name__})"
            )

    if errors:
        raise SpecValidationError(errors)

    return SimpleSpec(
        name=name,
        owner=owner,
        topic=topic,
        goal=str(d.get("goal", "") or ""),
        problem=str(d.get("problem", "") or ""),
        scope_include=[str(x) for x in scope_raw.get("include", []) or []],
        scope_exclude=[str(x) for x in scope_raw.get("exclude", []) or []],
        growth_mode=growth_mode,
        research_mode=research_mode,
        sources=sources,
        acceptance=[str(x) for x in d.get("acceptance", []) or []],
        settings=settings,
        vault_corpus_dir=vault_corpus_dir,
        note_types=note_types,
    )


# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-") or "topic"


def _pluralise(name: str) -> str:
    """Return a title-cased plural form of `name`.

    Handles the most common English inflection rules. The dict-form
    ``note_types`` entry can override with an explicit ``folder:`` key.

    Examples:
        policy → Policies
        process → Processes
        box → Boxes
        dish → Dishes
        case → Cases
        source → Sources
    """
    lower = name.lower()
    if lower.endswith("y") and len(lower) > 1 and lower[-2] not in "aeiou":
        plural = lower[:-1] + "ies"
    elif lower.endswith(("s", "x", "ch", "sh")):
        plural = lower + "es"
    else:
        plural = lower + "s"
    return plural.title()


def expand(simple: SimpleSpec, *, location: Path) -> SpecConfig:
    """Expand a SimpleSpec into a fully-populated SpecConfig.

    The expander fills in:

    - `note_types` — always at least `concept`, with a hard source policy so
      Principle IX (Vault-First Citation) is enforced from the start.
    - `search_dimensions` — always includes `domain` and `market` (validator
      rejects specs missing these). `technical`, `organizational`, `temporal`
      are added as well; the orchestrator can prune at scout time if the user
      has set a narrow topic.
    - `coverage_targets` — one category per `scope.include` line when present,
      or a single catch-all when not. Target counts come from growth-mode
      defaults.
    - `data_sources` — uses the user-supplied `sources` list, or a default
      `{name: Web, type: external, role: domain}` when absent.
    - `budget` — only the spec-declarable warn threshold (spec 061 moved the
      cycle/dollar caps to the vault `settings.yaml`; the growth-mode
      `max_cycles`/`budget_usd` defaults are seeded there at install time, not
      baked into the spec).
    - `scope.source_of_truth_rules` — always seeded with the two-tier rule so
      the validator stays happy for Principle IX use cases.
    """
    defaults = GROWTH_DEFAULTS[simple.growth_mode]

    if simple.note_types:
        note_types = _expand_note_types(simple.note_types)
    else:
        note_types = _note_types_for(simple.growth_mode, _is_code_first(simple))

    coverage_categories = _coverage_categories(simple, defaults)

    data_sources = _data_sources(simple)

    # `scope.boundaries` = in-scope lines, `scope.out_of_scope` = excluded lines.
    # The simple spec's `scope.include`/`scope.exclude` lists map 1:1. Prior
    # versions of this expander swapped these, which caused CLAUDE.md to
    # render every exclude item under "In scope" (bug fixed in v0.2.7).
    scope = ScopeConfig(
        domain=_infer_domain(simple),
        organization=simple.owner,
        boundaries=list(simple.scope_include),
        out_of_scope=list(simple.scope_exclude),
        source_of_truth_rules=[
            "Vault notes are the Tier-1 authoritative answer surface (Principle IX).",
            "External sources listed in each note's `source_urls` are the "
            "Tier-2 origin of record; code wins for behaviour when present.",
        ],
    )

    spec = SpecConfig(
        name=simple.name,
        location=location,
        owner=simple.owner,
        scope=scope,
        note_types=note_types,
        data_sources=data_sources,
        search_dimensions=[
            "technical",
            "organizational",
            "domain",
            "market",
            "temporal",
        ],
        coverage_targets=CoverageTargets(categories=coverage_categories),
        budget=BudgetConfig(),
        research_mode=simple.research_mode,
        vault_corpus_dir=simple.vault_corpus_dir,
    )
    return spec


def _expand_note_types(
    raw: list[str | dict[str, Any]],
) -> list[NoteTypeConfig]:
    """Convert the simple-spec ``note_types`` list to ``NoteTypeConfig`` objects.

    Short form (string ``"case"``) auto-generates a numbered folder:
    ``01 - Cases``, ``02 - Statutes``, …  The counter starts at 1 and
    increments only for short-form entries — long-form entries that supply
    an explicit ``folder:`` do not consume a slot.

    Long form (mapping) is passed through to ``NoteTypeConfig`` directly;
    the only mandatory key is ``name``. All other ``NoteTypeConfig`` fields
    (``description``, ``required_sections``, ``contextual_questions``,
    ``folder``, …) default to their dataclass defaults.
    """
    result: list[NoteTypeConfig] = []
    auto_idx = 1
    for entry in raw:
        if isinstance(entry, str):
            name = entry.strip()
            folder = f"{auto_idx:02d} - {_pluralise(name)}"
            auto_idx += 1
            result.append(
                NoteTypeConfig(
                    name=name,
                    description="",
                    folder=folder,
                )
            )
        else:
            # dict — already validated by parser; name is present
            name = str(entry["name"]).strip()
            # If no explicit folder, auto-generate one (does not consume
            # an auto_idx slot since long-form callers usually supply folder)
            folder = str(entry.get("folder", "") or "").strip()
            if not folder:
                folder = f"{auto_idx:02d} - {_pluralise(name)}"
                auto_idx += 1
            result.append(
                NoteTypeConfig(
                    name=name,
                    description=str(entry.get("description", "") or ""),
                    folder=folder,
                    required_sections=list(entry.get("required_sections", []) or []),
                    contextual_questions=list(
                        entry.get("contextual_questions", []) or []
                    ),
                    min_word_count=int(entry.get("min_word_count", 200)),
                    source_policy=str(entry.get("source_policy", "") or ""),
                    template_version=str(
                        entry.get("template_version", "1.0.0") or "1.0.0"
                    ),
                )
            )
    return result


def _note_types_for(growth_mode: str, code_first: bool = False) -> list[NoteTypeConfig]:
    """Return the starter note-type set for a given growth mode.

    Folder-shape lessons learned from the three reference vaults
    (``~/Documents/notes``, ``codebase-vault``, ``reference-vault``):

    - ``concept`` is universal — every vault has it.
    - ``source`` is universally useful once a vault lasts longer than a single
      throwaway run: the notes and codebase-vault patterns both keep a
      dedicated sources folder so agents can audit where a claim originated.
    - ``moc`` (Map-of-Content index pages) show up in the bigger reference-vault
      and notes shapes; they're pure navigation aids, soft policy.

    ``code_first`` controls whether ``concept`` requires a code source URL.
    Code-first vaults (codebase-vault, reference-vault) get ``source_policy: hard``
    so the verifier gate forces citations back to the repo. Non-code-first
    vaults (a recipes vault, a photography vault, etc.) get ``soft`` — they
    have no repo to cite, and forcing the rule produces the
    ``MISSING CODE SOURCE`` flood seen before v0.2.7.

    Topic-specific buckets (``People``, ``Companies``, ``Trends``…) are *not*
    hardcoded — they're emergent from ``scope.include`` and the scout skill,
    so this function stays focused on the replicable universals.
    """
    concept = NoteTypeConfig(
        name="concept",
        description="Standalone knowledge note summarising one topic.",
        folder="01 - Concepts",
        min_word_count=200,
        source_policy="hard" if code_first else "soft",
    )

    if growth_mode == "throwaway":
        return [concept]

    # ``source`` captures the primary-source record (an article, paper, video,
    # forum thread…). Soft policy because the note IS the source; its
    # ``source-type`` frontmatter identifies the medium (article/video/paper/…)
    # and the notes ``01 - Sources/{Articles,Video,Reddit,Research}`` layout
    # can be emulated by agents writing into subdirs of this folder.
    source = NoteTypeConfig(
        name="source",
        description=(
            "Primary-source record: one article, paper, video, forum thread, "
            "or other external artefact with extracted findings."
        ),
        folder="02 - Sources",
        required_sections=[
            "Summary",
            "Key Claims",
            "Extracted Findings",
            "Relevance",
        ],
        contextual_questions=[
            "What is the single-sentence thesis of this source?",
            "Which claims are directly supported vs. inferred?",
            "Which vault notes should cite this (and which should not)?",
        ],
        min_word_count=150,
        source_policy="soft",
    )

    if growth_mode == "incremental":
        return [concept, source]

    # big-bang: add MOC scaffolding. Soft policy; MOCs are navigation, not
    # claims, so they don't need their own citations.
    moc = NoteTypeConfig(
        name="moc",
        description="Map-of-Content index page linking related notes.",
        folder="00 - MOC",
        required_sections=["Overview", "Linked Notes"],
        contextual_questions=[
            "Which notes in this vault belong under this index?",
            "What is the one-paragraph overview a reader needs before diving in?",
        ],
        min_word_count=80,
        source_policy="soft",
    )
    return [moc, concept, source]


def _infer_domain(simple: SimpleSpec) -> str:
    """Pick a reasonable `scope.domain` string from the simple spec.

    Users rarely set a domain explicitly — the topic sentence or the first
    include item is a better signal. Validator only requires a non-empty
    string, so we just need *something* descriptive.
    """
    if simple.topic:
        return simple.topic.split(".", 1)[0].strip() or simple.name
    if simple.scope_include:
        return simple.scope_include[0]
    return simple.name


def _coverage_categories(
    simple: SimpleSpec, defaults: GrowthDefaults
) -> list[CoverageCategory]:
    """One coverage category per `scope.include` entry, or one catch-all.

    Category names are sluggified versions of the include text so multiple
    vaults don't collide in telemetry.
    """
    if simple.scope_include:
        return [
            CoverageCategory(
                name=_slug(item),
                note_type="concept",
                target_count=defaults.coverage_target_per_include,
                display_name=item,
            )
            for item in simple.scope_include
        ]
    return [
        CoverageCategory(
            name=_slug(simple.topic),
            note_type="concept",
            target_count=defaults.coverage_target_floor,
            display_name=simple.topic,
        )
    ]


def _is_code_first(simple: SimpleSpec) -> bool:
    """Detect whether the user intends a code-first vault.

    Mirrors ``validator._is_code_first_spec`` but runs on the simple spec
    *before* expansion, so the expander can pick the right defaults (notably
    ``concept.source_policy``). A source qualifies when ANY of:

    - `priority: 1` is set explicitly (a canonical primary source)
    - `role: intent` is set (the intent axis is code-first only)
    - a non-empty `repos` list is declared (hard code-first signal)

    ``role: domain`` / ``role: behaviour`` / absent priority do NOT trigger —
    that keeps simple recipe / photography / news vaults off the code-first
    path even when they name several sources.
    """
    for s in simple.sources or []:
        if not isinstance(s, dict):
            continue
        if s.get("priority") == 1:
            return True
        if s.get("role") == "intent":
            return True
        repos = s.get("repos") or []
        if isinstance(repos, list) and repos:
            return True
    return False


def _data_sources(simple: SimpleSpec) -> list[DataSourceConfig]:
    """Convert the user-supplied sources list to DataSourceConfig objects.

    When `sources` is empty we inject a single default external Web source so
    the validator's "at least one data source" rule is satisfied. Users who
    want code-first behaviour will have written the detailed spec instead.
    """
    if not simple.sources:
        return [
            DataSourceConfig(
                name="Web",
                type="external",
                description="Open web search for domain background.",
                required=True,
                priority=2,
                role="domain",
                # Open web search is LLM-fetch guidance, not a module-backed
                # source — annotate it honestly so spec-069's source-backing
                # validation treats it as a strategy hint, not an unbacked
                # declaration (the rc7 trap).
                kind="strategy_hint",
            )
        ]

    result: list[DataSourceConfig] = []
    for s in simple.sources:
        result.append(
            DataSourceConfig(
                name=str(s.get("name", "")),
                type=str(s.get("type", "external")),
                description=str(s.get("description", "") or ""),
                required=bool(s.get("required", True)),
                access_method=str(s.get("access_method", "") or ""),
                priority=int(s.get("priority", 2)),
                role=str(s.get("role", "domain")),
                phases=[str(p) for p in (s.get("phases") or [])],
                # Spec 070 F8: these were dropped, which left a simple-format
                # vault unable to satisfy spec 069's fail-closed source-backing
                # gate — whose error message tells the operator to "annotate
                # kind: strategy_hint", an instruction this parser then
                # discarded. It also put the credibility model's source-default
                # rung permanently out of reach for simple specs.
                kind=str(s.get("kind", "") or ""),
                default_credibility=str(s.get("default_credibility", "") or ""),
                url=str(s.get("url", "") or ""),
                urls=[str(u) for u in (s.get("urls") or [])],
                local_path=str(s.get("local_path", "") or ""),
            )
        )
    return result


# ---------------------------------------------------------------------------
# Auto-detecting loader
# ---------------------------------------------------------------------------


def is_simple(data: dict[str, Any]) -> bool:
    """Heuristic: a spec is 'simple' unless it uses detailed structural keys.

    The detailed format (`parser.parse`) is recognised by the presence of
    ``data_sources`` or ``coverage_targets`` — only power users set those.
    ``note_types`` is intentionally NOT a differentiator: the simple spec now
    supports an optional ``note_types:`` block (list of strings or minimal
    mappings) so users can declare richer taxonomies without leaving the
    friendly format. The simple parser handles both the old two-type default
    and the new explicit-list form.

    Everything else is routed to the simple parser, including specs that are
    *structurally broken* (missing ``topic`` / ``growth_mode`` entirely). The
    simple parser emits clearer, user-friendly errors for those cases; routing
    a half-formed spec to the detailed parser produced confusing error stacks
    about ``note_types`` and ``search_dimensions`` fields the user never wrote.
    """
    detailed_keys = {"data_sources", "coverage_targets"}
    return not bool(detailed_keys & data.keys())


def load(spec_path: Path, *, location: Path | None = None) -> SpecConfig:
    """Load either a simple or detailed spec file, returning SpecConfig.

    - If the file uses the detailed schema, delegates to `parser.parse()`.
    - If the file uses the simple schema, runs `parse_simple()` + `expand()`.

    `location` overrides where the generated vault will live; when omitted,
    expansion falls back to the spec file's parent directory. (Detailed specs
    carry their own `location` field and ignore this argument.)
    """
    # Local import avoids a circular dependency: parser doesn't know about
    # simple.py, so we keep the relationship one-way.
    from .parser import parse as parse_detailed

    if not spec_path.exists():
        raise SpecValidationError([f"spec file not found: {spec_path}"])

    text = spec_path.read_text(encoding="utf-8")
    data = _read_frontmatter(text, spec_path)
    if is_simple(data):
        simple = _simple_spec_from_dict(data, spec_path)
        resolved_location = location or spec_path.parent / simple.name
        return expand(simple, location=resolved_location)
    return parse_detailed(spec_path)
