# Spec 012 — Multi-Vault Pipeline

**Status**: superseded(by spec 023)

> **🗄️ SUBSUMED BY spec 023 (2026-05-22).** Spec 023 (Flow Separation
> + ./vault refactor + local module integration) is the active home
> for this scope — it folds 010 + 012 together with the 2026-05-20
> triage's headless-/ask-/write + active-sources.json items. Do NOT
> plan against 012 directly; open `specs/023-flow-separation/spec.md`
> instead. This file is kept as a design-history reference.
>
> **Vision spec.** This is a design-intent document, not an implementation
> plan. Do not start implementation until a tasks.md is written with full detail.

## Problem Statement

The current design is 1:1: one orchestrator, one vault. The user already has
multiple vaults created with different versions of this pipeline. As the
number of vaults grows, running them independently becomes operationally
expensive:

- Each vault runs its own budget tracking with no aggregate view
- Source discoveries in one vault are invisible to others, even when scopes
  overlap (e.g. two product vaults that both benefit from the same
  Kafka topic documentation)
- Scheduling research across multiple vaults requires N separate `systemd`
  timers with no coordination
- No single place to see "which vault is healthiest, which needs work"

## Proposed Solution

A **vault registry** — a simple JSON file listing all vaults the pipeline
manages — and a refactored orchestrator that can operate on a list of
`VaultHandle` objects rather than a single vault path.

The vault binary (`./vault`) and the research-vault CLI remain per-vault
entry points. The registry enables an optional engine-level view for users
who want cross-vault coordination.

### Key architectural change

`orchestrator.py` currently takes `vault_dir: Path`. The change: introduce
`VaultHandle` as a thin wrapper that carries the vault path, its parsed spec,
and its `sources.db` connection. The orchestrator works identically for a
single vault (backwards compatible) but can also iterate a list.

```python
@dataclass
class VaultHandle:
    vault_dir: Path
    spec: SpecConfig
    # sources.db connection deferred — opened on first use

def run_cycles(handle: VaultHandle, ...) -> int  # unchanged interface
def run_all(handles: list[VaultHandle], ...) -> dict[str, int]  # new
```

### Vault registry (`~/.config/research-vault/vaults.json`)

```json
{
  "vaults": [
    {
      "name": "codebase-vault",
      "path": "/Users/me/Documents/codebase-vault",
      "spec": "/Users/me/Documents/codebase-vault/settings.yaml",
      "last_cycle": 12,
      "last_run": "2026-05-12T14:00:00Z",
      "status": "active"
    }
  ]
}
```

Managed by `research-vault vault register/unregister/list` subcommands.
The registry is user-level, not vault-level — it lives in `~/.config/`, not
inside any vault. Vaults remain independently portable.

### Budget pooling (opt-in)

A `budget_pool` entry in the registry aggregates spend across all registered
vaults:

```json
"budget_pool": {
  "monthly_cap_usd": 200.0,
  "current_month_usd": 47.30,
  "resets_on": "2026-06-01"
}
```

Individual vault budget caps still apply (per-vault floor). The pool cap is
an additional ceiling.

### Cross-vault source sharing (opt-in per vault)

When `spec.source_sharing: true`, the vault participates in the cross-vault
source pool. `source_manager.py` writes a summary of its active sources to
a shared location; other vaults can query it before deciding whether to add
a new discovered source.

This is a read-only query — vaults never write into each other's `sources.db`.
The shared summary is a JSON file per vault in `~/.config/research-vault/sources/`.

### Engine CLI (`research-vault engine`)

New top-level subcommand for engine-level operations:

```
research-vault engine status       # show all registered vaults + health
research-vault engine run-all      # run one cycle on each active vault
research-vault engine audit-all    # run vault_audit.py on each vault
research-vault engine budget       # show aggregate spend
```

## Non-Goals

- Vaults sharing `data_vault/` content — vaults remain independent data
  stores; only sources are shared, never notes
- A centralised database of notes across vaults — that's a different product
- Real-time sync between vaults — async, cycle-based coordination only
- Automatic vault discovery — users register vaults explicitly

## Constraints to Preserve Until This Ships

**The most important constraint:** all vault state lives under the vault root.
Nothing that the vault needs to function should live outside its directory
tree. The registry is an optional convenience layer — a vault must work
perfectly if the registry doesn't exist.

Other constraints:
- `spec-parse.json` is self-contained; the engine reads it fresh each run
- `sources.db` remains per-vault; cross-vault source data is a read-only
  summary, not a shared write target
- `VaultHandle` must be a drop-in for `vault_dir: Path` at all current
  call sites — no breaking change to the existing single-vault flow

## Provisional Acceptance Criteria

1. `research-vault vault register ~/Documents/codebase-vault` adds the vault
   to the registry and `research-vault engine status` shows it
2. `research-vault engine run-all` runs one research cycle on each registered
   active vault, respecting per-vault and pool budget caps
3. A vault not in the registry continues to work identically via `./vault`
4. Cross-vault source sharing: if vault A has `source_sharing: true` and
   discovers `source X`, vault B can query the shared summary and see X as
   a candidate source
5. Budget pool: when the pool cap is reached, `run-all` stops scheduling
   new cycles and logs a clear message
6. Removing a vault from the registry does not modify the vault directory

## Open Questions (resolve before implementation)

1. **Registry location**: `~/.config/research-vault/` vs a user-specified
   path. XDG-compatible location preferred for Linux.
2. **Scheduling**: does `run-all` run vaults sequentially or in parallel?
   Sequential is safer for budget tracking; parallel is faster. Setting?
3. **Cross-vault source conflicts**: if vault A and B both discover the same
   source URL under different names, how is the dedup handled?
