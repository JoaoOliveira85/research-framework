"""Tests for research_framework.processors.extract.

LLM calls are mocked via monkeypatching ``extract._call_claude``. Real LLM
calls only happen in tests marked ``@pytest.mark.live_llm``, which are
skipped by default by ``tests/conftest.py::pytest_collection_modifyitems``
— opt in with ``pytest --live-llm`` or ``LIVE_LLM=1`` (renamed from
``integration`` in ADR-0008 so Tier 3 can use "Integration" as its label).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

# The __init__.py re-exports `extract` as a function, so
# `import research_framework.processors.extract` would resolve to that function.
# Use importlib to get the actual module object for monkeypatching.
_extract_mod = importlib.import_module("research_framework.processors.extract")

from research_framework.processors._common import parse_frontmatter  # noqa: E402
from research_framework.processors.extract import (  # noqa: E402  (must follow importlib above)
    ExtractResult,
    SandboxDetectedError,
    _build_haiku_prompt,
    _default_call_claude,
    _find_extraction_targets,
    _SandboxClassifier,
    _score_quality,
    _stderr_matches_sandbox_signature,
    _synthesize_context_tree,
    _validate_haiku_output,
    extract,
    load_topic_index,
)

# ---------------------------------------------------------------------------
# LLM mock factory
# ---------------------------------------------------------------------------

DETERMINISTIC_EXTRACTION = """\
## Direct Data
- Model size: 70B parameters (source: abstract)

## Entities
- Tools: ExampleTool
- People: Jane Doe (researcher at ExampleLab)
- Companies: ExampleCorp
- Papers/Sources: none

## Concepts
- Scaling laws: how increasing model size improves capability

## Connections to Vault
[[AI Tools]]: ExampleTool is an AI assistant mentioned in the content

## Signals
- Consensus: larger models perform better on benchmarks
- Controversy: none
- Questions: Will scaling continue to work?

## Cross-Reference Candidates
- type: tool
  value: "ExampleTool"
  context: "Mentioned as the primary tool evaluated"
  already_tracked: false
"""

DETERMINISTIC_CONTEXT_TREE = """\
# Context Tree — 2026-05-13

Batch: 1 sources (1 web)

## Topics

### AI Scaling
**Description:** Research on how model size affects performance
**Sources:** test-article.md (1)
**Vault status:** partially covered
**Key data:** 70B parameters
**Connections:** AI Tools
"""

MOCK_USAGE: dict[str, Any] = {
    "input_tokens": 100,
    "output_tokens": 200,
    "cache_read": 0,
    "cache_creation": 0,
    "cost_usd": 0.001,
}


def make_mock_claude(
    haiku_response: str = DETERMINISTIC_EXTRACTION,
    sonnet_response: str = DETERMINISTIC_CONTEXT_TREE,
):
    """Return a mock that returns different responses based on the model arg."""

    def _mock(
        model: str, system_prompt: str, user_prompt: str, **kwargs
    ) -> tuple[str, dict]:
        if "haiku" in model.lower() or model == "haiku":
            return haiku_response, MOCK_USAGE
        return sonnet_response, MOCK_USAGE

    return _mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_raw_item(
    vault: Path,
    source_kind: str,
    stem: str,
    body: str = "AI research content about model scaling.",
    collected_at: str = "2026-05-01",
    original_url: str = "https://example.com/paper",
) -> Path:
    raw_dir = vault / "_pipeline" / "raw" / source_kind
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{stem}.md"
    path.write_text(
        f"""---
source_kind: {source_kind}
source_id: {stem}
collected_at: {collected_at}
original_url: {original_url}
title: Test Article {stem}
---

{body}
""",
        encoding="utf-8",
    )
    return path


def make_excerpt(
    vault: Path,
    source_kind: str,
    stem: str,
    body: str = "URL: https://example.com/paper\nTitle: Test Article\n---\n\nAI research content.",
) -> Path:
    exc_dir = vault / "_pipeline" / "extracted" / "excerpts" / source_kind
    exc_dir.mkdir(parents=True, exist_ok=True)
    path = exc_dir / f"{stem}.txt"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# FR-007 — dispatch migration seam tests
# ---------------------------------------------------------------------------


def test_call_claude_maps_dispatch_result_to_usage(tmp_path, monkeypatch):
    """Dispatch AgentCallResult fields map into body + usage dict."""
    from types import SimpleNamespace

    monkeypatch.setattr(_extract_mod, "_active_vault_dir", tmp_path)
    (tmp_path / "settings.yaml").write_text(
        "default_executor:\n  runtime: claude\n  model: haiku\n",
        encoding="utf-8",
    )

    fake_result = SimpleNamespace(
        stdout="extracted body",
        stderr="",
        exit_code=0,
        tokens_in=42,
        tokens_out=84,
        cost_usd=0.0123,
        latency_ms=100,
    )

    captured: dict[str, Any] = {}

    def fake_dispatch(**kwargs):
        captured.update(kwargs)
        return fake_result

    fake_module = SimpleNamespace(
        dispatch=fake_dispatch,
        _load_settings=lambda vault_dir: {"stages": {}},
    )

    monkeypatch.setattr(
        "research_framework.pipeline.plan_narrator._bootstrap_scripts_agent_call",
        lambda vault_dir=None: fake_module,
    )

    body, usage = _default_call_claude("custom-haiku", "system", "user")
    assert body == "extracted body"
    assert usage["input_tokens"] == 42
    assert usage["output_tokens"] == 84
    assert usage["cost_usd"] == 0.0123
    assert captured["model"] == "custom-haiku"
    assert captured["stage"] == "processor_extract"


def test_extract_never_subprocess_claude(tmp_path, monkeypatch):
    """extract() must not shell out to claude directly — uses dispatch seam."""
    import subprocess

    make_raw_item(tmp_path, "web", "test-article")
    make_excerpt(tmp_path, "web", "test-article")
    monkeypatch.setattr(_extract_mod, "_call_claude", make_mock_claude())

    claude_calls: list[list[str]] = []
    original_run = subprocess.run

    def tracking_run(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args")
        if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "claude":
            claude_calls.append(list(cmd))
        return original_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", tracking_run)
    extract(tmp_path, no_synthesis=True)
    assert claude_calls == []


def test_existing_extract_suite_uses_call_claude_seam(tmp_path, monkeypatch):
    """Regression: mocked _call_claude seam is exercised during extract()."""
    make_raw_item(tmp_path, "web", "test-article")
    make_excerpt(tmp_path, "web", "test-article")
    hits = {"count": 0}

    def counting_mock(model, system, prompt, **kwargs):
        hits["count"] += 1
        return DETERMINISTIC_EXTRACTION, MOCK_USAGE

    monkeypatch.setattr(_extract_mod, "_call_claude", counting_mock)
    extract(tmp_path, no_synthesis=True)
    assert hits["count"] >= 1


def _write_minimal_settings(vault: Path) -> None:
    (vault / "settings.yaml").write_text(
        "default_executor:\n  runtime: claude\n  model: haiku\n",
        encoding="utf-8",
    )


def _patch_dispatch_results(monkeypatch, results: list[Any]) -> None:
    from types import SimpleNamespace

    queue = list(results)

    def fake_dispatch(**kwargs):
        if not queue:
            raise AssertionError("dispatch called more times than queued results")
        return queue.pop(0)

    fake_module = SimpleNamespace(
        dispatch=fake_dispatch,
        _load_settings=lambda vault_dir: {"stages": {}},
    )
    monkeypatch.setattr(
        "research_framework.pipeline.plan_narrator._bootstrap_scripts_agent_call",
        lambda vault_dir=None: fake_module,
    )


def _extracted_stub_paths(vault: Path) -> list[Path]:
    root = vault / "_pipeline" / "extracted"
    if not root.exists():
        return []
    return [p for p in root.rglob("*.md") if "excerpts" not in p.parts]


class TestSandboxDetection:
    def test_sandbox_stderr_signature_hard_exits_zero_stubs(
        self, tmp_path, monkeypatch
    ):
        make_raw_item(tmp_path, "web", "test-article")
        make_excerpt(tmp_path, "web", "test-article")
        _write_minimal_settings(tmp_path)
        from types import SimpleNamespace

        _patch_dispatch_results(
            monkeypatch,
            [
                SimpleNamespace(
                    stdout="",
                    stderr="please run /login",
                    exit_code=1,
                    tokens_in=0,
                    tokens_out=0,
                    cost_usd=0.0,
                    latency_ms=50,
                )
            ],
        )
        with pytest.raises(SandboxDetectedError):
            extract(tmp_path, no_synthesis=True)
        assert _extracted_stub_paths(tmp_path) == []

    def test_sandbox_time_fallback_three_fast_failures(self, tmp_path, monkeypatch):
        for stem in ("a", "b", "c"):
            make_raw_item(tmp_path, "web", stem)
            make_excerpt(tmp_path, "web", stem)
        _write_minimal_settings(tmp_path)
        from types import SimpleNamespace

        fast_fail = SimpleNamespace(
            stdout="",
            stderr="upstream unavailable",
            exit_code=1,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            latency_ms=50,
        )
        _patch_dispatch_results(monkeypatch, [fast_fail, fast_fail, fast_fail])
        with pytest.raises(SandboxDetectedError) as exc_info:
            extract(tmp_path, no_synthesis=True)
        assert "consecutive fast failures" in str(exc_info.value).lower()
        assert _extracted_stub_paths(tmp_path) == []

    def test_sandbox_detection_suppressed_by_rv_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RV_DISABLE_SANDBOX_DETECT", "1")
        make_raw_item(tmp_path, "web", "test-article")
        make_excerpt(tmp_path, "web", "test-article")
        _write_minimal_settings(tmp_path)
        from types import SimpleNamespace

        _patch_dispatch_results(
            monkeypatch,
            [
                SimpleNamespace(
                    stdout="",
                    stderr="please run /login",
                    exit_code=1,
                    tokens_in=0,
                    tokens_out=0,
                    cost_usd=0.0,
                    latency_ms=50,
                )
            ]
            * 3,
        )
        result = extract(tmp_path, no_synthesis=True)
        assert isinstance(result, ExtractResult)
        assert len(_extracted_stub_paths(tmp_path)) >= 1

    def test_non_sandbox_successful_dispatch_unchanged(self, tmp_path, monkeypatch):
        make_raw_item(tmp_path, "web", "test-article")
        make_excerpt(tmp_path, "web", "test-article")
        monkeypatch.setattr(_extract_mod, "_call_claude", make_mock_claude())
        result = extract(tmp_path, no_synthesis=True)
        assert result.files_processed == 1
        assert len(_extracted_stub_paths(tmp_path)) == 1

    def test_fast_dispatch_failure_increments_files_skipped(
        self, tmp_path, monkeypatch
    ):
        """A single fast-failure dispatch counts as skipped before sandbox trips."""
        for stem in ("fast-fail", "ok"):
            make_raw_item(tmp_path, "web", stem)
            make_excerpt(tmp_path, "web", stem)
        _write_minimal_settings(tmp_path)
        from types import SimpleNamespace

        fast_fail = SimpleNamespace(
            stdout="",
            stderr="upstream unavailable",
            exit_code=1,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            latency_ms=50,
        )
        success = SimpleNamespace(
            stdout=DETERMINISTIC_EXTRACTION,
            stderr="",
            exit_code=0,
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.01,
            latency_ms=5000,
        )
        _patch_dispatch_results(monkeypatch, [fast_fail, success])

        result = extract(tmp_path, no_synthesis=True)
        assert result.files_processed == 1
        assert result.files_skipped == 1


def test_sandbox_classifier_matches_stderr_patterns():
    from types import SimpleNamespace

    classifier = _SandboxClassifier()
    hit = classifier.evaluate(
        SimpleNamespace(
            exit_code=1,
            stderr="Invalid API key — please run /login",
            stdout="",
            latency_ms=5000,
        )
    )
    assert hit is not None
    assert _stderr_matches_sandbox_signature("benign timeout") is False
    assert (
        classifier.evaluate(
            SimpleNamespace(
                exit_code=1,
                stderr="benign timeout",
                stdout="",
                latency_ms=5000,
            )
        )
        is None
    )


def test_sandbox_classifier_time_fallback_counter():
    from types import SimpleNamespace

    classifier = _SandboxClassifier()
    fail = SimpleNamespace(exit_code=1, stderr="generic", stdout="", latency_ms=50)
    assert classifier.evaluate(fail) is None
    assert classifier.evaluate(fail) is None
    reason = classifier.evaluate(fail)
    assert reason is not None
    assert "consecutive fast failures" in reason


def test_sandbox_classifier_honors_rv_disable_env(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("RV_DISABLE_SANDBOX_DETECT", "1")
    classifier = _SandboxClassifier()
    assert (
        classifier.evaluate(
            SimpleNamespace(
                exit_code=1,
                stderr="please run /login",
                stdout="",
                latency_ms=50,
            )
        )
        is None
    )


def test_extract_aborts_before_writing_stubs_on_sandbox(tmp_path, monkeypatch):
    make_raw_item(tmp_path, "web", "one")
    make_excerpt(tmp_path, "web", "one")
    _write_minimal_settings(tmp_path)
    from types import SimpleNamespace

    _patch_dispatch_results(
        monkeypatch,
        [
            SimpleNamespace(
                stdout="",
                stderr="not logged in",
                exit_code=1,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                latency_ms=20,
            )
        ],
    )
    with pytest.raises(SandboxDetectedError):
        extract(tmp_path, no_synthesis=True)
    assert _extracted_stub_paths(tmp_path) == []


def test_sandbox_error_message_includes_remediation_and_doc_link(tmp_path, monkeypatch):
    make_raw_item(tmp_path, "web", "test-article")
    make_excerpt(tmp_path, "web", "test-article")
    _write_minimal_settings(tmp_path)
    from types import SimpleNamespace

    _patch_dispatch_results(
        monkeypatch,
        [
            SimpleNamespace(
                stdout="",
                stderr="please run /login",
                exit_code=1,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                latency_ms=10,
            )
        ],
    )
    with pytest.raises(SandboxDetectedError) as exc_info:
        extract(tmp_path, no_synthesis=True)
    msg = str(exc_info.value).lower()
    assert "auth-failure" in msg or "sandbox" in msg
    assert "dangerouslydisablesandbox" in msg
    assert "specs/032-pipeline-reliability/quickstart.md" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Unit tests — helpers
# ---------------------------------------------------------------------------


class TestBuildHaikuPrompt:
    def test_contains_required_sections(self):
        prompt = _build_haiku_prompt(
            source_url="https://example.com",
            source_type="web",
            title="Test",
            excerpt="Some content.",
            topic_index="## Topic Index\n- AI Tools",
        )
        for section in ("## Direct Data", "## Entities", "## Concepts", "## Signals"):
            assert section in prompt

    def test_includes_source_url(self):
        prompt = _build_haiku_prompt(
            source_url="https://my-source.com",
            source_type="web",
            title="Test",
            excerpt="Content.",
            topic_index="",
        )
        assert "https://my-source.com" in prompt


class TestValidateHaikuOutput:
    def test_valid_output(self):
        ok, why = _validate_haiku_output(DETERMINISTIC_EXTRACTION)
        assert ok
        assert why == ""

    def test_missing_section(self):
        partial = "\n".join(
            line
            for line in DETERMINISTIC_EXTRACTION.splitlines()
            if "## Signals" not in line
            and "Consensus" not in line
            and "Controversy" not in line
            and "Questions" not in line
        )
        ok, why = _validate_haiku_output(partial)
        assert not ok
        assert "## Signals" in why


class TestScoreQuality:
    def test_good_signal(self):
        assert _score_quality(DETERMINISTIC_EXTRACTION) == "ok"

    def test_low_signal(self):
        low_body = """\
## Direct Data
- none

## Entities
- Tools: none
- People: none
- Companies: none
- Papers/Sources: none

## Concepts
- nothing

## Connections to Vault

## Signals
- Consensus: none
- Controversy: none
- Questions: none

## Cross-Reference Candidates
"""
        assert _score_quality(low_body) == "low-signal"


class TestLoadTopicIndex:
    def test_returns_empty_when_no_agents_md(self, tmp_path):
        result = load_topic_index(tmp_path)
        assert result == ""

    def test_extracts_topic_index_section(self, tmp_path):
        agents = tmp_path / "AGENTS.md"
        agents.write_text(
            "# AGENTS\n\n## Topic Index\n- AI Tools\n- Scaling\n\n## Other Section\n- stuff\n",
            encoding="utf-8",
        )
        result = load_topic_index(tmp_path)
        assert "AI Tools" in result
        assert "## Topic Index" in result


# ---------------------------------------------------------------------------
# Integration-style: extract() end-to-end with mocked LLM
# ---------------------------------------------------------------------------


class TestExtractFunction:
    def test_extract_processes_excerpt(self, tmp_path, monkeypatch):
        """Fixture-driven: excerpt exists; mock LLM returns deterministic extraction."""
        make_raw_item(tmp_path, "web", "test-article")
        make_excerpt(tmp_path, "web", "test-article")
        monkeypatch.setattr(_extract_mod, "_call_claude", make_mock_claude())

        result = extract(tmp_path, no_synthesis=True)

        assert isinstance(result, ExtractResult)
        assert result.files_processed == 1
        assert result.errors == ()

        # Extraction file should exist.
        out = tmp_path / "_pipeline" / "extracted" / "web" / "test-article.md"
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "## Direct Data" in content

    def test_extract_skips_already_extracted(self, tmp_path, monkeypatch):
        make_raw_item(tmp_path, "web", "test-article")
        make_excerpt(tmp_path, "web", "test-article")
        monkeypatch.setattr(_extract_mod, "_call_claude", make_mock_claude())

        # First run.
        extract(tmp_path, no_synthesis=True)
        # Second run — same excerpt should be skipped.
        call_count = 0

        def counting_mock(model, system, prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            return DETERMINISTIC_EXTRACTION, MOCK_USAGE

        monkeypatch.setattr(_extract_mod, "_call_claude", counting_mock)
        extract(tmp_path, no_synthesis=True)
        assert call_count == 0

    def test_force_re_extracts(self, tmp_path, monkeypatch):
        make_raw_item(tmp_path, "web", "test-article")
        make_excerpt(tmp_path, "web", "test-article")
        monkeypatch.setattr(_extract_mod, "_call_claude", make_mock_claude())

        extract(tmp_path, no_synthesis=True)

        call_count = 0

        def counting_mock(model, system, prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            return DETERMINISTIC_EXTRACTION, MOCK_USAGE

        monkeypatch.setattr(_extract_mod, "_call_claude", counting_mock)
        extract(tmp_path, no_synthesis=True, force=True)
        assert call_count >= 1

    def test_dry_run_makes_no_calls(self, tmp_path, monkeypatch):
        make_raw_item(tmp_path, "web", "test-article")
        make_excerpt(tmp_path, "web", "test-article")

        called = False

        def fail_mock(model, system, prompt, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("LLM should not be called in dry_run mode")

        monkeypatch.setattr(_extract_mod, "_call_claude", fail_mock)
        result = extract(tmp_path, dry_run=True)
        assert not called
        assert result.files_processed == 0

    def test_context_tree_generated(self, tmp_path, monkeypatch):
        """Synthesis step produces context-tree.md at the expected path."""
        make_raw_item(tmp_path, "web", "test-article")
        make_excerpt(tmp_path, "web", "test-article")
        monkeypatch.setattr(_extract_mod, "_call_claude", make_mock_claude())

        # First extract so extraction file exists for synthesis.
        extract(tmp_path, no_synthesis=True)
        # Now run with synthesis.
        result = extract(tmp_path, no_synthesis=False, force=True)

        ct = tmp_path / "_pipeline" / "extracted" / "context-tree.md"
        assert ct.exists()
        assert result.context_tree_path == ct

    def test_non_english_excerpt_skipped(self, tmp_path, monkeypatch):
        make_raw_item(tmp_path, "web", "russian")
        make_excerpt(
            tmp_path,
            "web",
            "russian",
            body="(Non-English content — skipped for AI processing)\n\nПривет мир",
        )

        called = False

        def fail_mock(model, system, prompt, **kwargs):
            nonlocal called
            called = True
            return DETERMINISTIC_EXTRACTION, MOCK_USAGE

        monkeypatch.setattr(_extract_mod, "_call_claude", fail_mock)
        result = extract(tmp_path, no_synthesis=True)

        # Non-English items are skipped — no LLM call, counted as skipped.
        assert not called
        assert result.files_skipped >= 1

    def test_llm_error_recorded_in_errors(self, tmp_path, monkeypatch):
        make_raw_item(tmp_path, "web", "test-article")
        make_excerpt(tmp_path, "web", "test-article")

        def error_mock(model, system, prompt, **kwargs):
            raise RuntimeError("Simulated LLM failure")

        monkeypatch.setattr(_extract_mod, "_call_claude", error_mock)
        result = extract(tmp_path, no_synthesis=True)
        assert len(result.errors) >= 1
        assert "Simulated LLM failure" in result.errors[0]

    @pytest.mark.live_llm
    def test_real_claude_cli_extract(self, tmp_path):
        """Live-LLM test: real claude CLI call. Skipped by default; opt in with `--live-llm`."""
        import shutil

        if shutil.which("claude") is None:
            pytest.skip("claude CLI not available")
        make_raw_item(tmp_path, "web", "test-article")
        make_excerpt(tmp_path, "web", "test-article")
        result = extract(tmp_path, no_synthesis=True)
        # Just check it doesn't crash.
        assert isinstance(result, ExtractResult)


# ---------------------------------------------------------------------------
# US2 — stub auto-retry on resume (FR-003, FR-004)
# ---------------------------------------------------------------------------


def make_failed_stub(
    vault: Path,
    source_kind: str,
    stem: str,
    *,
    status: str = "extraction-failed",
    retry_attempts: int | None = None,
) -> Path:
    out_dir = vault / "_pipeline" / "extracted" / source_kind
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem}.md"
    fm_lines = [
        "---",
        f'source: "../raw/{source_kind}/{stem}.md"',
        "extracted: 2026-05-01 00:00",
        "model: haiku-cli",
        f"status: {status}",
    ]
    if retry_attempts is not None:
        fm_lines.append(f"retry_attempts: {retry_attempts}")
    fm_lines.extend(["---", "", "_Extraction failed: test_"])
    path.write_text("\n".join(fm_lines) + "\n", encoding="utf-8")
    return path


def test_resume_auto_retries_extraction_failed_stubs(tmp_path, monkeypatch):
    """Three extraction-failed stubs are re-queued on resume without flags."""
    stems = ["article-a", "article-b", "article-c"]
    for stem in stems:
        make_raw_item(tmp_path, "web", stem)
        make_excerpt(tmp_path, "web", stem)
        make_failed_stub(tmp_path, "web", stem)

    hits: list[str] = []

    def tracking_mock(model, system, prompt, **kwargs):
        for stem in stems:
            if stem in prompt:
                hits.append(stem)
                break
        return DETERMINISTIC_EXTRACTION, MOCK_USAGE

    monkeypatch.setattr(_extract_mod, "_call_claude", tracking_mock)
    extract(tmp_path, no_synthesis=True)
    assert sorted(hits) == sorted(stems)


def test_retry_exhaustion_marks_extraction_failed_permanent(tmp_path, monkeypatch):
    """After max_retry_attempts failures the stub becomes permanent."""
    make_raw_item(tmp_path, "web", "retry-me")
    make_excerpt(tmp_path, "web", "retry-me")
    make_failed_stub(tmp_path, "web", "retry-me", retry_attempts=2)

    def error_mock(model, system, prompt, **kwargs):
        raise RuntimeError("Simulated LLM failure")

    monkeypatch.setattr(_extract_mod, "_call_claude", error_mock)
    extract(tmp_path, no_synthesis=True)

    stub = tmp_path / "_pipeline" / "extracted" / "web" / "retry-me.md"
    fm, _ = parse_frontmatter(stub.read_text(encoding="utf-8"))
    assert fm.get("status") == "extraction-failed-permanent"
    assert int(fm.get("retry_attempts", 0)) >= 3


def test_force_reattempts_permanent_stubs(tmp_path, monkeypatch):
    """--force re-queues extraction-failed-permanent stubs."""
    make_raw_item(tmp_path, "web", "permanent-one")
    make_excerpt(tmp_path, "web", "permanent-one")
    make_failed_stub(
        tmp_path,
        "web",
        "permanent-one",
        status="extraction-failed-permanent",
        retry_attempts=3,
    )

    hits = {"count": 0}

    def counting_mock(model, system, prompt, **kwargs):
        hits["count"] += 1
        return DETERMINISTIC_EXTRACTION, MOCK_USAGE

    monkeypatch.setattr(_extract_mod, "_call_claude", counting_mock)
    extract(tmp_path, no_synthesis=True, force=True)
    assert hits["count"] >= 1


def test_find_targets_requeues_failed_stubs_within_max_attempts(tmp_path):
    """Failed stubs below max_retry_attempts are included; permanent stubs are not."""
    for stem, attempts in [("retry-a", 0), ("retry-b", 1), ("retry-c", 2)]:
        make_excerpt(tmp_path, "web", stem)
        make_failed_stub(tmp_path, "web", stem, retry_attempts=attempts)
    make_excerpt(tmp_path, "web", "permanent")
    make_failed_stub(
        tmp_path,
        "web",
        "permanent",
        status="extraction-failed-permanent",
        retry_attempts=3,
    )

    targets = _find_extraction_targets(
        tmp_path, "web", force=False, name_filter=None, since=None, max_retry_attempts=3
    )
    assert {p.stem for p in targets} == {"retry-a", "retry-b", "retry-c"}


def test_find_targets_increments_retry_count_in_frontmatter(tmp_path, monkeypatch):
    """A failed retry records an incremented retry_attempts count in the stub."""
    make_raw_item(tmp_path, "web", "retry-me")
    make_excerpt(tmp_path, "web", "retry-me")
    make_failed_stub(tmp_path, "web", "retry-me", retry_attempts=1)

    def error_mock(model, system, prompt, **kwargs):
        raise RuntimeError("Simulated LLM failure")

    monkeypatch.setattr(_extract_mod, "_call_claude", error_mock)
    extract(tmp_path, no_synthesis=True)

    stub = tmp_path / "_pipeline" / "extracted" / "web" / "retry-me.md"
    fm, _ = parse_frontmatter(stub.read_text(encoding="utf-8"))
    assert int(fm.get("retry_attempts", 0)) == 2


def test_exhausted_retry_rewrites_stub_to_permanent(tmp_path, monkeypatch):
    """The third consecutive failure marks the stub permanent."""
    make_raw_item(tmp_path, "web", "exhaust-me")
    make_excerpt(tmp_path, "web", "exhaust-me")
    make_failed_stub(tmp_path, "web", "exhaust-me", retry_attempts=2)

    def error_mock(model, system, prompt, **kwargs):
        raise RuntimeError("Simulated LLM failure")

    monkeypatch.setattr(_extract_mod, "_call_claude", error_mock)
    extract(tmp_path, no_synthesis=True)

    stub = tmp_path / "_pipeline" / "extracted" / "web" / "exhaust-me.md"
    fm, _ = parse_frontmatter(stub.read_text(encoding="utf-8"))
    assert fm.get("status") == "extraction-failed-permanent"
    assert int(fm.get("retry_attempts", 0)) == 3


def test_force_flag_bypasses_permanent_skip_in_find_targets(tmp_path):
    """_find_extraction_targets(..., force=True) includes permanent stubs."""
    make_excerpt(tmp_path, "web", "permanent-one")
    make_failed_stub(
        tmp_path,
        "web",
        "permanent-one",
        status="extraction-failed-permanent",
        retry_attempts=3,
    )

    targets = _find_extraction_targets(
        tmp_path, "web", force=True, name_filter=None, since=None, max_retry_attempts=3
    )
    assert [p.stem for p in targets] == ["permanent-one"]


# ---------------------------------------------------------------------------
# US3 — synthesis timeout ladder (FR-005, FR-006)
# ---------------------------------------------------------------------------

_SYNTHESIS_TODAY = "2026-06-03"


def _patch_synthesis_today(monkeypatch):
    from datetime import datetime as real_datetime

    class FixedDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 3, 12, 0, 0)

    monkeypatch.setattr(_extract_mod, "datetime", FixedDateTime)


def make_successful_extraction(
    vault: Path,
    source_kind: str,
    stem: str,
    *,
    extracted_date: str = "2026-05-01 00:00",
    body: str | None = None,
) -> Path:
    out_dir = vault / "_pipeline" / "extracted" / source_kind
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem}.md"
    content_body = body or DETERMINISTIC_EXTRACTION
    fm_lines = [
        "---",
        f'source: "../raw/{source_kind}/{stem}.md"',
        f"extracted: {extracted_date}",
        "model: haiku-cli",
        "---",
        "",
        content_body,
    ]
    path.write_text("\n".join(fm_lines) + "\n", encoding="utf-8")
    return path


def _synthesis_timeout_error() -> RuntimeError:
    return RuntimeError("agent dispatch exit 1: timed out")


def _context_tree_for_sources(sources: list[str]) -> str:
    source_line = ", ".join(sources)
    return f"""# Context Tree — {_SYNTHESIS_TODAY}

Batch: {len(sources)} sources ({len(sources)} web)

## Topics

### AI Scaling
**Description:** Research on how model size affects performance
**Sources:** {source_line}
**Vault status:** partially covered
**Key data:** 70B parameters
**Connections:** AI Tools
"""


def test_synthesis_ladder_falls_back_to_date_filter_on_timeout(tmp_path, monkeypatch):
    """Full bundle timeout → date-filter regather succeeds → context-tree.md written."""
    _patch_synthesis_today(monkeypatch)
    make_successful_extraction(tmp_path, "web", "legacy-item")
    make_successful_extraction(
        tmp_path,
        "web",
        f"{_SYNTHESIS_TODAY}-fresh",
        extracted_date=f"{_SYNTHESIS_TODAY} 00:00",
    )

    calls: list[str] = []

    def ladder_mock(model, system, prompt, **kwargs):
        if "legacy-item" in prompt and f"{_SYNTHESIS_TODAY}-fresh" in prompt:
            calls.append("full")
            raise _synthesis_timeout_error()
        calls.append("filtered")
        return _context_tree_for_sources([f"{_SYNTHESIS_TODAY}-fresh.md"]), MOCK_USAGE

    monkeypatch.setattr(_extract_mod, "_call_claude", ladder_mock)

    result = _synthesize_context_tree(
        vault=tmp_path,
        source_types=["web"],
        name_filter=None,
        topic_index="",
        context_tree_target="_pipeline/extracted/context-tree.md",
    )

    ct = tmp_path / "_pipeline" / "extracted" / "context-tree.md"
    assert result["status"] == "ok"
    assert ct.exists()
    assert calls == ["full", "filtered"]
    fm, _ = parse_frontmatter(ct.read_text(encoding="utf-8"))
    assert int(fm.get("batch_size", 0)) == 1
    assert "web" in str(fm.get("source_types", ""))


def test_synthesis_ladder_chunks_after_date_filter_timeout(tmp_path, monkeypatch):
    """Full + date-filter timeouts → chunked path succeeds with manifest sidecar."""
    _patch_synthesis_today(monkeypatch)
    stems = [f"{_SYNTHESIS_TODAY}-a", f"{_SYNTHESIS_TODAY}-b", f"{_SYNTHESIS_TODAY}-c"]
    for stem in stems:
        make_successful_extraction(
            tmp_path,
            "web",
            stem,
            extracted_date=f"{_SYNTHESIS_TODAY} 00:00",
        )

    calls: list[str] = []

    def ladder_mock(model, system, prompt, **kwargs):
        if len(calls) < 2:
            calls.append("bundle")
            raise _synthesis_timeout_error()
        calls.append("chunk")
        mentioned = [f"{stem}.md" for stem in stems if stem in prompt]
        return _context_tree_for_sources(mentioned), MOCK_USAGE

    monkeypatch.setattr(_extract_mod, "_call_claude", ladder_mock)

    result = _synthesize_context_tree(
        vault=tmp_path,
        source_types=["web"],
        name_filter=None,
        topic_index="",
        context_tree_target="_pipeline/extracted/context-tree.md",
        synthesis_chunk_size=2,
    )

    ct = tmp_path / "_pipeline" / "extracted" / "context-tree.md"
    manifest = tmp_path / "_pipeline" / "extracted" / "context-tree-chunks.json"
    assert result["status"] == "ok"
    assert ct.exists()
    assert manifest.exists()
    assert "chunk" in calls


def test_synthesis_ladder_exhausted_lists_attempted_strategies(tmp_path, monkeypatch):
    """All ladder steps fail → terminal error lists strategies and missing sources."""
    _patch_synthesis_today(monkeypatch)
    make_successful_extraction(
        tmp_path,
        "web",
        f"{_SYNTHESIS_TODAY}-only",
        extracted_date=f"{_SYNTHESIS_TODAY} 00:00",
    )

    def always_timeout(model, system, prompt, **kwargs):
        raise _synthesis_timeout_error()

    monkeypatch.setattr(_extract_mod, "_call_claude", always_timeout)

    with pytest.raises(RuntimeError) as exc_info:
        _synthesize_context_tree(
            vault=tmp_path,
            source_types=["web"],
            name_filter=None,
            topic_index="",
            context_tree_target="_pipeline/extracted/context-tree.md",
        )

    message = str(exc_info.value).lower()
    assert "full bundle" in message or "full" in message
    assert "filter" in message or _SYNTHESIS_TODAY in message
    assert "chunk" in message
    assert f"{_SYNTHESIS_TODAY}-only" in str(exc_info.value)


def test_chunked_synthesis_semantic_equivalence(tmp_path, monkeypatch):
    """Chunked reconciliation preserves source coverage vs a full-bundle success."""
    _patch_synthesis_today(monkeypatch)
    stems = ["alpha", "beta", "gamma"]
    for stem in stems:
        make_successful_extraction(tmp_path, "web", stem)

    full_tree = _context_tree_for_sources([f"{stem}.md" for stem in stems])

    def ladder_mock(model, system, prompt, **kwargs):
        if all(stem in prompt for stem in stems):
            raise _synthesis_timeout_error()
        mentioned = [f"{stem}.md" for stem in stems if stem in prompt]
        return _context_tree_for_sources(mentioned), MOCK_USAGE

    monkeypatch.setattr(_extract_mod, "_call_claude", ladder_mock)

    result = _synthesize_context_tree(
        vault=tmp_path,
        source_types=["web"],
        name_filter=None,
        topic_index="",
        context_tree_target="_pipeline/extracted/context-tree.md",
        synthesis_chunk_size=1,
    )

    body = (tmp_path / "_pipeline" / "extracted" / "context-tree.md").read_text(
        encoding="utf-8"
    )
    assert result["status"] == "ok"
    for stem in stems:
        assert f"{stem}.md" in body
    assert "## Topics" in body
    assert "AI Scaling" in full_tree


def test_synthesize_walks_ladder_in_order(tmp_path, monkeypatch):
    """Ladder attempts full bundle → date filter → chunked batches in order."""
    _patch_synthesis_today(monkeypatch)
    make_successful_extraction(
        tmp_path,
        "web",
        f"{_SYNTHESIS_TODAY}-item",
        extracted_date=f"{_SYNTHESIS_TODAY} 00:00",
    )

    stages: list[str] = []

    def ladder_mock(model, system, prompt, **kwargs):
        if len(stages) == 0:
            stages.append("full")
            raise _synthesis_timeout_error()
        if len(stages) == 1:
            stages.append("filter")
            raise _synthesis_timeout_error()
        stages.append("chunk")
        raise _synthesis_timeout_error()

    monkeypatch.setattr(_extract_mod, "_call_claude", ladder_mock)

    with pytest.raises(RuntimeError):
        _synthesize_context_tree(
            vault=tmp_path,
            source_types=["web"],
            name_filter=None,
            topic_index="",
            context_tree_target="_pipeline/extracted/context-tree.md",
            synthesis_chunk_size=1,
        )

    assert stages == ["full", "filter", "chunk"]


def test_synthesis_ladder_respects_processor_config_budget(tmp_path, monkeypatch):
    """Reduced retry budget stops after the configured ladder depth."""
    _patch_synthesis_today(monkeypatch)
    make_successful_extraction(tmp_path, "web", "legacy-only")

    calls: list[str] = []

    def always_timeout(model, system, prompt, **kwargs):
        calls.append("call")
        raise _synthesis_timeout_error()

    monkeypatch.setattr(_extract_mod, "_call_claude", always_timeout)

    with pytest.raises(RuntimeError) as exc_info:
        _synthesize_context_tree(
            vault=tmp_path,
            source_types=["web"],
            name_filter=None,
            topic_index="",
            context_tree_target="_pipeline/extracted/context-tree.md",
            synthesis_retry_budget=1,
        )

    assert len(calls) == 1
    message = str(exc_info.value).lower()
    assert "full bundle" in message
    assert "chunk" not in message


def test_chunk_manifest_records_attempted_and_succeeded_chunks(tmp_path, monkeypatch):
    """Chunk manifest sidecar records attempted and succeeded chunk entries."""
    _patch_synthesis_today(monkeypatch)
    stems = ["chunk-a", "chunk-b", "chunk-c"]
    for stem in stems:
        make_successful_extraction(tmp_path, "web", stem)

    def ladder_mock(model, system, prompt, **kwargs):
        hits = sum(1 for stem in stems if f"### {stem}.md" in prompt)
        if hits >= 2:
            raise _synthesis_timeout_error()
        mentioned = [f"{stem}.md" for stem in stems if f"### {stem}.md" in prompt]
        return _context_tree_for_sources(mentioned), MOCK_USAGE

    monkeypatch.setattr(_extract_mod, "_call_claude", ladder_mock)

    result = _synthesize_context_tree(
        vault=tmp_path,
        source_types=["web"],
        name_filter=None,
        topic_index="",
        context_tree_target="_pipeline/extracted/context-tree.md",
        synthesis_chunk_size=1,
    )

    manifest_path = tmp_path / "_pipeline" / "extracted" / "context-tree-chunks.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert len(manifest["attempted"]) == 3
    assert len(manifest["succeeded"]) == 3
    assert manifest["attempted"][0]["files"] == ["chunk-a.md"]


def test_chunk_reconciliation_preserves_source_coverage(tmp_path, monkeypatch):
    """Reconciled context tree retains every source filename from the fixture."""
    _patch_synthesis_today(monkeypatch)
    stems = ["src-a", "src-b", "src-c"]
    for stem in stems:
        make_successful_extraction(tmp_path, "web", stem)

    def ladder_mock(model, system, prompt, **kwargs):
        if len(stems) == sum(1 for stem in stems if stem in prompt):
            raise _synthesis_timeout_error()
        mentioned = [f"{stem}.md" for stem in stems if stem in prompt]
        return _context_tree_for_sources(mentioned), MOCK_USAGE

    monkeypatch.setattr(_extract_mod, "_call_claude", ladder_mock)

    _synthesize_context_tree(
        vault=tmp_path,
        source_types=["web"],
        name_filter=None,
        topic_index="",
        context_tree_target="_pipeline/extracted/context-tree.md",
        synthesis_chunk_size=1,
    )

    body = (tmp_path / "_pipeline" / "extracted" / "context-tree.md").read_text(
        encoding="utf-8"
    )
    for stem in stems:
        assert f"{stem}.md" in body


def test_explicit_workers_is_honoured(tmp_path, monkeypatch):
    """``cfg.get("workers", workers)`` always found ``PROCESSOR_DEFAULTS``'s 5,
    so an explicit ``workers`` (and the CLI's ``--workers``) was ignored."""
    make_raw_item(tmp_path, "web", "w1")
    make_excerpt(tmp_path, "web", "w1")
    monkeypatch.setattr(_extract_mod, "_call_claude", make_mock_claude())
    seen: list[int] = []
    real_pool = _extract_mod.ThreadPoolExecutor

    def recording_pool(*args, **kwargs):
        seen.append(kwargs.get("max_workers"))
        return real_pool(*args, **kwargs)

    monkeypatch.setattr(_extract_mod, "ThreadPoolExecutor", recording_pool)

    extract(tmp_path, no_synthesis=True, workers=2)

    assert seen == [2]
