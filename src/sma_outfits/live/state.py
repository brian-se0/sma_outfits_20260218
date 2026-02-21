from __future__ import annotations

from pathlib import Path
from typing import Any

import orjson


class LiveStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        payload = orjson.loads(self.path.read_bytes())
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"Live state payload must be a JSON object: {self.path}"
            )
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_bytes(
            orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
            + b"\n"
        )
        temp_path.replace(self.path)
