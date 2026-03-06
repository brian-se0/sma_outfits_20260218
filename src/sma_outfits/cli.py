from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

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
from sma_outfits.data.storage import (
    StorageManager,
    legacy_case_collision_groups,
)
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
_ALPACA_BASIC_HISTORICAL_START_UTC = "2016-01-01T00:00:00Z"
_ALPACA_BASIC_HISTORICAL_DELAY_MINUTES = 15
_STRICT_CONFIG_PATH = Path(
    "configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml"
)
_CONTEXT_CONFIG_PATH = Path(
    "configs/settings.jan2025_confluence_atr_svix211_106_crossctx_context_v1.yaml"
)
_DEFAULT_CONFIG_PATH = _CONTEXT_CONFIG_PATH


def _load_runtime_settings(config: Path) -> Settings:
    return load_settings(config_path=config, env_path=Path(".env.local"))


def _slugify_token(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "custom"


def _config_profile_slug(config: Path | None) -> str:
    if config is None:
        return "context"
    normalized = str(config).replace("\\", "/").lower()
    if normalized == str(_STRICT_CONFIG_PATH).replace("\\", "/").lower():
        return "strict"
    if normalized == str(_CONTEXT_CONFIG_PATH).replace("\\", "/").lower():
        return "context"
    return _slugify_token(config.stem)


def _default_readiness_output(config: Path | None, filename: str) -> Path:
    return Path("artifacts/readiness") / _config_profile_slug(config) / filename


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
    serialized_with_trailing_newline = f"{serialized}\n"
    serialized_bytes = serialized_with_trailing_newline.encode("utf-8")
    output.write_bytes(serialized_bytes)
    digest = hashlib.sha256(serialized_bytes).hexdigest()
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


def _new_storage_manager(settings: Settings) -> StorageManager:
    return StorageManager(
        root=Path(settings.storage_root),
        events_root=Path(settings.events_root),
    )


_INTRADAY_TIMEFRAME_MINUTES = {
    "1m": 1,
    "2m": 2,
    "3m": 3,
    "5m": 5,
    "10m": 10,
    "15m": 15,
    "20m": 20,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
}


def _boundary_tolerance(
    *,
    timeframe: str,
    symbol: str,
    settings: Settings,
) -> pd.Timedelta:
    market = market_for_symbol(symbol, settings.universe.symbol_markets)
    intraday_minutes = _INTRADAY_TIMEFRAME_MINUTES.get(timeframe)
    if market == "stocks":
        if intraday_minutes is not None:
            if settings.sessions.regular_only and not settings.sessions.extended_enabled:
                return pd.Timedelta(hours=72)
            return pd.Timedelta(minutes=intraday_minutes * 2)
        if timeframe == "1D":
            return pd.Timedelta(days=4)
        if timeframe == "1W":
            return pd.Timedelta(days=10)
        if timeframe == "1M":
            return pd.Timedelta(days=40)
        if timeframe == "1Q":
            return pd.Timedelta(days=100)
        return pd.Timedelta(days=7)
    if intraday_minutes is not None:
        return pd.Timedelta(minutes=intraday_minutes * 2)
    if timeframe == "1D":
        return pd.Timedelta(days=2)
    if timeframe == "1W":
        return pd.Timedelta(days=10)
    if timeframe == "1M":
        return pd.Timedelta(days=40)
    if timeframe == "1Q":
        return pd.Timedelta(days=100)
    return pd.Timedelta(days=7)


def _gap_quality_metrics(
    *,
    bars: pd.DataFrame,
    symbol: str,
    timeframe: str,
    settings: Settings,
) -> tuple[int, float | None]:
    if bars.empty or len(bars) < 2:
        return 0, None
    market = market_for_symbol(symbol, settings.universe.symbol_markets)
    ts = pd.to_datetime(bars["ts"], utc=True).sort_values().reset_index(drop=True)
    if ts.empty:
        return 0, None

    if (
        market == "stocks"
        and settings.sessions.regular_only
        and not settings.sessions.extended_enabled
        and timeframe in _INTRADAY_TIMEFRAME_MINUTES
    ):
        timezone = settings.sessions.timezone
        local = ts.dt.tz_convert(timezone)
        deltas = local.diff().dropna()
        max_gap_minutes = (
            float((deltas.dt.total_seconds() / 60.0).max()) if not deltas.empty else None
        )
        # Alpaca/IEX trade bars are sparse for many symbols intraday, so
        # within-session minute continuity is not a reliable quality signal.
        # For regular-session readiness, treat missing business sessions as
        # the gap-quality failure mode and tolerate one business-day miss for
        # exchange holidays.
        local_dates = local.dt.normalize().drop_duplicates().reset_index(drop=True)
        unexpected_missing_business_days = 0
        for index in range(1, len(local_dates)):
            previous = pd.Timestamp(local_dates.iloc[index - 1])
            current = pd.Timestamp(local_dates.iloc[index])
            if current <= previous:
                continue
            start = previous + pd.Timedelta(days=1)
            end = current - pd.Timedelta(days=1)
            if start > end:
                continue
            missing_business_days = len(pd.bdate_range(start, end))
            if missing_business_days > 1:
                unexpected_missing_business_days += missing_business_days - 1
        return unexpected_missing_business_days, max_gap_minutes

    deltas = ts.diff().dropna()
    if deltas.empty:
        return 0, None
    delta_minutes = deltas.dt.total_seconds() / 60.0
    max_gap_minutes = float(delta_minutes.max())

    if market == "stocks" and timeframe == "1D":
        local_dates = ts.dt.tz_convert(settings.sessions.timezone).dt.normalize()
        unexpected_missing_business_days = 0
        for index in range(1, len(local_dates)):
            previous = pd.Timestamp(local_dates.iloc[index - 1])
            current = pd.Timestamp(local_dates.iloc[index])
            if current <= previous:
                continue
            start = previous + pd.Timedelta(days=1)
            end = current - pd.Timedelta(days=1)
            if start > end:
                continue
            missing_business_days = len(pd.bdate_range(start, end))
            # Tolerate one business-day miss for exchange holidays.
            if missing_business_days > 1:
                unexpected_missing_business_days += missing_business_days - 1
        return unexpected_missing_business_days, max_gap_minutes

    if market == "stocks" and timeframe == "1W":
        threshold_minutes = 10 * 24 * 60
        unexpected_count = int((delta_minutes > threshold_minutes).sum())
        return unexpected_count, max_gap_minutes
    if market == "stocks" and timeframe == "1M":
        threshold_minutes = 45 * 24 * 60
        unexpected_count = int((delta_minutes > threshold_minutes).sum())
        return unexpected_count, max_gap_minutes
    if market == "stocks" and timeframe == "1Q":
        threshold_minutes = 120 * 24 * 60
        unexpected_count = int((delta_minutes > threshold_minutes).sum())
        return unexpected_count, max_gap_minutes

    expected_minutes = _INTRADAY_TIMEFRAME_MINUTES.get(timeframe, 1440)
    threshold_minutes = expected_minutes * 2
    unexpected_count = int((delta_minutes > threshold_minutes).sum())
    return unexpected_count, max_gap_minutes


def _latest_run_manifest_path(archive_root: Path) -> Path | None:
    runs_root = archive_root / "runs"
    if not runs_root.exists():
        return None
    candidates = sorted(
        runs_root.glob("*/run_manifest.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _build_paper_hardening_init_payload(
    *,
    settings: Settings,
    config: Path,
) -> dict[str, object]:
    live = settings.live
    capabilities: dict[str, object] = {
        "state_persistence_enabled": bool(live.state_persistence_enabled),
        "state_file": str(live.state_file) if live.state_file else "default:<storage_root>/live_state.json",
        "state_flush_interval_seconds": float(live.state_flush_interval_seconds),
        "reconciliation_enabled": bool(live.reconciliation_enabled),
        "reconciliation_interval_seconds": float(live.reconciliation_interval_seconds),
        "stale_feed_seconds": int(live.stale_feed_seconds),
        "symbol_stale_threshold_seconds": int(live.symbol_stale_threshold_seconds),
        "data_gap_threshold_seconds": int(live.data_gap_threshold_seconds),
        # Known non-goals in the current implementation contract.
        "broker_order_submission_enabled": False,
        "fill_callback_processing_enabled": False,
        "drawdown_alerting_enabled": False,
    }

    blocking_gaps: list[dict[str, str]] = []
    if not bool(live.state_persistence_enabled):
        blocking_gaps.append(
            {
                "id": "state_persistence_disabled",
                "message": "Enable live.state_persistence_enabled for restart-safe paper runs.",
            }
        )
    if not bool(live.reconciliation_enabled):
        blocking_gaps.append(
            {
                "id": "reconciliation_disabled",
                "message": "Enable live.reconciliation_enabled for broker/state drift checks.",
            }
        )

    blocking_gaps.extend(
        [
            {
                "id": "missing_broker_order_submission",
                "message": "Implement broker paper order submission path in live execution.",
            },
            {
                "id": "missing_fill_callback_processing",
                "message": "Implement fill callback ingestion/reconciliation for paper fills.",
            },
            {
                "id": "missing_drawdown_alerting",
                "message": "Implement drawdown/stale-feed alert channel for unattended runs.",
            },
        ]
    )

    return {
        "status": "ok",
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "config": str(config),
        "profile_defaults": {
            "sessions_regular_only": bool(settings.sessions.regular_only),
            "trigger_mode": str(settings.strategy.trigger_mode),
            "strict_routing": bool(settings.strategy.strict_routing),
            "routes_count": len(settings.strategy.routes),
        },
        "capabilities": capabilities,
        "blocking_gaps": blocking_gaps,
        "next_commands": [
            "make run ACTION=phase2-preflight CONFIG_PROFILE=context",
            "make run ACTION=run-live CONFIG_PROFILE=context",
            (
                "make run ACTION=verify-readiness CONFIG_PROFILE=context "
                "START=<full_range_start> END=<readiness_end> "
                "UNIVERSE=all TIMEFRAME_SET=all"
            ),
        ],
    }


def _validate_run_manifest_payload(payload: dict[str, object]) -> list[str]:
    required_keys = {
        "status",
        "generated_at",
        "config",
        "stages_requested",
        "stage_outcomes",
        "resolved_windows",
        "paths",
        "artifact_hashes",
    }
    missing = [key for key in sorted(required_keys) if key not in payload]
    if missing:
        return missing
    stage_outcomes = payload.get("stage_outcomes")
    if not isinstance(stage_outcomes, dict):
        return ["stage_outcomes"]
    return []


def _write_coverage_artifacts(
    *,
    output: Path,
    coverage_rows: list[dict[str, object]],
    quality_payload: dict[str, object],
) -> tuple[Path, Path]:
    csv_path = output.with_name(output.stem + "_coverage_details.csv")
    json_path = output.with_name(output.stem + "_coverage_quality.json")
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "symbol",
        "timeframe",
        "rows_in_window",
        "window_min_ts",
        "window_max_ts",
        "start_gap_seconds",
        "end_gap_seconds",
        "boundary_tolerance_seconds",
        "boundary_ok",
        "non_monotonic",
        "duplicate_timestamps",
        "unexpected_gap_count",
        "max_gap_minutes",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in coverage_rows:
            writer.writerow({field: row.get(field) for field in fields})

    json_path.write_text(json.dumps(quality_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return csv_path, json_path


def _require_event_key(row: dict[str, object], *, event: str, key: str) -> str:
    if key not in row:
        raise RuntimeError(
            "Event file contract violation: "
            f"'{key}' missing in {event}.jsonl row"
        )
    value = row[key]
    if value is None:
        raise RuntimeError(
            "Event file contract violation: "
            f"'{key}' cannot be null in {event}.jsonl row"
        )
    return str(value)


def _load_summary_event_rows(
    *,
    storage: StorageManager,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    if start is None or end is None:
        return (
            storage.load_events("strikes"),
            storage.load_events("signals"),
            storage.load_events("positions"),
        )

    strikes_all = storage.load_events("strikes")
    positions_all = storage.load_events("positions")

    strike_ids_in_window: set[str] = set()
    for row in strikes_all:
        bar_ts = ensure_utc_timestamp(
            _require_event_key(row, event="strikes", key="bar_ts")
        )
        if start <= bar_ts <= end:
            strike_ids_in_window.add(_require_event_key(row, event="strikes", key="id"))

    close_signal_ids_in_window: set[str] = set()
    for row in positions_all:
        action = _require_event_key(row, event="positions", key="action")
        if action != "close":
            continue
        close_ts = ensure_utc_timestamp(
            _require_event_key(row, event="positions", key="ts")
        )
        if start <= close_ts <= end:
            close_signal_ids_in_window.add(
                _require_event_key(row, event="positions", key="signal_id")
            )

    signal_filters: dict[str, set[str]] = {}
    if strike_ids_in_window:
        signal_filters["strike_id"] = strike_ids_in_window
    if close_signal_ids_in_window:
        signal_filters["id"] = close_signal_ids_in_window

    selected_signals = (
        storage.load_events("signals", id_filters=signal_filters)
        if signal_filters
        else []
    )
    selected_signal_ids = {
        _require_event_key(row, event="signals", key="id")
        for row in selected_signals
    }
    selected_strike_ids = strike_ids_in_window.union(
        {
            _require_event_key(row, event="signals", key="strike_id")
            for row in selected_signals
        }
    )

    selected_strikes = [
        row
        for row in strikes_all
        if _require_event_key(row, event="strikes", key="id") in selected_strike_ids
    ]
    selected_positions = [
        row
        for row in positions_all
        if _require_event_key(row, event="positions", key="signal_id")
        in selected_signal_ids
    ]
    return selected_strikes, selected_signals, selected_positions


def _build_regime_proxy_monthly_vol(
    *,
    storage: StorageManager,
    settings: Settings,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> dict[str, float]:
    proxy_symbol = settings.validation.regime.proxy_symbol
    proxy_timeframe = settings.validation.regime.proxy_timeframe
    bars = storage.read_bars(
        symbol=proxy_symbol,
        timeframe=proxy_timeframe,
        start=start,
        end=end,
    )
    if bars.empty:
        return {}

    close_series = pd.to_numeric(bars["close"], errors="coerce")
    if bool(close_series.isna().any()):
        raise RuntimeError(
            "Regime proxy bar contract violation: non-numeric close values for "
            f"{proxy_symbol}/{proxy_timeframe}"
        )

    proxy_frame = pd.DataFrame(
        {
            "ts": pd.to_datetime(bars["ts"], utc=True),
            "close_return": close_series.pct_change(),
        }
    ).dropna(subset=["close_return"])
    if proxy_frame.empty:
        return {}

    for value in proxy_frame["close_return"]:
        if not math.isfinite(float(value)):
            raise RuntimeError(
                "Regime proxy bar contract violation: non-finite pct_change(close) for "
                f"{proxy_symbol}/{proxy_timeframe}"
            )

    proxy_frame["month_key"] = proxy_frame["ts"].dt.strftime("%Y-%m")
    month_std = proxy_frame.groupby("month_key", sort=True)["close_return"].std()
    regime_proxy_monthly_vol: dict[str, float] = {}
    for month, raw_value in month_std.items():
        if pd.isna(raw_value):
            continue
        candidate = float(raw_value)
        if not math.isfinite(candidate):
            raise RuntimeError(
                "Regime proxy bar contract violation: monthly volatility must be finite for "
                f"{proxy_symbol}/{proxy_timeframe} month={month}"
            )
        regime_proxy_monthly_vol[str(month)] = candidate
    return regime_proxy_monthly_vol


@app.command("validate-config")
def validate_config(
    config: Path = typer.Option(
        _DEFAULT_CONFIG_PATH,
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
        _DEFAULT_CONFIG_PATH,
        "--config",
        help="Optional config for universe/timeframes/session defaults",
    ),
    symbols: str = typer.Option("", "--symbols", help="CSV symbols override"),
    timeframes: str = typer.Option("", "--timeframes", help="CSV timeframes override"),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Output manifest path",
    ),
    start: str = typer.Option(
        _ALPACA_BASIC_HISTORICAL_START_UTC,
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
    end_ts = (
        ensure_utc_timestamp(end)
        if end is not None
        else (
            pd.Timestamp.now(tz="UTC")
            - pd.Timedelta(minutes=_ALPACA_BASIC_HISTORICAL_DELAY_MINUTES)
        )
    )
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
    # Readiness coverage checks require a start that is valid for every pair.
    # Use the latest discovered earliest timestamp across all pairs so no
    # pair is forced before its own available history boundary.
    full_range_start = max(
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
    resolved_output = output or _default_readiness_output(
        config,
        "discovered_range_manifest.json",
    )
    manifest_path, hash_path, digest = _write_json_with_hash(payload, resolved_output)
    typer.echo(json.dumps(payload, indent=2))
    typer.echo(f"manifest_path={manifest_path}")
    typer.echo(f"manifest_sha256={digest}")
    typer.echo(f"manifest_hash_path={hash_path}")


@app.command("backfill")
def backfill(
    config: Path = typer.Option(_DEFAULT_CONFIG_PATH, "--config"),
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
    storage = _new_storage_manager(settings)
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
    config: Path = typer.Option(_DEFAULT_CONFIG_PATH, "--config"),
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
    storage = _new_storage_manager(settings)
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
            data_gaps_detected = int(payload["data_gaps_detected"])
            stale_symbol_warnings = int(payload["stale_symbol_warnings"])
            reconciliation_checks = int(payload["reconciliation_checks"])
            reconciliation_mismatches = int(payload["reconciliation_mismatches"])
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
                f"gaps={data_gaps_detected} stale_sym={stale_symbol_warnings} "
                f"recon={reconciliation_mismatches}/{reconciliation_checks} "
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
            "data_gaps_detected": result.data_gaps_detected,
            "stale_symbol_warnings": result.stale_symbol_warnings,
            "reconciliation_checks": result.reconciliation_checks,
            "reconciliation_mismatches": result.reconciliation_mismatches,
            "started_at": result.started_at.isoformat(),
            "ended_at": result.ended_at.isoformat(),
        }
    )
    typer.echo(json.dumps(payload, indent=2))


@app.command("replay")
def replay(
    config: Path = typer.Option(_DEFAULT_CONFIG_PATH, "--config"),
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
    storage = _new_storage_manager(settings)
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
    regime_proxy_monthly_vol = _build_regime_proxy_monthly_vol(
        storage=storage,
        settings=settings,
        start=start_ts,
        end=end_ts,
    )
    summary = build_summary_from_records(
        strike_rows=[event_to_record(event) for event in result.strikes],
        signal_rows=[event_to_record(event) for event in result.signals],
        position_rows=[event_to_record(event) for event in result.position_events],
        start=start_ts,
        end=end_ts,
        validation=settings.validation,
        execution_costs=settings.execution_costs,
        citations=settings.citations,
        regime_proxy_monthly_vol=regime_proxy_monthly_vol,
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
    config: Path = typer.Option(_DEFAULT_CONFIG_PATH, "--config"),
    start: str = typer.Option(..., "--start", help="UTC start timestamp"),
    end: str = typer.Option(..., "--end", help="UTC end timestamp"),
    symbols: str = typer.Option("", "--symbols", help="CSV symbols override"),
    timeframes: str = typer.Option("", "--timeframes", help="CSV timeframes override"),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Output readiness acceptance manifest path",
    ),
    require_report_artifacts: bool = typer.Option(
        True,
        "--require-report-artifacts/--no-require-report-artifacts",
        help="Require at least one report artifact under archive/reports",
    ),
    require_boundary_coverage: bool = typer.Option(
        True,
        "--require-boundary-coverage/--no-require-boundary-coverage",
        help="Require each pair to satisfy timeframe-aware start/end coverage tolerances",
    ),
    require_gap_quality: bool = typer.Option(
        True,
        "--require-gap-quality/--no-require-gap-quality",
        help="Require session-aware gap quality checks to pass for all pairs",
    ),
    require_run_manifest: bool = typer.Option(
        True,
        "--require-run-manifest/--no-require-run-manifest",
        help="Require a complete archive/runs/*/run_manifest.json",
    ),
    require_academic_validation: bool = typer.Option(
        True,
        "--require-academic-validation/--no-require-academic-validation",
        help="Require strict academic validation gate from summary appendix outputs",
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

    storage = _new_storage_manager(settings)
    missing_pairs: list[str] = []
    monotonicity_failures: list[str] = []
    boundary_failures: list[str] = []
    gap_quality_failures: list[str] = []
    coverage_rows: list[dict[str, object]] = []
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
            non_monotonic = not bool(ts.is_monotonic_increasing)
            duplicate_ts = bool(ts.duplicated().any())
            min_ts = pd.Timestamp(ts.iloc[0]).tz_convert("UTC")
            max_ts = pd.Timestamp(ts.iloc[-1]).tz_convert("UTC")
            start_gap_seconds = max(0.0, (min_ts - start_ts).total_seconds())
            end_gap_seconds = max(0.0, (end_ts - max_ts).total_seconds())
            boundary_tolerance = _boundary_tolerance(
                timeframe=timeframe,
                symbol=symbol,
                settings=settings,
            )
            boundary_ok = (
                start_gap_seconds <= boundary_tolerance.total_seconds()
                and end_gap_seconds <= boundary_tolerance.total_seconds()
            )
            unexpected_gap_count, max_gap_minutes = _gap_quality_metrics(
                bars=bars,
                symbol=symbol,
                timeframe=timeframe,
                settings=settings,
            )

            if not bool(ts.is_monotonic_increasing):
                monotonicity_failures.append(f"{symbol}/{timeframe}:non_monotonic")
            if bool(ts.duplicated().any()):
                monotonicity_failures.append(f"{symbol}/{timeframe}:duplicate_ts")
            if not boundary_ok:
                boundary_failures.append(
                    (
                        f"{symbol}/{timeframe}: start_gap_seconds={start_gap_seconds:.0f} "
                        f"end_gap_seconds={end_gap_seconds:.0f} "
                        f"tolerance_seconds={boundary_tolerance.total_seconds():.0f}"
                    )
                )
            if unexpected_gap_count > 0:
                gap_quality_failures.append(
                    (
                        f"{symbol}/{timeframe}: unexpected_gap_count={unexpected_gap_count} "
                        f"max_gap_minutes={max_gap_minutes if max_gap_minutes is not None else 'unknown'}"
                    )
                )

            coverage_rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "rows_in_window": int(len(bars)),
                    "window_min_ts": min_ts.isoformat(),
                    "window_max_ts": max_ts.isoformat(),
                    "start_gap_seconds": round(start_gap_seconds, 3),
                    "end_gap_seconds": round(end_gap_seconds, 3),
                    "boundary_tolerance_seconds": boundary_tolerance.total_seconds(),
                    "boundary_ok": boundary_ok,
                    "non_monotonic": non_monotonic,
                    "duplicate_timestamps": duplicate_ts,
                    "unexpected_gap_count": unexpected_gap_count,
                    "max_gap_minutes": max_gap_minutes,
                }
            )

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

    quality_payload: dict[str, object] = {
        "status": "ok",
        "checked_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "config": str(config),
        "start": start_ts.isoformat(),
        "end": end_ts.isoformat(),
        "pairs_checked": checked_pairs,
        "boundary_failures": sorted(boundary_failures),
        "gap_quality_failures": sorted(gap_quality_failures),
    }
    resolved_output = output or _default_readiness_output(
        config,
        "readiness_acceptance.json",
    )
    coverage_csv_path, coverage_quality_path = _write_coverage_artifacts(
        output=resolved_output,
        coverage_rows=coverage_rows,
        quality_payload=quality_payload,
    )

    if require_boundary_coverage and boundary_failures:
        preview = ", ".join(sorted(boundary_failures)[:8])
        raise RuntimeError(
            "Readiness acceptance failed: boundary coverage violations for pairs "
            + preview
            + ". "
            + f"Coverage details: {coverage_csv_path}"
        )
    if require_gap_quality and gap_quality_failures:
        preview = ", ".join(sorted(gap_quality_failures)[:8])
        raise RuntimeError(
            "Readiness acceptance failed: unexpected gap quality violations for pairs "
            + preview
            + ". "
            + f"Gap quality details: {coverage_quality_path}"
        )

    run_manifest_path: Path | None = None
    archive_root = Path(settings.archive.root)
    if require_run_manifest:
        run_manifest_path = _latest_run_manifest_path(archive_root)
        if run_manifest_path is None:
            raise RuntimeError(
                "Readiness acceptance failed: no run manifest found under "
                f"{archive_root / 'runs'}"
            )
        try:
            manifest_payload = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Readiness acceptance failed: invalid run manifest JSON at "
                f"{run_manifest_path}: {exc}"
            ) from exc
        if not isinstance(manifest_payload, dict):
            raise RuntimeError(
                "Readiness acceptance failed: run manifest must be a JSON object at "
                f"{run_manifest_path}"
            )
        manifest_missing = _validate_run_manifest_payload(manifest_payload)
        if manifest_missing:
            raise RuntimeError(
                "Readiness acceptance failed: run manifest missing required keys "
                + ", ".join(sorted(manifest_missing))
                + f" at {run_manifest_path}"
            )

    strikes, signals, positions = _load_summary_event_rows(
        storage=storage,
        start=start_ts,
        end=end_ts,
    )
    regime_proxy_monthly_vol = _build_regime_proxy_monthly_vol(
        storage=storage,
        settings=settings,
        start=start_ts,
        end=end_ts,
    )
    summary = build_summary_from_records(
        strike_rows=strikes,
        signal_rows=signals,
        position_rows=positions,
        start=start_ts,
        end=end_ts,
        validation=settings.validation,
        execution_costs=settings.execution_costs,
        citations=settings.citations,
        regime_proxy_monthly_vol=regime_proxy_monthly_vol,
    )
    academic_validation = summary.get("academic_validation")
    if not isinstance(academic_validation, dict):
        raise RuntimeError(
            "Readiness acceptance failed: summary contract missing academic_validation payload"
        )
    academic_ready = bool(academic_validation.get("ready", False))
    academic_blocking_reasons = academic_validation.get("blocking_reasons", [])
    if not isinstance(academic_blocking_reasons, list):
        academic_blocking_reasons = []
    if require_academic_validation and not academic_ready:
        raise RuntimeError(
            "Readiness acceptance failed: academic validation gate failed: "
            + (
                ", ".join(str(reason) for reason in academic_blocking_reasons)
                if academic_blocking_reasons
                else "unknown_reason"
            )
        )

    report_root = Path(settings.archive.root) / "reports"
    report_files = sorted(
        [
            *report_root.glob("*.md"),
            *report_root.glob("*.csv"),
            *report_root.glob("*.json"),
            *(report_root / "figures").glob("*.png"),
        ]
    )
    if require_report_artifacts and not report_files:
        raise RuntimeError(
            "Readiness acceptance failed: no report artifacts found in "
            f"{report_root}"
        )

    events_root = Path(settings.events_root)
    hash_files: list[Path] = []
    for path in sorted(
        [
            events_root / "strikes.jsonl",
            events_root / "signals.jsonl",
            events_root / "positions.jsonl",
            coverage_csv_path,
            coverage_quality_path,
            *report_files,
        ]
    ):
        if path.exists() and path.is_file():
            hash_files.append(path)
    if run_manifest_path is not None and run_manifest_path.exists():
        hash_files.append(run_manifest_path)

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
        "boundary_failures_count": len(boundary_failures),
        "gap_quality_failures_count": len(gap_quality_failures),
        "coverage_details_csv": str(coverage_csv_path),
        "coverage_quality_json": str(coverage_quality_path),
        "run_manifest_path": str(run_manifest_path) if run_manifest_path is not None else None,
        "summary_snapshot": {
            "total_strikes": summary["strike_attribution"]["total_strikes"],
            "total_signals": summary["strike_attribution"]["total_signals"],
            "closed_positions": summary["strike_attribution"]["closed_positions"],
            "attribution_mode": summary["attribution_mode"],
        },
        "academic_validation": {
            "ready": academic_ready,
            "blocking_reasons": academic_blocking_reasons,
            "fold_count": int(academic_validation.get("fold_count", 0)),
            "min_fold_trade_count": int(academic_validation.get("min_fold_trade_count", 0)),
            "wfo_feasibility": academic_validation.get("wfo_feasibility", {}),
            "bootstrap_p_value": academic_validation.get("bootstrap_p_value"),
            "fdr_summary": academic_validation.get("fdr_summary", {}),
        },
        "artifact_hashes": hashes,
    }
    manifest_path, hash_path, digest = _write_json_with_hash(payload, resolved_output)
    typer.echo(json.dumps(payload, indent=2))
    typer.echo(f"readiness_manifest_path={manifest_path}")
    typer.echo(f"readiness_manifest_sha256={digest}")
    typer.echo(f"readiness_manifest_hash_path={hash_path}")


@app.command("paper-hardening-init")
def paper_hardening_init(
    config: Path = typer.Option(_DEFAULT_CONFIG_PATH, "--config"),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Output Part-2 hardening scaffold manifest path",
    ),
) -> None:
    assert_python_runtime()
    settings = _load_runtime_settings(config)
    payload = _build_paper_hardening_init_payload(
        settings=settings,
        config=config,
    )
    resolved_output = output or _default_readiness_output(
        config,
        "paper_hardening_init.json",
    )
    manifest_path, hash_path, digest = _write_json_with_hash(payload, resolved_output)
    typer.echo(json.dumps(payload, indent=2))
    typer.echo(f"paper_hardening_init_path={manifest_path}")
    typer.echo(f"paper_hardening_init_sha256={digest}")
    typer.echo(f"paper_hardening_init_hash_path={hash_path}")


@app.command("report")
def report(
    config: Path = typer.Option(_DEFAULT_CONFIG_PATH, "--config"),
    date: str | None = typer.Option(None, "--date", help="YYYY-MM-DD"),
    range_: str | None = typer.Option(
        None,
        "--range",
        help="UTC range format start:end (date-only) or start,end (full timestamps)",
    ),
) -> None:
    assert_python_runtime()
    settings = _load_runtime_settings(config)
    storage = _new_storage_manager(settings)
    start_ts, end_ts = _resolve_report_range(date, range_)
    strikes, signals, positions = _load_summary_event_rows(
        storage=storage,
        start=start_ts,
        end=end_ts,
    )
    regime_proxy_monthly_vol = _build_regime_proxy_monthly_vol(
        storage=storage,
        settings=settings,
        start=start_ts,
        end=end_ts,
    )
    summary = build_summary_from_records(
        strike_rows=strikes,
        signal_rows=signals,
        position_rows=positions,
        start=start_ts,
        end=end_ts,
        validation=settings.validation,
        execution_costs=settings.execution_costs,
        citations=settings.citations,
        regime_proxy_monthly_vol=regime_proxy_monthly_vol,
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


@app.command("write-run-manifest")
def write_run_manifest(
    config: Path = typer.Option(_DEFAULT_CONFIG_PATH, "--config"),
    profile: str = typer.Option("custom", "--profile"),
    stages: str = typer.Option(
        "validate-config,backfill,replay,report",
        "--stages",
        help="CSV stage list requested by orchestrator",
    ),
    analysis_start: str = typer.Option(..., "--analysis-start"),
    analysis_end: str = typer.Option(..., "--analysis-end"),
    warmup_days: int = typer.Option(..., "--warmup-days"),
    warmup_start: str = typer.Option(..., "--warmup-start"),
    backfill_start: str = typer.Option(..., "--backfill-start"),
    backfill_end: str = typer.Option(..., "--backfill-end"),
    replay_start: str = typer.Option(..., "--replay-start"),
    replay_end: str = typer.Option(..., "--replay-end"),
    report_range: str = typer.Option("", "--report-range"),
    symbols: str = typer.Option("", "--symbols"),
    timeframes: str = typer.Option("", "--timeframes"),
    command: str = typer.Option("", "--command"),
    run_id: str | None = typer.Option(None, "--run-id"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    assert_python_runtime()
    settings = _load_runtime_settings(config)

    requested_stages = dedupe_keep_order(parse_csv(stages))
    valid_stages = ["validate-config", "backfill", "replay", "report"]
    invalid = [stage for stage in requested_stages if stage not in valid_stages]
    if invalid:
        raise ValueError(
            "Unsupported stage(s) for write-run-manifest: "
            + ", ".join(invalid)
        )
    stage_outcomes = {
        stage: ("completed" if stage in requested_stages else "skipped")
        for stage in valid_stages
    }

    archive_root = Path(settings.archive.root)
    generated_at = pd.Timestamp.now(tz="UTC")
    effective_run_id = run_id or generated_at.strftime("%Y%m%dT%H%M%SZ")
    manifest_path = output or archive_root / "runs" / effective_run_id / "run_manifest.json"

    git_sha: str | None = None
    try:
        git_sha = (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                cwd=Path.cwd(),
            )
            .stdout.strip()
            or None
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        git_sha = None

    events_root = Path(settings.events_root)
    reports_root = archive_root / "reports"
    threads_root = archive_root / "threads"
    events_files = sorted(events_root.glob("*.jsonl")) if events_root.exists() else []
    report_files = sorted(
        [
            *reports_root.glob("*.md"),
            *reports_root.glob("*.csv"),
            *reports_root.glob("*.json"),
            *(reports_root / "figures").glob("*.png"),
        ]
    )
    thread_files = sorted(threads_root.glob("*.md")) if threads_root.exists() else []
    artifact_hashes: dict[str, str] = {}
    for path in sorted([*events_files, *report_files]):
        artifact_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()

    payload: dict[str, object] = {
        "status": "ok",
        "generated_at": generated_at.isoformat(),
        "config": str(config),
        "git_sha": git_sha,
        "profile": profile,
        "command": command,
        "stages_requested": requested_stages,
        "stage_outcomes": stage_outcomes,
        "resolved_windows": {
            "analysis_start": ensure_utc_timestamp(analysis_start).isoformat(),
            "analysis_end": ensure_utc_timestamp(analysis_end).isoformat(),
            "warmup_days": warmup_days,
            "warmup_start": ensure_utc_timestamp(warmup_start).isoformat(),
            "backfill_start": ensure_utc_timestamp(backfill_start).isoformat(),
            "backfill_end": ensure_utc_timestamp(backfill_end).isoformat(),
            "replay_start": ensure_utc_timestamp(replay_start).isoformat(),
            "replay_end": ensure_utc_timestamp(replay_end).isoformat(),
            "report_range": report_range,
        },
        "symbols": dedupe_keep_order([value.upper() for value in parse_csv(symbols)]),
        "timeframes": dedupe_keep_order(parse_csv(timeframes)),
        "paths": {
            "archive_root": str(archive_root),
            "storage_root": str(settings.storage_root),
            "events_root": str(events_root),
            "reports_root": str(reports_root),
            "threads_root": str(threads_root),
        },
        "artifacts": {
            "events": [str(path) for path in events_files],
            "reports": [str(path) for path in report_files],
            "threads": [str(path) for path in thread_files],
        },
        "artifact_hashes": artifact_hashes,
    }

    manifest_written, hash_path, digest = _write_json_with_hash(payload, manifest_path)
    typer.echo(json.dumps(payload, indent=2))
    typer.echo(f"run_manifest_path={manifest_written}")
    typer.echo(f"run_manifest_sha256={digest}")
    typer.echo(f"run_manifest_hash_path={hash_path}")


@app.command("migrate-storage-layout")
def migrate_storage_layout(
    config: Path = typer.Option(_DEFAULT_CONFIG_PATH, "--config"),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Preview or apply legacy timeframe directory migration",
    ),
) -> None:
    assert_python_runtime()
    settings = _load_runtime_settings(config)
    storage = _new_storage_manager(settings)
    report = storage.migrate_legacy_timeframe_layout(dry_run=dry_run)
    report["legacy_case_collision_groups"] = legacy_case_collision_groups()
    typer.echo(json.dumps(report, indent=2))
    if report.get("status") != "ok":
        raise RuntimeError(
            "Storage migration blocked due to ambiguous legacy timeframe directories. "
            "Clean the affected timeframe directories and rerun backfill."
        )


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
