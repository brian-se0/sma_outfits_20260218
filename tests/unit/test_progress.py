from __future__ import annotations

from sma_outfits.monitoring.progress import TerminalProgressBar, TerminalStatusLine


class _TTYBuffer:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def isatty(self) -> bool:
        return True

    def write(self, value: str) -> int:
        self.parts.append(value)
        return len(value)

    def flush(self) -> None:
        return None

    def text(self) -> str:
        return "".join(self.parts)


def test_terminal_progress_bar_initializes_and_closes_under_slots() -> None:
    stream = _TTYBuffer()
    bar = TerminalProgressBar(
        total=2,
        label="backfill",
        min_interval_seconds=0.0,
        stream=stream,
        enabled=True,
    )

    bar.update(1, status="SPY/1m")
    bar.close()

    output = stream.text()
    assert "backfill [" in output
    assert "2/2 100%" in output


def test_terminal_status_line_initializes_and_flushes_newline_under_slots() -> None:
    stream = _TTYBuffer()
    line = TerminalStatusLine(
        label="run-live",
        min_interval_seconds=0.0,
        stream=stream,
        enabled=True,
    )

    line.update("status=running")
    line.close()

    output = stream.text()
    assert "run-live status=running" in output
    assert output.endswith("\n")
