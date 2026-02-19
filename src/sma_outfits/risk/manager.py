from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sma_outfits.config.models import RouteRule
from sma_outfits.events import BarEvent, PositionEvent, SignalEvent
from sma_outfits.signals.detector import RouteBarContext
from sma_outfits.utils import stable_id


@dataclass(slots=True)
class ManagedPosition:
    signal_id: str
    symbol: str
    side: str
    entry: float
    stop: float
    opened_ts: datetime
    route_id: str
    remaining_qty: float = 1.0
    closed: bool = False
    risk_unit: float = 0.0

    def __post_init__(self) -> None:
        self.risk_unit = abs(self.entry - self.stop)
        if self.risk_unit <= 0:
            raise ValueError("position stop must differ from entry")


class RiskManager:
    def __init__(
        self,
        long_break: float = 0.01,
        short_break: float = 0.01,
        partial_take_r: float = 1.0,
        final_take_r: float = 3.0,
        timeout_bars: int = 120,
        *,
        migrations: dict[str, Any],
        routes: dict[str, RouteRule],
        allow_same_bar_exit: bool = False,
    ) -> None:
        self.long_break = long_break
        self.short_break = short_break
        self.partial_take_r = partial_take_r
        self.final_take_r = final_take_r
        self.timeout_bars = timeout_bars
        self.allow_same_bar_exit = allow_same_bar_exit
        if not isinstance(migrations, dict):
            raise TypeError("migrations must be an explicit dict")
        if not isinstance(routes, dict):
            raise TypeError("routes must be an explicit dict")
        self.migrations = migrations
        self.routes = routes

    def open_position(
        self,
        signal: SignalEvent,
        symbol: str,
        ts: datetime,
    ) -> ManagedPosition:
        route = self._require_route(signal.route_id)
        stop = (
            signal.entry - route.stop_offset
            if signal.side == "LONG"
            else signal.entry + route.stop_offset
        )
        return ManagedPosition(
            signal_id=signal.id,
            symbol=symbol,
            side=signal.side,
            entry=signal.entry,
            stop=round(float(stop), 6),
            opened_ts=ts,
            route_id=signal.route_id,
        )

    def evaluate_bar(
        self,
        position: ManagedPosition,
        bar: BarEvent,
        proxy_prices: dict[str, float],
        route_context: RouteBarContext | None = None,
    ) -> list[PositionEvent]:
        if position.closed:
            return []
        if not isinstance(proxy_prices, dict):
            raise TypeError("proxy_prices must be an explicit dict")

        if not self.allow_same_bar_exit and bar.ts == position.opened_ts:
            return []

        route = self._require_route(position.route_id)
        if route_context is not None and route_context.route.id != route.id:
            raise RuntimeError(
                "Route context mismatch: "
                f"position route_id={route.id}, context route_id={route_context.route.id}"
            )

        events: list[PositionEvent] = []
        migration = self.migrations.get(position.symbol)
        if migration is not None:
            if not isinstance(migration, dict):
                raise RuntimeError(
                    f"Invalid risk migration config for {position.symbol}: expected map"
                )
            missing_keys = {"proxy_symbol", "break_level", "mode"}.difference(migration.keys())
            if missing_keys:
                raise RuntimeError(
                    "Invalid risk migration config for "
                    f"{position.symbol}: missing keys {sorted(missing_keys)}"
                )
            proxy_symbol = str(migration["proxy_symbol"])
            if proxy_symbol in proxy_prices:
                level = float(migration["break_level"])
                mode = str(migration["mode"])
                if mode not in {"below", "above"}:
                    raise RuntimeError(
                        f"Invalid risk migration mode for {position.symbol}: {mode}"
                    )
                proxy_price = proxy_prices[proxy_symbol]
                breached = proxy_price <= level if mode == "below" else proxy_price >= level
                if breached:
                    events.append(
                        self._close_event(
                            position,
                            bar.ts,
                            bar.close,
                            reason="risk_migration_cut",
                        )
                    )
                    return events

        if route.risk_mode != "singular_penny_only":
            raise RuntimeError(
                f"Unsupported route risk_mode '{route.risk_mode}' for route '{route.id}'"
            )

        if self._is_stop_hit(position, bar):
            if (
                route.ignore_close_below_key_when_micro_positive
                and route_context is not None
                and route_context.micro_positive
            ):
                return []
            events.append(
                self._close_event(
                    position,
                    bar.ts,
                    position.stop,
                    reason="singular_point_hard_stop",
                )
            )
            return events
        return events

    def _require_route(self, route_id: str) -> RouteRule:
        route = self.routes.get(route_id)
        if route is None:
            raise RuntimeError(f"Unknown route_id '{route_id}' in risk manager")
        return route

    def _is_stop_hit(self, position: ManagedPosition, bar: BarEvent) -> bool:
        if position.side == "LONG":
            return bar.low <= position.stop
        return bar.high >= position.stop

    def _close_event(
        self,
        position: ManagedPosition,
        ts: datetime,
        price: float,
        reason: str,
    ) -> PositionEvent:
        qty = position.remaining_qty
        position.remaining_qty = 0.0
        position.closed = True
        return self._event(
            position,
            ts=ts,
            action="close",
            qty=qty,
            price=price,
            reason=reason,
        )

    @staticmethod
    def _event(
        position: ManagedPosition,
        ts: datetime,
        action: str,
        qty: float,
        price: float,
        reason: str,
    ) -> PositionEvent:
        return PositionEvent(
            id=stable_id(position.signal_id, action, str(ts), reason, str(price)),
            signal_id=position.signal_id,
            action=action,
            qty=qty,
            price=round(float(price), 6),
            reason=reason,
            ts=ts,
        )
