"""Stub modules with controllable extractor behaviour (spec 020)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

# spec 051 FR4: every manifest now needs a preflight block. Build sites splat
# this into their manifest dict; write_fake_extractor drops the matching
# preflight.py so parse_manifest's entry_point-exists check passes.
FAKE_PREFLIGHT_BLOCK: dict[str, Any] = {
    "entry_point": "preflight.py",
    "timeout_seconds": 30,
}


def write_fake_preflight(module_dir: Path) -> Path:
    """Write a minimal valid preflight.py (always emits a success
    PreflightResult). Mirrors the subprocess contract (spec 051 FR4)."""
    module_dir.mkdir(parents=True, exist_ok=True)
    script = module_dir / "preflight.py"
    script.write_text(
        textwrap.dedent(
            """
            import json, sys
            def main():
                cmd = sys.argv[1] if len(sys.argv) > 1 else "preflight"
                sys.stdin.read()
                verdict = "success" if cmd == "preflight" else "fatal_fail"
                print(json.dumps({"schema_version": "1.0", "verdict": verdict,
                                  "corrections": [], "messages": []}))
            if __name__ == "__main__":
                main()
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return script


def write_fake_extractor(
    module_dir: Path,
    *,
    stdout_payload: dict[str, Any] | None = None,
    fail_attempts: set[int] | None = None,
) -> Path:
    """Write a minimal extractor.py that emits JSON or fails on attempt N."""
    module_dir.mkdir(parents=True, exist_ok=True)
    payload = stdout_payload or {
        "module": module_dir.name,
        "source_id": "stub",
        "source_version": "v1",
        "bridge_version": "0.3.2",
        "extracted_at": "2026-01-01T00:00:00Z",
        "verdict": "ok",
        "truncated": False,
        "partial": False,
        "facts": {},
        "notable": [],
    }
    fail_on = sorted(fail_attempts or [])
    script = module_dir / "extractor.py"
    counter = module_dir / ".attempt-counter"
    script.write_text(
        textwrap.dedent(
            f"""
            import json, sys
            from pathlib import Path
            _FAIL = {fail_on!r}
            _PAYLOAD = {repr(payload)}
            _COUNTER = Path({str(counter)!r})
            def _git_head(source):
                import subprocess
                from pathlib import Path
                path = (source or {{}}).get("path") or (source or {{}}).get("url") or ""
                fallback = _PAYLOAD.get("source_version", "v1")
                if not path:
                    return fallback
                proc = subprocess.run(
                    ["git", "-C", str(Path(path)), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                )
                return proc.stdout.strip() if proc.returncode == 0 else fallback

            def main():
                cmd = sys.argv[1] if len(sys.argv) > 1 else "extract"
                key = f"{{cmd}}"
                counts = {{}}
                if _COUNTER.is_file():
                    counts = json.loads(_COUNTER.read_text())
                n = counts.get(key, 0) + 1
                counts[key] = n
                _COUNTER.write_text(json.dumps(counts))
                if n in _FAIL:
                    raise RuntimeError(f"injected failure attempt {{n}}")
                payload = dict(_PAYLOAD)
                stdin = json.loads(sys.stdin.read() or "{{}}")
                source = stdin.get("source") or {{}}
                version = _git_head(source)
                if cmd == "get_source_version":
                    print(json.dumps({{"source_version": version}}))
                else:
                    payload["source_version"] = version
                    print(json.dumps(payload))
            if __name__ == "__main__":
                main()
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    write_fake_preflight(module_dir)
    return script


def isolated_call_attempt_counter() -> dict[str, int]:
    return {}
