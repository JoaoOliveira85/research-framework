"""The one place the abstraction gates get their inputs (SG-003, CG-003).

SG-003 (scout topics) and CG-003 (vault filenames) ask the same question — is
this vault naming notes after internal artifacts rather than concepts? — and
three callers used to answer it from three places: the in-process step gate,
the cycle gate, and ``scripts/check_abstraction.py``, the CLI twin shipped into
every generated vault. The CLI read ``cycle-*-research.json`` while the gate
read ``cycle-NNN-scout.json``; those are different documents from different
stages, so the two could disagree on the same cycle. And both gates keyed off
``spec.forbidden_filename_prefixes``, which defaults to empty and is written by
nothing in the generator, so on a stock generated vault both reported ``NA`` —
"inactive" — for ever.

This module owns both answers: which prefixes count, and which report SG-003
reads. Callers import from here rather than re-deriving either.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from research_framework.pipeline.settings import SettingsError, load_vault_settings

DEFAULT_FORBIDDEN_FILENAME_PREFIXES: tuple[str, ...] = (
    "svc_",
    "srv_",
    "lib_",
    "pkg_",
    "job_",
    "tbl_",
    "tmp_",
    "internal_",
)
"""Framework starter set, used when a spec declares no prefixes of its own.

R-007 says the gate must not hardcode a *vault's* service codes (``oms_``,
``wms_``) — those are the spec's to declare. It does not say the framework may
ship a gate that is off in the only configuration the framework produces. These
eight are naming shapes for internal artifacts in any domain — a service, a
library, a package, a scheduled job, a database table, a scratch file, an
internal-only document — not concepts a reader would look up. A vault whose own
codes differ overrides the list in ``research.spec.md``; a vault that wants the
gate off sets ``pipeline.gates.abstraction_enabled: false`` in ``settings.yaml``.

The bands cushion a false positive: a single ``lib_`` note among ten topics is
10%, well under the 20% WARN threshold.
"""


def gates_settings(vault_dir: Path) -> dict[str, Any]:
    """``pipeline.gates`` from the vault's ``settings.yaml``, or an empty dict.

    Falls back to a raw YAML read when the typed loader rejects the file, so a
    gate never fails because some unrelated settings key is malformed.
    """
    try:
        pipe_extra = load_vault_settings(vault_dir).extras.get("pipeline") or {}
    except SettingsError:
        path = vault_dir / "settings.yaml"
        if not path.is_file():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        pipe_extra = data.get("pipeline") if isinstance(data, dict) else None
    if not isinstance(pipe_extra, dict):
        return {}
    gates = pipe_extra.get("gates")
    return gates if isinstance(gates, dict) else {}


def abstraction_gates_enabled(vault_dir: Path) -> bool:
    """Whether SG-003 / CG-003 run at all for this vault.

    Opting out is deliberate and explicit — ``pipeline.gates.abstraction_enabled:
    false`` — so that "inactive" is a recorded vault decision rather than the
    accident of an unpopulated spec key.
    """
    value = gates_settings(vault_dir).get("abstraction_enabled", True)
    return bool(value)


def effective_forbidden_filename_prefixes(spec: Any) -> list[str]:
    """The prefixes a spec is graded against, ignoring the vault's on/off switch.

    The spec wins when it declares prefixes; otherwise the framework starter set
    applies. Prompt rendering uses this directly — a rendered template has no
    vault settings to consult and must still name the rule the agent will be
    graded on.
    """
    declared = getattr(spec, "forbidden_filename_prefixes", None) or []
    return [str(p) for p in declared] or list(DEFAULT_FORBIDDEN_FILENAME_PREFIXES)


def resolve_forbidden_filename_prefixes(spec: Any, vault_dir: Path) -> list[str] | None:
    """Effective prefixes for the abstraction gates, or ``None`` when disabled.

    ``None`` is returned only for a vault that switched the gates off, and it is
    what both gates turn into their ``NA`` result.
    """
    if not abstraction_gates_enabled(vault_dir):
        return None
    return effective_forbidden_filename_prefixes(spec)


def latest_scout_report(cycles_dir: Path) -> Path | None:
    """Newest ``cycle-NNN-scout.json`` under ``cycles_dir``, or ``None``.

    SG-003 reads ``topics_found.new``, which only the scout report carries;
    the research report is the DFS output and has no such field. Anything that
    picks a report for this gate picks it here.
    """
    paths = sorted(cycles_dir.glob("cycle-*-scout.json"))
    return paths[-1] if paths else None
