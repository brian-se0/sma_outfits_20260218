from __future__ import annotations

from datetime import date
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from sma_outfits.utils import SUPPORTED_TIMEFRAMES

DEFAULT_SYMBOLS = [
    "SPY",
    "QQQ",
    "DIA",
    "UPRO",
    "TQQQ",
    "SQQQ",
    "UDOW",
    "SDOW",
    "SOXL",
    "SOXS",
    "SVIX",
    "VIXY",
    "XLF",
    "JPM",
    "NVDA",
    "TSLA",
    "AMD",
    "GME",
    "RWM",
    "SMH",
    "FAS",
    "FAZ",
    "BTC/USD",
    "ETH/USD",
]

DEFAULT_PROXY_MAP = {
    "SPX": "SPY",
    "IXIC": "QQQ",
    "NDX": "QQQ",
    "DJI": "DIA",
    "VIX": "VIXY",
}

DEFAULT_SYMBOL_MARKETS = {
    "SPY": "stocks",
    "QQQ": "stocks",
    "DIA": "stocks",
    "UPRO": "stocks",
    "TQQQ": "stocks",
    "SQQQ": "stocks",
    "UDOW": "stocks",
    "SDOW": "stocks",
    "SOXL": "stocks",
    "SOXS": "stocks",
    "SVIX": "stocks",
    "VIXY": "stocks",
    "XLF": "stocks",
    "JPM": "stocks",
    "NVDA": "stocks",
    "TSLA": "stocks",
    "AMD": "stocks",
    "GME": "stocks",
    "RWM": "stocks",
    "SMH": "stocks",
    "FAS": "stocks",
    "FAZ": "stocks",
    "BTC/USD": "crypto",
    "ETH/USD": "crypto",
}

DEFAULT_LIVE_TIMEFRAMES = [
    "1m",
    "2m",
    "3m",
    "5m",
    "10m",
    "15m",
    "20m",
    "30m",
    "1h",
    "2h",
    "4h",
    "1D",
]

DEFAULT_DERIVED_TIMEFRAMES = ["1W", "1M", "1Q"]
DEFAULT_RESAMPLE_ANCHORS = {"1W": "W-FRI", "1M": "ME", "1Q": "QE"}
DEFAULT_STRATEGY_ROUTES = [
    {
        "id": "qqq_1h_author",
        "symbol": "QQQ",
        "timeframe": "1h",
        "outfit_id": "base2_nvda",
        "key_period": 512,
        "side": "LONG",
        "signal_type": "optimized_buy",
        "micro_periods": [16, 32, 64, 128, 256],
        "ignore_close_below_key_when_micro_positive": True,
        "macro_gate": "nas",
        "risk_mode": "singular_penny_only",
        "stop_offset": 0.01,
    },
    {
        "id": "rwm_30m_author",
        "symbol": "RWM",
        "timeframe": "30m",
        "outfit_id": "svix_211",
        "key_period": 844,
        "side": "LONG",
        "signal_type": "magnetized_buy",
        "micro_periods": [26, 52, 116, 211, 422],
        "ignore_close_below_key_when_micro_positive": False,
        "macro_gate": "none",
        "risk_mode": "singular_penny_only",
        "stop_offset": 0.01,
    },
]

REQUIRED_ENV_KEYS = (
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "ALPACA_BASE_URL",
    "ALPACA_DATA_URL",
    "ALPACA_DATA_FEED",
)


class AlpacaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str
    secret_key: str
    base_url: str = "https://paper-api.alpaca.markets"
    data_url: str = "https://data.alpaca.markets"
    data_feed: str = "iex"
    adjustment: str = "raw"
    asof: str = "2025-01-01"
    crypto_loc: str = "us"

    @field_validator(
        "api_key",
        "secret_key",
        "base_url",
        "data_url",
        "data_feed",
        "adjustment",
        "crypto_loc",
    )
    @classmethod
    def _non_empty(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            raise ValueError("value must be non-empty")
        return candidate

    @field_validator("base_url", "data_url")
    @classmethod
    def _validate_host_only_url(cls, value: str, info: ValidationInfo) -> str:
        candidate = value.strip()
        parsed = urlparse(candidate)
        field_name = info.field_name or "url"
        field_path = f"alpaca.{field_name}"

        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"{field_path} must be an absolute http(s) URL")
        if parsed.params or parsed.query or parsed.fragment:
            raise ValueError(f"{field_path} must not include params, query, or fragment")
        if parsed.path not in {"", "/"}:
            raise ValueError(
                f"{field_path} must be host-only (no path). "
                "Use values like https://paper-api.alpaca.markets and "
                "https://data.alpaca.markets"
            )
        return f"{parsed.scheme}://{parsed.netloc}"

    @field_validator("asof")
    @classmethod
    def _validate_asof_date(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            raise ValueError("alpaca.asof must be non-empty YYYY-MM-DD")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate) is None:
            raise ValueError("alpaca.asof must be valid YYYY-MM-DD")
        try:
            date.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError("alpaca.asof must be valid YYYY-MM-DD") from exc
        return candidate


class UniverseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbols: list[str] = Field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    proxy_map: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_PROXY_MAP))
    symbol_markets: dict[str, Literal["stocks", "crypto"]] = Field(
        default_factory=lambda: dict(DEFAULT_SYMBOL_MARKETS)
    )

    @field_validator("symbols")
    @classmethod
    def _validate_symbols(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("at least one symbol is required")
        cleaned: list[str] = []
        for value in values:
            symbol = value.strip().upper()
            if not symbol:
                raise ValueError("symbols cannot include empty values")
            cleaned.append(symbol)
        return cleaned

    @field_validator("symbol_markets")
    @classmethod
    def _validate_symbol_markets(
        cls,
        values: dict[str, Literal["stocks", "crypto"]],
    ) -> dict[str, Literal["stocks", "crypto"]]:
        if not values:
            raise ValueError("universe.symbol_markets cannot be empty")
        normalized: dict[str, Literal["stocks", "crypto"]] = {}
        for raw_symbol, raw_market in values.items():
            symbol = str(raw_symbol).strip().upper()
            if not symbol:
                raise ValueError("universe.symbol_markets cannot include empty symbol keys")
            market = str(raw_market).strip().lower()
            if market not in {"stocks", "crypto"}:
                raise ValueError(
                    "universe.symbol_markets values must be one of: stocks, crypto"
                )
            if market == "stocks":
                normalized[symbol] = "stocks"
            else:
                normalized[symbol] = "crypto"
        return normalized

    @model_validator(mode="after")
    def _validate_symbol_market_coverage(self) -> UniverseConfig:
        missing = [symbol for symbol in self.symbols if symbol not in self.symbol_markets]
        if missing:
            raise ValueError(
                "universe.symbol_markets is missing entries for symbols: "
                + ", ".join(sorted(missing))
            )
        return self


class SessionsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regular_only: bool = True
    extended_enabled: bool = False
    timezone: str = "America/New_York"


class TimeframesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    live: list[str] = Field(default_factory=lambda: list(DEFAULT_LIVE_TIMEFRAMES))
    derived: list[str] = Field(default_factory=lambda: list(DEFAULT_DERIVED_TIMEFRAMES))
    anchors: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_RESAMPLE_ANCHORS))

    @field_validator("live", "derived")
    @classmethod
    def _validate_timeframes(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("timeframe list cannot be empty")
        out: list[str] = []
        for value in values:
            candidate = value.strip()
            if candidate not in SUPPORTED_TIMEFRAMES:
                raise ValueError(
                    f"Unsupported timeframe '{candidate}'. Supported: {SUPPORTED_TIMEFRAMES}"
                )
            out.append(candidate)
        return out

    @field_validator("anchors")
    @classmethod
    def _validate_anchors(cls, values: dict[str, str]) -> dict[str, str]:
        required = {"1W", "1M", "1Q"}
        normalized: dict[str, str] = {}
        for raw_timeframe, raw_rule in values.items():
            timeframe = str(raw_timeframe).strip()
            if timeframe not in required:
                raise ValueError(
                    "timeframes.anchors keys must be exactly: 1W, 1M, 1Q"
                )
            rule = str(raw_rule).strip()
            if not rule:
                raise ValueError(
                    f"timeframes.anchors[{timeframe}] must be a non-empty pandas offset rule"
                )
            normalized[timeframe] = rule
        missing = sorted(required.difference(normalized.keys()))
        if missing:
            raise ValueError(
                "timeframes.anchors is missing required keys: " + ", ".join(missing)
            )
        return normalized


class SignalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tolerance: float = 0.01
    trigger_mode: str = "bar_touch"
    volatility_percentile_threshold: float = 75.0

    @field_validator("tolerance")
    @classmethod
    def _positive_tolerance(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("signal.tolerance must be > 0")
        return value


class RouteRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    symbol: str
    timeframe: str
    outfit_id: str
    key_period: int
    side: Literal["LONG", "SHORT"]
    signal_type: Literal[
        "precision_buy",
        "optimized_buy",
        "magnetized_buy",
        "automated_short",
    ]
    micro_periods: list[int]
    ignore_close_below_key_when_micro_positive: bool = False
    macro_gate: Literal["none", "spx", "nas", "dji"] = "none"
    risk_mode: Literal["singular_penny_only"] = "singular_penny_only"
    stop_offset: float = 0.01

    @field_validator("id", "outfit_id")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            raise ValueError("route value must be non-empty")
        return candidate

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, value: str) -> str:
        candidate = value.strip().upper()
        if not candidate:
            raise ValueError("strategy route symbol must be non-empty")
        return candidate

    @field_validator("timeframe")
    @classmethod
    def _validate_route_timeframe(cls, value: str) -> str:
        candidate = value.strip()
        if candidate not in SUPPORTED_TIMEFRAMES:
            raise ValueError(
                f"Unsupported route timeframe '{candidate}'. Supported: {SUPPORTED_TIMEFRAMES}"
            )
        return candidate

    @field_validator("key_period")
    @classmethod
    def _validate_key_period(cls, value: int) -> int:
        if value < 1 or value > 999:
            raise ValueError("strategy route key_period must be within [1, 999]")
        return value

    @field_validator("micro_periods")
    @classmethod
    def _validate_micro_periods(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("strategy route micro_periods must be non-empty")
        out: list[int] = []
        for period in value:
            if isinstance(period, bool) or not isinstance(period, int):
                raise ValueError("strategy route micro_periods must contain integers only")
            if period < 1 or period > 999:
                raise ValueError("strategy route micro_periods must be within [1, 999]")
            out.append(period)
        return out

    @field_validator("stop_offset")
    @classmethod
    def _validate_stop_offset(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("strategy route stop_offset must be > 0")
        return value


def _default_strategy_routes() -> list[RouteRule]:
    return [RouteRule.model_validate(route) for route in DEFAULT_STRATEGY_ROUTES]


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["author_v1"] = "author_v1"
    price_basis: Literal["ohlc4", "close"] = "ohlc4"
    trigger_mode: Literal["close_touch_or_cross"] = "close_touch_or_cross"
    strict_routing: bool = True
    allow_same_bar_exit: bool = False
    ambiguity_policy: Literal["fail"] = "fail"
    routes: list[RouteRule] = Field(default_factory=_default_strategy_routes)


class RiskMigrationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proxy_symbol: str
    break_level: float
    mode: Literal["below", "above"] = "below"
    offset: float = 0.01


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    long_break: float = 0.01
    short_break: float = 0.01
    partial_take_r: float = 1.0
    final_take_r: float = 3.0
    timeout_bars: int = 120
    migrations: dict[str, RiskMigrationConfig] = Field(default_factory=dict)

    @field_validator("timeout_bars")
    @classmethod
    def _timeout_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("risk.timeout_bars must be > 0")
        return value


class ArchiveConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    root: str = "artifacts"


class IngestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    empty_source_policy: Literal["fail"] = "fail"


class LiveConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_minutes: int | None = None
    warmup_minutes: int = 480
    reconnect_max_attempts: int = 8
    reconnect_base_delay_seconds: float = 1.0
    reconnect_max_delay_seconds: float = 30.0
    stale_feed_seconds: int = 120
    heartbeat_interval_seconds: int = 20
    heartbeat_timeout_seconds: int = 10

    @field_validator("runtime_minutes")
    @classmethod
    def _validate_runtime_minutes(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value <= 0:
            raise ValueError("live.runtime_minutes must be > 0 when set")
        return value

    @field_validator("warmup_minutes", "reconnect_max_attempts", "stale_feed_seconds")
    @classmethod
    def _positive_integers(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("live config values must be > 0")
        return value

    @field_validator(
        "reconnect_base_delay_seconds",
        "reconnect_max_delay_seconds",
        "heartbeat_interval_seconds",
        "heartbeat_timeout_seconds",
    )
    @classmethod
    def _positive_floats(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("live config values must be > 0")
        return value

    @field_validator("reconnect_max_delay_seconds")
    @classmethod
    def _validate_reconnect_bounds(cls, value: float, info) -> float:  # type: ignore[override]
        base = info.data.get("reconnect_base_delay_seconds")
        if isinstance(base, (int, float)) and value < float(base):
            raise ValueError(
                "live.reconnect_max_delay_seconds must be >= live.reconnect_base_delay_seconds"
            )
        return value


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alpaca: AlpacaConfig
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    sessions: SessionsConfig = Field(default_factory=SessionsConfig)
    timeframes: TimeframesConfig = Field(default_factory=TimeframesConfig)
    signal: SignalConfig = Field(default_factory=SignalConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    archive: ArchiveConfig = Field(default_factory=ArchiveConfig)
    ingest: IngestConfig = Field(default_factory=IngestConfig)
    live: LiveConfig = Field(default_factory=LiveConfig)
    storage_root: str = "artifacts/storage"
    events_root: str = "artifacts/events"
    outfits_path: str = "src/sma_outfits/config/outfits.yaml"

    @property
    def all_timeframes(self) -> list[str]:
        return list(dict.fromkeys([*self.timeframes.live, *self.timeframes.derived]))

    @model_validator(mode="after")
    def _validate_strategy_routes(self) -> Settings:
        routes = self.strategy.routes
        if self.strategy.strict_routing and not routes:
            raise ValueError(
                "strategy.routes must be non-empty when strategy.strict_routing=true"
            )

        seen_route_ids: set[str] = set()
        seen_route_keys: set[tuple[str, str]] = set()
        for route in routes:
            if route.id in seen_route_ids:
                raise ValueError(f"Duplicate strategy route id '{route.id}'")
            seen_route_ids.add(route.id)
            if self.strategy.strict_routing:
                route_key = (route.symbol, route.timeframe)
                if route_key in seen_route_keys:
                    raise ValueError(
                        "Duplicate strategy route key for strict routing: "
                        f"{route.symbol}/{route.timeframe}"
                    )
                seen_route_keys.add(route_key)

        outfit_metadata = _load_outfit_metadata(Path(self.outfits_path))
        for index, route in enumerate(routes):
            metadata = outfit_metadata.get(route.outfit_id)
            if metadata is None:
                raise ValueError(
                    "strategy.routes[{}] references unknown outfit_id '{}'".format(
                        index,
                        route.outfit_id,
                    )
                )
            periods = metadata["periods"]
            missing = [
                period
                for period in [route.key_period, *route.micro_periods]
                if period not in periods
            ]
            if missing:
                raise ValueError(
                    "strategy.routes[{}] includes period(s) not present in outfit '{}': {}".format(
                        index,
                        route.outfit_id,
                        sorted(set(missing)),
                    )
                )
            if self.strategy.ambiguity_policy == "fail" and metadata["source_ambiguous"]:
                raise ValueError(
                    "strategy.routes[{}] references ambiguous outfit '{}' while "
                    "strategy.ambiguity_policy=fail".format(index, route.outfit_id)
                )
        return self


def read_env_local(path: Path = Path(".env.local")) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"Required environment file not found: {path}")
    env: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid .env.local line {line_number}: '{raw_line}'")
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")

    missing = [key for key in REQUIRED_ENV_KEYS if not env.get(key)]
    if missing:
        raise ValueError(
            "Missing required keys in .env.local: " + ", ".join(missing)
        )
    return env


def load_settings(
    config_path: Path,
    env_path: Path = Path(".env.local"),
) -> Settings:
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        raise ValueError("YAML root must be a map")

    env = read_env_local(env_path)
    alpaca_data = dict(parsed.get("alpaca", {}))
    if not isinstance(alpaca_data, dict):
        raise ValueError("alpaca section must be a map")

    key_map = {
        "ALPACA_API_KEY": "api_key",
        "ALPACA_SECRET_KEY": "secret_key",
        "ALPACA_BASE_URL": "base_url",
        "ALPACA_DATA_URL": "data_url",
        "ALPACA_DATA_FEED": "data_feed",
    }
    strict_secret_keys = {"ALPACA_API_KEY", "ALPACA_SECRET_KEY"}
    for env_key, config_key in key_map.items():
        existing = alpaca_data.get(config_key)
        env_value = env[env_key]
        if (
            env_key in strict_secret_keys
            and existing
            and str(existing).strip() != env_value
        ):
            raise ValueError(
                f"Config value alpaca.{config_key} does not match .env.local:{env_key}"
            )
        alpaca_data[config_key] = env_value
    parsed["alpaca"] = alpaca_data

    sessions = parsed.get("sessions", {})
    if sessions is None:
        sessions = {}
    if not isinstance(sessions, dict):
        raise ValueError("sessions section must be a map")
    parsed["sessions"] = dict(sessions)

    return Settings.model_validate(parsed)


def _load_outfit_metadata(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(f"Outfit catalog not found: {path}")
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or "outfits" not in parsed:
        raise ValueError("Outfit catalog must be a map with key 'outfits'")
    rows = parsed["outfits"]
    if not isinstance(rows, list):
        raise ValueError("Outfit catalog 'outfits' must be a list")

    metadata: dict[str, dict[str, object]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("Each outfit row must be a map")
        outfit_id = row.get("id")
        if not isinstance(outfit_id, str) or not outfit_id.strip():
            raise ValueError(f"Outfit row[{index}] id must be non-empty string")
        periods_raw = row.get("periods")
        if not isinstance(periods_raw, list) or not periods_raw:
            raise ValueError(f"Outfit row[{index}] periods must be a non-empty list")
        if any(not isinstance(period, int) or isinstance(period, bool) for period in periods_raw):
            raise ValueError(f"Outfit row[{index}] periods must contain integers only")
        source_ambiguous = row.get("source_ambiguous")
        if not isinstance(source_ambiguous, bool):
            raise ValueError(f"Outfit row[{index}] source_ambiguous must be boolean")
        metadata[outfit_id.strip()] = {
            "periods": set(periods_raw),
            "source_ambiguous": source_ambiguous,
        }
    return metadata
