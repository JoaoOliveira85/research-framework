#!/usr/bin/env python3
"""Vault health check — the single entry point for structural integrity.

Wraps the individual validators that already exist under ``scripts/`` and adds
network-reachability checks plus a classification-driven broken-wikilink
fixer. Writes a consolidated report to ``_pipeline/health-report.md``.

Sub-checks
----------

1. **Broken wikilinks** — every ``[[Target]]`` in a note's ``related``
   frontmatter or body must resolve to an existing note stem. Unresolved
   targets are classified:

   - ``moved`` — a close Levenshtein match exists in the vault; likely a
     rename / typo. ``--apply`` updates the link to the matching stem.
   - ``stub`` — the target reads like a legitimate title (capital words,
     reasonable length). ``--apply`` creates a ``draft`` stub note in the
     first available ``concept``-like folder so Principle VIII's
     stub-free-exit rule picks it up on the next research cycle.
   - ``orphan`` — neither. ``--apply`` removes the link from ``related``.

2. **Outdated template versions** — delegated to
   ``check_template_compliance.py --check-version``; the report surfaces its
   findings but this script never auto-upgrades frontmatter (that's a
   hand-review decision).

3. **Broken external URLs** — for every ``source_urls[].url`` in every note,
   issue a short-timeout HEAD (then GET fallback) request. On failure:

   - Prefer an in-vault ``raw_data/`` mirror if raw-capture ran;
   - Else query the archive.org Wayback Machine's ``available`` API for the
     closest snapshot;
   - Else mark the URL ``verifier_status: rejected`` in the note (only with
     ``--apply``) and list it in ``_pipeline/broken-links.md``.

Flags
-----

``--offline``    skip URL reachability + archive.org lookup (tests / CI).
``--apply``      actually write fixes (default is dry-run).
``--report``     override path of the Markdown report (default
                 ``{vault}/_pipeline/health-report.md``).

Exit codes
----------
  0 — clean vault (or dry-run that reported only already-planned fixes).
  1 — unresolved issues remain (hard fail for ``generate.sh`` pre-exit gate).
  2 — abort (vault missing, malformed, or network-required flag combo).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path

import yaml

# Wayback Machine "available" API. Returns ``{archived_snapshots: {closest: {url}}}``
# when a snapshot exists, or an empty ``archived_snapshots`` dict when not.
_WAYBACK_AVAILABLE = "https://archive.org/wayback/available?url="
_URL_TIMEOUT_SECONDS = 5.0
_USER_AGENT = "research-framework-health/1.0 (+https://github.com/research-framework)"
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]+)?\]\]")
_LEVENSHTEIN_SIMILAR = 0.82  # tuned to catch typos while rejecting near-misses
_STUB_TITLE_RE = re.compile(r"^[A-Z][A-Za-z0-9 \-'&]{2,80}$")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class WikilinkIssue:
    source_note: Path
    target: str
    classification: str  # "stub" | "moved" | "orphan"
    suggestion: str = ""  # replacement stem when classification=="moved"
    location: str = "body"  # "body" | "related"

    def describe(self, vault: Path) -> str:
        try:
            rel = self.source_note.relative_to(vault)
        except ValueError:
            rel = self.source_note
        tail = f" → '{self.suggestion}'" if self.suggestion else ""
        return f"{self.classification.upper():<6} [{self.location}] {rel}: [[{self.target}]]{tail}"


@dataclass
class UrlIssue:
    source_note: Path
    url: str
    status: str  # "unreachable" | "restored-from-archive" | "restored-from-mirror"
    replacement: str = ""
    http_status: int | None = None

    def describe(self, vault: Path) -> str:
        try:
            rel = self.source_note.relative_to(vault)
        except ValueError:
            rel = self.source_note
        code = f" [{self.http_status}]" if self.http_status else ""
        tail = f" → {self.replacement}" if self.replacement else ""
        return f"{self.status.upper():<24}{code} {rel}: {self.url}{tail}"


@dataclass
class HealthReport:
    wikilinks: list[WikilinkIssue] = field(default_factory=list)
    urls: list[UrlIssue] = field(default_factory=list)
    template_versions: list[tuple[Path, str, str, str]] = field(default_factory=list)
    applied: bool = False
    offline: bool = False

    @property
    def unresolved_count(self) -> int:
        unresolved = sum(1 for u in self.urls if u.status == "unreachable")
        unresolved += sum(
            1
            for w in self.wikilinks
            if w.classification == "orphan"
            and (not self.applied)  # orphans auto-cleared on apply
        )
        unresolved += len(self.template_versions)
        return unresolved


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------


def _parse_frontmatter(path: Path) -> tuple[dict | None, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None, text
    if not isinstance(fm, dict):
        return None, text
    return fm, parts[2]


def _write_note(path: Path, fm: dict, body: str) -> None:
    new_fm = yaml.safe_dump(fm, sort_keys=False).strip()
    path.write_text(f"---\n{new_fm}\n---\n{body}", encoding="utf-8")


def _vault_note_stems(vault: Path) -> set[str]:
    data = vault / "data_vault"
    if not data.exists():
        return set()
    return {p.stem for p in data.rglob("*.md") if not p.name.startswith("_")}


def _pick_concept_folder(vault: Path) -> Path:
    """Folder to drop stub notes into. Prefers ``01 - Concepts/``."""
    data = vault / "data_vault"
    preferred = data / "01 - Concepts"
    if preferred.exists():
        return preferred
    # Fallback: first alphabetic subfolder of data_vault/.
    subs = sorted(p for p in data.iterdir() if p.is_dir())
    if subs:
        return subs[0]
    preferred.mkdir(parents=True, exist_ok=True)
    return preferred


# ---------------------------------------------------------------------------
# Wikilink scan + classification
# ---------------------------------------------------------------------------


def _classify_wikilink(target: str, known: set[str]) -> tuple[str, str]:
    """Return ``(classification, suggestion)``.

    classification is one of ``"moved"``, ``"stub"``, ``"orphan"``.
    suggestion is the matching stem when classification=="moved", else "".
    """
    best_stem, best_ratio = "", 0.0
    for stem in known:
        ratio = SequenceMatcher(None, target.lower(), stem.lower()).ratio()
        if ratio > best_ratio:
            best_stem, best_ratio = stem, ratio
    if best_ratio >= _LEVENSHTEIN_SIMILAR:
        return "moved", best_stem
    if _STUB_TITLE_RE.match(target):
        return "stub", ""
    return "orphan", ""


def scan_wikilinks(vault: Path) -> list[WikilinkIssue]:
    """Scan every note for unresolved wikilinks in ``related`` and body."""
    data = vault / "data_vault"
    if not data.exists():
        return []
    known = _vault_note_stems(vault)
    issues: list[WikilinkIssue] = []

    for note in sorted(data.rglob("*.md")):
        if note.name.startswith("_"):
            continue
        fm, body = _parse_frontmatter(note)
        if fm is None:
            continue

        related = fm.get("related") or []
        if isinstance(related, list):
            for link in related:
                target = str(link).strip("[]").strip()
                if not target or target in known:
                    continue
                klass, suggest = _classify_wikilink(target, known)
                issues.append(
                    WikilinkIssue(
                        source_note=note,
                        target=target,
                        classification=klass,
                        suggestion=suggest,
                        location="related",
                    )
                )

        for match in _WIKILINK_RE.finditer(body):
            target = match.group(1).strip()
            if not target or target in known:
                continue
            klass, suggest = _classify_wikilink(target, known)
            issues.append(
                WikilinkIssue(
                    source_note=note,
                    target=target,
                    classification=klass,
                    suggestion=suggest,
                    location="body",
                )
            )

    return issues


def apply_wikilink_fixes(
    vault: Path, issues: list[WikilinkIssue]
) -> list[WikilinkIssue]:
    """Mutate notes in-place. Returns the (possibly-different) list of
    *remaining* issues after applying.

    - ``moved`` → rewrite ``related`` entries and body ``[[target]]`` tokens
      to the suggested stem.
    - ``stub`` → create a draft note in the concept folder, leave link as-is.
    - ``orphan`` → strip from ``related`` only (body orphans surface on next
      run and are a scout-skill signal rather than an auto-delete).
    """
    stub_folder = None
    # Group by source note to minimise rewrites.
    by_note: dict[Path, list[WikilinkIssue]] = {}
    for issue in issues:
        by_note.setdefault(issue.source_note, []).append(issue)

    stubs_created: set[str] = set()
    remaining: list[WikilinkIssue] = []

    for note, note_issues in by_note.items():
        fm, body = _parse_frontmatter(note)
        if fm is None:
            remaining.extend(note_issues)
            continue

        changed = False
        related = fm.get("related") or []
        if not isinstance(related, list):
            related = []

        new_related: list[str] = list(related)
        new_body = body

        for issue in note_issues:
            if issue.classification == "moved":
                if issue.location == "related":
                    new_related = [
                        (
                            issue.suggestion
                            if str(r).strip("[]").strip() == issue.target
                            else r
                        )
                        for r in new_related
                    ]
                else:
                    new_body = re.sub(
                        rf"\[\[{re.escape(issue.target)}(\|[^\]]+)?\]\]",
                        f"[[{issue.suggestion}\\1]]",
                        new_body,
                    )
                changed = True
            elif issue.classification == "stub":
                if issue.target not in stubs_created:
                    if stub_folder is None:
                        stub_folder = _pick_concept_folder(vault)
                    _create_stub_note(stub_folder, issue.target)
                    stubs_created.add(issue.target)
                # Stub created; link is no longer broken.
            elif issue.classification == "orphan":
                if issue.location == "related":
                    new_related = [
                        r
                        for r in new_related
                        if str(r).strip("[]").strip() != issue.target
                    ]
                    changed = True
                else:
                    remaining.append(issue)

        if changed:
            fm["related"] = new_related
            _write_note(note, fm, new_body)

    return remaining


def _create_stub_note(folder: Path, title: str) -> Path:
    """Create a ``draft`` stub note that Principle VIII's stub-free-exit will
    later flag until a research cycle fills it in.

    The note's body intentionally stays empty so the existing
    ``pipeline/stubs.py`` classifier picks it up and the scout skill treats
    it as an open work item.
    """
    path = folder / f"{title}.md"
    if path.exists():
        return path
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    fm = {
        "title": title,
        "type": "concept",
        "status": "draft",
        "created": today,
        "updated": today,
        "source_urls": [],
        "related": [],
        "verifier_status": "pending",
        "template_version": "1.0.0",
    }
    body = (
        f"\n# {title}\n\n"
        "> This stub was auto-created by `scripts/vault_health.py` because a\n"
        "> wikilink pointed here. Principle VIII's stub-free-exit rule will\n"
        "> block vault termination until the next research cycle fills it in.\n"
    )
    _write_note(path, fm, body)
    return path


# ---------------------------------------------------------------------------
# External URL reachability + archive.org fallback
# ---------------------------------------------------------------------------


def _request_status(url: str) -> int | None:
    """Return HTTP status code or None on transport error.

    Uses HEAD first, falls back to GET (some servers 405 HEAD). Short
    timeout so a slow server can't stall a vault run.
    """
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(
            url, method=method, headers={"User-Agent": _USER_AGENT}
        )
        try:
            with urllib.request.urlopen(req, timeout=_URL_TIMEOUT_SECONDS) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception:
            continue
    return None


def _wayback_snapshot(url: str) -> str | None:
    """Return closest archive.org snapshot URL, or None if no snapshot."""
    api = _WAYBACK_AVAILABLE + urllib.parse.quote(url, safe="")
    req = urllib.request.Request(api, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_URL_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    snap = data.get("archived_snapshots") or {}
    closest = snap.get("closest") or {}
    snap_url = closest.get("url")
    if isinstance(snap_url, str) and snap_url.startswith("http"):
        return snap_url
    return None


def _raw_data_mirror(vault: Path, url: str) -> Path | None:
    """Look for a ``raw_data/`` sidecar file matching ``url``.

    ``raw_data/`` lives inside the vault (``<vault>/raw_data/``). The
    :mod:`scripts.raw_capture` writer emits ``{slug}-{hash}.meta.json``
    pairs, but older hand-written or test fixtures may use plain
    ``meta.json``. We accept both. Pre-0.2.8 vaults had ``raw_data/`` at
    ``<vault>/../raw_data/`` — we fall back to that location for backwards
    compatibility.
    """
    raw_root = vault / "raw_data"
    if not raw_root.exists():
        legacy = vault.parent / "raw_data"
        if not legacy.exists():
            return None
        raw_root = legacy
    for pattern in ("*.meta.json", "meta.json"):
        for meta in raw_root.rglob(pattern):
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("url") == url:
                payload = meta.parent / str(data.get("filename", ""))
                if payload.exists():
                    return payload
    return None


def scan_urls(vault: Path, offline: bool = False) -> list[UrlIssue]:
    """Check every ``source_urls[].url`` in every note. Network calls are
    skipped when ``offline=True`` — useful in tests and no-internet CI.
    """
    data = vault / "data_vault"
    if not data.exists():
        return []
    if offline:
        return []

    issues: list[UrlIssue] = []
    seen: set[tuple[Path, str]] = set()
    for note in sorted(data.rglob("*.md")):
        if note.name.startswith("_"):
            continue
        fm, _body = _parse_frontmatter(note)
        if fm is None:
            continue
        for entry in fm.get("source_urls") or []:
            url = entry.get("url") if isinstance(entry, dict) else str(entry)
            if not url or not isinstance(url, str) or not url.startswith("http"):
                continue
            key = (note, url)
            if key in seen:
                continue
            seen.add(key)

            status = _request_status(url)
            if status is None or status >= 400:
                mirror = _raw_data_mirror(vault, url)
                if mirror is not None:
                    issues.append(
                        UrlIssue(
                            source_note=note,
                            url=url,
                            status="restored-from-mirror",
                            replacement=str(mirror),
                            http_status=status,
                        )
                    )
                    continue
                snapshot = _wayback_snapshot(url)
                if snapshot:
                    issues.append(
                        UrlIssue(
                            source_note=note,
                            url=url,
                            status="restored-from-archive",
                            replacement=snapshot,
                            http_status=status,
                        )
                    )
                    continue
                issues.append(
                    UrlIssue(
                        source_note=note,
                        url=url,
                        status="unreachable",
                        http_status=status,
                    )
                )
    return issues


# ---------------------------------------------------------------------------
# Template-version check (delegates to check_template_compliance.py)
# ---------------------------------------------------------------------------


def scan_template_versions(vault: Path) -> list[tuple[Path, str, str, str]]:
    """Reuse :mod:`check_template_compliance` to find outdated notes."""
    sys.path.insert(0, str(Path(__file__).parent))
    from check_template_compliance import check_versions

    try:
        return check_versions(vault)
    except FileNotFoundError:
        return []


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def render_report(report: HealthReport, vault: Path) -> str:
    lines = [
        "# Vault Health Report",
        "",
        f"- generated: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"- mode: {'APPLY' if report.applied else 'DRY-RUN'}",
        f"- network: {'offline' if report.offline else 'online'}",
        "",
    ]

    lines.append("## Wikilinks")
    if not report.wikilinks:
        lines.append("all wikilinks resolve")
    else:
        by_class: dict[str, list[WikilinkIssue]] = {}
        for w in report.wikilinks:
            by_class.setdefault(w.classification, []).append(w)
        for klass in ("moved", "stub", "orphan"):
            bucket = by_class.get(klass, [])
            if not bucket:
                continue
            lines.append(f"### {klass} ({len(bucket)})")
            for w in bucket:
                lines.append(f"- {w.describe(vault)}")
    lines.append("")

    lines.append("## External URLs")
    if report.offline:
        lines.append("skipped (--offline)")
    elif not report.urls:
        lines.append("all URLs reachable")
    else:
        for u in report.urls:
            lines.append(f"- {u.describe(vault)}")
    lines.append("")

    lines.append("## Template versions")
    if not report.template_versions:
        lines.append("all notes match their template_version")
    else:
        for path, ntype, have, want in report.template_versions:
            try:
                rel = path.relative_to(vault)
            except ValueError:
                rel = path
            have_disp = have or "(missing)"
            lines.append(
                f"- OUTDATED {rel} (type={ntype}, note={have_disp}, template={want})"
            )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(
    vault: Path,
    *,
    apply: bool = False,
    offline: bool = False,
    report_path: Path | None = None,
) -> HealthReport:
    """Execute all sub-checks and (optionally) apply fixes."""
    if not vault.exists() or not vault.is_dir():
        raise FileNotFoundError(f"vault directory not found: {vault}")

    wikilinks = scan_wikilinks(vault)
    if apply and wikilinks:
        wikilinks = [
            w
            for w in wikilinks
            if w not in apply_wikilink_fixes(vault, list(wikilinks))
            or w.classification == "orphan"
        ]
        # Rescan after apply — the authoritative post-state.
        wikilinks = scan_wikilinks(vault)

    urls = scan_urls(vault, offline=offline)
    template_versions = scan_template_versions(vault)

    report = HealthReport(
        wikilinks=wikilinks,
        urls=urls,
        template_versions=template_versions,
        applied=apply,
        offline=offline,
    )

    report_dest = report_path or (vault / "_pipeline" / "health-report.md")
    report_dest.parent.mkdir(parents=True, exist_ok=True)
    report_dest.write_text(render_report(report, vault), encoding="utf-8")

    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else ""
    )
    parser.add_argument("vault", type=Path, help="Path to vault root directory")
    parser.add_argument(
        "--apply", action="store_true", help="Write fixes (default is dry-run)."
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip URL reachability + archive.org lookup.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Override report output path (default: {vault}/_pipeline/health-report.md).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        report = run(
            args.vault,
            apply=args.apply,
            offline=args.offline,
            report_path=args.report,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(render_report(report, args.vault))
    return 1 if report.unresolved_count else 0


if __name__ == "__main__":
    sys.exit(main())
