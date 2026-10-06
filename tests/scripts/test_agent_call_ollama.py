"""Spec 047 v1 — Ollama HTTP/API runtime (the first non-CLI backend).

Hermetic: we NEVER make a real network call. In-process tests patch
``_http_post_json`` with a canned response; one test exercises the
``OLLAMA_HTTP_FIXTURE`` file seam (the override the subprocess/CLI path uses).

Cost provenance for a LOCAL runtime: ``cost_usd: 0.0`` is the TRUE cost (not an
estimate) and the API returns REAL token counts, so ``cost_source: runtime``
(both measured) — distinct from cursor's ``runtime_tokens`` (estimated dollar).

Module-level functions (no classes) so the foreman Arm A verifier can collect
them by ``path::function`` node id (docs/foreman.md grammar).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "agent_call.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("agent_call", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_call"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def agent_call():
    return _load_module()


def _make_ollama_vault(tmp_path: Path, model: str = "gemma3:27b") -> Path:
    vault = tmp_path / "vault-ollama"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "pipeline:\n"
        "  max_cycles: 20\n"
        "  budget_usd: 50\n"
        "communication:\n"
        "  mode: http\n"
        "default_executor:\n"
        "  type: api\n"
        "  runtime: ollama\n"
        "  base_url: http://test.local:11434\n"
        f"  model: {model}\n"
        "stages:\n"
        "  plan_narrator:\n"
        f"    model: {model}\n",
        encoding="utf-8",
    )
    return vault


def _cycle_dir(vault: Path, cycle: int = 2) -> Path:
    d = vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _openai_response(
    text: str = "hi from ollama", tin: int = 12, tout: int = 5
) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": tin, "completion_tokens": tout},
    }


def _native_response(text: str = "native reply", tin: int = 8, tout: int = 4) -> dict:
    return {
        "message": {"role": "assistant", "content": text},
        "prompt_eval_count": tin,
        "eval_count": tout,
    }


# ---------------------------------------------------------------------------
# Detection + endpoint + parser (pure functions)
# ---------------------------------------------------------------------------


def test_is_http_executor_detection(agent_call) -> None:
    assert agent_call._is_http_executor({"type": "api", "runtime": "ollama"}) is True
    # runtime name alone (no explicit type) still routes HTTP
    assert agent_call._is_http_executor({"runtime": "ollama"}) is True
    # CLI runtimes and script type are NOT http
    assert agent_call._is_http_executor({"type": "cli", "runtime": "claude"}) is False
    assert (
        agent_call._is_http_executor({"type": "script", "runtime": "ollama"}) is False
    )
    assert agent_call._is_http_executor({"runtime": "codex"}) is False


def test_ollama_in_llm_agent_names(agent_call) -> None:
    assert "ollama" in agent_call._LLM_AGENT_NAMES
    assert "ollama" in agent_call._HTTP_RUNTIMES
    # ollama must NOT be a streaming or flat-rate runtime
    assert "ollama" not in agent_call._STREAMING_AGENTS
    assert "ollama" not in agent_call._FLAT_RATE_AGENTS


def test_http_endpoint_default_and_overrides(agent_call) -> None:
    base = {"base_url": "http://h:11434"}
    assert agent_call._http_endpoint(base) == "http://h:11434/v1/chat/completions"
    # trailing slash on base + custom native path
    native = {"base_url": "http://h:11434/", "api_path": "/api/chat"}
    assert agent_call._http_endpoint(native) == "http://h:11434/api/chat"
    # OLLAMA_BASE_URL env wins when base_url is absent
    with patch.dict("os.environ", {"OLLAMA_BASE_URL": "http://env:1"}):
        assert agent_call._http_endpoint({}) == "http://env:1/v1/chat/completions"


def test_parse_http_response_openai_shape(agent_call) -> None:
    text, tin, tout = agent_call._parse_http_response(_openai_response("abc", 9, 3))
    assert text == "abc"
    assert (tin, tout) == (9, 3)


def test_parse_http_response_ollama_native_shape(agent_call) -> None:
    text, tin, tout = agent_call._parse_http_response(_native_response("xyz", 7, 2))
    assert text == "xyz"
    assert (tin, tout) == (7, 2)


def test_http_post_json_fixture_seam(agent_call, tmp_path: Path) -> None:
    """OLLAMA_HTTP_FIXTURE returns the file verbatim with NO network call."""
    fix = tmp_path / "resp.json"
    fix.write_text(json.dumps(_openai_response("fixtured", 1, 1)), encoding="utf-8")
    with patch.dict("os.environ", {"OLLAMA_HTTP_FIXTURE": str(fix)}):
        obj = agent_call._http_post_json("http://unused/x", {"k": "v"}, timeout=5)
    assert obj["choices"][0]["message"]["content"] == "fixtured"


# ---------------------------------------------------------------------------
# dispatch() — the programmatic path
# ---------------------------------------------------------------------------


def test_dispatch_ollama_returns_text_and_real_tokens(agent_call, tmp_path) -> None:
    vault = _make_ollama_vault(tmp_path)
    cycle_dir = _cycle_dir(vault)
    with patch.object(
        agent_call, "_http_post_json", return_value=_openai_response("answer", 30, 11)
    ):
        result = agent_call.dispatch(
            "plan_narrator", "question", vault_dir=vault, cycle_dir=cycle_dir
        )
    assert result.exit_code == 0
    assert "answer" in result.stdout
    assert result.tokens_in == 30 and result.tokens_out == 11
    assert result.cost_usd == 0.0


def test_dispatch_ollama_sidecar_cost_source_runtime(agent_call, tmp_path) -> None:
    vault = _make_ollama_vault(tmp_path)
    cycle_dir = _cycle_dir(vault)
    with patch.object(
        agent_call, "_http_post_json", return_value=_openai_response("a", 100, 40)
    ):
        agent_call.dispatch("plan_narrator", "q", vault_dir=vault, cycle_dir=cycle_dir)
    data = json.loads((cycle_dir / "agent-calls" / "plan_narrator.json").read_text())
    assert data["agent"] == "ollama"
    assert data["agent_kind"] == "real"
    # local ⇒ TRUE $0 with REAL tokens ⇒ cost_source runtime (both measured)
    assert data["cost_source"] == "runtime"
    assert data["cost_usd"] == 0.0
    assert data["tokens_in"] == 100 and data["tokens_out"] == 40
    assert data["status"] == "ok"


def test_dispatch_ollama_http_error_is_failed(agent_call, tmp_path) -> None:
    vault = _make_ollama_vault(tmp_path)
    cycle_dir = _cycle_dir(vault)
    with patch.object(
        agent_call, "_http_post_json", side_effect=OSError("connection refused")
    ):
        result = agent_call.dispatch(
            "plan_narrator", "q", vault_dir=vault, cycle_dir=cycle_dir
        )
    assert result.exit_code == 2
    assert "failed" in result.stderr
    data = json.loads((cycle_dir / "agent-calls" / "plan_narrator.json").read_text())
    assert data["agent"] == "ollama"
    assert data["status"] == "failed"
    assert data["cost_usd"] == 0.0


def test_dispatch_ollama_native_endpoint_shape(agent_call, tmp_path) -> None:
    vault = _make_ollama_vault(tmp_path)
    cycle_dir = _cycle_dir(vault)
    with patch.object(
        agent_call, "_http_post_json", return_value=_native_response("ndjson", 6, 2)
    ):
        result = agent_call.dispatch(
            "plan_narrator", "q", vault_dir=vault, cycle_dir=cycle_dir
        )
    assert "ndjson" in result.stdout
    assert result.tokens_in == 6 and result.tokens_out == 2


# ---------------------------------------------------------------------------
# run() — the CLI path used by the cycle runner
# ---------------------------------------------------------------------------


def test_run_ollama_writes_sidecar_and_output(agent_call, tmp_path) -> None:
    vault = _make_ollama_vault(tmp_path)
    cost_sidecar = _cycle_dir(vault) / "agent-calls" / "plan_narrator.json"
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text("write", encoding="utf-8")
    output_file = tmp_path / "out.txt"
    with patch.object(
        agent_call, "_http_post_json", return_value=_openai_response("doc body", 22, 9)
    ):
        rc = agent_call.run(
            vault,
            "plan_narrator",
            prompt_file,
            cost_sidecar=cost_sidecar,
            output_file=output_file,
        )
    assert rc == 0
    assert output_file.read_text(encoding="utf-8").strip() == "doc body"
    data = json.loads(cost_sidecar.read_text(encoding="utf-8"))
    assert data["agent"] == "ollama"
    assert data["cost_source"] == "runtime"
    assert data["cost_usd"] == 0.0
    assert data["tokens_in"] == 22 and data["tokens_out"] == 9


def test_run_ollama_never_builds_cli_command(agent_call, tmp_path) -> None:
    """ollama must not reach _build_command (it has no CLI adapter) — the HTTP
    branch handles it first. _build_command would raise 'unknown runtime'."""
    vault = _make_ollama_vault(tmp_path)
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text("x", encoding="utf-8")
    with (
        patch.object(
            agent_call, "_http_post_json", return_value=_openai_response("ok", 1, 1)
        ),
        patch.object(
            agent_call,
            "_build_command",
            side_effect=AssertionError("must not build CLI"),
        ),
    ):
        rc = agent_call.run(vault, "plan_narrator", prompt_file)
    assert rc == 0


def test_run_ollama_sidecar_is_real_with_wall_clock(agent_call, tmp_path) -> None:
    """Pre-rc5 fix: the run() HTTP path is a genuine network dispatch, so the
    sidecar must report agent_kind 'real', real wall-clock timestamps (NOT the
    deterministic 2000-01-01 sentinels), and a measured latency_ms field."""
    vault = _make_ollama_vault(tmp_path)
    cost_sidecar = _cycle_dir(vault) / "agent-calls" / "plan_narrator.json"
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text("write", encoding="utf-8")
    with patch.object(
        agent_call, "_http_post_json", return_value=_openai_response("body", 5, 3)
    ):
        rc = agent_call.run(
            vault, "plan_narrator", prompt_file, cost_sidecar=cost_sidecar
        )
    assert rc == 0
    data = json.loads(cost_sidecar.read_text(encoding="utf-8"))
    assert data["agent_kind"] == "real"
    sentinel_start, sentinel_end = agent_call._DETERMINISTIC_SIDECAR_TIMESTAMPS
    assert data["started_at"] != sentinel_start
    assert data["completed_at"] != sentinel_end
    assert isinstance(data["latency_ms"], int) and data["latency_ms"] >= 0


def test_run_ollama_stays_real_even_with_fake_shim(agent_call, tmp_path) -> None:
    """A vault carrying the fake-agent shim must NOT downgrade a real HTTP
    dispatch to agent_kind 'fake' — the shim heuristic is irrelevant once we
    are in the HTTP code path (which the fake shim does not even contain)."""
    vault = _make_ollama_vault(tmp_path)
    shim = vault / "scripts" / "agent_call.py"
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text("from tests._helpers import fake_agent  # noqa\n", encoding="utf-8")
    cost_sidecar = _cycle_dir(vault) / "agent-calls" / "plan_narrator.json"
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text("write", encoding="utf-8")
    with patch.object(
        agent_call, "_http_post_json", return_value=_openai_response("body", 5, 3)
    ):
        rc = agent_call.run(
            vault, "plan_narrator", prompt_file, cost_sidecar=cost_sidecar
        )
    assert rc == 0
    data = json.loads(cost_sidecar.read_text(encoding="utf-8"))
    assert data["agent_kind"] == "real"
