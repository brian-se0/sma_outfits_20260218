from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import typer

from sma_outfits.config.models import Settings, load_settings
from sma_outfits.data.alpaca_clients import AlpacaRESTClient
from sma_outfits.data.ingest import BackfillResult, backfill_historical
from sma_outfits.data.storage import StorageManager
from sma_outfits.monitoring.logging import configure_logging
from sma_outfits.reporting.summary import write_summary_report
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
    results = backfill_historical(
        settings=settings,
        symbols=selected_symbols,
        timeframes=selected_timeframes,
        start=start_ts,
        end=end_ts,
        client=client,
        storage=storage,
    )
    typer.echo(_format_backfill_results(results))


@app.command("run-live")
def run_live(
    config: Path = typer.Option(Path("configs/settings.example.yaml"), "--config"),
    lookback_hours: int = typer.Option(8, "--lookback-hours"),
) -> None:
    assert_python_runtime()
    settings = _load_runtime_settings(config)
    configure_logging()
    end_ts = pd.Timestamp.utcnow().tz_convert("UTC")
    start_ts = end_ts - timedelta(hours=lookback_hours)
    client = AlpacaRESTClient(settings.alpaca)
    storage = StorageManager(Path(settings.storage_root))
    backfill_historical(
        settings=settings,
        symbols=settings.universe.symbols,
        timeframes=settings.timeframes.live,
        start=start_ts,
        end=end_ts,
        client=client,
        storage=storage,
    )
    replay_engine = ReplayEngine(settings=settings, storage=storage)
    result = replay_engine.run(
        start=start_ts,
        end=end_ts,
        symbols=settings.universe.symbols,
        timeframes=settings.timeframes.live,
    )
    typer.echo(json.dumps(result.summary, indent=2))


@app.command("replay")
def replay(
    config: Path = typer.Option(Path("configs/settings.example.yaml"), "--config"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    symbols: str = typer.Option("", "--symbols"),
    timeframes: str = typer.Option("", "--timeframes"),
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
    result = replay_engine.run(
        start=start_ts,
        end=end_ts,
        symbols=selected_symbols,
        timeframes=selected_timeframes,
    )
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
    summary = _build_summary_from_records(strikes, signals, positions, start_ts, end_ts)
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


def _build_summary_from_records(
    strike_rows: list[dict[str, Any]],
    signal_rows: list[dict[str, Any]],
    position_rows: list[dict[str, Any]],
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> dict[str, Any]:
    strikes = _filter_rows(strike_rows, "bar_ts", start, end)
    positions = _filter_rows(position_rows, "ts", start, end)

    closed = [row for row in positions if row.get("action") == "close"]
    wins = [
        row
        for row in closed
        if row.get("reason") in {"+3R_final_take", "risk_migration_cut"}
    ]
    symbol_counts: dict[str, int] = {}
    outfit_counts: dict[str, int] = {}
    for row in strikes:
        symbol = str(row.get("symbol"))
        outfit = str(row.get("outfit_id"))
        symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
        outfit_counts[outfit] = outfit_counts.get(outfit, 0) + 1

    top_symbols = sorted(symbol_counts.items(), key=lambda item: item[1], reverse=True)[:5]
    top_outfits = sorted(outfit_counts.items(), key=lambda item: item[1], reverse=True)[:5]
    return {
        "total_strikes": len(strikes),
        "total_signals": len(signal_rows),
        "total_position_events": len(positions),
        "closed_positions": len(closed),
        "win_rate": (len(wins) / len(closed)) if closed else 0.0,
        "top_symbols": top_symbols,
        "top_outfits": top_outfits,
    }


def _filter_rows(
    rows: list[dict[str, Any]],
    timestamp_key: str,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> list[dict[str, Any]]:
    if start is None or end is None:
        return rows
    out: list[dict[str, Any]] = []
    for row in rows:
        raw = row.get(timestamp_key)
        if not raw:
            continue
        ts = ensure_utc_timestamp(str(raw))
        if start <= ts <= end:
            out.append(row)
    return out


if __name__ == "__main__":
    app()
