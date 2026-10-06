"""Spec Status header vocabulary guard (issue #279).

Before ``scripts/normalize_spec_status.py``, ``**Status:**`` (and a sibling
YAML frontmatter ``status:`` tag on 15 "simple spec" files) was free-form
prose in 25+ distinct forms — SHIPPED/Draft/SUBSUMED/TOMBSTONED/Active/
Clarified/... — validated by nothing. This guard is what makes the
normalization stick: every spec's header must now open with one of five
vocabulary tokens (CONTRIBUTING.md § 2):

    planned
    in-progress
    shipped(<YYYY-MM-DD>, <PR #N | commit <sha> | version <X.Y.Z[rcN]>>)
    superseded(by <ref>)
    archived

``KNOWN_AMBIGUOUS`` is a small, named exception list for the handful of
specs whose header makes a compound claim — shipped AND some part of the
same spec's own scope still open — that the normalizer deliberately did not
resolve by guessing (see the #279 PR body for the reasoning on each). It
exists to keep the fast loop green without pretending those headers are
settled; shrinking it requires a human to pick one term, same as this repo's
``tests/_helpers/llm_dispatch_allowlist.yaml`` precedent.
"""

from __future__ import annotations

from pathlib import Path

from scripts.normalize_spec_status import SPECS_DIR, find_status_header, is_canonical

# Each entry names the spec and, in one line, why it isn't in the vocabulary
# yet. New entries require a comment here — this list is meant to shrink,
# not grow silently.
KNOWN_AMBIGUOUS: dict[str, str] = {
    "001-speckit-implementation": '"Active" carries no ship evidence either way.',
    "017-vault-quality-fix": 'ship is "partial", rest deferred to 022/030.',
    "019-pipeline-architecture": 'ship is "partial", rest deferred to 024/025.',
    "022-e2e-quality-harness": 'fidelity correction lists items "remain open" (epic #216).',
    "023-flow-separation": '"Phase 2 remains deferred to post-Revival".',
    "053-source-authority-strategy": '"US3 ledger wire-in + Polish ... remain follow-ups".',
    "057-foreman-retro-matcher": '"SC-001 retro-rollout tasks ... are not done".',
    "060-source-modules-tier2": 'umbrella "otherwise IMPLEMENT-READY".',
    "069-source-relevance-tuning": '"FR4 ... split to a follow-up sub-spec".',
}


def discover_spec_paths() -> list[Path]:
    return sorted(SPECS_DIR.glob("*/spec.md"))


def test_every_spec_status_header_is_canonical() -> None:
    failures: list[str] = []
    for spec_path in discover_spec_paths():
        name = spec_path.parent.name
        if name in KNOWN_AMBIGUOUS:
            continue
        text = spec_path.read_text(encoding="utf-8")
        header = find_status_header(text)
        if header is None:
            failures.append(f"{name}: no Status header found")
            continue
        if not is_canonical(header.value):
            failures.append(f"{name}: {header.value!r} is not in the vocabulary")
    assert failures == [], "non-canonical Status headers:\n" + "\n".join(
        f"  - {f}" for f in failures
    )


def test_known_ambiguous_specs_are_still_non_canonical() -> None:
    """Guards KNOWN_AMBIGUOUS itself from rotting: once a listed spec's
    header is actually fixed, its entry must be deleted, not left stale."""
    stale = []
    for name, _reason in KNOWN_AMBIGUOUS.items():
        spec_path = SPECS_DIR / name / "spec.md"
        if not spec_path.is_file():
            stale.append(f"{name}: spec.md no longer exists")
            continue
        header = find_status_header(spec_path.read_text(encoding="utf-8"))
        if header is not None and is_canonical(header.value):
            stale.append(
                f"{name}: header is canonical now — remove from KNOWN_AMBIGUOUS"
            )
    assert stale == [], "stale KNOWN_AMBIGUOUS entries:\n" + "\n".join(
        f"  - {s}" for s in stale
    )


# --- inline mini-suite (vocabulary grammar, independent of repo content) ---


def test_planned_is_canonical() -> None:
    assert is_canonical("planned")


def test_in_progress_is_canonical() -> None:
    assert is_canonical("in-progress")


def test_archived_is_canonical() -> None:
    assert is_canonical("archived")


def test_shipped_with_pr_is_canonical() -> None:
    assert is_canonical("shipped(2026-06-04, PR #113)")


def test_shipped_with_commit_is_canonical() -> None:
    assert is_canonical("shipped(2026-05-04, commit a3ef8dd)")


def test_shipped_with_version_is_canonical() -> None:
    assert is_canonical("shipped(2026-05-29, version 0.5.0)")


def test_shipped_with_trailing_prose_is_canonical() -> None:
    """The token only has to open the header — free text may follow."""
    assert is_canonical("shipped(2026-06-04, PR #113) — reframed from ...")


def test_superseded_is_canonical() -> None:
    assert is_canonical("superseded(by spec 023)")


def test_bare_shipped_without_args_is_not_canonical() -> None:
    assert not is_canonical("shipped")


def test_shipped_missing_ref_is_not_canonical() -> None:
    assert not is_canonical("shipped(2026-06-04)")


def test_shipped_bad_date_is_not_canonical() -> None:
    assert not is_canonical("shipped(06-04-2026, PR #113)")


def test_free_form_prose_is_not_canonical() -> None:
    assert not is_canonical("Active")
    assert not is_canonical("Draft")
    assert not is_canonical("SHIPPED 0.10.0 (PR #113, 2026-06-04)")


def test_find_status_header_prefers_bold_over_frontmatter() -> None:
    text = (
        "---\n"
        "status: SHIPPED\n"
        "---\n"
        "\n"
        "**Status**: shipped(2026-06-04, PR #113) — SHIPPED\n"
    )
    header = find_status_header(text)
    assert header is not None
    assert header.value == "shipped(2026-06-04, PR #113) — SHIPPED"


def test_find_status_header_falls_back_to_frontmatter() -> None:
    text = "---\nstatus: superseded(by ./vault update)\n---\n\n# Body\n"
    header = find_status_header(text)
    assert header is not None
    assert header.value == "superseded(by ./vault update)"


def test_find_status_header_returns_none_when_absent() -> None:
    assert find_status_header("# Just a title\n\nNo status field here.\n") is None
