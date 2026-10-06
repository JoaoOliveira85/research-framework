#!/usr/bin/env python3
import sys
from pathlib import Path

vault = Path(__file__).resolve().parents[1]
out = vault / "raw_data" / "stub"
out.mkdir(parents=True, exist_ok=True)
(out / "touch").write_text("ok\n", encoding="utf-8")
sys.exit(0)
