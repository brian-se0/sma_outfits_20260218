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
from sma_outfits.utils import ALPACA_NATIVE_TIMEFRAMES, is_crypto_symbol


class HistoricalBarsClient(Protocol):
    def fetch_bars(
        self,
        symbol: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        timeframe: str,
    ) -> pd.DataFrame:
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


@dataclass(slots=True)
class AlpacaRESTClient:
    config: AlpacaConfig
    timeout_seconds: int = 30
    _session: requests.Session = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._session = requests.Session()
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
    ) -> pd.DataFrame:
        if timeframe not in ALPACA_NATIVE_TIMEFRAMES:
            raise ValueError(
                f"Timeframe '{timeframe}' is not a native Alpaca timeframe. "
                "Fetch native bars and resample instead."
            )
        native_tf = ALPACA_NATIVE_TIMEFRAMES[timeframe]
        if is_crypto_symbol(symbol):
            return self._fetch_crypto_bars(symbol, start, end, native_tf)
        return self._fetch_stock_bars(symbol, start, end, native_tf)

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
            "adjustment": "raw",
            "feed": self.config.data_feed,
            "limit": 10000,
        }
        rows: list[dict] = []
        while True:
            payload = self._get_json(endpoint, params)
            bars_data = payload.get("bars", {})
            if isinstance(bars_data, dict):
                next_rows = bars_data.get(symbol, [])
            else:
                next_rows = bars_data
            rows.extend(next_rows)
            token = payload.get("next_page_token")
            if not token:
                break
            params["page_token"] = token
        if not rows:
            raise RuntimeError(f"No Alpaca bars returned for {symbol} ({native_tf})")
        return ensure_ohlcv_schema(_rows_to_dataframe(rows))

    def _fetch_crypto_bars(
        self,
        symbol: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        native_tf: str,
    ) -> pd.DataFrame:
        endpoint = f"{self.config.data_url.rstrip('/')}/v1beta3/crypto/us/bars"
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
            bars_data = payload.get("bars", {})
            if isinstance(bars_data, dict):
                next_rows = bars_data.get(symbol, [])
            else:
                next_rows = bars_data
            rows.extend(next_rows)
            token = payload.get("next_page_token")
            if not token:
                break
            params["page_token"] = token
        if not rows:
            raise RuntimeError(f"No Alpaca crypto bars returned for {symbol} ({native_tf})")
        return ensure_ohlcv_schema(_rows_to_dataframe(rows))

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
                msg_type = str(row.get("T", ""))
                msg_value = str(row.get("msg", "")).lower()
                if msg_type == "error":
                    raise LiveStreamError(f"Alpaca auth failed: {row}")
                if msg_type == "success" and msg_value == "authenticated":
                    return
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
                msg_type = str(row.get("T", ""))
                if msg_type == "error":
                    raise LiveStreamError(f"Alpaca subscribe failed: {row}")
                if msg_type == "subscription":
                    bars = row.get("bars", [])
                    if isinstance(bars, list) and set(bars) >= set(self.symbols):
                        return
        raise LiveStreamError("Timed out waiting for Alpaca websocket subscription")

    @staticmethod
    def _decode_payload(raw_message: str | bytes) -> list[dict]:
        decoded = raw_message.decode("utf-8") if isinstance(raw_message, bytes) else raw_message
        payload = json.loads(decoded)
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            raise LiveStreamError(f"Unexpected websocket payload type: {type(payload)}")
        rows: list[dict] = []
        for row in payload:
            if not isinstance(row, dict):
                raise LiveStreamError(
                    f"Unexpected websocket row type: {type(row)} in payload"
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
        return f"{scheme}://{host}/v1beta3/crypto/us"


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
    ) -> pd.DataFrame:
        key = (symbol, timeframe)
        if key not in self._frames:
            raise KeyError(f"No in-memory bars for {symbol} {timeframe}")
        frame = self._frames[key].copy()
        frame = frame.loc[(frame["ts"] >= start) & (frame["ts"] <= end)]
        if frame.empty:
            raise RuntimeError(f"No in-range bars for {symbol} {timeframe}")
        return frame.reset_index(drop=True)


def _rows_to_dataframe(rows: list[dict]) -> pd.DataFrame:
    parsed: list[dict[str, float | str]] = []
    for row in rows:
        parsed.append(
            {
                "ts": row.get("t") or row.get("timestamp"),
                "open": row.get("o") if row.get("o") is not None else row.get("open"),
                "high": row.get("h") if row.get("h") is not None else row.get("high"),
                "low": row.get("l") if row.get("l") is not None else row.get("low"),
                "close": row.get("c") if row.get("c") is not None else row.get("close"),
                "volume": row.get("v") if row.get("v") is not None else row.get("volume"),
            }
        )
    frame = pd.DataFrame(parsed)
    if frame.empty:
        raise RuntimeError("No rows to normalize into DataFrame")
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame


def _parse_live_bar(row: dict, market: str) -> LiveBar | None:
    event_type = str(row.get("T", ""))
    if event_type != "b":
        return None

    symbol = row.get("S") or row.get("symbol")
    ts_value = row.get("t") or row.get("timestamp")
    if symbol is None or ts_value is None:
        raise LiveStreamError(f"Malformed live bar payload: {row}")

    open_value = row.get("o") if row.get("o") is not None else row.get("open")
    high_value = row.get("h") if row.get("h") is not None else row.get("high")
    low_value = row.get("l") if row.get("l") is not None else row.get("low")
    close_value = row.get("c") if row.get("c") is not None else row.get("close")
    volume_value = row.get("v") if row.get("v") is not None else row.get("volume")
    if any(
        value is None
        for value in (open_value, high_value, low_value, close_value, volume_value)
    ):
        raise LiveStreamError(f"Incomplete live bar payload: {row}")

    ts = pd.Timestamp(ts_value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return LiveBar(
        symbol=str(symbol).upper(),
        ts=ts,
        open=float(open_value),
        high=float(high_value),
        low=float(low_value),
        close=float(close_value),
        volume=float(volume_value),
        source=f"alpaca_ws_{market}",
    )
