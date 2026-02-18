from __future__ import annotations

import platform
import sys
from pathlib import Path

EXPECTED_PYTHON = (3, 14, 3)
EXPECTED_TIMEZONE = "America/New_York"
ENV_LOCAL_PATH = Path(".env.local")


def assert_python_runtime() -> None:
    current = sys.version_info[:3]
    if current != EXPECTED_PYTHON:
        raise RuntimeError(
            "Python runtime mismatch: expected "
            f"{EXPECTED_PYTHON[0]}.{EXPECTED_PYTHON[1]}.{EXPECTED_PYTHON[2]}, "
            f"got {platform.python_version()}."
        )
