"""spec-019 / 0.2.31 \u2014 verifier MUST extract JSON from non-strict agent responses.

Background \u2014 user trial-run audit 2026-05-18:

The user's reference-vault-0.2.30 ran 6 cycles to completion, produced 68
substantive notes, but the orchestrator reported \"65 stub notes\" and
the stub-free-exit rule fired on every cycle. Forensics showed:

- Every single verifier verdict across all 6 cycles had `status: pending`,
  `violations: []`, `suggested_fix: null` \u2014 the canonical \"I gave up\"
  shape.
- `verifier.py::_call_verifier` falls back to `pending` whenever
  `json.loads(raw)` fails on the agent's output, with no error logged.
- The verifier skill (`.agents/skills/verifier/SKILL.md`) tells the agent
  to emit `{verdict, violations, suggested_fix}` JSON, but codex doesn't
  auto-load `SKILL.md` like Claude Code does.
- The verifier prompt sent to `agent_call.py` is the BARE note content
  (`note_file.read_text()`) \u2014 no explicit instruction telling codex to
  produce JSON. The agent's natural response is a narrative summary,
  which fails `json.loads` \u2192 silent `pending` fallback.

Result: 65 perfectly fine notes (~520 words, sourced, structured) were
classified as stubs purely because the verifier never stamped them. The
\"stub-free exit\" rule \u2014 a core Principle VIII guarantee \u2014 became
permanently broken on codex runtimes.

0.2.31 fixes this with two complementary changes:

1. `_extract_json_blob(text)` \u2014 tolerant JSON extraction. Tries strict
   parse first, then code-fenced JSON (` ```json `), then any code
   fence, then the first balanced-braces block in the text. Returns the
   parsed dict or None.

2. Explicit verifier prompt wrapper \u2014 prepends a short instruction
   block to the note content telling the agent to verify per the
   verifier skill and respond ONLY with the JSON schema. Reinforces
   SKILL.md for runtimes that don't auto-load it.

These tests lock the contract for (1). Integration tests for the
wrapped prompt and end-to-end parse-then-stamp flow live in
`test_verifier_integration.py` (separate file because they need fake
subprocess scaffolding).
"""

from __future__ import annotations


def _import_extract_helper():
    """Defer import so the test can run after the helper is added to verifier.py."""
    from research_framework.pipeline.verifier import _extract_json_blob

    return _extract_json_blob


# ---- strict-parse cases ----------------------------------------------------


def test_strict_clean_json_returns_dict() -> None:
    """The cheap path: agent followed the schema exactly."""
    extract = _import_extract_helper()
    raw = '{"verdict": "accept", "violations": [], "suggested_fix": null}'
    result = extract(raw)
    assert result == {
        "verdict": "accept",
        "violations": [],
        "suggested_fix": None,
    }


def test_strict_json_with_surrounding_whitespace_returns_dict() -> None:
    """Pure JSON with leading/trailing whitespace is still strict-parseable.

    Common when the runtime appends a trailing newline.
    """
    extract = _import_extract_helper()
    raw = '\n\n   {"verdict": "reject", "violations": [{"rule_id": "X"}]}   \n'
    result = extract(raw)
    assert result["verdict"] == "reject"
    assert result["violations"][0]["rule_id"] == "X"


# ---- code-fenced cases (most common codex shape) --------------------------


def test_json_inside_json_codefence_returns_dict() -> None:
    """The codex / GPT-4-class common case: ```json ... ```.

    Agents trained on markdown conventionally wrap JSON in a fenced
    block. Strict parse fails on the fence; we must extract.
    """
    extract = _import_extract_helper()
    raw = (
        "Here's my verdict:\n\n"
        "```json\n"
        '{"verdict": "accept", "violations": []}\n'
        "```\n\n"
        "Let me know if you need anything else."
    )
    result = extract(raw)
    assert result == {"verdict": "accept", "violations": []}


def test_json_inside_bare_codefence_returns_dict() -> None:
    """Less common but valid: ``` without a language tag."""
    extract = _import_extract_helper()
    raw = '```\n{"verdict": "reject", "violations": [{"rule_id": "Y"}]}\n```'
    result = extract(raw)
    assert result["verdict"] == "reject"


def test_first_codefence_wins_when_multiple_present() -> None:
    """When the agent provides multiple JSON blocks (e.g. a draft + final),
    the FIRST valid one wins.

    Choosing first-valid is deterministic and matches how a human reader
    would scan the response top-to-bottom.
    """
    extract = _import_extract_helper()
    raw = (
        "First attempt:\n"
        "```json\n"
        '{"verdict": "accept", "violations": []}\n'
        "```\n\n"
        "Actually let me reconsider:\n"
        "```json\n"
        '{"verdict": "reject", "violations": [{"rule_id": "X"}]}\n'
        "```\n"
    )
    result = extract(raw)
    assert result["verdict"] == "accept"


# ---- narrative-wrapped cases (no codefence) --------------------------------


def test_json_embedded_in_narrative_returns_dict() -> None:
    """Agent narrates around bare JSON, no code fence.

    Less common than the fenced case but defensive parsing must handle
    it \u2014 otherwise narrative agents drop to `pending` silently.
    """
    extract = _import_extract_helper()
    raw = (
        "The note looks reasonable. My verdict is: "
        '{"verdict": "accept", "violations": [], "suggested_fix": null} '
        "and I have no further suggestions."
    )
    result = extract(raw)
    assert result == {
        "verdict": "accept",
        "violations": [],
        "suggested_fix": None,
    }


def test_nested_json_braces_handled_correctly() -> None:
    """JSON with nested objects must extract intact, not stop at the
    first inner `}`.

    A naive `text.find('{')..text.find('}')` would truncate at the
    first inner closing brace. Balanced-braces tracking required.
    """
    extract = _import_extract_helper()
    raw = (
        "Response:\n"
        '{"verdict": "reject", "violations": [{"rule_id": "X", "location": "L"}], '
        '"suggested_fix": null}'
    )
    result = extract(raw)
    assert result["verdict"] == "reject"
    assert result["violations"][0]["location"] == "L"


# ---- failure cases (must return None, not throw) ---------------------------


def test_pure_narrative_no_json_returns_none() -> None:
    """When the agent responds with text-only narrative, return None so
    the caller can default to `pending` deliberately.

    Must NOT raise: a JSON-parse-failure path inside the verifier was
    one of the silent-failure modes in 0.2.30.
    """
    extract = _import_extract_helper()
    raw = (
        "I reviewed the note and it looks fine. The content is well-organized "
        "and cites appropriate sources. No further action needed."
    )
    result = extract(raw)
    assert result is None


def test_malformed_json_falls_through_to_none() -> None:
    """Agent produces JSON-looking text that doesn't actually parse.

    Must not throw. None lets the caller default to `pending`.
    """
    extract = _import_extract_helper()
    raw = "```json\n{verdict: accept, violations: }\n```"  # missing quotes + bad list
    result = extract(raw)
    assert result is None


def test_empty_string_returns_none() -> None:
    """Edge case: agent produced no output at all."""
    extract = _import_extract_helper()
    assert extract("") is None


def test_only_whitespace_returns_none() -> None:
    """Edge case: agent produced only whitespace."""
    extract = _import_extract_helper()
    assert extract("   \n\n\t  \n") is None


# ---- mixed cases that exercise the fallback chain --------------------------


def test_invalid_codefence_then_valid_inline_extracts_inline() -> None:
    """Codefence has malformed JSON but later there's valid inline JSON.

    The extractor should try the codefence, recognise it's malformed,
    and continue to the next strategy rather than returning None on the
    first failed codefence.
    """
    extract = _import_extract_helper()
    raw = (
        "```json\n"
        "{verdict: bad}\n"  # malformed
        "```\n\n"
        'Actual verdict: {"verdict": "accept", "violations": []}'
    )
    result = extract(raw)
    assert result["verdict"] == "accept"


def test_array_at_top_level_returns_none() -> None:
    """The verifier contract expects an OBJECT (`{...}`). If the agent
    returns a top-level array, treat it as malformed and let the caller
    fall back to `pending` \u2014 the schema mismatch is informative.

    This guards against an agent that lists violations directly without
    the surrounding object.
    """
    extract = _import_extract_helper()
    raw = '[{"rule_id": "X"}, {"rule_id": "Y"}]'
    result = extract(raw)
    assert result is None
