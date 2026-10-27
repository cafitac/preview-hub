"""Free-space probe for the hub's own state and checkout volume."""

from __future__ import annotations

import os
from pathlib import Path


def free_bytes(path: Path) -> int:
    stat = os.statvfs(path)
    return stat.f_bavail * stat.f_frsize
