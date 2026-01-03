"""Console helpers.

Keep terminal output quiet by default. Set CR_VERBOSE=1 to enable verbose prints.
"""

from __future__ import annotations

import os
from typing import Any


def vprint(*args: Any, **kwargs: Any) -> None:
    """Verbose print (disabled by default)."""
    val = os.environ.get("CR_VERBOSE", "").strip().lower()
    if val in {"1", "true", "yes", "y", "on"}:
        print(*args, **kwargs)

