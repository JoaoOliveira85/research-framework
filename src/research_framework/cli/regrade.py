"""``./vault re-grade`` verb (spec 066 FR4).

Re-evaluate every quarantined note (``_pipeline/quarantine/*.md``) against the
*current* credibility model (post-066 catalog + vault override + policy) and
reinstate any that were rejected **only** on credibility and now resolve clean.
Deterministic — zero LLM dispatch (Q4/FR4): the verdict source is the note's own
frontmatter plus :func:`deterministic_credibility_violations`.

See ``specs/066-credibility-model-calibration/contracts/regrade-verb.contract.md``.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_LOG = logging.getLogger(__name__)

# verifier_notes are stored as message strings (verifier._stamp_frontmatter), so
# we recognise the credibility class by message rather than rule_id.
_CREDIBILITY_NOTE_MARKERS = (
    "citation lacks credibility",
    "no source default applies",
    "citation url is malformed",
    "coi must be a boolean",
    "credibility must be one of",
    "credibility value is not a valid enum",
)


@dataclass
class RegradeOutcome:
    """Per-note re-grade result (data-model Entity 4)."""

    note: str
    action: str  # "reinstated" | "still_quarantined" | "skipped_non_credibility"
    destination: str | None = None
    catalog_basis: str | None = None
    remaining: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "note": self.note,
            "action": self.action,
            "destination": self.destination,
            "catalog_basis": self.catalog_basis,
            "remaining": list(self.remaining),
        }


def _is_credibility_note(message: str) -> bool:
    low = (message or "").strip().lower()
    return any(marker in low for marker in _CREDIBILITY_NOTE_MARKERS)


def _quarantine_dir(vault_dir: Path) -> Path:
    return vault_dir / "_pipeline" / "quarantine"


def _quarantined_notes(vault_dir: Path, only: list[str] | None) -> list[Path]:
    qdir = _quarantine_dir(vault_dir)
    if not qdir.is_dir():
        return []
    if only:
        wanted = {Path(name).name for name in only}
        return [p for p in sorted(qdir.glob("*.md")) if p.name in wanted]
    return sorted(qdir.glob("*.md"))


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str] | None:
    """Return ``(frontmatter, body)`` preserving the body, or ``None`` if absent.

    The closing delimiter is a ``---`` LINE, as the canonical parser reads it. A
    ``---`` inside a value (a slug URL such as ``kafka---a-guide``) is not one:
    splitting on the first substring cut the frontmatter there, which hid every
    key below it — ``verifier_notes`` included — and moved them into the body.
    """
    from ..vault.frontmatter import FrontmatterParseError, parse_frontmatter_str

    if not text.startswith("---\n"):
        return None
    try:
        return parse_frontmatter_str(text)
    except FrontmatterParseError:
        return None


def _restamp_verified(fm: dict[str, Any], body: str) -> str:
    fm = dict(fm)
    fm["verifier_status"] = "verified"
    fm.pop("verifier_notes", None)
    return (
        "---\n"
        + yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False)
        + "---\n"
        + body
    )


_TIER_NAME = {"primary": "tier_1", "corroborated": "tier_2", "commentary": "tier_3"}


def _catalog_basis(vault_dir: Path, fm: dict[str, Any]) -> str | None:
    """Best-effort ``"tier_2 via fastify.dev"`` basis for the human/JSON output."""
    try:
        from urllib.parse import urlparse

        from ..vault.credibility import citation_url, iter_source_url_entries
        from ..vault.credibility_catalog import build_resolved_catalog

        override: list[Any] = []
        policy = "warn"
        try:
            from ..pipeline.settings import load_vault_settings

            cred = load_vault_settings(vault_dir).credibility
            override = list(cred.trusted_domains)
            policy = cred.unknown_domain_policy
        except Exception:  # pragma: no cover - default catalog suffices
            pass
        catalog = build_resolved_catalog(override, unknown_domain_policy=policy)

        for entry in iter_source_url_entries(fm):
            url = citation_url(entry)
            if not url:
                continue
            level = catalog.lookup(url)
            if level is not None:
                host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
                return f"{_TIER_NAME.get(level.value, level.value)} via {host}"
    except Exception:  # pragma: no cover - advisory only
        return None
    return None


def _evaluate_note(vault_dir: Path, note: Path) -> RegradeOutcome:
    """Classify one quarantined note without mutating anything (pure)."""
    from ..pipeline.verifier import deterministic_credibility_violations

    rel = note.name
    try:
        text = note.read_text(encoding="utf-8")
    except OSError:
        return RegradeOutcome(
            note=rel, action="still_quarantined", remaining=["unreadable"]
        )

    split = _split_frontmatter(text)
    if split is None:
        return RegradeOutcome(
            note=rel, action="still_quarantined", remaining=["no frontmatter"]
        )
    fm, _body = split

    notes = fm.get("verifier_notes") or []
    if not isinstance(notes, list):
        notes = [str(notes)]
    notes = [str(n) for n in notes]

    # Criterion 1: credibility-only rejection (skip agent-semantic rejections).
    non_credibility = [n for n in notes if not _is_credibility_note(n)]
    if non_credibility:
        return RegradeOutcome(
            note=rel, action="skipped_non_credibility", remaining=non_credibility
        )

    # Criterion 2: re-run the post-066 deterministic credibility check; a
    # ``severity: fail`` violation keeps the note quarantined.
    violations = deterministic_credibility_violations(vault_dir, rel, text)
    fails = [v for v in violations if v.get("severity", "fail") != "warn"]
    if fails:
        return RegradeOutcome(
            note=rel,
            action="still_quarantined",
            remaining=[str(v.get("message", v)) for v in fails],
        )

    basis = _catalog_basis(vault_dir, fm)
    return RegradeOutcome(note=rel, action="reinstated", catalog_basis=basis)


_COLLISION_SUFFIX_RX = re.compile(r"^(?P<stem>.+)-(?P<n>\d+)$")


def duplicate_of_live_note(vault_dir: Path, note: Path, body: str) -> Path | None:
    """Return the live note ``note`` is a collision-renamed copy of, else ``None``.

    Spec 070 F9. ``_quarantine_rejected_notes`` renames on collision — a second
    rejection of ``foo.md`` lands in quarantine as ``foo-3.md``. Re-grade then
    reinstated BOTH under their quarantine names, so a vault that quarantined
    the same note twice came back with ``foo.md`` and ``foo-3.md`` side by side:
    byte-identical duplicates polluting the graph and the coverage count.
    Observed live on `community-vault`, which gained 9 of them in one run.

    Deliberately conservative — a name is only treated as a collision copy when
    BOTH hold:

    - stripping a trailing ``-<digits>`` yields a note that actually exists in
      ``data_vault/`` (so a legitimate title like ``http-2`` is safe unless an
      ``http`` note also exists), and
    - the two bodies are byte-identical (so a genuine variant is never dropped).
    """
    m = _COLLISION_SUFFIX_RX.match(note.stem)
    if m is None:
        return None
    canonical = f"{m.group('stem')}.md"
    corpus = vault_dir / "data_vault"
    if not corpus.is_dir():
        return None
    for candidate in corpus.rglob(canonical):
        try:
            other = candidate.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover - defensive
            continue
        split = _split_frontmatter(other)
        if split is None:
            continue
        if split[1].strip() == body.strip():
            return candidate
    return None


def _live_destination(vault_dir: Path, fm: dict, name: str) -> Path | None:
    """Return the live note ``_reinstate`` would overwrite, if one exists."""
    from ..pipeline.coverage import resolve_category_folder

    dest = resolve_category_folder(vault_dir, fm) / name
    return dest if dest.exists() else None


def _reinstate(vault_dir: Path, note: Path, outcome: RegradeOutcome) -> None:
    """Restamp + move a reinstated note into ``data_vault/`` (atomic)."""
    from ..pipeline.atomic_write import write_text as _aw_text
    from ..pipeline.coverage import resolve_category_folder

    text = note.read_text(encoding="utf-8")
    split = _split_frontmatter(text)
    if split is None:
        return
    fm, body = split
    dest_dir = resolve_category_folder(vault_dir, fm)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / note.name
    _aw_text(dest, _restamp_verified(fm, body))
    try:
        note.unlink()
    except OSError:  # pragma: no cover - defensive
        pass
    try:
        outcome.destination = str(dest.relative_to(vault_dir))
    except ValueError:  # pragma: no cover
        outcome.destination = str(dest)
    _drop_backlog_pointer(vault_dir, note.stem)


def _drop_backlog_pointer(vault_dir: Path, stem: str) -> None:
    """Best-effort removal of the spec-062 "rewrite quarantined note" backlog line."""
    backlog = vault_dir / "_pipeline" / "research-backlog.md"
    if not backlog.is_file():
        return
    try:
        from ..pipeline.atomic_write import write_text as _aw_text

        lines = backlog.read_text(encoding="utf-8").splitlines(keepends=True)
        needle = f"rewrite quarantined note: {stem}".lower()
        kept = [ln for ln in lines if needle not in ln.lower()]
        if len(kept) != len(lines):
            _aw_text(backlog, "".join(kept))
    except OSError:  # pragma: no cover - advisory
        pass


def run_regrade(
    vault_dir: Path,
    *,
    dry_run: bool = False,
    notes: list[str] | None = None,
    json_output: bool = False,
) -> int:
    """Re-grade quarantined notes; reinstate the now-clean credibility-only ones."""
    targets = _quarantined_notes(vault_dir, notes)
    outcomes = [_evaluate_note(vault_dir, note) for note in targets]
    by_name = {note.name: note for note in targets}

    reinstated: list[RegradeOutcome] = []
    still: list[RegradeOutcome] = []
    skipped: list[RegradeOutcome] = []
    for outcome in outcomes:
        if outcome.action == "reinstated":
            reinstated.append(outcome)
        elif outcome.action == "skipped_non_credibility":
            skipped.append(outcome)
        else:
            still.append(outcome)

    # Spec 070 F9: a collision-renamed quarantine copy of a note that is already
    # live must not be reinstated as a second file. Left in quarantine rather
    # than deleted — dropping content is the operator's call, not ours.
    deduped: list[RegradeOutcome] = []
    for outcome in reinstated:
        note_path = by_name[outcome.note]
        split = _split_frontmatter(note_path.read_text(encoding="utf-8"))
        twin = (
            duplicate_of_live_note(vault_dir, note_path, split[1])
            if split is not None
            else None
        )
        occupied = (
            _live_destination(vault_dir, split[0], note_path.name)
            if (twin is None and split is not None)
            else None
        )
        if twin is not None:
            outcome.action = "skipped_non_credibility"
            outcome.remaining = [
                f"duplicate of the already-live note "
                f"{twin.relative_to(vault_dir).as_posix()} (identical body); "
                f"left in quarantine so it is not reinstated twice"
            ]
            skipped.append(outcome)
        elif occupied is not None:
            # Contract §2: live notes are never touched. A same-named live note
            # with a different body is usually the backlog's rewrite of this
            # one; reinstating would replace it with the stale copy.
            outcome.action = "skipped_non_credibility"
            outcome.remaining = [
                f"a different live note already exists at "
                f"{occupied.relative_to(vault_dir).as_posix()}; "
                f"left in quarantine rather than overwrite it"
            ]
            skipped.append(outcome)
        else:
            deduped.append(outcome)
    reinstated = deduped

    commit_sha: str | None = None
    if not dry_run and reinstated:
        for outcome in reinstated:
            _reinstate(vault_dir, by_name[outcome.note], outcome)
        commit_sha = _commit(vault_dir, reinstated)

    if json_output:
        print(
            json.dumps(
                {
                    "vault": str(vault_dir),
                    "reinstated": [o.to_dict() for o in reinstated],
                    "still_quarantined": [o.to_dict() for o in still],
                    "skipped": [o.to_dict() for o in skipped],
                    "commit": commit_sha,
                },
                indent=2,
            )
        )
    else:
        _print_human(vault_dir, reinstated, still, skipped, commit_sha, dry_run)
    return 0


def _commit(vault_dir: Path, reinstated: list[RegradeOutcome]) -> str | None:
    try:
        from ..pipeline.vault_commit import commit_regrade

        body_lines = ["**Reinstated**"]
        for o in reinstated:
            basis = f" ({o.catalog_basis})" if o.catalog_basis else ""
            body_lines.append(f"- {o.note} → {o.destination}{basis}")
        result = commit_regrade(
            vault_dir, count=len(reinstated), body="\n".join(body_lines)
        )
        return getattr(result, "sha", None)
    except Exception as exc:  # pragma: no cover - moves persist; next run re-commits
        _LOG.warning("re-grade: commit failed (%s); moves persist on disk", exc)
        return None


def _print_human(
    vault_dir: Path,
    reinstated: list[RegradeOutcome],
    still: list[RegradeOutcome],
    skipped: list[RegradeOutcome],
    commit_sha: str | None,
    dry_run: bool,
) -> None:
    print(f"Re-grade — {vault_dir.name}")
    print(
        f"  reinstated: {len(reinstated)}   still-quarantined: {len(still)}   "
        f"skipped (non-credibility): {len(skipped)}"
    )
    for o in reinstated:
        basis = f"  ({o.catalog_basis})" if o.catalog_basis else ""
        dest = o.destination or "(dry-run)"
        print(f"  {o.note}  → {dest}{basis}")
    for o in still:
        why = "; ".join(o.remaining) or "credibility unresolved"
        print(f"  {o.note}  \u2298 still-quarantined ({why})")
    if dry_run:
        print("  (dry-run — nothing written, no commit)")
    elif commit_sha:
        print(
            f"Committed regrade: {len(reinstated)} notes reinstated  ({commit_sha[:7]})"
        )


def _cmd_regrade(args: argparse.Namespace) -> int:
    vault = getattr(args, "vault", None)
    if vault is None:
        print("error: --vault is required", file=sys.stderr)
        return 2
    vault_dir = Path(vault).expanduser().resolve()
    if not vault_dir.is_dir():
        print(f"error: vault not found: {vault_dir}", file=sys.stderr)
        return 2
    return run_regrade(
        vault_dir,
        dry_run=bool(getattr(args, "dry_run", False)),
        notes=list(getattr(args, "note", []) or []),
        json_output=bool(getattr(args, "json", False)),
    )


__all__ = ["RegradeOutcome", "run_regrade", "_cmd_regrade"]
