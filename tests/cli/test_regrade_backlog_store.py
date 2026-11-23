"""Spec 084 T006: ``./vault re-grade`` resolves exactly the reinstated stem."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_framework.cli.regrade import run_regrade
from research_framework.pipeline import backlog
from research_framework.pipeline import state_layout as L

from .test_regrade import _CRED_NOTE, _build_vault, _quarantine


def _entries(vault: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(L.research_backlog_path(vault).read_text(encoding="utf-8"))
    return {e["stem"]: e for e in data["entries"] if e["origin"] == "quarantine"}


def test_regrade_resolves_exactly_the_reinstated_stem(tmp_path: Path) -> None:
    vault = _build_vault(tmp_path)
    _quarantine(vault, "deseq", url="https://fastify.dev/", notes=[_CRED_NOTE])
    # Siblings whose names contain the reinstated stem, and a retry pointer.
    for stem, kind in (("deseq2", "rewrite"), ("old-deseq", "retry")):
        _quarantine(
            vault, stem, url="https://x.example/", notes=["claim is fabricated"]
        )

    def _seed(tx: backlog.Transaction) -> None:
        tx.observe_quarantine(stem="deseq", kind="retry", detail="credibility")
        tx.observe_quarantine(stem="deseq2", kind="rewrite", detail="other")
        tx.observe_quarantine(stem="old-deseq", kind="retry", detail="other")

    assert backlog.update(vault, "quarantine", _seed)
    # An operator's own entry that merely mentions the phrase.
    store = L.research_backlog_path(vault)
    data = json.loads(store.read_text(encoding="utf-8"))
    data["entries"].append(
        {
            "title": "do not rewrite quarantined note: deseq until Q3",
            "origin": "operator",
            "status": "open",
        }
    )
    store.write_text(json.dumps(data), encoding="utf-8")

    assert run_regrade(vault, notes=["deseq.md"]) == 0

    after = _entries(vault)
    assert after["deseq"]["status"] == "resolved"
    assert after["deseq"]["status_by"] == "regrade"
    assert after["deseq2"]["status"] == "open"
    assert after["old-deseq"]["status"] == "open"
    operator = [
        e
        for e in json.loads(store.read_text(encoding="utf-8"))["entries"]
        if e["origin"] == "operator"
    ]
    assert [e["status"] for e in operator] == ["open"]
