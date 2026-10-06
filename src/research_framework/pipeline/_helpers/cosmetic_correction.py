"""Cosmetic-only correction detection and SG-005 synthetic gate helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..gates import GateResult

_FRONTMATTER_DELIM = "---"


def _split_note_frontmatter(text: str) -> tuple[str, str]:
    """Return ``(frontmatter, body)`` for a vault note. Frontmatter is empty if
    the note has no ``---``-delimited block.

    Used only by the anti-fraud detector. Lifted out of that function so a
    test can exercise the split rules in isolation (and so the cycle runner
    has exactly one parser for note frontmatter — the verifier uses a
    different one with stricter YAML loading and we don't want them to drift).
    """
    if not text.startswith(_FRONTMATTER_DELIM):
        return "", text
    parts = text.split(_FRONTMATTER_DELIM, 2)
    if len(parts) < 3:
        return "", text
    return parts[1], parts[2]


def _snapshot_note_bodies(data_vault: Path) -> dict[str, str]:
    """Hash the body (post-frontmatter content) of every note in ``data_vault``.

    Anti-fraud detector input — see :func:`_detect_cosmetic_only_correction`.
    Keyed by ``rel.as_posix()`` (filename can collide across folders, the
    relative path can't). Body-only hashing means a frontmatter-only edit
    yields the same hash before and after, which is exactly the
    "bookkeeping fraud" signal we want to catch.
    """
    out: dict[str, str] = {}
    if not data_vault.is_dir():
        return out
    for p in data_vault.rglob("*.md"):
        try:
            rel = p.relative_to(data_vault)
        except ValueError:
            continue
        if rel.name in ("_index.md", "_concepts.md", "_graph.md"):
            continue
        if "_templates" in rel.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        _fm, body = _split_note_frontmatter(text)
        out[rel.as_posix()] = hashlib.sha1(body.encode("utf-8")).hexdigest()
    return out


def _detect_cosmetic_only_correction(
    data_vault: Path,
    body_snapshot_before: dict[str, str],
    new_note_paths: list[Path],
) -> GateResult | None:
    """Return a FAIL gate when a correction batch is purely cosmetic.

    Fires when ALL three conditions hold:

    1. The batch was a correction batch (caller decides — only invoked from
       the correction path).
    2. The agent produced **zero** new note files (``new_note_paths`` is empty).
    3. Every change since the snapshot was inside the YAML frontmatter — the
       body hash is unchanged for every modified note, or no notes were
       modified at all.

    The v0.2.19 cycle-6 trace shows the exact failure mode this guards
    against: SG-005 told the agent to "restore frontmatter completeness", so
    the agent edited titles on already-written notes and rewrote the cycle
    research report to claim those nine notes as `notes_updated`. From the
    pipeline's point of view the correction was accepted; from the user's,
    no actual research happened.
    """
    if new_note_paths:
        return None
    snapshot_after = _snapshot_note_bodies(data_vault)
    body_changed: list[str] = []
    frontmatter_only_changed: list[str] = []
    for rel, before_hash in body_snapshot_before.items():
        after_hash = snapshot_after.get(rel)
        if after_hash is None:
            continue
        if after_hash == before_hash:
            continue
        body_changed.append(rel)
    # Surface all files present in both snapshots so the operator sees
    # what the correction batch touched. The list is only consumed when
    # `body_changed` is empty (we return early below otherwise), so the
    # surviving entries are by construction the ones with unchanged
    # body hashes — i.e. files where the modification, if any, must have
    # been in frontmatter. We can't *prove* a frontmatter touch without
    # storing the raw text, but the cycle runner has already established
    # that this is a correction batch with zero new notes, so any
    # touched-but-body-unchanged file is fraudulent.
    #
    # NOTE: an earlier draft of this loop included a `before_text = ""`
    # placeholder for a never-implemented body-vs-frontmatter diff. The
    # hash-only telemetry we have today is sufficient for the gate; the
    # placeholder was removed in the 0.6.x quality pass.
    for rel in snapshot_after:
        if rel not in body_snapshot_before:
            continue
        if rel in body_changed:
            # Real body edit — not cosmetic. Skip; the early-return on
            # body_changed below will short-circuit the gate.
            continue
        frontmatter_only_changed.append(rel)

    if body_changed:
        # The agent did real work on existing notes — that's a legitimate
        # "deepening" pass, not fraud. Don't fire.
        return None
    if not snapshot_after:
        return None
    # Zero new notes AND no body changes anywhere → either no-op (which the
    # batch_yield_empty gate already catches) or pure frontmatter renaming.
    # Either way, refuse to count it as a successful correction.
    return GateResult(
        gate_id="SG-006",
        status="FAIL",
        metric_name="correction_cosmetic_only",
        metric_value=len(frontmatter_only_changed),
        threshold=0,
        message=(
            "correction batch produced no new notes and no body changes — "
            "cosmetic frontmatter edits do not count as a research correction"
        ),
        correction_hint=(
            "Write a new note in data_vault/<folder>/ for each assigned topic "
            "(rename existing notes only as a side effect of legitimate "
            "research, never as the primary 'fix')."
        ),
    )


def _synthetic_mid_batch_empty_sg005(
    batch_number: int,
    n_batches_total: int,
    note_paths: list[Path],
    n_topics: int,
) -> GateResult | None:
    """Fail the midpoint batch when the writer produced no files (integration tests)."""
    if note_paths or n_topics == 0:
        return None
    mid = (n_batches_total + 1) // 2
    if batch_number != mid:
        return None
    return GateResult(
        gate_id="SG-005",
        status="FAIL",
        metric_name="batch_yield_empty",
        metric_value=0,
        threshold=n_topics,
        message=(
            f"batch {batch_number}: {n_topics} topics assigned but no notes were written"
        ),
        correction_hint=(
            # The old hint ("restore frontmatter completeness") was the wrong
            # diagnosis for a zero-yield batch — it nudged the correction agent
            # toward cosmetic frontmatter edits on existing notes, which is how
            # v0.2.19 cycle-6 produced the "bookkeeping fraud" pattern (the
            # correction batch faked compliance by renaming titles on already-
            # written notes instead of producing new ones).
            "SG-005 correction (batch yielded zero notes): write a new note "
            "in data_vault/<folder>/ for EACH assigned topic. Do NOT edit "
            "existing notes to make the count look right. If a topic cannot "
            "legitimately be researched (e.g. you can't find a code source), "
            "report it under skipped_topics with reason=insufficient_evidence "
            "rather than skipping the directive."
        ),
    )
