"""Spustí diagnostiku z kořene projektu, ať je PYTHONPATH nastavený nebo ne."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))

from solar_diag.main import main

if __name__ == "__main__":
    main()
