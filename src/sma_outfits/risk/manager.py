from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sma_outfits.events import BarEvent, PositionEvent, SignalEvent
from sma_outfits.utils import stable_id


@dataclass(slots=True)
class ManagedPosition:
    signal_id: str
    symbol: str
    side: str
    entry: float
    stop: float
    opened_ts: datetime
    remaining_qty: float = 1.0
    partial_taken: bool = False
    closed: bool = False
    bars_since_extreme: int = 0
    extreme_price: float = field(default=0.0)
    risk_unit: float = field(default=0.0)

    def __post_init__(self) -> None:
        self.extreme_price = self.entry
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
        migrations: dict[str, Any] | None = None,
    ) -> None:
        self.long_break = long_break
        self.short_break = short_break
        self.partial_take_r = partial_take_r
        self.final_take_r = final_take_r
        self.timeout_bars = timeout_bars
        self.migrations = migrations or {}

    def open_position(
        self,
        signal: SignalEvent,
        symbol: str,
        ts: datetime,
    ) -> ManagedPosition:
        return ManagedPosition(
            signal_id=signal.id,
            symbol=symbol,
            side=signal.side,
            entry=signal.entry,
            stop=signal.stop,
            opened_ts=ts,
        )

    def evaluate_bar(
        self,
        position: ManagedPosition,
        bar: BarEvent,
        proxy_prices: dict[str, float] | None = None,
    ) -> list[PositionEvent]:
        if position.closed:
            return []

        events: list[PositionEvent] = []
        proxy_prices = proxy_prices or {}
        migration = self.migrations.get(position.symbol)
        if migration:
            proxy_symbol = migration.get("proxy_symbol")
            if proxy_symbol in proxy_prices:
                level = float(migration.get("break_level"))
                mode = str(migration.get("mode", "below"))
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

        if self._is_stop_hit(position, bar):
            events.append(
                self._close_event(
                    position,
                    bar.ts,
                    position.stop,
                    reason="singular_point_hard_stop",
                )
            )
            return events

        r_unit = position.risk_unit

        self._update_extreme(position, bar)

        partial_target = (
            position.entry + self.partial_take_r * r_unit
            if position.side == "LONG"
            else position.entry - self.partial_take_r * r_unit
        )
        final_target = (
            position.entry + self.final_take_r * r_unit
            if position.side == "LONG"
            else position.entry - self.final_take_r * r_unit
        )

        if not position.partial_taken and self._target_hit(position.side, bar, partial_target):
            partial_qty = round(position.remaining_qty * 0.25, 6)
            if partial_qty > 0:
                position.remaining_qty = round(position.remaining_qty - partial_qty, 6)
                position.partial_taken = True
                position.stop = position.entry
                events.append(
                    self._event(
                        position,
                        ts=bar.ts,
                        action="partial_take",
                        qty=partial_qty,
                        price=partial_target,
                        reason="+1R_partial_and_breakeven_stop",
                    )
                )

        if self._target_hit(position.side, bar, final_target) and position.remaining_qty > 0:
            events.append(
                self._close_event(
                    position,
                    ts=bar.ts,
                    price=final_target,
                    reason="+3R_final_take",
                )
            )
            return events

        if position.bars_since_extreme >= self.timeout_bars and position.remaining_qty > 0:
            events.append(
                self._close_event(
                    position,
                    ts=bar.ts,
                    price=bar.close,
                    reason="timeout",
                )
            )
            return events
        return events

    def _is_stop_hit(self, position: ManagedPosition, bar: BarEvent) -> bool:
        if position.side == "LONG":
            return bar.low <= position.stop
        return bar.high >= position.stop

    @staticmethod
    def _target_hit(side: str, bar: BarEvent, target: float) -> bool:
        if side == "LONG":
            return bar.high >= target
        return bar.low <= target

    @staticmethod
    def _update_extreme(position: ManagedPosition, bar: BarEvent) -> None:
        new_extreme = (
            bar.high > position.extreme_price
            if position.side == "LONG"
            else bar.low < position.extreme_price
        )
        if new_extreme:
            position.extreme_price = bar.high if position.side == "LONG" else bar.low
            position.bars_since_extreme = 0
            return
        position.bars_since_extreme += 1

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
