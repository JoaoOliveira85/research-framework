"""Tier-2 static guard: no direct LLM dispatch inside the pipeline package.

Scan root (only paths scanned):
  ``src/research_framework/**/*.py``

Excluded from scan (never reported — per 018 contract):
  ``scripts/agent_call.py`` — outside scan root (canonical LLM dispatch)
  ``tests/**`` — outside scan root (fake agent substitution)

Two dispatch MODES are gated, because the framework ships two:

- **subprocess** — ``subprocess.run``/``Popen`` whose ``argv[0]`` is a shipped
  LLM binary (``claude``, ``codex``, ``cursor-agent``, ``opencode``, ``ollama``).
- **HTTP** — ``urlopen``/``Request``/``requests``/``httpx`` calls addressing a
  model-inference endpoint. ``ollama`` and every ``type: api`` executor reach
  their model this way and touch ``subprocess`` at no point, so a
  subprocess-only scan is blind to them *by construction*, not by omission.

The binary set is NOT declared here — it is derived from
``scripts/agent_call.py`` through ``tests._helpers.llm_dispatch``, which the
runtime interception guard reads too, so both guards agree on what an LLM
dispatch is and a newly shipped executor cannot silently un-guard itself.

Authority: ``specs/018-testing-strategy/contracts/llm-dispatch-guard.contract.md``
Allowlist: ``tests/_helpers/llm_dispatch_allowlist.yaml``
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tests._helpers.llm_dispatch import (
    is_inference_url,
    is_llm_binary,
    llm_binaries,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOT = _REPO_ROOT / "src" / "research_framework"
ALLOWLIST_PATH = Path(__file__).resolve().parent / "llm_dispatch_allowlist.yaml"

# Repo-relative paths under SCAN_ROOT that the contract excludes from gating.
_SCAN_SKIP_REL: frozenset[str] = frozenset()

_SUBPROCESS_ATTRS = frozenset({"run", "Popen"})

# Call names that put bytes on the wire (or build the request that will).
# ``Request`` is included because the shipped HTTP dispatch builds the URL
# there and hands an opaque object to ``urlopen`` — scanning only ``urlopen``
# would never see a URL at all.
_HTTP_CALL_NAMES = frozenset(
    {
        "urlopen",
        "Request",
        "get",
        "post",
        "put",
        "patch",
        "request",
        "stream",
        "send",
    }
)
# Only the verb-style names above are gated when they hang off one of these
# roots; ``urlopen``/``Request`` are gated wherever they appear.
_HTTP_CLIENT_ROOTS = frozenset({"requests", "httpx", "urllib", "session", "client"})


@dataclass(frozen=True)
class Violation:
    rel_path: str  # relative to SCAN_ROOT, e.g. pipeline/plan_narrator.py
    line: int
    snippet: str
    kind: str = "subprocess"  # "subprocess" | "http"


def _string_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _list_starts_with_llm(node: ast.AST) -> bool:
    if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
        return False
    first = _string_value(node.elts[0])
    return first is not None and is_llm_binary(first)


def _is_subprocess_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if not isinstance(func.value, ast.Name) or func.value.id != "subprocess":
        return False
    return func.attr in _SUBPROCESS_ATTRS


def _command_arg(node: ast.Call) -> ast.AST | None:
    if node.args:
        return node.args[0]
    for kw in node.keywords:
        if kw.arg == "args":
            return kw.value
    return None


def _collect_function_assignments(fn: ast.AST) -> dict[str, ast.List]:
    """Simple ``name = ["claude", ...]`` assignments in one function body."""
    locals_map: dict[str, ast.List] = {}
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and _list_starts_with_llm(node.value):
            locals_map[target.id] = node.value
    return locals_map


def _collect_name_bindings(scope: ast.AST) -> dict[str, ast.AST]:
    """Every simple ``name = <expr>`` binding in one scope.

    Wider than ``_collect_function_assignments`` on purpose: an inference URL
    is usually assembled (``url = base + "/v1/chat/completions"``) and handed
    to the request one statement later, so the guard has to be able to follow
    a plain name back to its value expression.
    """
    bindings: dict[str, ast.AST] = {}
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                bindings[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if isinstance(node.target, ast.Name):
                bindings[node.target.id] = node.value
    return bindings


def _literal_strings(
    node: ast.AST | None,
    bindings: dict[str, ast.AST],
    seen: frozenset[str] = frozenset(),
) -> list[str]:
    """Every string constant reachable from ``node``, following simple names.

    Returns FRAGMENTS, not URLs: the halves of a ``base + path`` concatenation
    and an f-string's literal chunks each come back on their own. That is why
    ``is_inference_url`` matches on substrings — ``"/v1/chat/completions"``
    alone is the tell, whichever half of the expression carries it.
    """
    if node is None:
        return []
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else []
    if isinstance(node, ast.Name):
        if node.id in seen:  # ``url = url + "…"`` — don't recurse forever.
            return []
        return _literal_strings(bindings.get(node.id), bindings, seen | {node.id})
    if isinstance(node, ast.JoinedStr):
        out: list[str] = []
        for value in node.values:
            out.extend(_literal_strings(value, bindings, seen))
        return out
    if isinstance(node, ast.FormattedValue):
        return _literal_strings(node.value, bindings, seen)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_strings(node.left, bindings, seen) + _literal_strings(
            node.right, bindings, seen
        )
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        out = []
        for elt in node.elts:
            out.extend(_literal_strings(elt, bindings, seen))
        return out
    if isinstance(node, ast.Call):
        # ``urlopen(Request(url))`` / ``Request(base + path)`` — the URL lives
        # one call deeper than the call that sends it.
        out = []
        for arg in node.args:
            out.extend(_literal_strings(arg, bindings, seen))
        for kw in node.keywords:
            out.extend(_literal_strings(kw.value, bindings, seen))
        return out
    return []


def _call_name_and_root(node: ast.Call) -> tuple[str, str]:
    """``(attribute-or-function name, leftmost root name)`` for a call."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id, func.id
    if isinstance(func, ast.Attribute):
        root: ast.AST = func.value
        while isinstance(root, (ast.Attribute, ast.Call, ast.Subscript)):
            root = root.value if not isinstance(root, ast.Call) else root.func
        root_name = root.id if isinstance(root, ast.Name) else ""
        return func.attr, root_name
    return "", ""


def _is_http_call(node: ast.Call) -> bool:
    """True when the call sends (or builds) an outbound HTTP request."""
    name, root = _call_name_and_root(node)
    if name in ("urlopen", "Request"):
        return True
    if name not in _HTTP_CALL_NAMES:
        return False
    return root.lower() in _HTTP_CLIENT_ROOTS


def _command_starts_with_llm(
    cmd_node: ast.AST,
    scope_assignments: dict[str, ast.List],
) -> bool:
    if _list_starts_with_llm(cmd_node):
        return True
    if isinstance(cmd_node, ast.Name):
        resolved = scope_assignments.get(cmd_node.id)
        return resolved is not None and _list_starts_with_llm(resolved)
    return False


def _snippet_for_call(node: ast.Call, source_lines: list[str]) -> str:
    line = node.lineno
    if 1 <= line <= len(source_lines):
        return source_lines[line - 1].strip()
    return "subprocess call"


def _violation_for_call(
    rel_path: str,
    call: ast.Call,
    lines: list[str],
    list_scope: dict[str, ast.List],
    name_scope: dict[str, ast.AST],
) -> Violation | None:
    """Classify one call as a subprocess LLM spawn, an inference POST, or clean."""
    if _is_subprocess_call(call):
        cmd = _command_arg(call)
        if cmd is not None and _command_starts_with_llm(cmd, list_scope):
            return Violation(
                rel_path=rel_path,
                line=call.lineno,
                snippet=_snippet_for_call(call, lines),
                kind="subprocess",
            )
        return None
    if _is_http_call(call):
        for fragment in _literal_strings(call, name_scope):
            if is_inference_url(fragment):
                return Violation(
                    rel_path=rel_path,
                    line=call.lineno,
                    snippet=_snippet_for_call(call, lines),
                    kind="http",
                )
    return None


def _violations_in_function(
    rel_path: str,
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    lines: list[str],
) -> list[Violation]:
    list_scope = _collect_function_assignments(fn)
    name_scope = _collect_name_bindings(fn)
    found: list[Violation] = []
    for child in ast.walk(fn):
        if not isinstance(child, ast.Call):
            continue
        hit = _violation_for_call(rel_path, child, lines, list_scope, name_scope)
        if hit is not None:
            found.append(hit)
    return found


def _violations_in_module(rel_path: str, source: str) -> list[Violation]:
    tree = ast.parse(source, filename=rel_path)
    lines = source.splitlines()
    found: list[Violation] = []
    module_scope = _collect_name_bindings(tree)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.extend(_violations_in_function(rel_path, node, lines))
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            hit = _violation_for_call(rel_path, child, lines, {}, module_scope)
            if hit is not None:
                found.append(hit)
    return found


def load_allowlist(path: Path = ALLOWLIST_PATH) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"allowlist must be a YAML list, got {type(data).__name__}")
    return data


def _is_allowlisted(violation: Violation, allowlist: list[dict[str, Any]]) -> bool:
    repo_path = f"src/research_framework/{violation.rel_path}".replace("\\", "/")
    for entry in allowlist:
        entry_file = str(entry.get("file", "")).replace("\\", "/")
        if entry_file != repo_path:
            continue
        line_range = entry.get("line_range")
        if (
            isinstance(line_range, list)
            and len(line_range) == 2
            and line_range[0] <= violation.line <= line_range[1]
        ):
            return True
    return False


def scan_for_violations(
    scan_root: Path,
    allowlist: list[dict[str, Any]],
) -> list[Violation]:
    violations: list[Violation] = []
    for py_file in sorted(scan_root.rglob("*.py")):
        rel = str(py_file.relative_to(scan_root)).replace("\\", "/")
        if rel in _SCAN_SKIP_REL:
            continue
        for v in _violations_in_module(rel, py_file.read_text(encoding="utf-8")):
            if not _is_allowlisted(v, allowlist):
                violations.append(v)
    return violations


def format_report(violations: list[Violation]) -> str:
    if not violations:
        return ""
    lines = ["LLM dispatch guard failed — direct LLM dispatch in production code:"]
    for v in sorted(violations, key=lambda x: (x.rel_path, x.line)):
        lines.append(f"  [{v.kind}] {v.rel_path}:{v.line}  {v.snippet}")
    lines.append(
        "Fix: route through scripts/agent_call.py, or add to ALLOWLIST with ROADMAP ref."
    )
    return "\n".join(lines)


def test_no_direct_llm_subprocess_in_pipeline_package() -> None:
    allowlist = load_allowlist()
    violations = scan_for_violations(SCAN_ROOT, allowlist)
    assert violations == [], format_report(violations)


def test_scan_root_is_not_vacuous() -> None:
    """Fail closed (#278): a moved/renamed/emptied SCAN_ROOT must not let
    the guard above pass by finding nothing to scan. `scan_for_violations`
    silently returns `[]` for a root with zero `.py` files under it — same
    shape as "on a branch with no code, this guard passes vacuously"."""
    scanned = list(SCAN_ROOT.rglob("*.py"))
    assert len(scanned) >= 50, (
        f"SCAN_ROOT ({SCAN_ROOT}) has only {len(scanned)} .py file(s) — "
        "expected at least 50 in the current package. A guard that finds "
        "nothing to scan is not the same thing as a guard that found "
        "nothing wrong."
    )


# --- Inline AST walker mini-suite ---


def test_ast_walker_clean_code_no_violations() -> None:
    source = """
import subprocess
def ok():
    subprocess.run(["echo", "hello"])
"""
    assert _violations_in_module("clean.py", source) == []


def test_ast_walker_inline_list_literal_one_violation() -> None:
    source = """
import subprocess
def bad():
    subprocess.run(["claude", "--print"])
"""
    hits = _violations_in_module("inline.py", source)
    assert len(hits) == 1
    assert hits[0].line == 4


def test_ast_walker_single_assigned_name_one_violation() -> None:
    source = """
import subprocess
def bad():
    args = ["claude", "--print"]
    subprocess.run(args)
"""
    hits = _violations_in_module("assigned.py", source)
    assert len(hits) == 1
    assert hits[0].line == 5


def test_cursor_agent_is_a_guarded_binary() -> None:
    """Spec 052: a stray ``cursor-agent`` subprocess in production code is a
    Principle-IV violation — it must route through scripts/agent_call.py."""
    assert "cursor-agent" in llm_binaries()
    source = """
import subprocess
def bad():
    subprocess.run(["cursor-agent", "-p"])
"""
    hits = _violations_in_module("cursor.py", source)
    assert len(hits) == 1
    assert hits[0].line == 4


def test_opencode_is_a_guarded_binary() -> None:
    """Spec 064: opencode is an ordinary CLI subprocess whose ``argv[0]`` is
    ``opencode`` — exactly the shape this guard detects. It shipped as the 4th
    first-class executor while the guard's hand-written list still stopped at
    cursor-agent (issue #292)."""
    assert "opencode" in llm_binaries()
    source = """
import subprocess
def bad():
    subprocess.run(["opencode", "run", "--format", "json"])
"""
    hits = _violations_in_module("opencode.py", source)
    assert len(hits) == 1
    assert hits[0].kind == "subprocess"


def test_absolute_binary_path_is_still_a_violation() -> None:
    """``CLAUDE_BIN``/``OPENCODE_BIN`` style absolute paths are the same
    dispatch; both guards basename ``argv[0]`` so neither can be evaded by
    spelling the binary with a directory in front of it."""
    source = """
import subprocess
def bad():
    subprocess.run(["/opt/homebrew/bin/opencode", "run"])
"""
    hits = _violations_in_module("abs.py", source)
    assert len(hits) == 1


def test_http_inference_call_is_a_violation() -> None:
    """Spec 047/064: ``ollama`` and every ``type: api`` executor are dispatched
    over HTTP and never spawn a subprocess, so a subprocess-only scan is blind
    to them by construction (issue #292)."""
    source = """
import urllib.request
def bad(payload):
    req = urllib.request.Request("http://127.0.0.1:11434/v1/chat/completions", data=payload)
    with urllib.request.urlopen(req) as resp:
        return resp.read()
"""
    hits = _violations_in_module("http_llm.py", source)
    assert hits, "an inference POST must be reported"
    assert all(h.kind == "http" for h in hits)


def test_http_inference_url_assembled_from_parts_is_a_violation() -> None:
    """The shipped dispatch builds ``{base_url}{api_path}`` before posting, so
    the guard follows a simple local binding and a ``+`` concatenation."""
    source = """
import requests
def bad(base):
    url = base + "/v1/chat/completions"
    return requests.post(url, json={})
"""
    hits = _violations_in_module("http_concat.py", source)
    assert len(hits) == 1
    assert hits[0].kind == "http"


def test_non_inference_http_is_not_a_violation() -> None:
    """The pipeline package legitimately fetches feeds and repo APIs (source
    collectors, preflight, refresh-sources). Only inference endpoints are
    LLM dispatch — a blanket outbound-HTTP ban would be noise, not a guard."""
    source = """
import urllib.request
def ok():
    req = urllib.request.Request("https://example.com/feed.rss")
    with urllib.request.urlopen(req) as resp:
        return resp.read()
"""
    assert _violations_in_module("feed.py", source) == []


def test_binary_set_is_derived_not_declared() -> None:
    """The guard must not re-declare the executor set; it reads the shipped one.

    A sixth executor added to ``agent_call._LLM_AGENT_NAMES`` is guarded the
    moment it ships, which is the whole point of issue #292's fix.
    """
    from tests._helpers.llm_dispatch import llm_agent_names

    assert llm_binaries() == llm_agent_names()
    assert {"claude", "codex", "cursor-agent", "ollama", "opencode"} <= llm_binaries()


def test_ast_walker_non_llm_subprocess_no_false_positive() -> None:
    source = """
import subprocess
def ok():
    subprocess.run(["echo", "hello"])
"""
    assert _violations_in_module("echo.py", source) == []


def test_allowlist_yaml_is_empty() -> None:
    """Principle IV invariant — allowlist MUST stay EMPTY pre- and post-migration."""
    assert load_allowlist() == []


def test_scan_root_excludes_contract_paths() -> None:
    """Boundary: agent_call and tests outside scan root; extract.py is gated."""
    assert not (_REPO_ROOT / "scripts" / "agent_call.py").is_relative_to(SCAN_ROOT)
    assert not (_REPO_ROOT / "tests").is_relative_to(SCAN_ROOT)
    extract_rel = "processors/extract.py"
    assert extract_rel not in _SCAN_SKIP_REL
    hits = [
        v
        for v in scan_for_violations(SCAN_ROOT, load_allowlist())
        if v.rel_path == extract_rel
    ]
    assert hits == []
