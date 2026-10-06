"""Orchestrator-side typed parse of the per-module preflight payload (spec 051
FR4).

Module preflight subprocesses emit the ``PreflightResult`` JSON shape directly
(they cannot import from ``src/`` — same constraint as the extractors); the
bridge parses that stdout JSON here into frozen dataclasses. ``from_json`` is
the trust boundary: it rejects malformed payloads, and the orchestrator treats
any parse failure (alongside subprocess crash/timeout/garbage) as
``fatal_fail`` — fail-closed, skipping only the offending module.

Contract: ``specs/051-post-revival-hardening/contracts/preflight.contract.md``
§3 + ``contracts/preflight-result.schema.json``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = "1.0"

Verdict = Literal["success", "warning", "fatal_fail"]
_VALID_VERDICTS = frozenset({"success", "warning", "fatal_fail"})


@dataclass(frozen=True)
class SourceCorrection:
    """A suggested fix for a malformed ``sources.yaml`` entry."""

    original: str  # malformed value exactly as written in sources.yaml
    suggested: str  # corrected value
    reason: str  # why the original is wrong
    applied: bool  # True = used this cycle; False = suggestion only

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> SourceCorrection:
        if not isinstance(raw, dict):
            raise ValueError("preflight correction must be a JSON object")
        for key in ("original", "suggested", "reason", "applied"):
            if key not in raw:
                raise ValueError(f"preflight correction missing required key {key!r}")
        # Trust boundary: ``applied`` must be a real JSON boolean. ``bool(...)``
        # would silently coerce (``"false"`` → True, ``0`` → False); reject
        # anything that isn't a genuine bool.
        if not isinstance(raw["applied"], bool):
            raise ValueError(
                f"preflight correction 'applied' must be a JSON boolean, got "
                f"{type(raw['applied']).__name__}"
            )
        return cls(
            original=str(raw["original"]),
            suggested=str(raw["suggested"]),
            reason=str(raw["reason"]),
            applied=raw["applied"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "suggested": self.suggested,
            "reason": self.reason,
            "applied": self.applied,
        }


@dataclass(frozen=True)
class PreflightResult:
    """The verdict of a module's preflight check on its declared sources."""

    verdict: Verdict
    corrections: list[SourceCorrection] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    # -- convenience constructors --------------------------------------------

    @classmethod
    def success(cls, messages: Iterable[str] | None = None) -> PreflightResult:
        return cls(verdict="success", messages=list(messages or []))

    @classmethod
    def warning(
        cls,
        corrections: Iterable[SourceCorrection] | None = None,
        messages: Iterable[str] | None = None,
    ) -> PreflightResult:
        return cls(
            verdict="warning",
            corrections=list(corrections or []),
            messages=list(messages or []),
        )

    @classmethod
    def fatal(cls, messages: str | Iterable[str]) -> PreflightResult:
        msgs = [messages] if isinstance(messages, str) else list(messages)
        return cls(verdict="fatal_fail", messages=msgs)

    # -- parsing -------------------------------------------------------------

    @classmethod
    def from_json(cls, raw: Any) -> PreflightResult:
        """Parse + validate a subprocess stdout payload. Raises ``ValueError``
        on any schema violation (the caller maps that to ``fatal_fail``)."""
        if not isinstance(raw, dict):
            raise ValueError("preflight result must be a JSON object")
        schema_version = raw.get("schema_version")
        if schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported preflight schema_version {schema_version!r} "
                f"(expected {SCHEMA_VERSION!r})"
            )
        verdict = raw.get("verdict")
        if verdict not in _VALID_VERDICTS:
            raise ValueError(f"invalid preflight verdict {verdict!r}")
        corrections_raw = raw.get("corrections", [])
        if not isinstance(corrections_raw, list):
            raise ValueError("preflight corrections must be a list")
        messages_raw = raw.get("messages", [])
        if not isinstance(messages_raw, list):
            raise ValueError("preflight messages must be a list")
        return cls(
            verdict=verdict,  # type: ignore[arg-type]  # validated above
            corrections=[SourceCorrection.from_json(c) for c in corrections_raw],
            messages=[str(m) for m in messages_raw],
            schema_version=schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "verdict": self.verdict,
            "corrections": [c.to_dict() for c in self.corrections],
            "messages": list(self.messages),
        }
