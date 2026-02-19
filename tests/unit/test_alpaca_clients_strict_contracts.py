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

    def get(self, *_args: Any, **_kwargs: Any) -> _FakeResponse:
        response = self._responses[self.calls]
        self.calls += 1
        return response


def _config() -> AlpacaConfig:
    return AlpacaConfig(
        api_key="test-key",
        secret_key="test-secret",
        base_url="https://paper-api.alpaca.markets",
        data_url="https://data.alpaca.markets",
        data_feed="iex",
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
        )


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
