from __future__ import annotations

import platform
import sys

EXPECTED_PYTHON = (3, 14, 3)


def assert_python_runtime() -> None:
    current = sys.version_info[:3]
    if current != EXPECTED_PYTHON:
        raise RuntimeError(
            "Python runtime mismatch: expected "
            f"{EXPECTED_PYTHON[0]}.{EXPECTED_PYTHON[1]}.{EXPECTED_PYTHON[2]}, "
            f"got {platform.python_version()}."
        )
