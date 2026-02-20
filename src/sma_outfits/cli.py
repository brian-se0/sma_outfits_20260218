from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pandas as pd
import typer
import yaml

from sma_outfits.config.models import (
    AlpacaConfig,
    SessionsConfig,
    Settings,
    TimeframesConfig,
    UniverseConfig,
    load_settings,
    read_env_local,
)
from sma_outfits.data.alpaca_clients import AlpacaRESTClient
from sma_outfits.data.ingest import BackfillResult, backfill_historical, source_timeframe_for
from sma_outfits.data.resample import resample_ohlcv
from sma_outfits.data.storage import StorageManager
from sma_outfits.events import event_to_record
from sma_outfits.execution import resolve_execution_pairs
from sma_outfits.live import LiveRunner
from sma_outfits.monitoring.logging import configure_logging
from sma_outfits.monitoring.progress import TerminalProgressBar, TerminalStatusLine
from sma_outfits.reporting.summary import build_summary_from_records, write_summary_report
from sma_outfits.replay.engine import ReplayEngine
from sma_outfits.runtime import assert_python_runtime
from sma_outfits.utils import dedupe_keep_order, ensure_utc_timestamp, market_for_symbol, parse_csv

app = typer.Typer(add_completion=False, help="SMA outfits Alpaca-only recreation CLI")


def _load_runtime_settings(config: Path) -> Settings:
    return load_settings(config_path=config, env_path=Path(".env.local"))


def _load_discovery_runtime(
    config: Path | None,
) -> tuple[AlpacaConfig, UniverseConfig, TimeframesConfig, SessionsConfig]:
    env = read_env_local(Path(".env.local"))
    alpaca = AlpacaConfig.model_validate(
        {
            "api_key": env["ALPACA_API_KEY"],
            "secret_key": env["ALPACA_SECRET_KEY"],
            "base_url": env["ALPACA_BASE_URL"],
            "data_url": env["ALPACA_DATA_URL"],
            "data_feed": env["ALPACA_DATA_FEED"],
        }
    )
    if config is None:
        return alpaca, UniverseConfig(), TimeframesConfig(), SessionsConfig()

    if not config.exists():
        raise FileNotFoundError(f"Config file not found: {config}")
    parsed = yaml.safe_load(config.read_text(encoding="utf-8"))
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        raise ValueError("YAML root must be a map")
    universe = UniverseConfig.model_validate(parsed.get("universe", {}))
    timeframes = TimeframesConfig.model_validate(parsed.get("timeframes", {}))
    sessions = SessionsConfig.model_validate(parsed.get("sessions", {}))
    return alpaca, universe, timeframes, sessions


def _effective_symbols(user_symbols: str, settings: Settings) -> list[str]:
    if not user_symbols:
        return settings.universe.symbols
    return dedupe_keep_order([value.upper() for value in parse_csv(user_symbols)])


def _effective_timeframes(user_timeframes: str, settings: Settings) -> list[str]:
    if not user_timeframes:
        return settings.all_timeframes
    return dedupe_keep_order(parse_csv(user_timeframes))


def _effective_strategy_symbols(user_symbols: str, settings: Settings) -> list[str]:
    if user_symbols:
        return dedupe_keep_order([value.upper() for value in parse_csv(user_symbols)])
    if settings.strategy.strict_routing:
        return dedupe_keep_order([route.symbol for route in settings.strategy.routes])
    return settings.universe.symbols


def _effective_strategy_timeframes(
    user_timeframes: str,
    settings: Settings,
    symbols: list[str],
) -> list[str]:
    if user_timeframes:
        return dedupe_keep_order(parse_csv(user_timeframes))
    if settings.strategy.strict_routing:
        symbol_set = {symbol.upper() for symbol in symbols}
        values = [
            route.timeframe
            for route in settings.strategy.routes
            if route.symbol in symbol_set
        ]
        if values:
            return dedupe_keep_order(values)
        return dedupe_keep_order([route.timeframe for route in settings.strategy.routes])
    return settings.timeframes.live


def _validate_symbol_market_mappings(symbols: list[str], settings: Settings) -> None:
    for symbol in symbols:
        market_for_symbol(symbol, settings.universe.symbol_markets)


def _stock_symbols_only(
    symbols: list[str],
    symbol_markets: dict[str, str],
) -> list[str]:
    stock_symbols = [
        symbol
        for symbol in symbols
        if market_for_symbol(symbol, symbol_markets) == "stocks"
    ]
    if not stock_symbols:
        raise RuntimeError(
            "No stock symbols available for requested scope. "
            "discover-range and readiness checks are stock-only."
        )
    return stock_symbols


def _write_json_with_hash(
    payload: dict[str, object],
    output: Path,
) -> tuple[Path, Path, str]:
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    output.write_text(serialized + "\n", encoding="utf-8")
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    hash_path = output.with_suffix(output.suffix + ".sha256")
    hash_path.write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    return output, hash_path, digest


def _preflight_strict_route_scope(
    *,
    command: str,
    symbols: list[str],
    timeframes: list[str],
    settings: Settings,
) -> None:
    resolve_execution_pairs(
        settings=settings,
        symbols=symbols,
        timeframes=timeframes,
        command=command,
    )


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


@app.command("discover-range")
def discover_range(
    config: Path | None = typer.Option(
        Path("configs/settings.example.yaml"),
        "--config",
        help="Optional config for universe/timeframes/session defaults",
    ),
    symbols: str = typer.Option("", "--symbols", help="CSV symbols override"),
    timeframes: str = typer.Option("", "--timeframes", help="CSV timeframes override"),
    output: Path = typer.Option(
        Path("artifacts/readiness/discovered_range_manifest.json"),
        "--output",
        help="Output manifest path",
    ),
    start: str = typer.Option(
        "2000-01-01T00:00:00Z",
        "--start",
        help="UTC discovery start bound",
    ),
    end: str | None = typer.Option(
        None,
        "--end",
        help="UTC discovery end bound (default: now)",
    ),
) -> None:
    assert_python_runtime()
    alpaca, universe, timeframe_cfg, sessions = _load_discovery_runtime(config)
    selected_symbols = (
        dedupe_keep_order([value.upper() for value in parse_csv(symbols)])
        if symbols
        else universe.symbols
    )
    selected_timeframes = (
        dedupe_keep_order(parse_csv(timeframes))
        if timeframes
        else list(dict.fromkeys([*timeframe_cfg.live, *timeframe_cfg.derived]))
    )
    stock_symbols = _stock_symbols_only(selected_symbols, universe.symbol_markets)
    start_ts = ensure_utc_timestamp(start)
    end_ts = ensure_utc_timestamp(end) if end is not None else pd.Timestamp.now(tz="UTC")
    if start_ts >= end_ts:
        raise ValueError("start must be earlier than end for discover-range")

    client = AlpacaRESTClient(alpaca)
    earliest_source_rows: dict[tuple[str, str], pd.DataFrame] = {}
    records: list[dict[str, str]] = []
    for symbol in stock_symbols:
        for timeframe in selected_timeframes:
            source_tf = source_timeframe_for(timeframe)
            source_key = (symbol, source_tf)
            source_frame = earliest_source_rows.get(source_key)
            if source_frame is None:
                source_frame = client.discover_earliest_bar_frame(
                    symbol=symbol,
                    timeframe=source_tf,
                    market="stocks",
                    start=start_ts,
                    end=end_ts,
                )
                earliest_source_rows[source_key] = source_frame

            if timeframe == source_tf:
                target_frame = source_frame
            else:
                target_frame = resample_ohlcv(
                    source_frame,
                    timeframe=timeframe,
                    timezone=sessions.timezone,
                    anchors=timeframe_cfg.anchors,
                )
                if target_frame.empty:
                    raise RuntimeError(
                        f"discover-range produced empty resample for {symbol} {timeframe}"
                    )
            earliest_ts = ensure_utc_timestamp(target_frame.iloc[0]["ts"])
            records.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "source_timeframe": source_tf,
                    "earliest_ts": earliest_ts.isoformat(),
                }
            )

    sorted_records = sorted(
        records,
        key=lambda row: (row["symbol"], row["timeframe"]),
    )
    if not sorted_records:
        raise RuntimeError("discover-range found no stock discovery records")
    full_range_start = min(
        ensure_utc_timestamp(row["earliest_ts"]) for row in sorted_records
    ).isoformat()
    payload: dict[str, object] = {
        "status": "ok",
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "config": str(config) if config is not None else None,
        "discovery_window_start": start_ts.isoformat(),
        "discovery_window_end": end_ts.isoformat(),
        "full_range_start": full_range_start,
        "stocks": stock_symbols,
        "timeframes": selected_timeframes,
        "records": sorted_records,
    }
    manifest_path, hash_path, digest = _write_json_with_hash(payload, output)
    typer.echo(json.dumps(payload, indent=2))
    typer.echo(f"manifest_path={manifest_path}")
    typer.echo(f"manifest_sha256={digest}")
    typer.echo(f"manifest_hash_path={hash_path}")


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
    _validate_symbol_market_mappings(selected_symbols, settings)
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
    symbols: str = typer.Option("", "--symbols", help="CSV symbols override"),
    timeframes: str = typer.Option("", "--timeframes", help="CSV timeframes override"),
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
    selected_symbols = _effective_strategy_symbols(symbols, settings)
    selected_timeframes = _effective_strategy_timeframes(
        timeframes,
        settings,
        selected_symbols,
    )
    _validate_symbol_market_mappings(selected_symbols, settings)
    _preflight_strict_route_scope(
        command="run-live",
        symbols=selected_symbols,
        timeframes=selected_timeframes,
        settings=settings,
    )
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
                symbols=selected_symbols,
                timeframes=selected_timeframes,
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
    selected_symbols = _effective_strategy_symbols(symbols, settings)
    _validate_symbol_market_mappings(selected_symbols, settings)
    selected_timeframes = _effective_strategy_timeframes(
        timeframes,
        settings,
        selected_symbols,
    )
    _preflight_strict_route_scope(
        command="replay",
        symbols=selected_symbols,
        timeframes=selected_timeframes,
        settings=settings,
    )
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
    summary = build_summary_from_records(
        strike_rows=[event_to_record(event) for event in result.strikes],
        signal_rows=[event_to_record(event) for event in result.signals],
        position_rows=[event_to_record(event) for event in result.position_events],
        start=start_ts,
        end=end_ts,
    )
    if progress_bar is not None:
        progress_bar.close()
    label = f"{start_ts.strftime('%Y%m%dT%H%M%S')}_{end_ts.strftime('%Y%m%dT%H%M%S')}"
    report_root = Path(settings.archive.root) / "reports"
    markdown_path, csv_path = write_summary_report(summary, report_root, label)
    typer.echo(json.dumps(summary, indent=2))
    typer.echo(f"report_markdown={markdown_path}")
    typer.echo(f"report_csv={csv_path}")


@app.command("verify-readiness")
def verify_readiness(
    config: Path = typer.Option(Path("configs/settings.example.yaml"), "--config"),
    start: str = typer.Option(..., "--start", help="UTC start timestamp"),
    end: str = typer.Option(..., "--end", help="UTC end timestamp"),
    symbols: str = typer.Option("", "--symbols", help="CSV symbols override"),
    timeframes: str = typer.Option("", "--timeframes", help="CSV timeframes override"),
    output: Path = typer.Option(
        Path("artifacts/readiness/readiness_acceptance.json"),
        "--output",
        help="Output readiness acceptance manifest path",
    ),
    require_report_artifacts: bool = typer.Option(
        True,
        "--require-report-artifacts/--no-require-report-artifacts",
        help="Require at least one report artifact under archive/reports",
    ),
) -> None:
    assert_python_runtime()
    settings = _load_runtime_settings(config)
    selected_symbols = _effective_symbols(symbols, settings)
    selected_timeframes = _effective_timeframes(timeframes, settings)
    stock_symbols = _stock_symbols_only(selected_symbols, settings.universe.symbol_markets)
    start_ts = ensure_utc_timestamp(start)
    end_ts = ensure_utc_timestamp(end)
    if start_ts >= end_ts:
        raise ValueError("start must be earlier than end for verify-readiness")

    storage = StorageManager(Path(settings.storage_root))
    missing_pairs: list[str] = []
    monotonicity_failures: list[str] = []
    checked_pairs = 0
    for symbol in stock_symbols:
        for timeframe in selected_timeframes:
            checked_pairs += 1
            bars = storage.read_bars(
                symbol=symbol,
                timeframe=timeframe,
                start=start_ts,
                end=end_ts,
            )
            if bars.empty:
                missing_pairs.append(f"{symbol}/{timeframe}")
                continue
            ts = pd.to_datetime(bars["ts"], utc=True)
            if not bool(ts.is_monotonic_increasing):
                monotonicity_failures.append(f"{symbol}/{timeframe}:non_monotonic")
            if bool(ts.duplicated().any()):
                monotonicity_failures.append(f"{symbol}/{timeframe}:duplicate_ts")

    if missing_pairs:
        raise RuntimeError(
            "Readiness acceptance failed: missing backfill coverage for pairs "
            + ", ".join(sorted(missing_pairs))
        )
    if monotonicity_failures:
        raise RuntimeError(
            "Readiness acceptance failed: timestamp monotonicity violations for pairs "
            + ", ".join(sorted(monotonicity_failures))
        )

    strikes = storage.load_events("strikes")
    signals = storage.load_events("signals")
    positions = storage.load_events("positions")
    summary = build_summary_from_records(
        strike_rows=strikes,
        signal_rows=signals,
        position_rows=positions,
        start=start_ts,
        end=end_ts,
    )

    report_root = Path(settings.archive.root) / "reports"
    report_files = sorted([*report_root.glob("*.md"), *report_root.glob("*.csv")])
    if require_report_artifacts and not report_files:
        raise RuntimeError(
            "Readiness acceptance failed: no report artifacts found in "
            f"{report_root}"
        )

    events_root = Path(settings.storage_root) / "events"
    hash_files: list[Path] = []
    for path in sorted(
        [
            events_root / "strikes.jsonl",
            events_root / "signals.jsonl",
            events_root / "positions.jsonl",
            *report_files,
        ]
    ):
        if path.exists() and path.is_file():
            hash_files.append(path)

    hashes: dict[str, str] = {}
    for path in hash_files:
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()

    payload: dict[str, object] = {
        "status": "ok",
        "checked_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "config": str(config),
        "start": start_ts.isoformat(),
        "end": end_ts.isoformat(),
        "stock_symbols": stock_symbols,
        "timeframes": selected_timeframes,
        "pairs_checked": checked_pairs,
        "summary_snapshot": {
            "total_strikes": summary["strike_attribution"]["total_strikes"],
            "total_signals": summary["strike_attribution"]["total_signals"],
            "closed_positions": summary["strike_attribution"]["closed_positions"],
            "attribution_mode": summary["attribution_mode"],
        },
        "artifact_hashes": hashes,
    }
    manifest_path, hash_path, digest = _write_json_with_hash(payload, output)
    typer.echo(json.dumps(payload, indent=2))
    typer.echo(f"readiness_manifest_path={manifest_path}")
    typer.echo(f"readiness_manifest_sha256={digest}")
    typer.echo(f"readiness_manifest_hash_path={hash_path}")


@app.command("report")
def report(
    config: Path = typer.Option(Path("configs/settings.example.yaml"), "--config"),
    date: str | None = typer.Option(None, "--date", help="YYYY-MM-DD"),
    range_: str | None = typer.Option(
        None,
        "--range",
        help="UTC range format start:end (date-only) or start,end (full timestamps)",
    ),
) -> None:
    assert_python_runtime()
    settings = _load_runtime_settings(config)
    storage = StorageManager(Path(settings.storage_root))
    strikes = storage.load_events("strikes")
    signals = storage.load_events("signals")
    positions = storage.load_events("positions")

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
        range_value = range_.strip()
        if "," in range_value:
            start_raw, end_raw = range_value.split(",", 1)
        elif range_value.count(":") == 1:
            start_raw, end_raw = range_value.split(":", 1)
        else:
            raise ValueError(
                "--range format must be start:end (date-only) or start,end (timestamps)"
            )
        start_clean = start_raw.strip()
        end_clean = end_raw.strip()
        if not start_clean or not end_clean:
            raise ValueError(
                "--range format must include non-empty start and end values"
            )
        return ensure_utc_timestamp(start_clean), ensure_utc_timestamp(end_clean)
    return None, None


if __name__ == "__main__":
    app()
