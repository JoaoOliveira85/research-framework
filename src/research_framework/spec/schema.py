"""Dataclasses for research-framework's vault specification.

All entities serialize to/from plain dicts (JSON-friendly). Each dataclass has
`to_dict()` and `from_dict()` methods. Validation is NOT performed at construction
time — `validator.py` is responsible for that, so invalid specs can still be
introspected for error reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

HARD_NOTE_TYPES = {"service", "flow", "concept", "decision"}

# Valid values for SpecConfig.research_mode and DataSourceConfig.phases entries.
# bootstrap → breadth-first scaffolding; new topics + authoritative sources.
# refresh   → depth-first currency; merge updates into existing notes only.
# expand    → mixed; grow coverage AND refresh existing. Ends with a tail refresh.
RESEARCH_MODES = ("bootstrap", "refresh", "expand")


class SpecValidationError(Exception):
    """Raised when a parsed spec fails validation.

    Attributes:
        messages: Ordered list of human-readable error messages.
    """

    def __init__(self, messages: list[str]):
        self.messages = messages
        super().__init__("\n".join(messages))


def _int_field(d: dict[str, Any], key: str, default: int, path: str) -> int:
    """Coerce ``d[key]`` to int for a spec dataclass's ``from_dict``.

    A bare ``int()`` call let a typo like ``priority: high`` — which reads
    like valid YAML, not an obvious mistake — surface as an unhandled
    ValueError with a traceback instead of the field-level error the spec
    parser promises (#255). Missing or blank values fall back to `default`,
    matching the tolerant behaviour `from_dict` already had for absent keys.
    """
    value = d.get(key, default)
    if value is None or (isinstance(value, str) and not value.strip()):
        value = default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SpecValidationError(
            [f"{path}: {key} must be an integer (got {value!r})"]
        ) from exc


@dataclass
class ScopeConfig:
    domain: str
    organization: str
    boundaries: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    contextual_questions: list[str] = field(default_factory=list)
    source_of_truth_rules: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "organization": self.organization,
            "boundaries": list(self.boundaries),
            "out_of_scope": list(self.out_of_scope),
            "contextual_questions": list(self.contextual_questions),
            "source_of_truth_rules": list(self.source_of_truth_rules),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        return cls(
            domain=d.get("domain", ""),
            organization=d.get("organization", ""),
            boundaries=list(d.get("boundaries", []) or []),
            out_of_scope=list(d.get("out_of_scope", []) or []),
            contextual_questions=list(d.get("contextual_questions", []) or []),
            source_of_truth_rules=list(d.get("source_of_truth_rules", []) or []),
        )


@dataclass
class NoteTypeConfig:
    name: str
    description: str
    folder: str
    required_sections: list[str] = field(default_factory=list)
    contextual_questions: list[str] = field(default_factory=list)
    min_word_count: int = 200
    source_policy: str = ""  # "hard" | "soft"; resolved via default_source_policy()
    # ``template_version`` stamps each note with the version of the note-type
    # template it was rendered from. The vault-health check compares this
    # against the current version declared in ``_templates/CHANGELOG.md`` to
    # detect notes that need a template upgrade. Follows SemVer; bump MINOR
    # for backward-compatible additions (new section, new frontmatter key),
    # MAJOR for renames/removals that break existing notes.
    template_version: str = "1.0.0"
    # spec 053 (FR-001 / D1): the authoritative `role` this note_type's claims
    # anchor — how the grounding gate resolves a note's claim-type. Empty =
    # undeclared (opt-in for back-compat: fully-legacy specs skip it; once
    # ANY note_type declares it, validation requires consistency on all).
    # The two section headings generalize the hardcoded ``## Current Behaviour``
    # / ``## Stated Intent``; the drift gate runs ONLY when BOTH are declared
    # (opt-in, D3).
    authoritative_role: str = ""  # "behaviour" | "intent" | "domain"
    authority_section: str = ""
    complementary_section: str = ""

    def resolved_source_policy(self) -> str:
        if self.source_policy:
            return self.source_policy
        return "hard" if self.name in HARD_NOTE_TYPES else "soft"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "folder": self.folder,
            "required_sections": list(self.required_sections),
            "contextual_questions": list(self.contextual_questions),
            "min_word_count": self.min_word_count,
            "source_policy": self.source_policy,
            "template_version": self.template_version,
            "authoritative_role": self.authoritative_role,
            "authority_section": self.authority_section,
            "complementary_section": self.complementary_section,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            folder=d.get("folder", ""),
            required_sections=list(d.get("required_sections", []) or []),
            contextual_questions=list(d.get("contextual_questions", []) or []),
            min_word_count=_int_field(
                d, "min_word_count", 200, f"note_types.{d.get('name') or '?'}"
            ),
            source_policy=d.get("source_policy", "") or "",
            template_version=str(d.get("template_version", "1.0.0") or "1.0.0"),
            authoritative_role=d.get("authoritative_role", "") or "",
            authority_section=d.get("authority_section", "") or "",
            complementary_section=d.get("complementary_section", "") or "",
        )


@dataclass
class RepoEnumeration:
    name: str
    url: str
    priority_paths: list[str] = field(default_factory=list)
    ignore_paths: list[str] = field(default_factory=list)
    owning_team: str = ""
    access_method: str = "both"  # "local" | "mcp" | "both"
    local_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "priority_paths": list(self.priority_paths),
            "ignore_paths": list(self.ignore_paths),
            "owning_team": self.owning_team,
            "access_method": self.access_method,
            "local_path": self.local_path,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        return cls(
            name=d.get("name", ""),
            url=d.get("url", ""),
            priority_paths=list(d.get("priority_paths", []) or []),
            ignore_paths=list(d.get("ignore_paths", []) or []),
            owning_team=d.get("owning_team", ""),
            access_method=d.get("access_method", "both"),
            local_path=d.get("local_path", "") or "",
        )


@dataclass
class DataSourceConfig:
    name: str
    type: str  # "internal" | "external"
    description: str = ""
    required: bool = True
    access_method: str = ""
    priority: int = 2  # 1 = primary
    role: str = "behaviour"  # "behaviour" | "intent" | "domain"
    default_credibility: str = ""
    repos: list[RepoEnumeration] = field(default_factory=list)
    # Spec 069 (FR1): how this declared source is backed.
    #   "module_backed" — must trigger-match an installed module (default intent).
    #   "strategy_hint" — an LLM-fetch guidance string, no module required.
    # Absent (empty) ⇒ inferred: backed iff a module trigger matches its locator,
    # else `unbacked` → scaffold error. Additive + optional ⇒ no schema_version bump.
    kind: str = ""
    # Optional source-level filesystem locator (D2 fallback after repos[]).
    local_path: str = ""
    # Spec 070 (FR1): the source's own canonical locator. Vault specs have
    # always declared this key; before 070 it was silently discarded here,
    # which is why a `kind: strategy_hint` source could not ground a citation
    # to its own domain (it has no `repos[]` to fall back on).
    url: str = ""
    # Spec 070 (FR1): additional locators this source covers. A strategy hint is
    # routinely a *set* of domains ("Regional company engineering blogs" spans
    # alpha, bravo, charlie, echo...), and `url` alone can only name one of them
    # — which left the rest ungrounded even after `url` started being indexed.
    urls: list[str] = field(default_factory=list)
    # Research-mode phases during which this source is consulted.
    # Empty list (the default) means "all phases" — the orchestrator treats
    # unset as universal rather than forcing users to list every mode.
    # Any non-empty list MUST contain only values from `RESEARCH_MODES`;
    # validator enforces that.
    phases: list[str] = field(default_factory=list)

    def applies_to(self, mode: str) -> bool:
        """True iff this source should be consulted during `mode`.

        An empty `phases` list means "all phases" — i.e. universal sources.
        """
        return not self.phases or mode in self.phases

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "required": self.required,
            "access_method": self.access_method,
            "priority": self.priority,
            "role": self.role,
            "repos": [r.to_dict() for r in self.repos],
            "phases": list(self.phases),
        }
        if self.default_credibility:
            payload["default_credibility"] = self.default_credibility
        if self.kind:
            payload["kind"] = self.kind
        if self.local_path:
            payload["local_path"] = self.local_path
        if self.url:
            payload["url"] = self.url
        if self.urls:
            payload["urls"] = list(self.urls)
        return payload

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        return cls(
            name=d.get("name", ""),
            type=d.get("type", ""),
            description=d.get("description", ""),
            required=bool(d.get("required", True)),
            access_method=d.get("access_method", ""),
            priority=_int_field(
                d, "priority", 2, f"data_sources.{d.get('name') or '?'}"
            ),
            role=d.get("role", "behaviour"),
            default_credibility=d.get("default_credibility", "") or "",
            repos=[RepoEnumeration.from_dict(r) for r in d.get("repos", []) or []],
            kind=d.get("kind", "") or "",
            local_path=d.get("local_path", "") or "",
            url=d.get("url", "") or "",
            urls=[str(u) for u in (d.get("urls") or [])],
            phases=list(d.get("phases", []) or []),
        )


@dataclass
class CoverageCategory:
    name: str
    note_type: str
    target_count: int
    met_count: int = 0
    required: bool = True
    expected_filenames: list[str] = field(default_factory=list)
    # Human-readable label carried forward from ``scope.include`` when the
    # category was synthesised by ``simple.py::_coverage_categories``. Shown
    # to agents in CLAUDE.md + DFS prompts so they can assign each note to
    # the right bucket without having to reason from a truncated slug. Empty
    # for categories authored directly in the detailed spec format, which
    # name themselves.
    display_name: str = ""
    # Feature 017: budget-constrained ordering. Higher value = filled first
    # when budget is constrained. Default 0 (no preference, ordering follows
    # spec definition order). Used by `pipeline.research_plan` to rank
    # categories in the priority queue (FR-005). Range [0, 100], validated
    # by `spec/validator.py`. Round-trip rule: `priority == 0` is omitted
    # from `to_dict()` output to keep specs readable for vaults that don't
    # use the field (per `contracts/spec-extension.schema.md`).
    priority: int = 0

    @property
    def is_met(self) -> bool:
        return self.met_count >= self.target_count

    @property
    def gap(self) -> int:
        return max(0, self.target_count - self.met_count)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "note_type": self.note_type,
            "target_count": self.target_count,
            "met_count": self.met_count,
            "required": self.required,
            "expected_filenames": list(self.expected_filenames),
            "display_name": self.display_name,
        }
        # Round-trip rule: omit default-zero priority so existing specs
        # round-trip byte-for-byte and new specs stay readable when they
        # don't use the field.
        if self.priority != 0:
            d["priority"] = self.priority
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        return cls(
            name=d.get("name", ""),
            note_type=d.get("note_type", ""),
            target_count=_int_field(
                d,
                "target_count",
                0,
                f"coverage_targets.categories.{d.get('name') or '?'}",
            ),
            met_count=_int_field(
                d,
                "met_count",
                0,
                f"coverage_targets.categories.{d.get('name') or '?'}",
            ),
            required=bool(d.get("required", True)),
            expected_filenames=list(d.get("expected_filenames", []) or []),
            display_name=str(d.get("display_name", "") or ""),
            priority=_int_field(
                d,
                "priority",
                0,
                f"coverage_targets.categories.{d.get('name') or '?'}",
            ),
        )


@dataclass
class CoverageTargets:
    categories: list[CoverageCategory] = field(default_factory=list)
    last_updated: str = ""
    cycle_number: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_updated": self.last_updated,
            "cycle_number": self.cycle_number,
            "categories": [c.to_dict() for c in self.categories],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        return cls(
            categories=[
                CoverageCategory.from_dict(c) for c in d.get("categories", []) or []
            ],
            last_updated=d.get("last_updated", ""),
            cycle_number=_int_field(d, "cycle_number", 0, "coverage_targets"),
        )


@dataclass
class BudgetConfig:
    """Spec-declared budget knobs.

    Spec 061 (ADR-0011): the per-cycle budget is *operational config*, so the
    cycle cap (``max_cycles``) and dollar cap (``max_usd``) were removed from the
    spec schema — they now live exclusively in the vault's ``settings.yaml``
    (canonical ``pipeline.max_cycles`` / ``pipeline.budget_usd``, resolved via
    ``cli._budget_resolve``). Only the warn threshold remains spec-declarable.
    Stray ``max_usd``/``max_cycles`` keys in a parsed spec are ignored (like any
    other unknown field) rather than rejected, for backward compatibility.
    """

    warn_at_pct: float = 0.8

    def to_dict(self) -> dict[str, Any]:
        return {
            "warn_at_pct": self.warn_at_pct,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        return cls(
            warn_at_pct=float(d.get("warn_at_pct", 0.8)),
        )


EXECUTOR_TYPES = {"cli", "script", "api"}
ON_FAIL_VALUES = {"abort", "skip", "continue"}


@dataclass
class ExecutorConfig:
    """Paired runtime + model + skill that backs a single pipeline stage.

    A stage executor is always an object (never a bare string like "sonnet").
    It pairs WHERE the call runs (runtime, e.g. `claude`, `codex`, or a python
    script) with WHAT model answers (`model`), WHICH prompt drives it
    (`skill`), and HOW failures are handled.
    """

    type: str = "cli"
    runtime: str = "claude"
    model: str = "sonnet"
    skill: str | None = None
    script_path: str | None = None  # only used when type == "script"
    args: list[str] = field(default_factory=list)
    timeout_s: int = 3600
    retry: int = 1
    on_fail: str = "abort"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "runtime": self.runtime,
            "model": self.model,
            "skill": self.skill,
            "script_path": self.script_path,
            "args": list(self.args),
            "timeout_s": self.timeout_s,
            "retry": self.retry,
            "on_fail": self.on_fail,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        return cls(
            type=d.get("type", "cli"),
            runtime=d.get("runtime", "claude"),
            model=d.get("model", "sonnet"),
            skill=d.get("skill"),
            script_path=d.get("script_path"),
            args=list(d.get("args", []) or []),
            timeout_s=_int_field(
                d, "timeout_s", 3600, f"settings.executor.{d.get('runtime') or '?'}"
            ),
            retry=_int_field(
                d, "retry", 1, f"settings.executor.{d.get('runtime') or '?'}"
            ),
            on_fail=d.get("on_fail", "abort"),
        )


@dataclass
class CommandsConfig:
    """Slash-command / script names exposed inside the generated vault.

    Users can override each name to taste (e.g. `/research-framework` instead
    of `/ask`) without touching the pipeline that backs it.
    """

    ask: str = "ask"
    research: str = "research"
    write: str = "write"

    def to_dict(self) -> dict[str, Any]:
        return {"ask": self.ask, "research": self.research, "write": self.write}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        return cls(
            ask=d.get("ask", "ask"),
            research=d.get("research", "research"),
            write=d.get("write", "write"),
        )


@dataclass
class SpecSettings:
    """Per-spec overrides on top of the global `settings.yaml` file.

    Shape mirrors `settings.yaml` but every field is optional; missing values
    fall back to the global defaults at runtime. Parser and validator do not
    merge the two — they keep the spec slice here and the orchestrator merges
    when it picks a stage executor.
    """

    default_executor: ExecutorConfig | None = None
    stages: dict[str, ExecutorConfig] = field(default_factory=dict)
    commands: CommandsConfig = field(default_factory=CommandsConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_executor": (
                self.default_executor.to_dict() if self.default_executor else None
            ),
            "stages": {k: v.to_dict() for k, v in self.stages.items()},
            "commands": self.commands.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        default = d.get("default_executor")
        return cls(
            default_executor=(ExecutorConfig.from_dict(default) if default else None),
            stages={
                k: ExecutorConfig.from_dict(v)
                for k, v in (d.get("stages") or {}).items()
            },
            commands=CommandsConfig.from_dict(d.get("commands") or {}),
        )


@dataclass
class SpecConfig:
    name: str
    location: Path
    owner: str
    scope: ScopeConfig
    note_types: list[NoteTypeConfig]
    data_sources: list[DataSourceConfig]
    search_dimensions: list[str]
    coverage_targets: CoverageTargets
    budget: BudgetConfig
    naming_convention: str = "full_name"
    jira_project: str | None = None
    access_modes: list[str] = field(default_factory=list)
    settings: SpecSettings = field(default_factory=SpecSettings)
    code_source_url_patterns: list[str] = field(default_factory=list)
    # Default research mode for this vault. The CLI `--mode` flag overrides
    # at run time; auto-detection (empty vault → bootstrap, non-empty →
    # refresh) overrides when the user supplies neither.
    research_mode: str = "bootstrap"
    # Corpus folder name, relative to the vault root. Defaults to the
    # historical value so existing vaults without the spec field are
    # unaffected. Declared per-vault in the spec's `vault.corpus_dir` key.
    vault_corpus_dir: str = "data_vault"
    # Per-processor configuration (015f). Each key is a processor name;
    # values are free-form dicts merged with processor defaults at runtime.
    # All fields optional — missing keys fall back to processor defaults.
    # Example:
    #   processors:
    #     extract:
    #       enabled: true
    #       model: "claude-haiku-4-5"
    #     verify:
    #       fail_threshold: 0.15
    processors: dict[str, Any] = field(default_factory=dict)
    # Feature 017: vault-specific filename prefixes (e.g. ['oms_', 'wms_'])
    # that mark notes named after internal artifacts rather than engineering
    # concepts. Read by abstraction gates SG-003, CG-003, and success
    # criterion SC-009. Default empty: those gates report N/A and never fail
    # (R-007 backwards compat). Round-trip rule: empty list is omitted from
    # `to_dict()` to keep frontmatter readable for vaults that don't use
    # the gate (per `contracts/spec-extension.schema.md`).
    forbidden_filename_prefixes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "location": str(self.location),
            "owner": self.owner,
            "scope": self.scope.to_dict(),
            "note_types": [nt.to_dict() for nt in self.note_types],
            "data_sources": [ds.to_dict() for ds in self.data_sources],
            "search_dimensions": list(self.search_dimensions),
            "coverage_targets": self.coverage_targets.to_dict(),
            "budget": self.budget.to_dict(),
            "naming_convention": self.naming_convention,
            "jira_project": self.jira_project,
            "access_modes": list(self.access_modes),
            "settings": self.settings.to_dict(),
            "code_source_url_patterns": list(self.code_source_url_patterns),
            "research_mode": self.research_mode,
            "vault_corpus_dir": self.vault_corpus_dir,
            "processors": dict(self.processors),
        }
        # Round-trip rule: omit default-empty list so existing specs round-trip
        # byte-for-byte and new specs without the gate stay readable.
        if self.forbidden_filename_prefixes:
            d["forbidden_filename_prefixes"] = list(self.forbidden_filename_prefixes)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        return cls(
            name=d.get("name", ""),
            location=Path(d.get("location", ".")),
            owner=d.get("owner", ""),
            scope=ScopeConfig.from_dict(d.get("scope") or {}),
            note_types=[
                NoteTypeConfig.from_dict(nt) for nt in d.get("note_types", []) or []
            ],
            data_sources=[
                DataSourceConfig.from_dict(ds) for ds in d.get("data_sources", []) or []
            ],
            search_dimensions=list(d.get("search_dimensions", []) or []),
            coverage_targets=CoverageTargets.from_dict(d.get("coverage_targets") or {}),
            budget=BudgetConfig.from_dict(d.get("budget") or {}),
            naming_convention=d.get("naming_convention", "full_name"),
            jira_project=d.get("jira_project"),
            access_modes=list(d.get("access_modes", []) or []),
            settings=SpecSettings.from_dict(d.get("settings") or {}),
            code_source_url_patterns=list(d.get("code_source_url_patterns", []) or []),
            research_mode=d.get("research_mode", "bootstrap"),
            # Accept either the flat key written by to_dict / spec-parse.json,
            # or the nested `vault.corpus_dir` key as declared in the YAML
            # frontmatter of both simple and detailed spec files.
            vault_corpus_dir=(
                d.get("vault_corpus_dir")
                or (d.get("vault") or {}).get("corpus_dir")
                or "data_vault"
            ),
            processors=dict(d.get("processors") or {}),
            forbidden_filename_prefixes=list(
                d.get("forbidden_filename_prefixes", []) or []
            ),
        )


def primary_source(spec: SpecConfig) -> DataSourceConfig:
    """Return the single priority=1 role=behaviour source.

    Raises SpecValidationError if none or more than one exists.
    """
    primaries = [
        ds for ds in spec.data_sources if ds.priority == 1 and ds.role == "behaviour"
    ]
    if not primaries:
        raise SpecValidationError(["no data_source has priority=1 and role=behaviour"])
    if len(primaries) > 1:
        names = ", ".join(ds.name for ds in primaries)
        raise SpecValidationError(
            [f"multiple priority=1 role=behaviour sources found: {names}"]
        )
    return primaries[0]


def intent_sources(spec: SpecConfig) -> list[DataSourceConfig]:
    """Return all sources with role=intent, ordered by priority then name."""
    intents = [ds for ds in spec.data_sources if ds.role == "intent"]
    return sorted(intents, key=lambda ds: (ds.priority, ds.name))


def derive_trunk(spec: SpecConfig) -> DataSourceConfig | None:
    """Return the vault's trunk source, or None when none is derivable.

    spec 053 / D2 / Analyze F3: the trunk is the single data_source holding the
    **minimum `priority` value** (lower = higher priority). Its `role` is *not*
    constrained — a journal-first vault's trunk is a `domain` source, a
    code-first vault's is `behaviour`. This generalizes the historically
    hardcoded `priority == 1 and role == "behaviour"` selector.

    Returns None when there is no *unique* minimum: a tie on the minimum
    priority (caught by spec validation, FR-002) or a vault with no priority
    differentiation at all (every source on the default priority — a valid
    pure-domain shape). Callers that seed from the trunk MUST no-op when this
    returns None rather than treat "no trunk" as an error.
    """
    if not spec.data_sources:
        return None
    min_priority = min(ds.priority for ds in spec.data_sources)
    at_min = [ds for ds in spec.data_sources if ds.priority == min_priority]
    if len(at_min) != 1:
        return None
    return at_min[0]
