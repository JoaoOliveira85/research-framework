"""Guard aggregator (issue #278).

See :mod:`scripts.guards.run_all` for the battery this package runs and
``docs/testing-strategy.md`` § Guard battery for why several product-level
guards (``check_abstraction.py``, ``validate_vault.py``, etc.) are NOT in
that battery — they require a generated vault this repo doesn't ship.
"""
