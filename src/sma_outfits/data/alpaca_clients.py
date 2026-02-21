from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from time import monotonic
from typing import AsyncIterator, Protocol
from urllib.parse import urlparse

import pandas as pd
import requests
import websockets
from websockets.exceptions import ConnectionClosed

from sma_outfits.config.models import AlpacaConfig
from sma_outfits.data.resample import ensure_ohlcv_schema
from sma_outfits.utils import ALPACA_NATIVE_TIMEFRAMES, ensure_utc_timestamp, normalize_market


class HistoricalBarsClient(Protocol):
    def fetch_bars(
        self,
        symbol: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        timeframe: str,
        market: str,
    ) -> pd.DataFrame:
        ...

    def fetch_calendar_sessions(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        timezone: str = "America/New_York",
    ) -> dict[str, tuple[pd.Timestamp, pd.Timestamp] | None]:
        ...


@dataclass(frozen=True, slots=True)
class LiveBar:
    symbol: str
    ts: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str


class LiveStreamError(RuntimeError):
    pass


class StreamStaleError(LiveStreamError):
    pass


class StreamHeartbeatError(LiveStreamError):
    pass


class StreamDisconnectedError(LiveStreamError):
    pass


REQUIRED_REST_BAR_KEYS = frozenset({"t", "o", "h", "l", "c", "v"})
OPTIONAL_REST_BAR_KEYS = frozenset({"n", "vw"})
ALLOWED_REST_BAR_KEYS = REQUIRED_REST_BAR_KEYS | OPTIONAL_REST_BAR_KEYS

REQUIRED_WS_BAR_KEYS = frozenset({"T", "S", "t", "o", "h", "l", "c", "v"})
OPTIONAL_WS_BAR_KEYS = frozenset({"n", "vw"})
ALLOWED_WS_BAR_KEYS = REQUIRED_WS_BAR_KEYS | OPTIONAL_WS_BAR_KEYS


@dataclass(slots=True)
class AlpacaRESTClient:
    config: AlpacaConfig
    timeout_seconds: int = 30
    _session: requests.Session = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._session = requests.Session()
        # Keep networking deterministic and config-driven; do not inherit proxy env vars.
        self._session.trust_env = False
        self._session.headers.update(
            {
                "APCA-API-KEY-ID": self.config.api_key,
                "APCA-API-SECRET-KEY": self.config.secret_key,
            }
        )

    def fetch_bars(
        self,
        symbol: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        timeframe: str,
        market: str,
    ) -> pd.DataFrame:
        if timeframe not in ALPACA_NATIVE_TIMEFRAMES:
            raise ValueError(
                f"Timeframe '{timeframe}' is not a native Alpaca timeframe. "
                "Fetch native bars and resample instead."
            )
        normalized_market = normalize_market(market)
        native_tf = ALPACA_NATIVE_TIMEFRAMES[timeframe]
        if normalized_market == "crypto":
            return self._fetch_crypto_bars(symbol, start, end, native_tf)
        return self._fetch_stock_bars(symbol, start, end, native_tf)

    def discover_earliest_bar_frame(
        self,
        symbol: str,
        timeframe: str,
        market: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> pd.DataFrame:
        if timeframe not in ALPACA_NATIVE_TIMEFRAMES:
            raise ValueError(
                f"Timeframe '{timeframe}' is not a native Alpaca timeframe. "
                "Use native source timeframe discovery."
            )
        if ensure_utc_timestamp(start) >= ensure_utc_timestamp(end):
            raise ValueError("start must be earlier than end for earliest-bar discovery")

        normalized_market = normalize_market(market)
        native_tf = ALPACA_NATIVE_TIMEFRAMES[timeframe]
        if normalized_market == "crypto":
            endpoint = (
                f"{self.config.data_url.rstrip('/')}/v1beta3/crypto/{self.config.crypto_loc}/bars"
            )
            params: dict[str, str | int] = {
                "symbols": symbol,
                "timeframe": native_tf,
                "start": ensure_utc_timestamp(start).isoformat().replace("+00:00", "Z"),
                "end": ensure_utc_timestamp(end).isoformat().replace("+00:00", "Z"),
                "limit": 1,
                "sort": "asc",
            }
        else:
            endpoint = f"{self.config.data_url.rstrip('/')}/v2/stocks/bars"
            params = {
                "symbols": symbol,
                "timeframe": native_tf,
                "start": ensure_utc_timestamp(start).isoformat().replace("+00:00", "Z"),
                "end": ensure_utc_timestamp(end).isoformat().replace("+00:00", "Z"),
                "adjustment": self.config.adjustment,
                "asof": self.config.asof,
                "feed": self.config.data_feed,
                "limit": 1,
                "sort": "asc",
            }

        payload = self._get_json(endpoint, params)
        rows = _extract_rest_symbol_rows(payload, endpoint=endpoint, symbol=symbol)
        if not rows:
            raise RuntimeError(
                f"No Alpaca bars returned for {symbol} ({native_tf}) in discovery window "
                f"{ensure_utc_timestamp(start).isoformat()} to {ensure_utc_timestamp(end).isoformat()}"
            )
        frame = ensure_ohlcv_schema(
            _rows_to_dataframe(rows, endpoint=endpoint, symbol=symbol)
        )
        if frame.empty:
            raise RuntimeError(f"No Alpaca bars returned for {symbol} ({native_tf})")
        return frame.iloc[[0]].reset_index(drop=True)

    def _fetch_stock_bars(
        self,
        symbol: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        native_tf: str,
    ) -> pd.DataFrame:
        endpoint = f"{self.config.data_url.rstrip('/')}/v2/stocks/bars"
        params = {
            "symbols": symbol,
            "timeframe": native_tf,
            "start": start.tz_convert("UTC").isoformat().replace("+00:00", "Z"),
            "end": end.tz_convert("UTC").isoformat().replace("+00:00", "Z"),
            "adjustment": self.config.adjustment,
            "asof": self.config.asof,
            "feed": self.config.data_feed,
            "limit": 10000,
        }
        rows: list[dict] = []
        while True:
            payload = self._get_json(endpoint, params)
            rows.extend(_extract_rest_symbol_rows(payload, endpoint=endpoint, symbol=symbol))
            token = _extract_next_page_token(payload, endpoint=endpoint)
            if not token:
                break
            params["page_token"] = token
        if not rows:
            raise RuntimeError(f"No Alpaca bars returned for {symbol} ({native_tf})")
        return ensure_ohlcv_schema(
            _rows_to_dataframe(rows, endpoint=endpoint, symbol=symbol)
        )

    def _fetch_crypto_bars(
        self,
        symbol: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        native_tf: str,
    ) -> pd.DataFrame:
        endpoint = (
            f"{self.config.data_url.rstrip('/')}/v1beta3/crypto/{self.config.crypto_loc}/bars"
        )
        params = {
            "symbols": symbol,
            "timeframe": native_tf,
            "start": start.tz_convert("UTC").isoformat().replace("+00:00", "Z"),
            "end": end.tz_convert("UTC").isoformat().replace("+00:00", "Z"),
            "limit": 10000,
        }
        rows: list[dict] = []
        while True:
            payload = self._get_json(endpoint, params)
            rows.extend(_extract_rest_symbol_rows(payload, endpoint=endpoint, symbol=symbol))
            token = _extract_next_page_token(payload, endpoint=endpoint)
            if not token:
                break
            params["page_token"] = token
        if not rows:
            raise RuntimeError(f"No Alpaca crypto bars returned for {symbol} ({native_tf})")
        return ensure_ohlcv_schema(
            _rows_to_dataframe(rows, endpoint=endpoint, symbol=symbol)
        )

    def fetch_calendar_sessions(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        timezone: str = "America/New_York",
    ) -> dict[str, tuple[pd.Timestamp, pd.Timestamp] | None]:
        start_utc = ensure_utc_timestamp(start)
        end_utc = ensure_utc_timestamp(end)
        if start_utc > end_utc:
            raise ValueError("start must be earlier than or equal to end for calendar lookup")

        local_start = start_utc.tz_convert(timezone).strftime("%Y-%m-%d")
        local_end = end_utc.tz_convert(timezone).strftime("%Y-%m-%d")
        endpoint = f"{self.config.base_url.rstrip('/')}/v2/calendar"
        response = self._session.get(
            endpoint,
            params={"start": local_start, "end": local_end},
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Alpaca request failed ({response.status_code}) for {endpoint}: {response.text}"
            )
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError(
                f"Unexpected Alpaca calendar payload type: {type(payload).__name__} (expected list)"
            )

        sessions: dict[str, tuple[pd.Timestamp, pd.Timestamp] | None] = {}
        for index, row in enumerate(payload):
            if not isinstance(row, dict):
                raise RuntimeError(
                    f"Alpaca calendar payload contract violation ({endpoint}): "
                    f"row[{index}] type={type(row).__name__} (expected dict)"
                )
            missing = {"date", "open", "close"}.difference(row.keys())
            if missing:
                raise RuntimeError(
                    f"Alpaca calendar payload contract violation ({endpoint}): "
                    f"row[{index}] missing={sorted(missing)}"
                )
            session_date = _coerce_non_empty_string(
                row["date"],
                context=f"{endpoint} row[{index}] field=date",
                error_cls=RuntimeError,
            )
            market_open_utc = _parse_calendar_clock_timestamp(
                session_date=session_date,
                value=row["open"],
                timezone=timezone,
                context=f"{endpoint} row[{index}] field=open",
            )
            market_close_utc = _parse_calendar_clock_timestamp(
                session_date=session_date,
                value=row["close"],
                timezone=timezone,
                context=f"{endpoint} row[{index}] field=close",
            )
            if market_close_utc < market_open_utc:
                raise RuntimeError(
                    f"Alpaca calendar payload contract violation ({endpoint}): "
                    f"row[{index}] close before open for date={session_date}"
                )
            sessions[session_date] = (market_open_utc, market_close_utc)

        for day in pd.date_range(start=local_start, end=local_end, freq="D"):
            day_key = day.strftime("%Y-%m-%d")
            if day_key not in sessions:
                sessions[day_key] = None
        return sessions

    def fetch_open_positions(self) -> list[dict[str, object]]:
        endpoint = f"{self.config.base_url.rstrip('/')}/v2/positions"
        response = self._session.get(
            endpoint,
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Alpaca request failed ({response.status_code}) for {endpoint}: {response.text}"
            )
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError(
                f"Unexpected Alpaca open-positions payload type: {type(payload).__name__} "
                "(expected list)"
            )
        rows: list[dict[str, object]] = []
        for index, row in enumerate(payload):
            if not isinstance(row, dict):
                raise RuntimeError(
                    f"Alpaca positions payload contract violation ({endpoint}): "
                    f"row[{index}] type={type(row).__name__} (expected dict)"
                )
            if "symbol" not in row:
                raise RuntimeError(
                    f"Alpaca positions payload contract violation ({endpoint}): "
                    f"row[{index}] missing required key 'symbol'"
                )
            rows.append(row)
        return rows

    def fetch_open_orders(self) -> list[dict[str, object]]:
        endpoint = f"{self.config.base_url.rstrip('/')}/v2/orders"
        response = self._session.get(
            endpoint,
            params={"status": "open", "limit": 500, "direction": "desc"},
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Alpaca request failed ({response.status_code}) for {endpoint}: {response.text}"
            )
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError(
                f"Unexpected Alpaca open-orders payload type: {type(payload).__name__} "
                "(expected list)"
            )
        rows: list[dict[str, object]] = []
        for index, row in enumerate(payload):
            if not isinstance(row, dict):
                raise RuntimeError(
                    f"Alpaca orders payload contract violation ({endpoint}): "
                    f"row[{index}] type={type(row).__name__} (expected dict)"
                )
            if "symbol" not in row:
                raise RuntimeError(
                    f"Alpaca orders payload contract violation ({endpoint}): "
                    f"row[{index}] missing required key 'symbol'"
                )
            rows.append(row)
        return rows

    def _get_json(self, endpoint: str, params: dict[str, str | int]) -> dict:
        response = self._session.get(
            endpoint,
            params=params,
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Alpaca request failed ({response.status_code}) for {endpoint}: {response.text}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected Alpaca payload type: {type(payload)}")
        return payload


@dataclass(slots=True)
class AlpacaWebSocketBarStream:
    config: AlpacaConfig
    market: str
    symbols: list[str]
    stale_feed_seconds: int = 120
    heartbeat_interval_seconds: int = 20
    heartbeat_timeout_seconds: int = 10

    def __post_init__(self) -> None:
        if self.market not in {"stocks", "crypto"}:
            raise ValueError(f"Unsupported market '{self.market}'")
        if not self.symbols:
            raise ValueError("At least one symbol is required for websocket subscription")
        if self.stale_feed_seconds <= 0:
            raise ValueError("stale_feed_seconds must be > 0")
        if self.heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be > 0")
        if self.heartbeat_timeout_seconds <= 0:
            raise ValueError("heartbeat_timeout_seconds must be > 0")

    async def stream_bars(self) -> AsyncIterator[LiveBar]:
        uri = self._stream_uri()
        try:
            async with websockets.connect(
                uri,
                proxy=None,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=5,
            ) as websocket:
                await self._authenticate(websocket)
                await self._subscribe(websocket)
                async for bar in self._iter_bars(websocket):
                    yield bar
        except ConnectionClosed as exc:
            raise StreamDisconnectedError(f"Websocket connection closed: {exc}") from exc
        except OSError as exc:
            raise StreamDisconnectedError(f"Websocket transport error: {exc}") from exc

    async def _iter_bars(self, websocket) -> AsyncIterator[LiveBar]:  # noqa: ANN001
        last_message_at = monotonic()
        last_heartbeat_at = monotonic()
        while True:
            now = monotonic()
            if now - last_message_at > self.stale_feed_seconds:
                raise StreamStaleError(
                    f"Feed stale for {self.stale_feed_seconds}s on {self.market} stream"
                )
            if now - last_heartbeat_at >= self.heartbeat_interval_seconds:
                pong_waiter = await websocket.ping()
                try:
                    await asyncio.wait_for(
                        pong_waiter,
                        timeout=self.heartbeat_timeout_seconds,
                    )
                except asyncio.TimeoutError as exc:
                    raise StreamHeartbeatError(
                        f"Heartbeat timeout after {self.heartbeat_timeout_seconds}s"
                    ) from exc
                last_heartbeat_at = monotonic()

            timeout = min(
                1.0,
                max(0.1, self.stale_feed_seconds - (monotonic() - last_message_at)),
            )
            try:
                raw_message = await asyncio.wait_for(websocket.recv(), timeout=timeout)
            except asyncio.TimeoutError:
                continue
            last_message_at = monotonic()

            for row in self._decode_payload(raw_message):
                bar = _parse_live_bar(row=row, market=self.market)
                if bar is not None:
                    yield bar

    async def _authenticate(self, websocket) -> None:  # noqa: ANN001
        await websocket.send(
            json.dumps(
                {
                    "action": "auth",
                    "key": self.config.api_key,
                    "secret": self.config.secret_key,
                }
            )
        )
        deadline = monotonic() + 10.0
        while monotonic() < deadline:
            raw_message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            for row in self._decode_payload(raw_message):
                msg_type = _require_ws_message_type(row, phase="auth")
                if msg_type == "error":
                    raise LiveStreamError(f"Alpaca auth failed: {row}")
                if msg_type == "success":
                    msg_value = _require_ws_message_field(row, key="msg", phase="auth")
                    if str(msg_value).lower() == "authenticated":
                        return
                    continue
        raise LiveStreamError("Timed out waiting for Alpaca websocket authentication")

    async def _subscribe(self, websocket) -> None:  # noqa: ANN001
        await websocket.send(
            json.dumps(
                {
                    "action": "subscribe",
                    "bars": sorted(set(self.symbols)),
                }
            )
        )
        deadline = monotonic() + 10.0
        while monotonic() < deadline:
            raw_message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            for row in self._decode_payload(raw_message):
                msg_type = _require_ws_message_type(row, phase="subscribe")
                if msg_type == "error":
                    raise LiveStreamError(f"Alpaca subscribe failed: {row}")
                if msg_type == "subscription":
                    bars = _require_ws_message_field(row, key="bars", phase="subscribe")
                    if not isinstance(bars, list) or any(
                        not isinstance(symbol, str) for symbol in bars
                    ):
                        raise LiveStreamError(
                            "Invalid websocket subscribe payload: "
                            f"bars must be a list[str], got {type(bars).__name__}"
                        )
                    normalized_bars = {symbol.upper() for symbol in bars}
                    if normalized_bars >= {symbol.upper() for symbol in self.symbols}:
                        return
        raise LiveStreamError("Timed out waiting for Alpaca websocket subscription")

    @staticmethod
    def _decode_payload(raw_message: str | bytes) -> list[dict[str, object]]:
        decoded = raw_message.decode("utf-8") if isinstance(raw_message, bytes) else raw_message
        payload = json.loads(decoded)
        if not isinstance(payload, list):
            raise LiveStreamError(
                "Unexpected websocket payload container: "
                f"{type(payload).__name__}; expected list"
            )
        rows: list[dict[str, object]] = []
        for row in payload:
            if not isinstance(row, dict):
                raise LiveStreamError(
                    "Unexpected websocket row type: "
                    f"{type(row).__name__}; expected dict"
                )
            rows.append(row)
        return rows

    def _stream_uri(self) -> str:
        parsed = urlparse(self.config.data_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(
                "alpaca.data_url must use http/https so websocket endpoint can be derived"
            )
        if not parsed.netloc:
            raise ValueError("alpaca.data_url host is required")

        host = parsed.netloc
        if host.startswith("data."):
            host = host.replace("data.", "stream.", 1)
        else:
            host = f"stream.{host}"
        scheme = "wss" if parsed.scheme == "https" else "ws"
        if self.market == "stocks":
            return f"{scheme}://{host}/v2/{self.config.data_feed}"
        return f"{scheme}://{host}/v1beta3/crypto/{self.config.crypto_loc}"


class InMemoryHistoricalClient:
    def __init__(self, frames: dict[tuple[str, str], pd.DataFrame]) -> None:
        self._frames: dict[tuple[str, str], pd.DataFrame] = {}
        for key, frame in frames.items():
            self._frames[key] = ensure_ohlcv_schema(frame)

    def fetch_bars(
        self,
        symbol: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        timeframe: str,
        market: str,
    ) -> pd.DataFrame:
        normalize_market(market)
        key = (symbol, timeframe)
        if key not in self._frames:
            raise KeyError(f"No in-memory bars for {symbol} {timeframe}")
        frame = self._frames[key].copy()
        frame = frame.loc[(frame["ts"] >= start) & (frame["ts"] <= end)]
        if frame.empty:
            raise RuntimeError(f"No in-range bars for {symbol} {timeframe}")
        return frame.reset_index(drop=True)

    def fetch_calendar_sessions(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        timezone: str = "America/New_York",
    ) -> dict[str, tuple[pd.Timestamp, pd.Timestamp] | None]:
        start_utc = ensure_utc_timestamp(start)
        end_utc = ensure_utc_timestamp(end)
        if start_utc > end_utc:
            raise ValueError("start must be earlier than or equal to end for calendar lookup")
        local_start = start_utc.tz_convert(timezone).strftime("%Y-%m-%d")
        local_end = end_utc.tz_convert(timezone).strftime("%Y-%m-%d")
        sessions: dict[str, tuple[pd.Timestamp, pd.Timestamp] | None] = {}
        for day in pd.date_range(start=local_start, end=local_end, freq="D"):
            if day.weekday() >= 5:
                sessions[day.strftime("%Y-%m-%d")] = None
                continue
            market_open = day.tz_localize(timezone).replace(hour=9, minute=30, second=0)
            market_close = day.tz_localize(timezone).replace(hour=16, minute=0, second=0)
            sessions[day.strftime("%Y-%m-%d")] = (
                market_open.tz_convert("UTC"),
                market_close.tz_convert("UTC"),
            )
        return sessions


def _rows_to_dataframe(
    rows: list[dict],
    endpoint: str,
    symbol: str,
) -> pd.DataFrame:
    parsed: list[dict[str, float | pd.Timestamp]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RuntimeError(
                f"Alpaca REST payload contract violation ({endpoint}, {symbol}): "
                f"row[{index}] type={type(row).__name__} (expected dict)"
            )
        missing = REQUIRED_REST_BAR_KEYS.difference(row.keys())
        unexpected = set(row.keys()).difference(ALLOWED_REST_BAR_KEYS)
        if missing or unexpected:
            raise RuntimeError(
                f"Alpaca REST payload contract violation ({endpoint}, {symbol}): "
                f"row[{index}] missing={sorted(missing)} unexpected={sorted(unexpected)}"
            )

        parsed.append(
            {
                "ts": _coerce_utc_timestamp(
                    row["t"],
                    context=f"{endpoint} {symbol} row[{index}] field=t",
                    error_cls=RuntimeError,
                ),
                "open": _coerce_float(
                    row["o"],
                    context=f"{endpoint} {symbol} row[{index}] field=o",
                    error_cls=RuntimeError,
                ),
                "high": _coerce_float(
                    row["h"],
                    context=f"{endpoint} {symbol} row[{index}] field=h",
                    error_cls=RuntimeError,
                ),
                "low": _coerce_float(
                    row["l"],
                    context=f"{endpoint} {symbol} row[{index}] field=l",
                    error_cls=RuntimeError,
                ),
                "close": _coerce_float(
                    row["c"],
                    context=f"{endpoint} {symbol} row[{index}] field=c",
                    error_cls=RuntimeError,
                ),
                "volume": _coerce_float(
                    row["v"],
                    context=f"{endpoint} {symbol} row[{index}] field=v",
                    error_cls=RuntimeError,
                ),
            }
        )
    frame = pd.DataFrame(parsed)
    if frame.empty:
        raise RuntimeError("No rows to normalize into DataFrame")
    return frame


def _parse_live_bar(row: dict[str, object], market: str) -> LiveBar | None:
    event_type_raw = row.get("T")
    if event_type_raw is None:
        raise LiveStreamError(
            f"Malformed websocket message for {market}: missing required key 'T'"
        )
    event_type = str(event_type_raw)
    if event_type != "b":
        return None

    missing = REQUIRED_WS_BAR_KEYS.difference(row.keys())
    unexpected = set(row.keys()).difference(ALLOWED_WS_BAR_KEYS)
    if missing or unexpected:
        raise LiveStreamError(
            f"Malformed websocket live bar for {market}: "
            f"missing={sorted(missing)} unexpected={sorted(unexpected)}"
        )

    symbol = str(row["S"]).strip().upper()
    if not symbol:
        raise LiveStreamError(f"Malformed websocket live bar for {market}: symbol is empty")
    ts = _coerce_utc_timestamp(
        row["t"],
        context=f"websocket {market} field=t",
        error_cls=LiveStreamError,
    )

    return LiveBar(
        symbol=symbol,
        ts=ts,
        open=_coerce_float(
            row["o"],
            context=f"websocket {market} field=o",
            error_cls=LiveStreamError,
        ),
        high=_coerce_float(
            row["h"],
            context=f"websocket {market} field=h",
            error_cls=LiveStreamError,
        ),
        low=_coerce_float(
            row["l"],
            context=f"websocket {market} field=l",
            error_cls=LiveStreamError,
        ),
        close=_coerce_float(
            row["c"],
            context=f"websocket {market} field=c",
            error_cls=LiveStreamError,
        ),
        volume=_coerce_float(
            row["v"],
            context=f"websocket {market} field=v",
            error_cls=LiveStreamError,
        ),
        source=f"alpaca_ws_{market}",
    )


def _extract_rest_symbol_rows(
    payload: dict[str, object],
    endpoint: str,
    symbol: str,
) -> list[dict]:
    bars_data = payload.get("bars")
    if not isinstance(bars_data, dict):
        raise RuntimeError(
            f"Alpaca REST payload contract violation ({endpoint}, {symbol}): "
            f"'bars' must be dict[symbol, list], got {type(bars_data).__name__}"
        )
    if not bars_data:
        return []
    if symbol not in bars_data:
        raise RuntimeError(
            f"Alpaca REST payload contract violation ({endpoint}, {symbol}): "
            f"missing bars entry for symbol. available_keys={sorted(map(str, bars_data.keys()))}"
        )
    rows = bars_data[symbol]
    if not isinstance(rows, list):
        raise RuntimeError(
            f"Alpaca REST payload contract violation ({endpoint}, {symbol}): "
            f"bars[{symbol!r}] type={type(rows).__name__} (expected list)"
        )
    return rows


def _extract_next_page_token(
    payload: dict[str, object],
    endpoint: str,
) -> str | None:
    if "next_page_token" not in payload:
        raise RuntimeError(
            f"Alpaca REST payload contract violation ({endpoint}): "
            "missing required key 'next_page_token'"
        )
    token = payload["next_page_token"]
    if token is None:
        return None
    if not isinstance(token, str):
        raise RuntimeError(
            f"Alpaca REST payload contract violation ({endpoint}): "
            f"next_page_token type={type(token).__name__} (expected str|null)"
        )
    if not token.strip():
        raise RuntimeError(
            f"Alpaca REST payload contract violation ({endpoint}): "
            "next_page_token must be non-empty string when present"
        )
    return token


def _coerce_utc_timestamp(
    value: object,
    context: str,
    error_cls: type[Exception],
) -> pd.Timestamp:
    try:
        ts = pd.Timestamp(value)
    except Exception as exc:  # noqa: BLE001
        raise error_cls(f"{context}: invalid timestamp value={value!r}") from exc
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _coerce_float(
    value: object,
    context: str,
    error_cls: type[Exception],
) -> float:
    try:
        return float(value)
    except Exception as exc:  # noqa: BLE001
        raise error_cls(f"{context}: expected numeric value, got {value!r}") from exc


def _coerce_non_empty_string(
    value: object,
    context: str,
    error_cls: type[Exception],
) -> str:
    candidate = str(value).strip()
    if not candidate:
        raise error_cls(f"{context}: expected non-empty string, got {value!r}")
    return candidate


def _parse_calendar_clock_timestamp(
    session_date: str,
    value: object,
    timezone: str,
    context: str,
) -> pd.Timestamp:
    clock_value = _coerce_non_empty_string(
        value=value,
        context=context,
        error_cls=RuntimeError,
    )
    normalized_clock = clock_value if len(clock_value) != 5 else f"{clock_value}:00"
    try:
        local_ts = pd.Timestamp(f"{session_date} {normalized_clock}")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"{context}: invalid session time value={value!r} for date={session_date}"
        ) from exc
    if local_ts.tzinfo is None:
        local_ts = local_ts.tz_localize(timezone)
    else:
        local_ts = local_ts.tz_convert(timezone)
    return local_ts.tz_convert("UTC")


def _require_ws_message_type(row: dict[str, object], phase: str) -> str:
    if "T" not in row:
        raise LiveStreamError(
            f"Malformed websocket payload during {phase}: missing required key 'T'"
        )
    return str(row["T"])


def _require_ws_message_field(
    row: dict[str, object],
    key: str,
    phase: str,
) -> object:
    if key not in row:
        raise LiveStreamError(
            f"Malformed websocket payload during {phase}: missing required key '{key}'"
        )
    return row[key]
