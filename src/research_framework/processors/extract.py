"""Extract phase processor — Haiku per-source extraction + Sonnet context tree.

Chains preprocess -> per-source Haiku extraction -> Sonnet context tree
synthesis. Idempotent and resumable: re-running skips items that already have
an extraction file, so it's safe to run until everything is processed.

AI calls route through ``agent_call.dispatch()`` (spec 028 / FR-007). The
processor requires a vault-local ``settings.yaml`` and authenticated Claude
Code runtime. **Sandbox incompatibility:** nested CLI dispatch inside a
sandboxed agent session typically cannot reach the OAuth keychain — the
layered sandbox detector (FR-001) hard-exits with zero stubs rather than
writing ``extraction-failed`` placeholders. Override:
``RV_DISABLE_SANDBOX_DETECT=1`` (SC-005).

Ported faithfully from feeds-vault/scripts/extract.py; key adaptations:
  1. Path conventions use vault root argument (no hard-coded BASE).
  2. ``_call_claude`` is a module-level callable that can be replaced in tests
     via ``extract._call_claude = mock_fn`` for deterministic unit testing.
  3. AGENTS.md topic index loading is a separate function for easy stubbing.

Python API:
    from research_framework.processors.extract import extract, ExtractResult
    result = extract(vault_path, since="2026-05-01")

CLI:
    python -m research_framework.processors.extract <vault> [options]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ._common import (
    excerpts_dir,
    extracted_dir,
    parse_frontmatter,
    processor_config,
    raw_dir,
    validate_raw_item,
)

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractResult:
    files_processed: int
    files_skipped: int
    context_tree_path: Path | None
    errors: tuple[str, ...]


# ---------------------------------------------------------------------------
# Constants (ported from feeds-vault/scripts/extract.py)
# ---------------------------------------------------------------------------

HAIKU_MODEL = "haiku"
SONNET_MODEL = "sonnet"
HAIKU_MAX_CHARS = 720_000
CLAUDE_CLI_TIMEOUT = 300

REQUIRED_SECTIONS = (
    "## Direct Data",
    "## Entities",
    "## Concepts",
    "## Connections to Vault",
    "## Signals",
    "## Cross-Reference Candidates",
)

HAIKU_SYSTEM = (
    "You are a precise information extractor. Given a piece of content "
    "(transcript, post, or article), extract structured data in the exact "
    "format requested. Be specific — prefer exact quotes, numbers, and "
    "names over paraphrases. If something is not present in the content, "
    'write "none" not a guess. Do not add information not in the source.'
)

SONNET_SYSTEM = (
    "You are a synthesis agent. You receive structured extractions from "
    "multiple sources and produce a compact context tree that maps what "
    "the current batch of content is about. Your output will be read by "
    "the Scout agent to produce a Topic Radar. Be specific and use exact "
    "names, numbers, and terms from the extractions. Vault status icons: "
    "check-mark = well covered, yellow-circle = partially covered, "
    "red-x = not covered, new-badge = brand new topic."
)


# ---------------------------------------------------------------------------
# Sandbox detection (FR-001 / FR-002)
# ---------------------------------------------------------------------------
#
# Primary stderr signatures (research.md §2 — tolerant set; live-probe may extend):
#   "invalid api key", "please run /login", "not logged in", "logged in",
#   auth+fail, oauth, credential/keychain.
# Fallback: first ≥3 extractions each fail with latency_ms < 1000.
# Override: RV_DISABLE_SANDBOX_DETECT=1 suppresses both layers (SC-005).

_SANDBOX_STDERR_MARKERS = (
    "invalid api key",
    "please run /login",
    "not logged in",
    "logged in",
)
_SANDBOX_DOC_LINK = "specs/032-pipeline-reliability/quickstart.md#sandbox-detection"
_FAST_SANDBOX_FAILURE_MS = 1000
_FAST_SANDBOX_FAILURE_THRESHOLD = 3


class SandboxDetectedError(RuntimeError):
    """Raised when layered sandbox heuristics detect an unauthenticated CLI context."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(
            "Sandboxed Claude Code environment detected "
            f"({reason}). Nested agent dispatch cannot authenticate — "
            "no extraction stubs were written. "
            "Remediation: run `claude /login` before autonomous extraction, or set "
            "`dangerouslyDisableSandbox: true` in the vault Claude settings when "
            "running inside a nested sandbox. "
            f"Documentation: {_SANDBOX_DOC_LINK}"
        )


class SynthesisTimeoutError(RuntimeError):
    """Raised when Sonnet synthesis dispatch hits the agent_call timeout sentinel."""


class _FastDispatchFailure(RuntimeError):
    """Fast failed dispatch counted toward time-based sandbox detection."""


def _sandbox_detect_disabled() -> bool:
    return os.environ.get("RV_DISABLE_SANDBOX_DETECT", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _stderr_matches_sandbox_signature(text: str) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in _SANDBOX_STDERR_MARKERS):
        return True
    if "auth" in lowered and "fail" in lowered:
        return True
    if "oauth" in lowered:
        return True
    return "credential" in lowered or "keychain" in lowered


class _SandboxClassifier:
    """Layered sandbox detector fed each dispatch ``AgentCallResult``."""

    def __init__(self) -> None:
        self._consecutive_fast_failures = 0
        self._lock = threading.Lock()
        self.tripped = False

    def evaluate(self, result: Any) -> str | None:
        with self._lock:
            if _sandbox_detect_disabled():
                return None
            if int(getattr(result, "exit_code", 0) or 0) == 0:
                self._consecutive_fast_failures = 0
                return None

            combined = "\n".join(
                str(getattr(result, field, "") or "") for field in ("stderr", "stdout")
            )
            if _stderr_matches_sandbox_signature(combined):
                self.tripped = True
                return "auth-failure signature in agent stderr/stdout"

            latency_ms = int(getattr(result, "latency_ms", 0) or 0)
            if latency_ms < _FAST_SANDBOX_FAILURE_MS:
                self._consecutive_fast_failures += 1
                if self._consecutive_fast_failures >= _FAST_SANDBOX_FAILURE_THRESHOLD:
                    self.tripped = True
                    return (
                        f"{_FAST_SANDBOX_FAILURE_THRESHOLD} consecutive fast failures "
                        f"(<{_FAST_SANDBOX_FAILURE_MS}ms each)"
                    )
            else:
                self._consecutive_fast_failures = 0
            return None

    def counting_fast_failure(self) -> bool:
        with self._lock:
            return (
                not _sandbox_detect_disabled()
                and 0
                < self._consecutive_fast_failures
                < _FAST_SANDBOX_FAILURE_THRESHOLD
            )


# ---------------------------------------------------------------------------
# LLM call (replaceable for tests)
# ---------------------------------------------------------------------------


# Module-level vault context for dispatch-backed LLM calls (set by extract()).
_active_vault_dir: Path | None = None
_active_sandbox_classifier: _SandboxClassifier | None = None


def _stage_for_model(model: str) -> str:
    if "sonnet" in model.lower():
        return "processor_synthesis"
    return "processor_extract"


def _default_call_claude(
    model: str,
    system_prompt: str,
    user_prompt: str,
    *,
    attempt: int = 1,
) -> tuple[str, dict[str, Any]]:
    """Invoke Claude through ``agent_call.dispatch()``. Returns (text, usage_dict).

    Retries up to 3 times with exponential backoff on non-zero exit or auth errors.
    Raises RuntimeError after 3 failures.
    """
    vault_dir = _active_vault_dir
    if vault_dir is None:
        raise RuntimeError(
            "extract._active_vault_dir is unset — call extract() before _call_claude"
        )

    from ..pipeline.plan_narrator import _bootstrap_scripts_agent_call

    agent_call = _bootstrap_scripts_agent_call(vault_dir=vault_dir)
    stage = _stage_for_model(model)
    prompt = f"{system_prompt}\n\n{user_prompt}"

    result = agent_call.dispatch(
        stage=stage,
        prompt=prompt,
        vault_dir=vault_dir,
        timeout_s=CLAUDE_CLI_TIMEOUT,
        model=model,
    )

    classifier = _active_sandbox_classifier
    if classifier is not None:
        sandbox_reason = classifier.evaluate(result)
        if sandbox_reason:
            raise SandboxDetectedError(sandbox_reason)
        if result.exit_code != 0 and classifier.counting_fast_failure():
            raise _FastDispatchFailure("fast dispatch failure under sandbox watch")

    if result.exit_code != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()
        if attempt >= 3 or "logged in" in detail.lower():
            raise RuntimeError(
                f"agent dispatch exit {result.exit_code}: {detail[:400]}"
            )
        time.sleep(2**attempt)
        return _default_call_claude(
            model, system_prompt, user_prompt, attempt=attempt + 1
        )

    body = (result.stdout or "").strip()
    if not body:
        if attempt >= 3:
            raise RuntimeError("agent dispatch returned empty stdout")
        time.sleep(2**attempt)
        return _default_call_claude(
            model, system_prompt, user_prompt, attempt=attempt + 1
        )

    usage: dict[str, Any] = {
        "input_tokens": result.tokens_in,
        "output_tokens": result.tokens_out,
        "cache_read": 0,
        "cache_creation": 0,
        "cost_usd": result.cost_usd,
    }
    return body, usage


# Module-level reference — replace in tests: extract._call_claude = my_mock
_call_claude = _default_call_claude


# ---------------------------------------------------------------------------
# Topic index loading
# ---------------------------------------------------------------------------


def load_topic_index(vault: Path) -> str:
    """Pull Topic Index + Key Numbers sections from <vault>/AGENTS.md."""
    agents_md = vault / "AGENTS.md"
    # Also check <vault>/<corpus>/AGENTS.md heuristic.
    if not agents_md.exists():
        for candidate in vault.rglob("AGENTS.md"):
            agents_md = candidate
            break
    if not agents_md.exists():
        return ""
    text = agents_md.read_text(encoding="utf-8", errors="replace")
    m = re.search(
        r"^## Topic Index.*?(?=\n## |\Z)", text, flags=re.MULTILINE | re.DOTALL
    )
    topic = m.group(0) if m else ""
    m2 = re.search(
        r"^## Key Numbers.*?(?=\n## |\Z)", text, flags=re.MULTILINE | re.DOTALL
    )
    key_numbers = m2.group(0) if m2 else ""
    combined = (topic + "\n\n" + key_numbers).strip()
    return combined or text


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _find_extraction_targets(
    vault: Path,
    source_type: str,
    *,
    force: bool,
    name_filter: str | None,
    since: str | None,
    max_retry_attempts: int = 3,
) -> list[Path]:
    """Return excerpt .txt paths that need extraction for one source type."""
    exc_dir = excerpts_dir(vault) / source_type
    out_dir = extracted_dir(vault) / source_type
    if not exc_dir.exists():
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = []
    for excerpt in sorted(exc_dir.glob("*.txt")):
        if name_filter and name_filter not in excerpt.name:
            continue
        if since and excerpt.stem < since:
            continue
        out_path = out_dir / f"{excerpt.stem}.md"
        if out_path.exists():
            if force:
                targets.append(excerpt)
                continue
            try:
                text = out_path.read_text(encoding="utf-8", errors="replace")
                fm, _ = parse_frontmatter(text)
            except OSError:
                fm = {}
            status = fm.get("status")
            if status == "extraction-failed-permanent":
                continue
            if status == "extraction-failed":
                attempts = int(fm.get("retry_attempts", 1))
                if attempts < max_retry_attempts:
                    targets.append(excerpt)
            continue
        targets.append(excerpt)
    return targets


def _next_retry_attempt(out_path: Path) -> int:
    """Return the attempt count to record after the next extraction failure."""
    if not out_path.exists():
        return 1
    try:
        text = out_path.read_text(encoding="utf-8", errors="replace")
        fm, _ = parse_frontmatter(text)
    except OSError:
        return 1
    if fm.get("status") in ("extraction-failed", "extraction-failed-permanent"):
        return int(fm.get("retry_attempts", 1)) + 1
    return 1


def _failure_stub_status(out_path: Path, *, max_retry_attempts: int) -> tuple[str, int]:
    """Map a failed extraction to stub status + retry_attempts frontmatter."""
    attempt = _next_retry_attempt(out_path)
    if attempt >= max_retry_attempts:
        return "extraction-failed-permanent", attempt
    return "extraction-failed", attempt


def _is_non_english(excerpt_text: str) -> bool:
    head = "\n".join(excerpt_text.splitlines()[:5])
    return "(Non-English content" in head


# ---------------------------------------------------------------------------
# Haiku extraction
# ---------------------------------------------------------------------------


def _build_haiku_prompt(
    *, source_url: str, source_type: str, title: str, excerpt: str, topic_index: str
) -> str:
    return f"""Source: {source_url}
Type: {source_type}
Title: {title}

Content:
{excerpt}

Extract the following sections. Use the exact headings shown.

## Direct Data
List key claims that include numbers, measurements, or specific evidence.
Format: - [claim]: [evidence] (source: [timestamp or section if available])
If none: "- none"

## Entities
- Tools: [comma-separated list, or "none"]
- People: [comma-separated list with role/affiliation if mentioned, or "none"]
- Companies: [comma-separated list, or "none"]
- Papers/Sources: [title + URL or DOI if mentioned, or "none"]

## Concepts
For each concept explained or debated in the content:
- [concept name]: [how it's discussed — one sentence max]

## Connections to Vault
Based on the content topics, list terms that likely match existing vault notes.
Use this topic index for matching:

{topic_index}

Format: [[Term]]: [one sentence on how this content relates]
If uncertain, omit rather than guess.

## Signals
- Consensus: [what most sources/comments agree on, or "not determinable from single source"]
- Controversy: [what's debated or disputed, or "none"]
- Questions: [unanswered questions raised in the content, or "none"]

## Cross-Reference Candidates
For each external reference found in the content (URLs, authors, papers, tools, competing sources):
- type: url | author | tool | paper | source
  value: "[name or URL]"
  context: "[where/how it was mentioned — one sentence]"
  already_tracked: [true if the name appears in sources.yaml or the vault topic index, false otherwise]
"""


def _validate_haiku_output(body: str) -> tuple[bool, str]:
    missing = [s for s in REQUIRED_SECTIONS if s not in body]
    if missing:
        return False, f"missing sections: {', '.join(missing)}"
    return True, ""


def _slice_section(body: str, start: str, end: str | None) -> str:
    i = body.find(start)
    if i == -1:
        return ""
    if end is None:
        return body[i:]
    j = body.find(end, i + len(start))
    return body[i:j] if j != -1 else body[i:]


def _score_quality(body: str) -> str:
    data_section = _slice_section(body, "## Direct Data", "## Entities")
    ent_section = _slice_section(body, "## Entities", "## Concepts")
    data_empty = (
        "none" in data_section.lower() and len(data_section.strip().splitlines()) <= 3
    )
    ent_empty = all(
        f"{k}: none" in ent_section.lower() for k in ("tools", "people", "companies")
    )
    return "low-signal" if data_empty and ent_empty else "ok"


def _write_extraction(
    out_path: Path,
    body: str,
    *,
    raw_rel: str,
    status: str | None,
    quality: str | None,
    retry_attempts: int | None = None,
) -> None:
    fm_lines = [
        "---",
        f'source: "{raw_rel}"',
        f"extracted: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "model: haiku-cli",
    ]
    if status:
        fm_lines.append(f"status: {status}")
    if retry_attempts is not None:
        fm_lines.append(f"retry_attempts: {retry_attempts}")
    if quality:
        fm_lines.append(f"quality: {quality}")
    fm_lines.append("---")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if _active_sandbox_classifier is not None and _active_sandbox_classifier.tripped:
        raise SandboxDetectedError("aborting stub write after sandbox trip")
    out_path.write_text(
        "\n".join(fm_lines) + "\n\n" + body.strip() + "\n", encoding="utf-8"
    )


def _extract_one(
    excerpt_path: Path,
    *,
    vault: Path,
    source_type: str,
    topic_index: str,
    haiku_model: str = HAIKU_MODEL,
    max_retry_attempts: int = 3,
) -> dict[str, Any]:
    """Process a single excerpt. Returns a result record."""
    stem = excerpt_path.stem
    raw_path = raw_dir(vault) / source_type / f"{stem}.md"
    out_path = extracted_dir(vault) / source_type / f"{stem}.md"
    result: dict[str, Any] = {
        "file": stem,
        "source_type": source_type,
        "status": "ok",
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
    }

    try:
        excerpt = excerpt_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        result.update(status="read-error", error=str(exc))
        return result

    if _is_non_english(excerpt):
        result["status"] = "skipped-non-english"
        return result
    if len(excerpt) > HAIKU_MAX_CHARS:
        result.update(status="skipped-too-large", chars=len(excerpt))
        return result

    # Validate raw item frontmatter at input boundary.
    if raw_path.exists():
        try:
            text = raw_path.read_text(encoding="utf-8", errors="replace")
            fm, _ = parse_frontmatter(text)
            validate_raw_item(fm, raw_path)
        except Exception:
            pass  # Non-fatal; extraction still attempted.

    fm = {}
    if raw_path.exists():
        try:
            text = raw_path.read_text(encoding="utf-8", errors="replace")
            fm, _ = parse_frontmatter(text)
        except Exception:
            pass

    prompt = _build_haiku_prompt(
        source_url=fm.get("source_url", fm.get("original_url", "unknown")),
        source_type=source_type,
        title=fm.get("title", stem),
        excerpt=excerpt,
        topic_index=topic_index,
    )

    try:
        body, usage = _call_claude(haiku_model, HAIKU_SYSTEM, prompt)
    except SandboxDetectedError:
        raise
    except _FastDispatchFailure:
        raise
    except Exception as exc:
        result.update(status="api-error", error=str(exc))
        fail_status, attempt = _failure_stub_status(
            out_path, max_retry_attempts=max_retry_attempts
        )
        _write_extraction(
            out_path,
            f"_Extraction failed: {exc}_",
            raw_rel=f"../raw/{source_type}/{stem}.md",
            status=fail_status,
            quality=None,
            retry_attempts=attempt,
        )
        return result

    result["tokens_in"] = usage["input_tokens"]
    result["tokens_out"] = usage["output_tokens"]
    result["cost_usd"] = usage.get("cost_usd", 0.0)

    ok, why = _validate_haiku_output(body)
    if not ok:
        result.update(status="malformed", error=why)
        fail_status, attempt = _failure_stub_status(
            out_path, max_retry_attempts=max_retry_attempts
        )
        _write_extraction(
            out_path,
            body,
            raw_rel=f"../raw/{source_type}/{stem}.md",
            status=fail_status,
            quality=None,
            retry_attempts=attempt,
        )
        return result

    quality = _score_quality(body)
    _write_extraction(
        out_path,
        body,
        raw_rel=f"../raw/{source_type}/{stem}.md",
        status=None,
        quality=quality if quality != "ok" else None,
    )
    if quality == "low-signal":
        result["status"] = "ok-low-signal"
    return result


# ---------------------------------------------------------------------------
# Sonnet context tree synthesis
# ---------------------------------------------------------------------------

SYNTHESIS_CHUNK_SIZE = 25
SYNTHESIS_RETRY_BUDGET_DEFAULT = 3
_CHUNK_MANIFEST_NAME = "context-tree-chunks.json"


def _dispatch_timed_out(exc: BaseException) -> bool:
    if isinstance(exc, SynthesisTimeoutError):
        return True
    return "timed out" in str(exc).lower()


def _invoke_synthesis_call(
    model: str, system_prompt: str, user_prompt: str
) -> tuple[str, dict[str, Any]]:
    try:
        return _call_claude(model, system_prompt, user_prompt)
    except RuntimeError as exc:
        if _dispatch_timed_out(exc):
            raise SynthesisTimeoutError(str(exc)) from exc
        raise


def _source_counts(paths: list[Path], source_types: list[str]) -> dict[str, int]:
    return {st: sum(1 for p in paths if p.parent.name == st) for st in source_types}


def _chunk_paths(paths: list[Path], chunk_size: int) -> list[list[Path]]:
    size = max(1, chunk_size)
    return [paths[i : i + size] for i in range(0, len(paths), size)]


def _extract_topics_section(body: str) -> str:
    if "## Topics" not in body:
        return body.strip()
    rest = body.split("## Topics", 1)[1]
    for marker in (
        "## Cross-Cutting Themes",
        "## Strongest Signals",
        "## Gaps Identified",
        "## Cross-Reference Queue",
    ):
        if marker in rest:
            rest = rest.split(marker, 1)[0]
    return rest.strip()


def _reconcile_chunk_bodies(
    bodies: list[str], *, date_str: str, total_sources: int
) -> str:
    topic_sections = [_extract_topics_section(body) for body in bodies if body.strip()]
    merged_topics = "\n\n".join(section for section in topic_sections if section)
    return f"""# Context Tree — {date_str}

Batch: {total_sources} sources (chunked synthesis)

## Topics

{merged_topics}

## Cross-Cutting Themes
- Chunked synthesis merge — see topic sections above

## Strongest Signals
1. See merged topic sections

## Gaps Identified
- See individual chunk outputs

## Cross-Reference Queue
- See individual chunk outputs
"""


def _write_context_tree_file(
    *,
    ct_path: Path,
    body: str,
    kept: int,
    counts: dict[str, int],
) -> None:
    ct_path.parent.mkdir(parents=True, exist_ok=True)
    fm = [
        "---",
        f"generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"batch_size: {kept}",
        f"source_types: [{', '.join(st for st, n in counts.items() if n)}]",
        "model: sonnet-cli",
        "---",
        "",
    ]
    ct_path.write_text("\n".join(fm) + body.strip() + "\n", encoding="utf-8")


def _write_chunk_manifest(vault: Path, manifest: dict[str, Any]) -> Path:
    manifest_path = extracted_dir(vault) / _CHUNK_MANIFEST_NAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def _run_single_synthesis(
    *,
    paths: list[Path],
    source_types: list[str],
    topic_index: str,
    sonnet_model: str,
    date_str: str,
) -> tuple[str, dict[str, Any], int, dict[str, int]]:
    counts = _source_counts(paths, source_types)
    bundle, kept = _read_extraction_bundle(paths)
    if kept == 0:
        raise RuntimeError("no successful extractions available for synthesis")
    prompt = _build_sonnet_prompt(
        bundle=bundle,
        batch_size=kept,
        source_counts=counts,
        topic_index=topic_index,
        date_str=date_str,
    )
    body, usage = _invoke_synthesis_call(sonnet_model, SONNET_SYSTEM, prompt)
    return body, usage, kept, counts


def _synthesis_failure_message(
    *,
    strategies: list[str],
    missing_sources: list[str],
) -> str:
    attempted = ", ".join(strategies) if strategies else "none"
    missing = ", ".join(missing_sources) if missing_sources else "none"
    return (
        "Sonnet synthesis failed after exhausting the timeout ladder. "
        f"Attempted strategies: {attempted}. "
        f"Missing sources: {missing}. "
        f"Documentation: specs/032-pipeline-reliability/quickstart.md#us3"
    )


def _gather_extractions(
    vault: Path, source_types: list[str], name_filter: str | None
) -> list[Path]:
    out: list[Path] = []
    for st in source_types:
        d = extracted_dir(vault) / st
        if not d.exists():
            continue
        for p in sorted(d.glob("*.md")):
            if name_filter and name_filter not in p.name:
                continue
            out.append(p)
    return out


def _read_extraction_bundle(paths: list[Path]) -> tuple[str, int]:
    parts = []
    kept = 0
    for p in paths:
        text = p.read_text(encoding="utf-8", errors="replace")
        fm, _ = parse_frontmatter(text)
        if fm.get("status") == "extraction-failed":
            continue
        parts.append(f"### {p.name}\n\n{text}")
        kept += 1
    return "\n\n---\n\n".join(parts), kept


def _build_sonnet_prompt(
    *,
    bundle: str,
    batch_size: int,
    source_counts: dict[str, int],
    topic_index: str,
    date_str: str,
) -> str:
    counts_str = ", ".join(f"{v} {k}" for k, v in source_counts.items() if v)
    return f"""Below are structured extractions from {batch_size} sources collected on {date_str}. After the extractions, you'll find the vault's current topic index for cross-referencing vault coverage.

Produce a context tree in the exact format below. Keep total output under ~4000 tokens. If the batch is large, prioritize by signal strength (source count, data quality, recency).

{bundle}

---

VAULT TOPIC INDEX (for determining vault status):
{topic_index}

---

Output format (use exactly):

# Context Tree — {date_str}

Batch: {batch_size} sources ({counts_str})

## Topics

### [Topic Name]
**Description:** [synthesized description across sources]
**Sources:** [filenames of raw files that mention this topic] ([count])
**Vault status:** [use status icons]
**Key data:** [most important number or claim from the batch]
**Connections:** [related topics in this tree or existing vault note names]

(repeat for each topic)

## Cross-Cutting Themes
- [Theme]: appears in [topic names], connecting [X] to [Y]

## Strongest Signals
1. [Topic] — [why: source count, data quality, recency]

## Gaps Identified
- [Topic the vault should cover but doesn't, based on batch signals]

## Cross-Reference Queue
New sources/authors/papers/tools surfaced by extraction that are not yet tracked:
- type: [url|author|tool|paper|source]
  value: "[name or URL]"
  context: "[brief context]"
  already_tracked: false
"""


def _synthesize_context_tree(
    *,
    vault: Path,
    source_types: list[str],
    name_filter: str | None,
    topic_index: str,
    context_tree_target: str,
    sonnet_model: str = SONNET_MODEL,
    synthesis_chunk_size: int = SYNTHESIS_CHUNK_SIZE,
    synthesis_retry_budget: int = SYNTHESIS_RETRY_BUDGET_DEFAULT,
) -> dict[str, Any]:
    paths = _gather_extractions(vault, source_types, name_filter)
    if not paths:
        return {"status": "no-extractions"}

    bundle, kept = _read_extraction_bundle(paths)
    if kept == 0:
        return {"status": "all-failed"}

    date_str = datetime.now().strftime("%Y-%m-%d")
    ct_path = vault / context_tree_target
    strategies_attempted: list[str] = []
    budget = max(1, synthesis_retry_budget)
    chunk_size = max(1, synthesis_chunk_size)

    def _finish_ok(
        body: str,
        usage: dict[str, Any],
        batch_size: int,
        *,
        effective_paths: list[Path] | None = None,
        manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        path_set = effective_paths if effective_paths is not None else paths
        counts = _source_counts(path_set, source_types)
        _write_context_tree_file(
            ct_path=ct_path, body=body, kept=batch_size, counts=counts
        )
        result: dict[str, Any] = {
            "status": "ok",
            "batch_size": batch_size,
            "usage": usage,
            "path": ct_path,
        }
        if manifest is not None:
            manifest_path = _write_chunk_manifest(vault, manifest)
            result["chunk_manifest"] = manifest_path
        return result

    # Step 1 — full bundle (respecting caller name_filter).
    if budget >= 1:
        try:
            body, usage, batch_size, _counts = _run_single_synthesis(
                paths=paths,
                source_types=source_types,
                topic_index=topic_index,
                sonnet_model=sonnet_model,
                date_str=date_str,
            )
            return _finish_ok(body, usage, batch_size)
        except SynthesisTimeoutError:
            strategies_attempted.append("full bundle")

    # Step 2 — date-scoped regather (`--filter <today>`).
    filtered_paths: list[Path] = []
    if budget >= 2:
        filtered_paths = _gather_extractions(vault, source_types, date_str)
        if filtered_paths:
            try:
                body, usage, batch_size, _counts = _run_single_synthesis(
                    paths=filtered_paths,
                    source_types=source_types,
                    topic_index=topic_index,
                    sonnet_model=sonnet_model,
                    date_str=date_str,
                )
                return _finish_ok(
                    body, usage, batch_size, effective_paths=filtered_paths
                )
            except SynthesisTimeoutError:
                strategies_attempted.append(f"date filter ({date_str})")
        else:
            strategies_attempted.append(f"date filter ({date_str}, no matches)")

    # Step 3 — chunked batches.
    chunk_paths = filtered_paths or paths
    if budget >= 3 and chunk_paths:
        strategies_attempted.append("chunked batches")
        manifest: dict[str, Any] = {
            "schema_version": "1.0",
            "attempted": [],
            "succeeded": [],
        }
        chunk_bodies: list[str] = []
        total_usage: dict[str, Any] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read": 0,
            "cache_creation": 0,
            "cost_usd": 0.0,
        }
        for index, chunk in enumerate(_chunk_paths(chunk_paths, chunk_size)):
            entry = {"chunk": index, "files": [p.name for p in chunk]}
            manifest["attempted"].append(entry)
            try:
                body, usage, _batch_size, _counts = _run_single_synthesis(
                    paths=chunk,
                    source_types=source_types,
                    topic_index=topic_index,
                    sonnet_model=sonnet_model,
                    date_str=date_str,
                )
            except SynthesisTimeoutError:
                continue
            manifest["succeeded"].append(entry)
            chunk_bodies.append(body)
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_read",
                "cache_creation",
            ):
                total_usage[key] += int(usage.get(key, 0) or 0)
            total_usage["cost_usd"] += float(usage.get("cost_usd", 0.0) or 0.0)

        if chunk_bodies:
            merged = _reconcile_chunk_bodies(
                chunk_bodies, date_str=date_str, total_sources=kept
            )
            return _finish_ok(
                merged,
                total_usage,
                kept,
                effective_paths=chunk_paths,
                manifest=manifest,
            )

    missing = [p.stem for p in paths]
    raise RuntimeError(
        _synthesis_failure_message(
            strategies=strategies_attempted,
            missing_sources=missing,
        )
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract(
    vault: Path,
    *,
    since: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    no_synthesis: bool = False,
    source_types: list[str] | None = None,
    name_filter: str | None = None,
    workers: int | None = None,
    spec_processors: dict[str, Any] | None = None,
) -> ExtractResult:
    """Extract structured data from raw pipeline items.

    Reads excerpts from <vault>/_pipeline/extracted/excerpts/<source_kind>/,
    runs per-file Haiku extraction, then synthesises a context tree via Sonnet.

    Args:
        vault: Root directory of the vault.
        since: Only process files whose stem >= this string (e.g. "2026-05-01").
        force: Re-extract items that already have an extraction file.
        dry_run: Discover targets but make no LLM calls.
        no_synthesis: Skip Sonnet context tree synthesis step.
        source_types: Source sub-directories to scan. Defaults to all found.
        name_filter: Only process files whose name contains this substring.
        workers: Thread pool size for parallel Haiku calls. ``None`` defers to
            spec config, then to 5.
        spec_processors: Optional processors section from SpecConfig.

    Returns:
        ExtractResult with counts and any errors.
    """
    cfg = processor_config(spec_processors, "extract")
    # Explicit argument > spec config > default (``cfg`` always carries the
    # PROCESSOR_DEFAULTS key, so ``cfg.get(key, param)`` discarded the argument).
    if workers is None:
        workers = cfg.get("workers", 5)
    workers = int(workers)
    haiku_model = str(cfg.get("model", HAIKU_MODEL))
    max_retry_attempts = int(cfg.get("max_retry_attempts", 3))
    context_tree_target = str(
        cfg.get("context_tree_target", "_pipeline/extracted/context-tree.md")
    )
    synthesis_chunk_size = int(cfg.get("synthesis_chunk_size", SYNTHESIS_CHUNK_SIZE))
    synthesis_retry_budget = int(
        cfg.get("synthesis_retry_budget", SYNTHESIS_RETRY_BUDGET_DEFAULT)
    )

    global _active_vault_dir, _active_sandbox_classifier
    _active_vault_dir = vault
    _active_sandbox_classifier = _SandboxClassifier()
    try:
        if source_types is None:
            exc_root = excerpts_dir(vault)
            if exc_root.exists():
                source_types = [
                    d.name for d in sorted(exc_root.iterdir()) if d.is_dir()
                ]
            else:
                source_types = []

        targets: list[tuple[Path, str]] = []
        for st in source_types:
            for p in _find_extraction_targets(
                vault,
                st,
                force=force,
                name_filter=name_filter,
                since=since,
                max_retry_attempts=max_retry_attempts,
            ):
                targets.append((p, st))

        errors: list[str] = []
        files_processed = 0
        files_skipped = 0

        if dry_run:
            return ExtractResult(
                files_processed=0,
                files_skipped=len(targets),
                context_tree_path=None,
                errors=(),
            )

        if not targets:
            # Nothing to extract; maybe still synthesise.
            pass
        else:
            topic_index = load_topic_index(vault)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {
                    pool.submit(
                        _extract_one,
                        p,
                        vault=vault,
                        source_type=st,
                        topic_index=topic_index,
                        haiku_model=haiku_model,
                        max_retry_attempts=max_retry_attempts,
                    ): (p, st)
                    for p, st in targets
                }
                for fut in as_completed(futs):
                    try:
                        res = fut.result()
                    except SandboxDetectedError:
                        raise
                    except _FastDispatchFailure:
                        files_skipped += 1
                        continue
                    except Exception as exc:
                        errors.append(str(exc))
                        continue
                    status = res["status"]
                    if status.startswith("skipped"):
                        files_skipped += 1
                    elif status in ("api-error", "malformed", "read-error"):
                        files_skipped += 1
                        if "error" in res:
                            errors.append(f"{res['file']}: {res['error']}")
                    else:
                        files_processed += 1

        context_tree_path: Path | None = None

        if not no_synthesis:
            topic_index = load_topic_index(vault)
            syn = _synthesize_context_tree(
                vault=vault,
                source_types=source_types,
                name_filter=name_filter,
                topic_index=topic_index,
                context_tree_target=context_tree_target,
                sonnet_model=SONNET_MODEL,
                synthesis_chunk_size=synthesis_chunk_size,
                synthesis_retry_budget=synthesis_retry_budget,
            )
            if syn["status"] == "ok":
                context_tree_path = syn["path"]
            elif syn["status"] in ("no-extractions", "all-failed"):
                pass  # Not an error — just nothing to synthesise.

        return ExtractResult(
            files_processed=files_processed,
            files_skipped=files_skipped,
            context_tree_path=context_tree_path,
            errors=tuple(errors),
        )
    finally:
        _active_vault_dir = None
        _active_sandbox_classifier = None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli_main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extract phase processor")
    ap.add_argument("vault", type=Path, help="Vault root directory")
    ap.add_argument("--since", help="Only process files with stem >= DATE")
    ap.add_argument("--force", action="store_true", help="Re-extract existing files")
    ap.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Parallel Haiku workers (default: spec config, else 5)",
    )
    ap.add_argument(
        "--no-synthesis", action="store_true", help="Skip Sonnet context tree"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Preview targets; no AI calls"
    )
    ap.add_argument("--source-type", help="Only one source type")
    ap.add_argument("--filter", dest="name_filter", help="Filename filter substring")
    args = ap.parse_args(argv)

    source_types = [args.source_type] if args.source_type else None
    try:
        result = extract(
            args.vault,
            since=args.since,
            force=args.force,
            dry_run=args.dry_run,
            no_synthesis=args.no_synthesis,
            source_types=source_types,
            name_filter=args.name_filter,
            workers=args.workers,
        )
    except SandboxDetectedError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Processed: {result.files_processed}")
    print(f"Skipped:   {result.files_skipped}")
    if result.context_tree_path:
        print(f"Context tree: {result.context_tree_path}")
    if result.errors:
        print(f"Errors ({len(result.errors)}):", file=sys.stderr)
        for e in result.errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
