from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

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

    @field_validator("api_key", "secret_key", "base_url", "data_url", "data_feed")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            raise ValueError("value must be non-empty")
        return candidate


class UniverseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbols: list[str] = Field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    proxy_map: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_PROXY_MAP))

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


class SessionsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regular_only: bool = True
    extended_enabled: bool = False
    timezone: str = "America/New_York"


class TimeframesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    live: list[str] = Field(default_factory=lambda: list(DEFAULT_LIVE_TIMEFRAMES))
    derived: list[str] = Field(default_factory=lambda: list(DEFAULT_DERIVED_TIMEFRAMES))

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
    risk: RiskConfig = Field(default_factory=RiskConfig)
    archive: ArchiveConfig = Field(default_factory=ArchiveConfig)
    live: LiveConfig = Field(default_factory=LiveConfig)
    storage_root: str = "artifacts/storage"
    events_root: str = "artifacts/events"
    outfits_path: str = "src/sma_outfits/config/outfits.yaml"

    @property
    def all_timeframes(self) -> list[str]:
        return list(dict.fromkeys([*self.timeframes.live, *self.timeframes.derived]))


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
