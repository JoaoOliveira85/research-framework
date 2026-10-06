from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..spec.schema import SpecValidationError
from ..spec.simple import load as load_spec


def _cmd_inventory(args: argparse.Namespace) -> int:
    from ..cli_inventory import build_inventory, format_json, format_text

    vault_root = args.vault_path.resolve()

    try:
        inv = build_inventory(vault_root)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    fmt = args.format
    if fmt is None:
        fmt = "text" if sys.stdout.isatty() else "json"

    output = format_text(inv) if fmt == "text" else format_json(inv)

    if args.out:
        args.out.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)

    return 0


def _cmd_onboard(args: argparse.Namespace) -> int:
    from ..onboard import run_onboard

    return run_onboard(
        args.vault_path,
        draft_only=args.draft_only,
        no_git=args.no_git,
    )


def _cmd_prune(args: argparse.Namespace) -> int:
    from ..prune import prune_vault

    vault_root = args.vault_path.resolve()
    try:
        result = prune_vault(
            vault_root,
            keep=args.keep,
            yes=args.yes,
            force=args.force,
        )
        # Spec 077 D4/T003: `prune` returned 0 and `regenerate-agents` returned
        # 1 for the identical interaction — the operator answering "no" to a
        # confirmation. They agree on 1 now: nothing was done, so a caller that
        # reads 0 as "pruned" would be wrong, and 1 is the model's "this unit of
        # work is over, move on" (FR-012). It is not an error and nothing is
        # written to stderr.
        return 1 if getattr(result, "declined", False) else 0
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 2


def _cmd_parse_spec(args: argparse.Namespace) -> int:
    """Parse a research-framework spec file and rewrite _pipeline/spec-parse.json.

    Supports the recovery flow when a vault's spec-parse.json is missing or
    has drifted from the spec format the framework expects (e.g., after a
    framework upgrade, or after the migrator catastrophically clobbered it).
    """

    vault_root: Path = args.vault_path.resolve()
    if not vault_root.exists() or not vault_root.is_dir():
        print(f"error: not a directory: {vault_root}", file=sys.stderr)
        return 2
    if not (vault_root / "data_vault").exists():
        print(
            f"error: not a vault (no data_vault/ directory): {vault_root}",
            file=sys.stderr,
        )
        return 2

    if args.spec_path is not None:
        spec_path = args.spec_path.resolve()
    else:
        # Probe common locations. First match wins.
        candidates = [
            vault_root / f"{vault_root.name}-spec.md",
            vault_root / "research.spec.md",
        ]
        spec_path = next((p for p in candidates if p.exists()), None)
        if spec_path is None:
            print(
                f"error: no spec file found. Tried: "
                f"{', '.join(str(p.relative_to(vault_root)) for p in candidates)}.\n"
                f"Pass the spec path as the second argument.",
                file=sys.stderr,
            )
            return 2

    if not spec_path.exists():
        print(f"error: spec file not found: {spec_path}", file=sys.stderr)
        return 2

    try:
        spec = load_spec(spec_path, location=vault_root)
    except SpecValidationError as exc:
        print(f"error: spec failed validation:\n  {exc}", file=sys.stderr)
        return 2

    out = vault_root / "_pipeline" / "spec-parse.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(spec.to_dict(), indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out}")
    print(f"  name: {spec.name}")
    print(f"  owner: {spec.owner}")
    print(f"  note_types: {len(spec.note_types)}")
    print(f"  data_sources: {len(spec.data_sources)}")
    return 0


def _cmd_regenerate_agents(args: argparse.Namespace) -> int:
    """Overwrite agent-definition files in a vault from framework templates."""
    import json as _json

    from ..agents import AGENT_NAMES, write_agents

    vault_root = args.vault_path.resolve()
    if not vault_root.exists() or not vault_root.is_dir():
        print(f"error: not a directory: {vault_root}", file=sys.stderr)
        return 2

    spec_parse = vault_root / "_pipeline" / "spec-parse.json"
    if not spec_parse.exists():
        print(f"error: spec-parse.json not found: {spec_parse}", file=sys.stderr)
        return 2

    try:
        spec_dict = _json.loads(spec_parse.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: could not read spec-parse.json: {exc}", file=sys.stderr)
        return 2

    # Validate requested agent names.
    requested: list[str] = args.agent or list(AGENT_NAMES)
    unknown = [n for n in requested if n not in AGENT_NAMES]
    if unknown:
        print(
            f"error: unknown agent name(s): {', '.join(unknown)}. "
            f"Known: {', '.join(AGENT_NAMES)}",
            file=sys.stderr,
        )
        return 2

    commands_dir = vault_root / ".claude" / "commands"
    for name in requested:
        print(
            f"[regenerate-agents] would overwrite {commands_dir.relative_to(vault_root)}/{name}.md"
        )

    if not args.force:
        try:
            answer = input("Continue? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("[regenerate-agents] aborted")
            return 1

    # Load spec as a SimpleNamespace-compatible object by using the real loader.
    try:
        from ..spec.simple import load as _load_spec

        spec = _load_spec(
            (
                vault_root / "research.spec.md"
                if (vault_root / "research.spec.md").exists()
                else vault_root / f"{vault_root.name}-spec.md"
            ),
            location=vault_root,
        )
    except Exception:
        # Fallback: use a lightweight dict-to-namespace shim from spec-parse.json.
        import types

        def _ns(d: object) -> object:
            if isinstance(d, dict):
                return types.SimpleNamespace(**{k: _ns(v) for k, v in d.items()})
            if isinstance(d, list):
                return [_ns(i) for i in d]
            return d

        spec = _ns(spec_dict)

    try:
        written = write_agents(vault_root, spec, only=requested, overwrite=True)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"wrote {len(written)} files")
    return 0


def _cmd_reindex(args: argparse.Namespace) -> int:
    try:
        from ..vault.indexer import rebuild
    except ImportError:
        print("indexer not available in this build", file=sys.stderr)
        return 2
    # The indexer creates the corpus folder it indexes (parents included), so
    # a mistyped --vault would otherwise become a fresh vault, reported as 0.
    if not args.vault.is_dir():
        print(f"ERROR: vault directory not found: {args.vault}", file=sys.stderr)
        return 2
    rebuild(args.vault)
    return 0
