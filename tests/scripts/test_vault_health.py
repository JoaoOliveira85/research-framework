"""Tests for scripts/vault_health.py — the unified health-check orchestrator."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "vault_health.py"


def _load_module():
    """Load vault_health.py as a regular module (it's an executable script)."""
    spec = importlib.util.spec_from_file_location("vault_health", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["vault_health"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def vh():
    return _load_module()


def _build_minimal_vault(tmp_path: Path) -> Path:
    """Scaffold a tiny vault with _templates and one note."""
    vault = tmp_path / "v"
    (vault / "_templates").mkdir(parents=True)
    (vault / "data_vault" / "01 - Concepts").mkdir(parents=True)
    (vault / "_pipeline").mkdir()
    (vault / "_templates" / "concept.md").write_text(
        '---\ntype: concept\ntemplate_version: "1.0.0"\n---\n\n## Overview\n',
        encoding="utf-8",
    )
    return vault


def _write_note(
    vault: Path,
    filename: str,
    *,
    related: list[str] | None = None,
    body: str = "",
    template_version: str = "1.0.0",
    source_urls: list[dict] | None = None,
) -> Path:
    path = vault / "data_vault" / "01 - Concepts" / filename
    fm = [
        "---",
        f'title: "{path.stem}"',
        "type: concept",
        f'template_version: "{template_version}"',
    ]
    if related is not None:
        fm.append("related:")
        for r in related:
            fm.append(f"  - {r}")
    if source_urls is not None:
        fm.append("source_urls:")
        for s in source_urls:
            url = s.get("url") if isinstance(s, dict) else s
            fm.append(f"  - url: {url}")
    fm.append("---")
    path.write_text("\n".join(fm) + "\n\n" + body + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Spec 058 — control-file git-tracking helpers
# ---------------------------------------------------------------------------

_ALL_CONTROL = (
    "research.spec.md",
    "settings.yaml",
    "_pipeline/research-backlog.md",
    "_pipeline/coverage-targets.json",
)


def _git_init_vault(tmp_path: Path, files: tuple[str, ...] = _ALL_CONTROL) -> Path:
    """Minimal vault scaffold + the given control files + ``git init`` (no add).

    Defaults to creating all four control files (spec 058 T002). Staging
    into the index (``git add``) is enough for tracked/untracked detection —
    no commit is required, keeping the tests fast and hermetic.
    """
    vault = _build_minimal_vault(tmp_path)
    for rel in files:
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("placeholder\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(vault)], check=True)
    subprocess.run(
        ["git", "-C", str(vault), "config", "user.email", "t@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(vault), "config", "user.name", "T"], check=True)
    subprocess.run(
        ["git", "-C", str(vault), "config", "commit.gpgsign", "false"], check=True
    )
    return vault


def _git_add(vault: Path, *rel_paths: str) -> None:
    subprocess.run(["git", "-C", str(vault), "add", "--", *rel_paths], check=True)


# ---------------------------------------------------------------------------
# Wikilink scan + classification
# ---------------------------------------------------------------------------


class TestWikilinkClassification:
    def test_moved_classification_prefers_close_match(self, tmp_path: Path, vh) -> None:
        vault = _build_minimal_vault(tmp_path)
        _write_note(vault, "Universal Scalability Law.md", body="## Overview\n")
        _write_note(vault, "Amdahls Law.md", related=["Universal Scalablity Law"])
        issues = vh.scan_wikilinks(vault)
        assert len(issues) == 1
        assert issues[0].classification == "moved"
        assert issues[0].suggestion == "Universal Scalability Law"

    def test_stub_classification_for_capitalised_title(
        self, tmp_path: Path, vh
    ) -> None:
        vault = _build_minimal_vault(tmp_path)
        _write_note(vault, "A.md", related=["Context Engineering for Agents"])
        issues = vh.scan_wikilinks(vault)
        assert len(issues) == 1
        assert issues[0].classification == "stub"
        assert issues[0].suggestion == ""

    def test_orphan_classification_for_garbage(self, tmp_path: Path, vh) -> None:
        vault = _build_minimal_vault(tmp_path)
        _write_note(vault, "A.md", related=["asdf"])
        issues = vh.scan_wikilinks(vault)
        assert len(issues) == 1
        assert issues[0].classification == "orphan"

    def test_resolved_wikilinks_emit_no_issues(self, tmp_path: Path, vh) -> None:
        vault = _build_minimal_vault(tmp_path)
        _write_note(vault, "A.md", body="## Overview\n")
        _write_note(vault, "B.md", related=["A"])
        assert vh.scan_wikilinks(vault) == []

    def test_body_wikilinks_are_also_scanned(self, tmp_path: Path, vh) -> None:
        vault = _build_minimal_vault(tmp_path)
        _write_note(vault, "A.md", body="See [[Missing Concept]].")
        issues = vh.scan_wikilinks(vault)
        assert len(issues) == 1
        assert issues[0].location == "body"


# ---------------------------------------------------------------------------
# Apply fixes
# ---------------------------------------------------------------------------


class TestApplyFixes:
    def test_moved_rewrites_related_entry(self, tmp_path: Path, vh) -> None:
        vault = _build_minimal_vault(tmp_path)
        _write_note(vault, "Universal Scalability Law.md", body="## Overview\n")
        src = _write_note(vault, "Amdahls Law.md", related=["Universal Scalablity Law"])
        issues = vh.scan_wikilinks(vault)
        vh.apply_wikilink_fixes(vault, issues)
        text = src.read_text(encoding="utf-8")
        assert "Universal Scalability Law" in text
        assert "Universal Scalablity Law" not in text

    def test_stub_creation_produces_draft_note(self, tmp_path: Path, vh) -> None:
        vault = _build_minimal_vault(tmp_path)
        _write_note(vault, "A.md", related=["Context Engineering for Agents"])
        issues = vh.scan_wikilinks(vault)
        vh.apply_wikilink_fixes(vault, issues)

        stub = (
            vault / "data_vault" / "01 - Concepts" / "Context Engineering for Agents.md"
        )
        assert stub.exists()
        text = stub.read_text(encoding="utf-8")
        assert "status: draft" in text
        # Verifier status seeds Principle VIII stub-free-exit.
        assert "verifier_status: pending" in text

    def test_orphan_removed_from_related(self, tmp_path: Path, vh) -> None:
        vault = _build_minimal_vault(tmp_path)
        src = _write_note(vault, "A.md", related=["asdf", "qwerty"])
        issues = vh.scan_wikilinks(vault)
        vh.apply_wikilink_fixes(vault, issues)
        text = src.read_text(encoding="utf-8")
        assert "asdf" not in text
        assert "qwerty" not in text

    def test_apply_keeps_a_frontmatter_value_containing_dashes(
        self, tmp_path: Path, vh
    ) -> None:
        """A `---` inside a value is not the closing delimiter.

        The parser split on the first `---` substring, so a slug URL ended the
        frontmatter there and `--apply` wrote the cut note back: the URL in two
        pieces, every key below it moved into the body.
        """
        vault = _build_minimal_vault(tmp_path)
        note = vault / "data_vault" / "01 - Concepts" / "A.md"
        note.write_text(
            "---\n"
            "title: A\n"
            "type: concept\n"
            "related:\n"
            "- asdf\n"
            "source_urls:\n"
            "- url: https://example.com/kafka---a-guide\n"
            "verifier_status: verified\n"
            "---\n"
            "\n"
            "## Overview\n",
            encoding="utf-8",
        )

        vh.apply_wikilink_fixes(vault, vh.scan_wikilinks(vault))

        assert note.read_text(encoding="utf-8") == (
            "---\n"
            "title: A\n"
            "type: concept\n"
            "related: []\n"
            "source_urls:\n"
            "- url: https://example.com/kafka---a-guide\n"
            "verifier_status: verified\n"
            "---\n"
            "\n"
            "## Overview\n"
        )

    def test_apply_writes_non_ascii_values_as_they_were(
        self, tmp_path: Path, vh
    ) -> None:
        """A rewrite keeps accented text readable.

        The frontmatter was dumped without ``allow_unicode``, so `--apply`
        turned `title: Café` into `title: "Caf\\xE9"` in every note it touched.
        """
        vault = _build_minimal_vault(tmp_path)
        note = vault / "data_vault" / "01 - Concepts" / "A.md"
        note.write_text(
            "---\n"
            "title: Café\n"
            "summary: Naïve caching in São Paulo — a guide\n"
            "related:\n"
            "- asdf\n"
            "---\n"
            "\n"
            "## Overview\n",
            encoding="utf-8",
        )

        vh.apply_wikilink_fixes(vault, vh.scan_wikilinks(vault))

        assert note.read_text(encoding="utf-8") == (
            "---\n"
            "title: Café\n"
            "summary: Naïve caching in São Paulo — a guide\n"
            "related: []\n"
            "---\n"
            "\n"
            "## Overview\n"
        )

    def test_apply_does_not_grow_the_gap_below_the_frontmatter(
        self, tmp_path: Path, vh
    ) -> None:
        """A rewrite leaves the body as it was.

        The body was taken from just after the closing `---`, its newline
        included, and written back after a second one: every rewrite pushed
        the body one blank line further down.
        """
        vault = _build_minimal_vault(tmp_path)
        note = _write_note(vault, "A.md", related=["asdf"], body="## Overview")
        _frontmatter, _, body = note.read_text(encoding="utf-8").partition("\n---\n")

        vh.apply_wikilink_fixes(vault, vh.scan_wikilinks(vault))

        assert note.read_text(encoding="utf-8").partition("\n---\n")[2] == body


# ---------------------------------------------------------------------------
# URL reachability (offline mode only — network tests would be flaky)
# ---------------------------------------------------------------------------


class TestUrlScan:
    def test_offline_skips_all_urls(self, tmp_path: Path, vh) -> None:
        vault = _build_minimal_vault(tmp_path)
        _write_note(
            vault,
            "A.md",
            source_urls=[{"url": "http://does-not-exist.invalid/x"}],
        )
        assert vh.scan_urls(vault, offline=True) == []

    def test_raw_data_mirror_lookup_inside_vault(self, tmp_path: Path, vh) -> None:
        """When a raw_data/ mirror exists INSIDE the vault, the scanner uses
        it instead of going to the network. This is the current convention
        (kept inside the vault so sandboxed agents can write captures)."""
        vault = _build_minimal_vault(tmp_path)
        raw = vault / "raw_data" / "2026" / "04"
        raw.mkdir(parents=True)
        (raw / "meta.json").write_text(
            '{"url": "http://example.invalid/x", "filename": "payload.html"}',
            encoding="utf-8",
        )
        (raw / "payload.html").write_text("<html/>", encoding="utf-8")

        mirror = vh._raw_data_mirror(vault, "http://example.invalid/x")
        assert mirror is not None
        assert mirror.name == "payload.html"

    def test_raw_data_mirror_lookup_legacy_sibling(self, tmp_path: Path, vh) -> None:
        """Backwards-compat: pre-0.2.8 vaults kept raw_data/ as a sibling of
        the vault (``<vault>/../raw_data/``). The scanner still resolves
        mirrors there when the in-vault location is absent."""
        vault = _build_minimal_vault(tmp_path)
        raw = tmp_path / "raw_data" / "2026" / "04"
        raw.mkdir(parents=True)
        (raw / "meta.json").write_text(
            '{"url": "http://example.invalid/legacy", "filename": "payload.html"}',
            encoding="utf-8",
        )
        (raw / "payload.html").write_text("<html/>", encoding="utf-8")

        mirror = vh._raw_data_mirror(vault, "http://example.invalid/legacy")
        assert mirror is not None
        assert mirror.name == "payload.html"


# ---------------------------------------------------------------------------
# run() integration
# ---------------------------------------------------------------------------


class TestRun:
    def test_run_offline_produces_report_file(self, tmp_path: Path, vh) -> None:
        vault = _build_minimal_vault(tmp_path)
        _write_note(vault, "A.md", body="## Overview\n")

        report = vh.run(vault, apply=False, offline=True)
        assert report.unresolved_count == 0

        report_file = vault / "_pipeline" / "health-report.md"
        assert report_file.exists()
        assert "Vault Health Report" in report_file.read_text(encoding="utf-8")

    def test_run_classifies_all_three_link_types(self, tmp_path: Path, vh) -> None:
        vault = _build_minimal_vault(tmp_path)
        _write_note(vault, "Known.md", body="## Overview\n")
        _write_note(
            vault,
            "A.md",
            related=["Known ", "Context Engineering for Agents", "asdf"],
        )
        report = vh.run(vault, apply=False, offline=True)
        classes = {w.classification for w in report.wikilinks}
        # "Known " (with trailing space) resolves via strip to Known; so two issues only.
        assert {"stub", "orphan"}.issubset(classes)

    def test_run_apply_removes_orphans_and_creates_stubs(
        self, tmp_path: Path, vh
    ) -> None:
        vault = _build_minimal_vault(tmp_path)
        _write_note(vault, "A.md", related=["asdf"])
        _write_note(vault, "B.md", related=["Context Engineering for Agents"])

        report = vh.run(vault, apply=True, offline=True)
        # Orphan 'asdf' is now stripped; stub 'Context Engineering…' created
        # as a new note. Remaining unresolved wikilinks should be zero.
        assert report.unresolved_count == 0

    def test_apply_still_fails_on_the_orphans_it_cannot_remove(
        self, tmp_path: Path, vh, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`--apply` strips an orphan from `related`, never from a body.

        Every orphan was left out of the unresolved count once `--apply` was
        given, "auto-cleared on apply". The body orphans are still there in
        the post-apply rescan, and the report lists them — under exit 0.
        """
        vault = _build_minimal_vault(tmp_path)
        _write_note(vault, "A.md", body="## Overview\n\nSee [[asdf]].\n")

        report = vh.run(vault, apply=True, offline=True)

        assert [(w.target, w.classification) for w in report.wikilinks] == [
            ("asdf", "orphan")
        ]
        assert report.unresolved_count == 1
        assert vh.main([str(vault), "--apply", "--offline"]) == 1
        assert "### orphan (1)" in capsys.readouterr().out

    def test_run_reports_template_version_drift(self, tmp_path: Path, vh) -> None:
        vault = _build_minimal_vault(tmp_path)
        (vault / "_templates" / "concept.md").write_text(
            '---\ntype: concept\ntemplate_version: "2.0.0"\n---\n\n## Overview\n',
            encoding="utf-8",
        )
        _write_note(vault, "A.md", body="## Overview\n", template_version="1.0.0")
        report = vh.run(vault, apply=False, offline=True)
        assert len(report.template_versions) == 1
        assert report.unresolved_count >= 1

    def test_run_missing_vault_raises(self, tmp_path: Path, vh) -> None:
        with pytest.raises(FileNotFoundError):
            vh.run(tmp_path / "nope", apply=False, offline=True)


# ---------------------------------------------------------------------------
# Spec 058 — control-file git tracking
# ---------------------------------------------------------------------------


class TestControlFileGitTracking:
    # --- US1: warn when a control file isn't in git (T003) ---

    def test_untracked_research_spec_warns(self, tmp_path: Path, vh) -> None:
        vault = _git_init_vault(tmp_path)
        # Track everything except research.spec.md.
        _git_add(
            vault,
            "settings.yaml",
            "_pipeline/research-backlog.md",
            "_pipeline/coverage-targets.json",
        )
        warnings = vh.scan_control_file_git_tracking(vault)
        assert len(warnings) == 1
        assert warnings[0].rel_path == "research.spec.md"
        assert warnings[0].reason == "untracked"

    def test_ignored_settings_warns(self, tmp_path: Path, vh) -> None:
        vault = _git_init_vault(tmp_path)
        (vault / ".gitignore").write_text("settings.yaml\n", encoding="utf-8")
        # Track the other three so settings.yaml is the only warning.
        _git_add(
            vault,
            "research.spec.md",
            "_pipeline/research-backlog.md",
            "_pipeline/coverage-targets.json",
        )
        warnings = vh.scan_control_file_git_tracking(vault)
        assert len(warnings) == 1
        assert warnings[0].rel_path == "settings.yaml"
        assert warnings[0].reason == "ignored"

    def test_all_tracked_no_warnings(self, tmp_path: Path, vh) -> None:
        vault = _git_init_vault(tmp_path)
        _git_add(vault, *_ALL_CONTROL)
        assert vh.scan_control_file_git_tracking(vault) == []

    def test_absent_file_skipped(self, tmp_path: Path, vh) -> None:
        # Only research.spec.md exists; the other three are never created.
        vault = _git_init_vault(tmp_path, files=("research.spec.md",))
        _git_add(vault, "research.spec.md")
        assert vh.scan_control_file_git_tracking(vault) == []

    # --- US2: stay silent on non-git vaults (T007) ---

    def test_non_git_vault_silent(self, tmp_path: Path, vh) -> None:
        vault = _build_minimal_vault(tmp_path)
        for rel in _ALL_CONTROL:
            p = vault / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x\n", encoding="utf-8")
        assert vh.scan_control_file_git_tracking(vault) == []

    # --- US3: advisory, never blocking (T009) ---

    def test_run_exit_zero_despite_tracking_warnings(self, tmp_path: Path, vh) -> None:
        vault = _git_init_vault(tmp_path)  # all four present, none added → untracked
        report = vh.run(vault, apply=False, offline=True)
        assert len(report.control_file_tracking) >= 1
        assert report.unresolved_count == 0
        assert vh.main([str(vault), "--offline"]) == 0

    def test_multiple_warnings_list_each_file(self, tmp_path: Path, vh) -> None:
        vault = _git_init_vault(tmp_path)
        (vault / ".gitignore").write_text("settings.yaml\n", encoding="utf-8")
        # Track backlog + coverage; settings ignored; research.spec untracked.
        _git_add(
            vault,
            "_pipeline/research-backlog.md",
            "_pipeline/coverage-targets.json",
        )
        warnings = vh.scan_control_file_git_tracking(vault)
        assert len(warnings) == 2
        by_path = {w.rel_path: w.reason for w in warnings}
        assert by_path["research.spec.md"] == "untracked"
        assert by_path["settings.yaml"] == "ignored"
        # Sorted by rel_path (deterministic output, FR-007).
        assert [w.rel_path for w in warnings] == [
            "research.spec.md",
            "settings.yaml",
        ]

    # --- determinism (T011) ---

    def test_deterministic_repeat_run(self, tmp_path: Path, vh) -> None:
        vault = _git_init_vault(tmp_path)
        _git_add(vault, "settings.yaml")
        first = vh.scan_control_file_git_tracking(vault)
        second = vh.scan_control_file_git_tracking(vault)
        assert first == second

    # --- render section (T005 / T008) ---

    def test_render_all_clear_when_tracked(self, tmp_path: Path, vh) -> None:
        vault = _git_init_vault(tmp_path)
        _git_add(vault, *_ALL_CONTROL)
        vh.run(vault, apply=False, offline=True)
        report_text = (vault / "_pipeline" / "health-report.md").read_text(
            encoding="utf-8"
        )
        assert "## Control-file git tracking" in report_text
        assert "all four present control files are tracked in git" in report_text

    def test_render_skipped_on_non_git(self, tmp_path: Path, vh) -> None:
        vault = _build_minimal_vault(tmp_path)
        vh.run(vault, apply=False, offline=True)
        report_text = (vault / "_pipeline" / "health-report.md").read_text(
            encoding="utf-8"
        )
        assert "## Control-file git tracking" in report_text
        assert "skipped (not a git work tree)" in report_text

    def test_render_lists_warning_bullets(self, tmp_path: Path, vh) -> None:
        vault = _git_init_vault(tmp_path)
        (vault / ".gitignore").write_text("settings.yaml\n", encoding="utf-8")
        _git_add(
            vault,
            "_pipeline/research-backlog.md",
            "_pipeline/coverage-targets.json",
        )
        vh.run(vault, apply=False, offline=True)
        report_text = (vault / "_pipeline" / "health-report.md").read_text(
            encoding="utf-8"
        )
        assert "- WARN UNTRACKED research.spec.md" in report_text
        assert "- WARN IGNORED settings.yaml" in report_text
