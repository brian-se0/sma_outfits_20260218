from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pandas as pd
import typer

from sma_outfits.config.models import Settings, load_settings
from sma_outfits.data.alpaca_clients import AlpacaRESTClient
from sma_outfits.data.ingest import BackfillResult, backfill_historical
from sma_outfits.data.storage import StorageManager
from sma_outfits.live import LiveRunner
from sma_outfits.monitoring.logging import configure_logging
from sma_outfits.monitoring.progress import TerminalProgressBar, TerminalStatusLine
from sma_outfits.reporting.summary import build_summary_from_records, write_summary_report
from sma_outfits.replay.engine import ReplayEngine
from sma_outfits.runtime import assert_python_runtime
from sma_outfits.utils import dedupe_keep_order, ensure_utc_timestamp, parse_csv

app = typer.Typer(add_completion=False, help="SMA outfits Alpaca-only recreation CLI")


def _load_runtime_settings(config: Path) -> Settings:
    return load_settings(config_path=config, env_path=Path(".env.local"))


def _effective_symbols(user_symbols: str, settings: Settings) -> list[str]:
    if not user_symbols:
        return settings.universe.symbols
    return dedupe_keep_order([value.upper() for value in parse_csv(user_symbols)])


def _effective_timeframes(user_timeframes: str, settings: Settings) -> list[str]:
    if not user_timeframes:
        return settings.all_timeframes
    return dedupe_keep_order(parse_csv(user_timeframes))


@app.command("validate-config")
def validate_config(
    config: Path = typer.Option(
        Path("configs/settings.example.yaml"),
        "--config",
        help="Path to settings YAML file",
    ),
) -> None:
    assert_python_runtime()
    settings = _load_runtime_settings(config)
    payload = {
        "status": "ok",
        "symbols": len(settings.universe.symbols),
        "timeframes": settings.all_timeframes,
        "archive_enabled": settings.archive.enabled,
    }
    typer.echo(json.dumps(payload, indent=2))


@app.command("backfill")
def backfill(
    config: Path = typer.Option(Path("configs/settings.example.yaml"), "--config"),
    symbols: str = typer.Option("", "--symbols", help="CSV symbols override"),
    start: str = typer.Option(..., "--start", help="UTC start timestamp"),
    end: str = typer.Option(..., "--end", help="UTC end timestamp"),
    timeframes: str = typer.Option("", "--timeframes", help="CSV timeframes override"),
    progress: bool = typer.Option(
        True,
        "--progress/--no-progress",
        help="Show terminal progress bar",
    ),
) -> None:
    assert_python_runtime()
    settings = _load_runtime_settings(config)
    configure_logging()
    selected_symbols = _effective_symbols(symbols, settings)
    selected_timeframes = _effective_timeframes(timeframes, settings)
    start_ts = ensure_utc_timestamp(start)
    end_ts = ensure_utc_timestamp(end)

    client = AlpacaRESTClient(settings.alpaca)
    storage = StorageManager(Path(settings.storage_root))
    progress_bar = TerminalProgressBar(
        total=max(1, len(selected_symbols) * len(selected_timeframes)),
        label="backfill",
        enabled=progress,
    )

    def _on_progress(done: int, total: int, row: BackfillResult) -> None:
        progress_bar.update(
            done,
            status=f"{row.symbol}/{row.timeframe} written={row.bars_written}",
        )

    results = backfill_historical(
        settings=settings,
        symbols=selected_symbols,
        timeframes=selected_timeframes,
        start=start_ts,
        end=end_ts,
        client=client,
        storage=storage,
        progress_callback=_on_progress if progress else None,
    )
    progress_bar.close()
    typer.echo(_format_backfill_results(results))


@app.command("run-live")
def run_live(
    config: Path = typer.Option(Path("configs/settings.example.yaml"), "--config"),
    lookback_hours: int | None = typer.Option(
        None,
        "--lookback-hours",
        help="Optional warmup override (hours) used to seed SMA state before streaming",
    ),
    runtime_minutes: int | None = typer.Option(
        None,
        "--runtime-minutes",
        help="Optional run length. When omitted, uses config live.runtime_minutes.",
    ),
    progress: bool = typer.Option(
        True,
        "--progress/--no-progress",
        help="Show live status line in terminal",
    ),
) -> None:
    assert_python_runtime()
    settings = _load_runtime_settings(config)
    configure_logging()
    storage = StorageManager(Path(settings.storage_root))
    runner = LiveRunner(settings=settings, storage=storage)
    status_line = TerminalStatusLine(label="run-live", enabled=progress)
    warmup_minutes = lookback_hours * 60 if lookback_hours is not None else None
    result = None

    def _on_live_progress(payload: dict[str, object]) -> None:
        try:
            status = str(payload["status"])
            bars_received = int(payload["bars_received"])
            bars_processed = int(payload["bars_processed"])
            duplicate_bars_skipped = int(payload["duplicate_bars_skipped"])
            reconnects = int(payload["reconnects"])
            stale_reconnects = int(payload["stale_feed_reconnects"])
            heartbeat_failures = int(payload["heartbeat_failures"])
            uptime_seconds = float(payload["uptime_seconds"])
        except KeyError as exc:
            raise RuntimeError(
                f"Live progress payload contract violation: missing key {exc.args[0]!r}"
            ) from exc
        status_line.update(
            (
                f"status={status} recv={bars_received} proc={bars_processed} "
                f"dup={duplicate_bars_skipped} reconn={reconnects} "
                f"stale={stale_reconnects} hb={heartbeat_failures} "
                f"up={uptime_seconds:.0f}s"
            ),
            force=status != "running",
        )

    try:
        result = asyncio.run(
            runner.run(
                symbols=settings.universe.symbols,
                timeframes=settings.timeframes.live,
                runtime_minutes=runtime_minutes,
                warmup_minutes=warmup_minutes,
                progress_callback=_on_live_progress if progress else None,
            )
        )
    except KeyboardInterrupt:
        raise typer.Exit(code=130) from None
    finally:
        status_line.close()

    assert result is not None
    payload = dict(result.summary)
    payload.update(
        {
            "bars_received": result.bars_received,
            "bars_processed": result.bars_processed,
            "duplicate_bars_skipped": result.duplicate_bars_skipped,
            "reconnects": result.reconnects,
            "stale_feed_reconnects": result.stale_feed_reconnects,
            "heartbeat_failures": result.heartbeat_failures,
            "started_at": result.started_at.isoformat(),
            "ended_at": result.ended_at.isoformat(),
        }
    )
    typer.echo(json.dumps(payload, indent=2))


@app.command("replay")
def replay(
    config: Path = typer.Option(Path("configs/settings.example.yaml"), "--config"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    symbols: str = typer.Option("", "--symbols"),
    timeframes: str = typer.Option("", "--timeframes"),
    progress: bool = typer.Option(
        True,
        "--progress/--no-progress",
        help="Show terminal progress bar",
    ),
) -> None:
    assert_python_runtime()
    settings = _load_runtime_settings(config)
    configure_logging()
    selected_symbols = _effective_symbols(symbols, settings)
    selected_timeframes = _effective_timeframes(timeframes, settings)
    start_ts = ensure_utc_timestamp(start)
    end_ts = ensure_utc_timestamp(end)
    storage = StorageManager(Path(settings.storage_root))
    replay_engine = ReplayEngine(settings=settings, storage=storage)
    progress_bar: TerminalProgressBar | None = None

    def _on_progress(
        done: int,
        total: int,
        symbol: str,
        timeframe: str,
        ts: pd.Timestamp,
    ) -> None:
        nonlocal progress_bar
        if progress_bar is None:
            progress_bar = TerminalProgressBar(
                total=max(1, total),
                label="replay",
                enabled=progress,
            )
        progress_bar.update(
            done,
            status=f"{symbol}/{timeframe} {pd.Timestamp(ts).strftime('%H:%M:%S')}",
        )

    result = replay_engine.run(
        start=start_ts,
        end=end_ts,
        symbols=selected_symbols,
        timeframes=selected_timeframes,
        progress_callback=_on_progress if progress else None,
    )
    if progress_bar is not None:
        progress_bar.close()
    label = f"{start_ts.strftime('%Y%m%dT%H%M%S')}_{end_ts.strftime('%Y%m%dT%H%M%S')}"
    report_root = Path(settings.archive.root) / "reports"
    markdown_path, csv_path = write_summary_report(result.summary, report_root, label)
    typer.echo(json.dumps(result.summary, indent=2))
    typer.echo(f"report_markdown={markdown_path}")
    typer.echo(f"report_csv={csv_path}")


@app.command("report")
def report(
    config: Path = typer.Option(Path("configs/settings.example.yaml"), "--config"),
    date: str | None = typer.Option(None, "--date", help="YYYY-MM-DD"),
    range_: str | None = typer.Option(
        None,
        "--range",
        help="UTC range format start:end",
    ),
) -> None:
    assert_python_runtime()
    settings = _load_runtime_settings(config)
    storage = StorageManager(Path(settings.storage_root))
    strikes = storage.load_events("strikes")
    signals = storage.load_events("signals")
    positions = storage.load_events("positions")
    if not strikes and not signals and not positions:
        raise RuntimeError("No stored replay events found. Run `make replay` first.")

    start_ts, end_ts = _resolve_report_range(date, range_)
    summary = build_summary_from_records(
        strike_rows=strikes,
        signal_rows=signals,
        position_rows=positions,
        start=start_ts,
        end=end_ts,
    )
    label = (
        f"{start_ts.strftime('%Y%m%d')}_{end_ts.strftime('%Y%m%d')}"
        if start_ts and end_ts
        else "all_time"
    )
    report_root = Path(settings.archive.root) / "reports"
    markdown_path, csv_path = write_summary_report(summary, report_root, label)
    typer.echo(json.dumps(summary, indent=2))
    typer.echo(f"report_markdown={markdown_path}")
    typer.echo(f"report_csv={csv_path}")


def _format_backfill_results(results: list[BackfillResult]) -> str:
    rows = [
        {
            "symbol": row.symbol,
            "timeframe": row.timeframe,
            "bars_written": row.bars_written,
        }
        for row in results
    ]
    return json.dumps(rows, indent=2)


def _resolve_report_range(
    date: str | None,
    range_: str | None,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if date and range_:
        raise ValueError("Use either --date or --range, not both.")
    if date:
        start = ensure_utc_timestamp(f"{date}T00:00:00Z")
        end = ensure_utc_timestamp(f"{date}T23:59:59Z")
        return start, end
    if range_:
        if ":" not in range_:
            raise ValueError("--range format must be start:end")
        start_raw, end_raw = range_.split(":", 1)
        return ensure_utc_timestamp(start_raw), ensure_utc_timestamp(end_raw)
    return None, None


if __name__ == "__main__":
    app()
