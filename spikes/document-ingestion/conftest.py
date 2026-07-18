from __future__ import annotations

import sys
from pathlib import Path


SPIKE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = SPIKE_ROOT / "src"

if str(SPIKE_ROOT) not in sys.path:
    sys.path.insert(0, str(SPIKE_ROOT))
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
