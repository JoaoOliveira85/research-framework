"""Entry point for ``python -m research_framework.quality`` (delegates to runner)."""

from __future__ import annotations

import sys

from .runner import main

if __name__ == "__main__":
    sys.exit(main())
