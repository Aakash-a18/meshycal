"""pytest config: add the parent demos/phase_1/ dir to sys.path.

Lets test files import ``slot_picker``, ``synthetic_calendar`` etc. directly
without needing to publish them as a real package. Phase 1 demos are
hand-crafted modules, not a redistributable library — per MeshyCal CLAUDE.md
discipline #7 ("Don't abstract MeshyCal prematurely").
"""

from __future__ import annotations

import sys
from pathlib import Path

_PHASE_1_DIR = Path(__file__).resolve().parent.parent
if str(_PHASE_1_DIR) not in sys.path:
    sys.path.insert(0, str(_PHASE_1_DIR))
