from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import TextIO

import sys


@dataclass(slots=True)
class TerminalProgressBar:
    total: int
    label: str
    width: int = 32
    min_interval_seconds: float = 0.1
    stream: TextIO = sys.stderr
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.total <= 0:
            raise ValueError("Progress total must be > 0")
        self.enabled = self.enabled and bool(getattr(self.stream, "isatty", lambda: False)())
        self._last_render = 0.0
        self._current = 0

    def update(self, current: int, status: str = "") -> None:
        clamped = min(max(current, 0), self.total)
        self._current = clamped
        if not self.enabled:
            return

        now = monotonic()
        if (
            clamped < self.total
            and (now - self._last_render) < self.min_interval_seconds
        ):
            return
        self._last_render = now
        self._render(status=status)

    def close(self) -> None:
        self.update(self.total)

    def _render(self, status: str = "") -> None:
        ratio = self._current / self.total
        filled = int(self.width * ratio)
        bar = ("#" * filled) + ("-" * (self.width - filled))
        percent = int(ratio * 100)
        payload = f"\r{self.label} [{bar}] {self._current}/{self.total} {percent:3d}%"
        if status:
            payload += f" | {status}"
        self.stream.write(payload)
        if self._current >= self.total:
            self.stream.write("\n")
        self.stream.flush()


@dataclass(slots=True)
class TerminalStatusLine:
    label: str
    min_interval_seconds: float = 1.0
    stream: TextIO = sys.stderr
    enabled: bool = True

    def __post_init__(self) -> None:
        self.enabled = self.enabled and bool(getattr(self.stream, "isatty", lambda: False)())
        self._last_emit = 0.0
        self._last_text = ""

    def update(self, text: str, force: bool = False) -> None:
        if not self.enabled:
            return
        now = monotonic()
        if not force and (now - self._last_emit) < self.min_interval_seconds:
            return
        self._last_emit = now
        self._last_text = text
        self.stream.write(f"\r{self.label} {text}")
        self.stream.flush()

    def close(self) -> None:
        if not self.enabled:
            return
        if self._last_text:
            self.stream.write("\n")
            self.stream.flush()
