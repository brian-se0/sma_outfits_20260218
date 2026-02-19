from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import pytest

from sma_outfits.config.models import AlpacaConfig
from sma_outfits.data.alpaca_clients import (
    AlpacaRESTClient,
    AlpacaWebSocketBarStream,
    LiveStreamError,
    _parse_live_bar,
)


@dataclass
class _FakeResponse:
    payload: dict[str, Any]
    status_code: int = 200
    text: str = ""

    def json(self) -> dict[str, Any]:
        return self.payload


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self.headers: dict[str, str] = {}
        self.calls = 0
        self.call_args: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def get(self, *_args: Any, **_kwargs: Any) -> _FakeResponse:
        response = self._responses[self.calls]
        self.call_args.append((_args, _kwargs))
        self.calls += 1
        return response


def _config() -> AlpacaConfig:
    return AlpacaConfig(
        api_key="test-key",
        secret_key="test-secret",
        base_url="https://paper-api.alpaca.markets",
        data_url="https://data.alpaca.markets",
        data_feed="iex",
        adjustment="raw",
        asof="2025-01-01",
        crypto_loc="us",
    )


def test_rejects_non_canonical_rest_bars_shape() -> None:
    client = AlpacaRESTClient(_config())
    client._session = _FakeSession(
        responses=[
            _FakeResponse(
                payload={
                    "bars": [
                        {
                            "t": "2025-01-02T14:30:00Z",
                            "o": 100.0,
                            "h": 101.0,
                            "l": 99.0,
                            "c": 100.5,
                            "v": 1000,
                        }
                    ],
                    "next_page_token": None,
                }
            )
        ]
    )

    with pytest.raises(RuntimeError, match="bars.*dict\\[symbol, list\\]"):
        client.fetch_bars(
            symbol="SPY",
            start=pd.Timestamp("2025-01-02T14:30:00Z"),
            end=pd.Timestamp("2025-01-02T14:40:00Z"),
            timeframe="1m",
            market="stocks",
        )


def test_empty_rest_bars_map_treated_as_no_data() -> None:
    client = AlpacaRESTClient(_config())
    client._session = _FakeSession(
        responses=[
            _FakeResponse(
                payload={
                    "bars": {},
                    "next_page_token": None,
                }
            )
        ]
    )

    with pytest.raises(RuntimeError, match="No Alpaca bars returned for SPY"):
        client.fetch_bars(
            symbol="SPY",
            start=pd.Timestamp("2025-01-02T14:30:00Z"),
            end=pd.Timestamp("2025-01-02T14:40:00Z"),
            timeframe="1m",
            market="stocks",
        )


def test_rejects_rest_payload_missing_requested_symbol_when_other_keys_exist() -> None:
    client = AlpacaRESTClient(_config())
    client._session = _FakeSession(
        responses=[
            _FakeResponse(
                payload={
                    "bars": {"QQQ": []},
                    "next_page_token": None,
                }
            )
        ]
    )

    with pytest.raises(RuntimeError, match="missing bars entry for symbol"):
        client.fetch_bars(
            symbol="SPY",
            start=pd.Timestamp("2025-01-02T14:30:00Z"),
            end=pd.Timestamp("2025-01-02T14:40:00Z"),
            timeframe="1m",
            market="stocks",
        )


def test_rejects_rest_alias_keys() -> None:
    client = AlpacaRESTClient(_config())
    client._session = _FakeSession(
        responses=[
            _FakeResponse(
                payload={
                    "bars": {
                        "SPY": [
                            {
                                "timestamp": "2025-01-02T14:30:00Z",
                                "open": 100.0,
                                "high": 101.0,
                                "low": 99.0,
                                "close": 100.5,
                                "volume": 1000.0,
                            }
                        ]
                    },
                    "next_page_token": None,
                }
            )
        ]
    )

    with pytest.raises(RuntimeError, match="missing=.*unexpected=.*"):
        client.fetch_bars(
            symbol="SPY",
            start=pd.Timestamp("2025-01-02T14:30:00Z"),
            end=pd.Timestamp("2025-01-02T14:40:00Z"),
            timeframe="1m",
            market="stocks",
        )


def test_stock_bar_request_includes_explicit_adjustment_and_asof() -> None:
    client = AlpacaRESTClient(_config())
    fake_session = _FakeSession(
        responses=[
            _FakeResponse(
                payload={
                    "bars": {
                        "SPY": [
                            {
                                "t": "2025-01-02T14:30:00Z",
                                "o": 100.0,
                                "h": 101.0,
                                "l": 99.0,
                                "c": 100.5,
                                "v": 1000.0,
                            }
                        ]
                    },
                    "next_page_token": None,
                }
            )
        ]
    )
    client._session = fake_session

    bars = client.fetch_bars(
        symbol="SPY",
        start=pd.Timestamp("2025-01-02T14:30:00Z"),
        end=pd.Timestamp("2025-01-02T14:40:00Z"),
        timeframe="1m",
        market="stocks",
    )

    assert len(bars) == 1
    assert fake_session.call_args
    _, kwargs = fake_session.call_args[0]
    params = kwargs.get("params")
    assert isinstance(params, dict)
    assert params.get("adjustment") == "raw"
    assert params.get("asof") == "2025-01-01"


def test_crypto_bar_request_uses_configured_crypto_loc() -> None:
    config = _config().model_copy(update={"crypto_loc": "global"})
    client = AlpacaRESTClient(config)
    fake_session = _FakeSession(
        responses=[
            _FakeResponse(
                payload={
                    "bars": {
                        "BTC/USD": [
                            {
                                "t": "2025-01-02T14:30:00Z",
                                "o": 40000.0,
                                "h": 40100.0,
                                "l": 39900.0,
                                "c": 40050.0,
                                "v": 2.0,
                            }
                        ]
                    },
                    "next_page_token": None,
                }
            )
        ]
    )
    client._session = fake_session

    bars = client.fetch_bars(
        symbol="BTC/USD",
        start=pd.Timestamp("2025-01-02T14:30:00Z"),
        end=pd.Timestamp("2025-01-02T14:40:00Z"),
        timeframe="1m",
        market="crypto",
    )

    assert len(bars) == 1
    assert fake_session.call_args
    args, _kwargs = fake_session.call_args[0]
    assert args
    assert str(args[0]).endswith("/v1beta3/crypto/global/bars")


def test_rejects_single_object_websocket_payload() -> None:
    stream = AlpacaWebSocketBarStream(
        config=_config(),
        market="stocks",
        symbols=["SPY"],
    )
    with pytest.raises(LiveStreamError, match="container: dict; expected list"):
        stream._decode_payload('{"T":"success","msg":"connected"}')


def test_rejects_malformed_websocket_bar_payload() -> None:
    with pytest.raises(LiveStreamError, match="missing=.*"):
        _parse_live_bar(
            row={
                "T": "b",
                "S": "SPY",
                "t": "2025-01-02T14:30:00Z",
                "o": 100.0,
                "h": 101.0,
                "l": 99.0,
            },
            market="stocks",
        )
