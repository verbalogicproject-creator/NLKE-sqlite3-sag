"""Make the in-repo packages importable when running the suite from a checkout
(no install needed): sqlite3_sag, declared_core, and the project_memory shim all
live at the repo root."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
