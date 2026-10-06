"""Validate a SpecConfig — raises SpecValidationError with field-level messages."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .schema import RESEARCH_MODES, SpecConfig, SpecValidationError, derive_trunk

_AUTHORITY_ROLES = ("behaviour", "intent", "domain")

REQUIRED_DIMENSIONS = {"domain", "market"}


def _local_path_resolves(raw: str) -> bool:
    """True iff ``raw`` is a non-empty filesystem path that exists.

    ``~`` and environment variables are expanded so users can write
    ``local_path: ~/src/foo`` or ``local_path: $WORK/foo`` and have
    them resolve without surprises. Empty / None / falsey strings are
    treated as "no local path declared".
    """
    if not raw:
        return False
    expanded = os.path.expandvars(os.path.expanduser(raw))
    try:
        return Path(expanded).exists()
    except OSError:
        return False


# Default repo URL shape: any github / gitlab / bitbucket org + a `file://`
# escape hatch for local enumerated checkouts. Vaults that want to scope
# repos to a specific org override this by declaring
# `code_source_url_patterns` in the spec; the validator then requires every
# repo URL to match at least one of those patterns.
DEFAULT_REPO_URL_PATTERNS: tuple[str, ...] = (
    r"^https?://github\.com/[^/]+/",
    r"^https?://gitlab\.com/[^/]+/",
    r"^https?://bitbucket\.org/[^/]+/",
    r"^file://",
)
CODE_WINS_PATTERN = re.compile(
    r"code.*(wins|primary|truth|authoritative|source[- ]of[- ]truth)", re.IGNORECASE
)


def _compile_repo_url_patterns(spec: SpecConfig) -> list[re.Pattern[str]]:
    """Return compiled patterns for validating repo URLs.

    Honours ``spec.code_source_url_patterns`` when set, otherwise falls back
    to :data:`DEFAULT_REPO_URL_PATTERNS`. Malformed user-supplied regexes
    are silently skipped — validation will fall through to "no pattern
    matched" and surface a single clear error rather than a confusing
    traceback.
    """
    raw = list(spec.code_source_url_patterns) or list(DEFAULT_REPO_URL_PATTERNS)
    compiled: list[re.Pattern[str]] = []
    for pat in raw:
        try:
            compiled.append(re.compile(pat, re.IGNORECASE))
        except re.error:
            continue
    return compiled


def validate(spec: SpecConfig, *, vault_dir: Path | None = None) -> None:
    """Validate SpecConfig invariants. Raises SpecValidationError on any violation.

    When ``vault_dir`` is provided (the ``generate`` / ``--resume`` gate), spec
    069 FR1 also runs: every declared ``data_source`` must trigger-match an
    installed module OR carry ``kind: strategy_hint``; an ``unbacked`` source is a
    hard validation error. Omitting ``vault_dir`` (the default, used by unit tests
    and callers without a module context) skips the backing check.
    """
    errors: list[str] = []

    if not spec.name:
        errors.append("missing required field: name")
    if not spec.owner:
        errors.append("missing required field: owner")

    if not spec.note_types:
        errors.append("note_types must contain at least one entry")
    if not spec.data_sources:
        errors.append("data_sources must contain at least one entry")

    missing_dims = REQUIRED_DIMENSIONS - set(spec.search_dimensions)
    if missing_dims:
        errors.append(
            f"search_dimensions must include {sorted(REQUIRED_DIMENSIONS)} "
            f"(missing: {sorted(missing_dims)})"
        )

    if not spec.coverage_targets.categories:
        errors.append("coverage_targets must contain at least one category")

    for nt in spec.note_types:
        if not nt.name:
            errors.append("note_types entry missing 'name'")
        if not nt.folder:
            errors.append(f"note_types entry '{nt.name}' missing 'folder'")
        if nt.source_policy and nt.source_policy not in ("hard", "soft"):
            errors.append(
                f"note_types '{nt.name}' has invalid source_policy "
                f"'{nt.source_policy}' (must be 'hard' or 'soft')"
            )
        # spec 053 FR-001: the authoritative role (when declared) anchors the
        # note's claim-type at gate time, so it must be a valid role.
        if nt.authoritative_role and nt.authoritative_role not in _AUTHORITY_ROLES:
            errors.append(
                f"note_types '{nt.name}' has invalid authoritative_role "
                f"'{nt.authoritative_role}' (must be one of {list(_AUTHORITY_ROLES)})"
            )

    # spec 053 FR-001: authoritative_role is opt-in for back-compat with
    # pre-053 specs, but once ANY note_type adopts it the gates resolve every
    # note's claim-type from it — so it must be declared consistently. A
    # fully-legacy spec (no note_type declares it) is exempt.
    declared = [nt for nt in spec.note_types if nt.authoritative_role]
    if declared and len(declared) != len(spec.note_types):
        missing = [nt.name for nt in spec.note_types if not nt.authoritative_role]
        errors.append(
            "note_types declare authoritative_role inconsistently — these lack "
            f"it: {', '.join(missing)}. Declare authoritative_role on every "
            "note_type once any adopts the authority model (spec 053 FR-001)."
        )

    # `role` semantics differ between code-first and simple specs:
    #
    # - Code-first specs (feature 002) use a fixed vocabulary:
    #   `behaviour | intent | domain`. The strict check lives in
    #   `_validate_code_first` so we only enforce it when the heuristic
    #   identifies the spec as code-first.
    # - Simple specs (recipe vaults, photography vaults, etc.) use `role`
    #   as a free-form semantic tag authored by the user or the vault-spec
    #   skill (e.g. `recipes`, `nutrition`, `reference`). Here we only
    #   require the value to be a non-empty string so typos like
    #   `role: ""` still get caught.
    code_first = _is_code_first_spec(spec)

    for ds in spec.data_sources:
        if not ds.name:
            errors.append("data_sources entry missing 'name'")
        if ds.type not in ("internal", "external"):
            errors.append(
                f"data_sources '{ds.name}' has invalid type '{ds.type}' "
                "(must be 'internal' or 'external')"
            )
        if code_first:
            if ds.role not in ("behaviour", "intent", "domain"):
                errors.append(
                    f"data_sources '{ds.name}' has invalid role '{ds.role}' "
                    "(must be 'behaviour', 'intent', or 'domain' in "
                    "code-first specs)"
                )
        else:
            if not isinstance(ds.role, str) or not ds.role.strip():
                errors.append(
                    f"data_sources '{ds.name}' role must be a non-empty "
                    f"string (got {ds.role!r})"
                )
        if not isinstance(ds.priority, int) or ds.priority < 1:
            errors.append(
                f"data_sources '{ds.name}' priority must be a positive int "
                f"(got {ds.priority})"
            )
        for phase in ds.phases:
            if phase not in RESEARCH_MODES:
                errors.append(
                    f"data_sources '{ds.name}' has invalid phase '{phase}' "
                    f"(must be one of {list(RESEARCH_MODES)})"
                )

    if spec.research_mode not in RESEARCH_MODES:
        errors.append(
            f"research_mode '{spec.research_mode}' is invalid "
            f"(must be one of {list(RESEARCH_MODES)})"
        )

    # spec 053 FR-002 / Analyze F3: the trunk is the source holding the unique
    # minimum `priority`. If `derive_trunk` finds no unique minimum it is either
    # a genuine tie (ambiguous trunk — FAIL) or a pure-domain vault with no
    # priority differentiation at all (valid — no trunk intended). Distinguish:
    # >1 distinct priority value means differentiation exists, so a tie at the
    # minimum is the ambiguous case.
    if spec.data_sources and derive_trunk(spec) is None:
        distinct = {ds.priority for ds in spec.data_sources}
        if len(distinct) > 1:
            min_p = min(distinct)
            tied = [ds.name for ds in spec.data_sources if ds.priority == min_p]
            errors.append(
                f"ambiguous trunk: the minimum priority {min_p} is shared by "
                f"{', '.join(tied)} — exactly one source must hold the minimum "
                "priority so the trunk is unambiguous (spec 053 FR-002)."
            )

    # Code-first invariants — auto-detected via non-default role/priority/repos
    # usage (see `_is_code_first_spec` above). v0.1 specs with default
    # priority=2/role=behaviour/repos=[] on every source skip this path.
    if code_first:
        errors.extend(_validate_code_first(spec))

    # Coverage categories must reference existing note types
    note_type_names = {nt.name for nt in spec.note_types}
    for cat in spec.coverage_targets.categories:
        if cat.note_type and cat.note_type not in note_type_names:
            errors.append(
                f"coverage category '{cat.name}' references unknown "
                f"note_type '{cat.note_type}'"
            )
        # Feature 017: per-category priority bound. Default 0 (unset) is
        # always valid; range [0, 100] is enforced.
        _validate_priority(cat.name, cat.priority, errors)

    # Feature 017: forbidden_filename_prefixes is additive optional. Empty
    # list is valid (gate reports N/A); non-empty entries MUST be
    # non-empty strings ending in `_` or `-` so they're unambiguous prefix
    # matchers downstream (per `contracts/spec-extension.schema.md`).
    _validate_forbidden_filename_prefixes(spec.forbidden_filename_prefixes, errors)

    # spec 069 FR1: declared-source backing. Only when a module context is
    # available (the generate / resume gate); skipped for context-free callers.
    if vault_dir is not None:
        errors.extend(_validate_source_backing(spec, vault_dir))
        errors.extend(_validate_credibility_binding(spec, vault_dir))

    if errors:
        raise SpecValidationError(errors)


def _validate_source_backing(spec: SpecConfig, vault_dir: Path) -> list[str]:
    """spec 069 FR1 (C2-a): every declared source must be backed or strategy_hint."""
    from .source_backing import (
        build_available_registry,
        source_is_backed,
        unbacked_message,
    )

    registry = build_available_registry(vault_dir)
    errors: list[str] = []
    for ds in spec.data_sources:
        if source_is_backed(ds, registry) == "unbacked":
            errors.append(unbacked_message(ds.name))
    return errors


def _validate_credibility_binding(spec: SpecConfig, vault_dir: Path) -> list[str]:
    """spec 070 FR2: a declared default_credibility must be able to bind."""
    from .source_backing import (
        build_available_registry,
        credibility_binding,
        unbindable_credibility_message,
    )

    registry = build_available_registry(vault_dir)
    return [
        unbindable_credibility_message(ds.name)
        for ds in spec.data_sources
        if credibility_binding(ds, registry) == "unbindable"
    ]


def _validate_forbidden_filename_prefixes(
    prefixes: list[str], errors: list[str]
) -> None:
    """Per spec-extension.schema.md: each entry MUST be a non-empty string
    ending with `_` or `-`. Empty list is valid."""
    for i, p in enumerate(prefixes):
        if not isinstance(p, str) or not p:
            errors.append(
                f"forbidden_filename_prefixes[{i}]: must be non-empty string "
                f"(got {p!r})"
            )
        elif not (p.endswith("_") or p.endswith("-")):
            errors.append(
                f"forbidden_filename_prefixes[{i}]={p!r}: must end with "
                "'_' or '-' so it's an unambiguous prefix matcher"
            )


def _validate_priority(category_name: str, priority: int, errors: list[str]) -> None:
    """Per spec-extension.schema.md: priority MUST be int in [0, 100]."""
    if not isinstance(priority, int) or isinstance(priority, bool):
        errors.append(
            f"coverage category '{category_name}' priority: must be int, "
            f"got {type(priority).__name__}"
        )
    elif not (0 <= priority <= 100):
        errors.append(
            f"coverage category '{category_name}' priority={priority}: "
            "must be in [0, 100]"
        )


def _is_code_first_spec(spec: SpecConfig) -> bool:
    """Detect whether the spec uses the code-first feature.

    Trigger on any of:
      - a source with BOTH `priority=1` AND `role="behaviour"` (the canonical
        primary behaviour trunk), OR
      - a source with `role="intent"` (intent axis is code-first only), OR
      - a source with a non-empty `repos` list (hard code-first signal).

    spec 053 (FR-002): `priority=1` *alone* is NOT a trigger. Under the
    generalized authority model any vault has a minimum-priority trunk, and a
    journal-/docs-first vault legitimately puts a `domain` source at priority 1.
    Firing the behaviour-primary invariants on it (the pre-053 behaviour) wrongly
    rejected those valid vaults. `role="domain"` is likewise never a trigger:
    domain sources are standard in simple-spec vaults (e.g. a "photography on
    film" vault). v0.1 specs at defaults (priority=2, role=behaviour, repos=[])
    also skip this path — FR-017 regression safety.
    """
    for ds in spec.data_sources:
        if (
            (ds.priority == 1 and ds.role == "behaviour")
            or ds.role == "intent"
            or ds.repos
        ):
            return True
    return False


def _validate_code_first(spec: SpecConfig) -> list[str]:
    """Invariants for code-first specs.

    Returns a list of error messages (empty when all rules pass).
    """
    errors: list[str] = []

    primaries = [
        ds for ds in spec.data_sources if ds.priority == 1 and ds.role == "behaviour"
    ]
    if not primaries:
        errors.append(
            "data_sources: no source has priority=1 and role=behaviour "
            "(code-first requires a single primary behaviour source)"
        )
    elif len(primaries) > 1:
        names = ", ".join(ds.name for ds in primaries)
        errors.append(
            f"data_sources: multiple sources declare priority=1 role=behaviour "
            f"({names}); exactly one primary behaviour source is required"
        )
    else:
        primary = primaries[0]
        if not primary.repos:
            errors.append(
                f"data_sources '{primary.name}': primary behaviour source must "
                "declare at least one repo in `repos`"
            )
        patterns = _compile_repo_url_patterns(spec)
        for repo in primary.repos:
            if not repo.url:
                errors.append(
                    f"data_sources '{primary.name}' repo '{repo.name}' "
                    "missing required field: url"
                )
                continue
            # B.3 (post-mortem 2026-05-30): if the repo has a `local_path`
            # AND that path resolves on disk, the repo URL is implicitly
            # trusted regardless of the `code_source_url_patterns`
            # whitelist. Rationale: a user who declares
            # `local_path: /Users/me/src/foo` and points at it has already
            # "vouched" for the source physically. Requiring them to ALSO
            # add `^file://` to the URL pattern list was a footgun (the
            # most common feeds-vault failure during the revival).
            if _local_path_resolves(repo.local_path):
                continue
            if not any(pat.match(repo.url) for pat in patterns):
                displayed = list(spec.code_source_url_patterns) or list(
                    DEFAULT_REPO_URL_PATTERNS
                )
                errors.append(
                    f"data_sources '{primary.name}' repo '{repo.name}' url "
                    f"'{repo.url}' does not match any allowed pattern "
                    f"({displayed}); set `code_source_url_patterns` in the "
                    "spec to narrow or broaden the whitelist"
                )

    intents_required = [
        ds for ds in spec.data_sources if ds.role == "intent" and ds.required
    ]
    if not intents_required:
        errors.append(
            "data_sources: at least one source with role=intent and required=true "
            "is needed (so the intent axis can be validated in every cycle)"
        )

    if not any(
        CODE_WINS_PATTERN.search(rule) for rule in spec.scope.source_of_truth_rules
    ):
        errors.append(
            "scope.source_of_truth_rules: missing code-wins rule "
            "(one entry must state that code is the authoritative source for behaviour)"
        )

    return errors
