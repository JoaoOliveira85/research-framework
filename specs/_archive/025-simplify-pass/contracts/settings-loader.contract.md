# Contract: `pipeline.settings` Canonical Settings Loader (B7)

**Owner**: Spec 025 US9 B7.
**Status**: pinned at spec 025 plan time (2026-05-21).

Pins the canonical settings-loading API that replaces the 6+
scattered loaders in the codebase. Returns a frozen typed
dataclass, raises a single error type, falls back to documented
defaults consistently.

---

## § 1 — Public API

```python
# pipeline/settings.py

@dataclass(frozen=True)
class StageSettings:
    """Per-stage knobs.

    Reads from settings.yaml::stages.<stage_name>.
    """

    tier: Literal["basic", "standard", "expert"] = "standard"
    # Future per-stage knobs (e.g. retries, timeout) added here.


@dataclass(frozen=True)
class VaultSettings:
    """Typed access to a vault's settings.yaml.

    All fields are populated from settings.yaml; unknown YAML keys
    land in `extras` for forward-compat.
    """

    # --- Pipeline section ---
    max_cycles: int                  # required
    budget_usd: float                # required
    backlog_promotion_threshold: int = 2
    # --- Stages section ---
    stages: dict[str, StageSettings] = field(default_factory=dict)
    # --- Dimensions section ---
    dimensions: list[str] = field(default_factory=list)
    # --- Default agent / model selection ---
    default_agent: Literal["claude", "codex"] = "claude"
    # --- Forward-compat catchall ---
    extras: dict[str, Any] = field(default_factory=dict)

    def stage(self, name: str) -> StageSettings:
        """Convenience: read per-stage settings with default fallback.

        Returns self.stages.get(name, StageSettings()) — i.e. an
        empty StageSettings (tier="standard") if the stage is not
        configured.
        """
        return self.stages.get(name, StageSettings())


def load_vault_settings(vault_dir: Path) -> VaultSettings:
    """Load and validate <vault_dir>/settings.yaml.

    Raises SettingsError on:
      - missing file
      - malformed YAML
      - missing required keys (max_cycles, budget_usd)
      - invalid value types (e.g. max_cycles=-1, budget_usd="cheap")

    Falls back to defaults for optional keys without raising.
    """


class SettingsError(Exception):
    """Raised for any settings.yaml issue."""

    def __init__(
        self,
        message: str,
        *,
        vault_dir: Path | None = None,
        key: str | None = None,
    ):
        self.vault_dir = vault_dir
        self.key = key
        super().__init__(message)
```

---

## § 2 — Settings.yaml schema (preserved + clarified)

The YAML schema is unchanged from pre-refactor. Documented here
for the canonical loader's enforcement:

```yaml
# settings.yaml
pipeline:
  max_cycles: 10           # required int >= 1
  budget_usd: 5.00         # required float >= 0
  backlog_promotion_threshold: 2  # optional int >= 1, default 2

stages:
  scout:
    tier: standard         # optional, default standard
  note_writer:
    tier: standard
  verifier:
    tier: expert
  plan_narrator:           # NEW per spec 025 A1 (optional)
    tier: standard
  probe_retrieval:         # NEW per spec 025 A2 (optional)
    tier: standard
  # ... per-source-module stages added by spec 020 (forward-compat
  # via the dict[str, StageSettings] shape) ...

dimensions:               # optional, default []
  - technical
  - organizational
  - domain
  - market
  - temporal

default_agent: claude     # optional, default "claude"
                          # Permitted: "claude" | "codex"

# Any other top-level keys land in VaultSettings.extras for
# forward-compat.
```

---

## § 3 — Validation rules

| Field | Rule | On violation |
|-------|------|--------------|
| `pipeline.max_cycles` | int >= 1 | `SettingsError("max_cycles must be an integer >= 1, got <value>")` |
| `pipeline.budget_usd` | float >= 0 | `SettingsError("budget_usd must be a non-negative number, got <value>")` |
| `pipeline.backlog_promotion_threshold` | int >= 1; default 2 | Same shape as max_cycles. |
| `stages.<name>.tier` | one of "basic"/"standard"/"expert" | `SettingsError("stages.<name>.tier must be one of basic/standard/expert, got <value>")` |
| `dimensions` | list of strings; default [] | `SettingsError("dimensions must be a list, got <type>")` |
| `default_agent` | "claude" or "codex"; default "claude" | `SettingsError("default_agent must be 'claude' or 'codex', got <value>")` |
| missing `settings.yaml` file | — | `SettingsError("settings.yaml not found at <vault_dir>")` |
| YAML parse error | — | `SettingsError(f"YAML parse error in settings.yaml: {yaml_err}")` |

Validation messages include the vault dir + the offending key
path for traceability. The implementer SHOULD use the
`SettingsError.vault_dir` and `.key` attributes to enable
structured error handling at call sites.

---

## § 4 — Migration target

Pre-refactor inventory (approximate, enumerated during
`/speckit.tasks`):

| Site (approximate) | Migration plan |
|--------------------|----------------|
| `pipeline/orchestrator.py::_load_settings` | Replace with `load_vault_settings` |
| `pipeline/cycle_runner.py::_load_settings` | Replace |
| `cli/research.py::_resolve_settings` (post-B5) | Replace |
| `processors/coverage.py::_get_threshold` | Replace |
| `scripts/agent_call.py::_resolve_default_agent` | Replace or document as holdout (this site reads env vars too) |
| `tests/_helpers/vault_factory.py::_write_settings` | Use VaultSettings + dump_frontmatter shape |
| ... others ... | Various |

**Migration target (FR-012 + SC-008)**: ≥ 6 sites migrate.
Holdouts get inline comments per the same pattern as B4 (see
`contracts/frontmatter-parser.contract.md` § 6).

---

## § 5 — Backwards-compat with existing vaults

Spec 025 MUST NOT require existing vaults to update their
settings.yaml. Every field the canonical loader expects is
either:
- required AND already present in every vault generated by any
  framework version we still support (`max_cycles`, `budget_usd`),
  OR
- optional with a documented default.

The two NEW keys introduced by A1/A2 (`stages.plan_narrator.tier`
and `stages.probe_retrieval.tier`) are **optional** with default
`tier: "standard"`. Vaults without these keys continue to work
unchanged — the narrator and probe calls use the standard tier.

If a future spec needs to add a REQUIRED key, that's a breaking
change requiring an ADR and a vault-migration helper. Spec 025
does not introduce any such change.

---

## § 6 — Performance contract

- `load_vault_settings` MUST complete in < 50 ms on a recent Mac
  for a settings.yaml file of any realistic size (< 100 KB).
- The function MAY cache the parsed result per (vault_dir,
  mtime) — recommended for hot paths, but the default
  implementation re-parses each call. Caching is optional and
  per-site; the canonical loader itself is stateless.

---

## § 7 — Test coverage

| Test | Assertion |
|------|-----------|
| `tests/pipeline/test_settings_loader.py::test_load_well_formed` | Standard happy-path. |
| `tests/pipeline/test_settings_loader.py::test_missing_required_max_cycles` | Raises `SettingsError(key="max_cycles")`. |
| `tests/pipeline/test_settings_loader.py::test_missing_required_budget_usd` | Raises `SettingsError(key="budget_usd")`. |
| `tests/pipeline/test_settings_loader.py::test_invalid_tier_value` | `stages.scout.tier: "elite"` raises. |
| `tests/pipeline/test_settings_loader.py::test_unknown_keys_in_extras` | Unknown top-level keys land in `extras`. |
| `tests/pipeline/test_settings_loader.py::test_stage_convenience_method` | `settings.stage("plan_narrator")` returns `StageSettings(tier="standard")` for absent stage. |
| `tests/pipeline/test_settings_loader.py::test_yaml_parse_error` | Malformed YAML raises with parse-error wrapped message. |
| `tests/pipeline/test_settings_loader.py::test_missing_file` | Missing file raises clearly. |
| `tests/pipeline/test_settings_loader.py::test_frozen_immutability` | Attempting to mutate `VaultSettings` raises `FrozenInstanceError`. |
| `tests/pipeline/test_settings_loader.py::test_default_values` | Optional fields take documented defaults. |
| `tests/pipeline/test_settings_loader.py::test_backwards_compat_existing_vault` | A v0.2.33-era settings.yaml (no plan_narrator/probe_retrieval stages) loads without error. |

All tests tier-1 (unit) per ADR-0008.
