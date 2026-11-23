"""Which notes a cycle produced, from what the PIPELINE recorded (spec 087).

The research report is a file every note-writer agent rewrites whole on every
batch, so after the batch loop it holds only what the LAST batch's agent wrote.
With update and new batches interleaved, whichever kind came last lost its list
and the verifier never saw those notes. The pipeline therefore keeps its own
record per batch and writes it back over the report once the loop is done:

=========================  =================================================
report field               source after the loop
=========================  =================================================
``notes_created``          accumulated by the pipeline (files each new batch
                           created) plus the agents' entries, normalised
``notes_updated``          derived from the update-outcomes sidecar (UG-001
                           passed, outcome not ``confirmed``) plus the agents'
                           other entries, normalised
``update_outcomes`` and    derived from the sidecar
``update_outcome_results``
``capture_failures``,      accumulated across batches (union)
``new_wikilinks_discovered``,
``unresolved_wikilinks``
``skipped_topics``         read right after each batch, into its batch file
cost fields                agent estimates, last write; not binding (the
                           budget guard sums the metered sidecars)
``note_writer_cap_tripped``  written by the pipeline after the loop
``topics_researched``,     not read after the loop
``topics_deepened``,
``termination_condition``
=========================  =================================================
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .atomic_write import write_json

_LOG = logging.getLogger(__name__)

ACCUMULATED_LISTS = (
    "capture_failures",
    "new_wikilinks_discovered",
    "unresolved_wikilinks",
)


def normalise_notes(vault_dir: Path, names: list[Any]) -> list[str]:
    """Vault-relative paths, without duplicates, in first-seen order.

    A bare filename (``Foo.md``) is resolved by name under ``data_vault/``; an
    entry that does not resolve, or resolves to several files, is dropped with a
    WARNING instead of becoming a note nobody can find.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in names:
        if not isinstance(raw, str) or not raw.strip():
            continue
        name = raw.strip()
        rel: str | None = None
        candidate = vault_dir / name
        if candidate.is_file():
            try:
                rel = candidate.resolve().relative_to(vault_dir.resolve()).as_posix()
            except ValueError:
                rel = None
        if rel is None:
            matches = sorted(
                p
                for p in (vault_dir / "data_vault").rglob(Path(name).name)
                if p.is_file()
            )
            if len(matches) == 1:
                rel = matches[0].relative_to(vault_dir).as_posix()
            else:
                _LOG.warning(
                    "research report lists %r, which %s; dropping it",
                    raw,
                    "matches several notes"
                    if matches
                    else "is not a note in the vault",
                )
                continue
        if rel not in seen:
            seen.add(rel)
            out.append(rel)
    return out


def _union(first: list[Any], second: list[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for item in [*first, *second]:
        key = json.dumps(item, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


class CycleRecord:
    """What the pipeline saw each batch produce, kept across the batch loop."""

    def __init__(self, vault_dir: Path) -> None:
        self.vault_dir = vault_dir
        self.notes_created: list[str] = []
        self.lists: dict[str, list[Any]] = {k: [] for k in ACCUMULATED_LISTS}

    def absorb(self, report_path: Path, new_files: list[str]) -> None:
        """After a batch: its new files, and the lists its agent just wrote."""
        self.notes_created = normalise_notes(
            self.vault_dir, [*self.notes_created, *new_files]
        )
        try:
            doc = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(doc, dict):
            return
        for key in ACCUMULATED_LISTS:
            value = doc.get(key)
            if isinstance(value, list):
                self.lists[key] = _union(self.lists[key], value)

    def apply(self, cycles_dir: Path, report_path: Path, cycle: int) -> None:
        """Write the pipeline's record over the report (idempotent)."""
        from . import update_outcomes

        try:
            doc = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
        if not isinstance(doc, dict):
            doc = {}
        results = update_outcomes.sidecar_results(cycles_dir, cycle)
        assigned = {r["path"] for r in results if r.get("path")}
        derived = [
            r["path"]
            for r in results
            if r.get("status") == "passed"
            and r.get("outcome") != "confirmed"
            and r.get("path")
        ]
        doc["notes_created"] = [
            n
            for n in normalise_notes(
                self.vault_dir, [*(doc.get("notes_created") or []), *self.notes_created]
            )
            if n not in assigned
        ]
        agent_updated = [
            n
            for n in normalise_notes(self.vault_dir, doc.get("notes_updated") or [])
            if n not in assigned
        ]
        doc["notes_updated"] = _union(derived, agent_updated)
        if results:
            doc["update_outcomes"] = [r["row"] for r in results if r.get("row")]
            doc["update_outcome_results"] = [
                {k: v for k, v in r.items() if k != "row"} for r in results
            ]
        for key in ACCUMULATED_LISTS:
            merged = _union(self.lists[key], doc.get(key) or [])
            if merged or key in doc:
                doc[key] = merged
        write_json(report_path, doc)
