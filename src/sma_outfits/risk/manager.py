from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Callable, Literal

import pandas as pd

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
    reference_break_rules: tuple["ReferenceBreakRule", ...] = ()
    current_reference_price: float | None = None
    buy_hold_optimized: bool = False
    last_reference_session: str | None = None

    def __post_init__(self) -> None:
        self.risk_unit = abs(self.entry - self.stop)
        if self.risk_unit <= 0:
            raise ValueError("position stop must differ from entry")


@dataclass(frozen=True, slots=True)
class ReferenceBreakRule:
    symbol: str
    level: float
    threshold: float
    mode: Literal["below", "above"]
    source_route_id: str


class RiskManager:
    def __init__(
        self,
        long_break: float = 0.01,
        short_break: float = 0.01,
        partial_take_r: float = 1.0,
        final_take_r: float = 3.0,
        timeout_bars: int = 120,
        risk_dollar_per_trade: float = 1.0,
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
        if risk_dollar_per_trade <= 0:
            raise ValueError("risk_dollar_per_trade must be > 0")
        self.risk_dollar_per_trade = float(risk_dollar_per_trade)
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
        *,
        route_context: RouteBarContext | None = None,
        cross_context_lookup: Callable[[str, datetime], RouteBarContext | None] | None = None,
    ) -> ManagedPosition:
        route = self._require_route(signal.route_id)
        reference_break_rules: tuple[ReferenceBreakRule, ...] = ()
        current_reference_price: float | None = None
        last_reference_session: str | None = None
        normalized_stop = round(float(signal.stop), 6)
        risk_unit = abs(float(signal.entry) - normalized_stop)
        if risk_unit <= 0:
            raise ValueError("position stop must differ from entry")
        risk_dollar_per_trade = (
            float(route.risk_dollar_per_trade)
            if route.risk_dollar_per_trade is not None
            else self.risk_dollar_per_trade
        )
        qty = round(risk_dollar_per_trade / risk_unit, 6)
        if qty <= 0:
            raise RuntimeError(
                "Computed position qty must be > 0 "
                f"(signal_id={signal.id}, route_id={signal.route_id})"
            )
        if route.risk_mode == "penny_reference_break":
            reference_break_rules = self._build_reference_break_rules(
                signal=signal,
                route=route,
                route_context=route_context,
                cross_context_lookup=cross_context_lookup,
                opened_at=ts,
            )
            current_reference_price = self._primary_reference_level(
                reference_break_rules=reference_break_rules,
                symbol=symbol,
            )
            last_reference_session = self._session_date_key(ts)
        return ManagedPosition(
            signal_id=signal.id,
            symbol=symbol,
            side=signal.side,
            entry=signal.entry,
            stop=normalized_stop,
            opened_ts=ts,
            route_id=signal.route_id,
            remaining_qty=qty,
            reference_break_rules=reference_break_rules,
            current_reference_price=current_reference_price,
            last_reference_session=last_reference_session,
        )

    def prepare_signal_for_entry(
        self,
        signal: SignalEvent,
        route_history: pd.DataFrame | None = None,
    ) -> SignalEvent:
        route = self._require_route(signal.route_id)
        if route.risk_mode in {"singular_penny_only", "penny_reference_break"}:
            stop = (
                signal.entry - route.stop_offset
                if signal.side == "LONG"
                else signal.entry + route.stop_offset
            )
        elif route.risk_mode == "atr_dynamic_stop":
            if route_history is None:
                raise RuntimeError(
                    "ATR dynamic stop entry requires explicit route_history input"
                )
            atr_value = self._compute_atr(route_history, route.atr.period)
            if atr_value is None:
                raise RuntimeError(
                    "ATR unavailable at entry for route '{}' (need at least {} bars)".format(
                        route.id,
                        route.atr.period + 1,
                    )
                )
            distance = atr_value * route.atr.multiplier
            stop = (
                signal.entry - distance
                if signal.side == "LONG"
                else signal.entry + distance
            )
        else:
            raise RuntimeError(
                f"Unsupported route risk_mode '{route.risk_mode}' for route '{route.id}'"
            )

        normalized_stop = round(float(stop), 6)
        if round(float(signal.stop), 6) == normalized_stop:
            return signal
        return replace(signal, stop=normalized_stop)

    def evaluate_bar(
        self,
        position: ManagedPosition,
        bar: BarEvent,
        proxy_prices: dict[str, float],
        route_context: RouteBarContext | None = None,
        route_history: pd.DataFrame | None = None,
        cross_context_lookup: Callable[[str, datetime], RouteBarContext | None] | None = None,
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

        if route.risk_mode == "singular_penny_only":
            return self._evaluate_singular_penny_stop(
                position=position,
                bar=bar,
                route=route,
                route_context=route_context,
            )
        if route.risk_mode == "penny_reference_break":
            return self._evaluate_penny_reference_break(
                position=position,
                bar=bar,
                route=route,
                route_context=route_context,
                proxy_prices=proxy_prices,
                cross_context_lookup=cross_context_lookup,
            )
        if route.risk_mode == "atr_dynamic_stop":
            return self._evaluate_atr_dynamic_stop(
                position=position,
                bar=bar,
                route=route,
                route_history=route_history,
            )
        raise RuntimeError(
            f"Unsupported route risk_mode '{route.risk_mode}' for route '{route.id}'"
        )

    def _evaluate_singular_penny_stop(
        self,
        *,
        position: ManagedPosition,
        bar: BarEvent,
        route: RouteRule,
        route_context: RouteBarContext | None,
    ) -> list[PositionEvent]:
        events: list[PositionEvent] = []
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

    def _evaluate_penny_reference_break(
        self,
        *,
        position: ManagedPosition,
        bar: BarEvent,
        route: RouteRule,
        route_context: RouteBarContext | None,
        proxy_prices: dict[str, float],
        cross_context_lookup: Callable[[str, datetime], RouteBarContext | None] | None,
    ) -> list[PositionEvent]:
        if not position.reference_break_rules:
            raise RuntimeError(
                "penny_reference_break position has no reference_break_rules "
                f"(signal_id={position.signal_id}, route_id={position.route_id})"
            )
        has_cross_reference_rules = self._has_cross_reference_rules(position)

        if route.dynamic_reference_migration:
            self._update_buy_hold_state(
                position=position,
                route=route,
                route_context=route_context,
                bar_ts=bar.ts,
                cross_context_lookup=cross_context_lookup,
            )
            if position.buy_hold_optimized and not has_cross_reference_rules:
                raise RuntimeError(
                    "buy_hold_optimized requires at least one cross-symbol reference rule "
                    f"(signal_id={position.signal_id}, route_id={position.route_id})"
                )

        for reference_break in position.reference_break_rules:
            if (
                route.dynamic_reference_migration
                and position.buy_hold_optimized
                and has_cross_reference_rules
                and reference_break.symbol == position.symbol
            ):
                # In buy-and-hold optimization mode, the primary symbol is no longer
                # a liquidation trigger; only migrated cross-symbol rules can cut.
                continue
            if not self._is_reference_break_hit(
                reference_break=reference_break,
                position=position,
                bar=bar,
                proxy_prices=proxy_prices,
            ):
                continue

            if (
                reference_break.symbol == position.symbol
                and route.ignore_close_below_key_when_micro_positive
                and route_context is not None
                and route_context.micro_positive
            ):
                continue

            reason = (
                "penny_reference_break"
                if reference_break.symbol == position.symbol
                else "cross_symbol_reference_break"
            )
            close_price = self._reference_break_close_price(
                reference_break=reference_break,
                position=position,
                bar=bar,
                proxy_prices=proxy_prices,
            )
            return [
                self._close_event(
                    position,
                    bar.ts,
                    close_price,
                    reason=reason,
                )
            ]

        if route.dynamic_reference_migration:
            self._migrate_reference_break_rules(
                position=position,
                bar=bar,
                route=route,
                route_context=route_context,
                proxy_prices=proxy_prices,
                cross_context_lookup=cross_context_lookup,
            )
        return []

    def _evaluate_atr_dynamic_stop(
        self,
        *,
        position: ManagedPosition,
        bar: BarEvent,
        route: RouteRule,
        route_history: pd.DataFrame | None,
    ) -> list[PositionEvent]:
        if route_history is None:
            raise RuntimeError(
                "ATR dynamic stop evaluation requires explicit route_history input"
            )

        if self._is_stop_hit(position, bar):
            return [
                self._close_event(
                    position,
                    bar.ts,
                    position.stop,
                    reason="atr_dynamic_stop",
                )
            ]

        atr_value = self._compute_atr(route_history, route.atr.period)
        if atr_value is None:
            return []
        distance = atr_value * route.atr.multiplier
        if position.side == "LONG":
            next_stop = round(float(bar.close - distance), 6)
            if next_stop > position.stop:
                position.stop = next_stop
        else:
            next_stop = round(float(bar.close + distance), 6)
            if next_stop < position.stop:
                position.stop = next_stop
        return []

    def _require_route(self, route_id: str) -> RouteRule:
        route = self.routes.get(route_id)
        if route is None:
            raise RuntimeError(f"Unknown route_id '{route_id}' in risk manager")
        return route

    def _is_stop_hit(self, position: ManagedPosition, bar: BarEvent) -> bool:
        if position.side == "LONG":
            return bar.low <= position.stop
        return bar.high >= position.stop

    def _is_reference_break_hit(
        self,
        *,
        reference_break: ReferenceBreakRule,
        position: ManagedPosition,
        bar: BarEvent,
        proxy_prices: dict[str, float],
    ) -> bool:
        level = float(reference_break.level)
        threshold = float(reference_break.threshold)
        if threshold <= 0:
            raise RuntimeError(
                "reference_break threshold must be > 0 "
                f"(signal_id={position.signal_id}, symbol={reference_break.symbol})"
            )
        boundary = (
            level - threshold
            if reference_break.mode == "below"
            else level + threshold
        )

        if reference_break.symbol == position.symbol:
            if reference_break.mode == "below":
                return bar.low <= boundary
            return bar.high >= boundary

        if reference_break.symbol not in proxy_prices:
            raise RuntimeError(
                "Missing proxy price for cross-symbol reference break: "
                f"signal_id={position.signal_id} symbol={reference_break.symbol}"
            )
        proxy_price = float(proxy_prices[reference_break.symbol])
        if reference_break.mode == "below":
            return proxy_price <= boundary
        return proxy_price >= boundary

    def _reference_break_close_price(
        self,
        *,
        reference_break: ReferenceBreakRule,
        position: ManagedPosition,
        bar: BarEvent,
        proxy_prices: dict[str, float],
    ) -> float:
        if reference_break.symbol == position.symbol:
            boundary = (
                float(reference_break.level) - float(reference_break.threshold)
                if reference_break.mode == "below"
                else float(reference_break.level) + float(reference_break.threshold)
            )
            return round(boundary, 6)
        if reference_break.symbol not in proxy_prices:
            raise RuntimeError(
                "Missing proxy price for cross-symbol reference break: "
                f"signal_id={position.signal_id} symbol={reference_break.symbol}"
            )
        # Cross-symbol triggers liquidate the traded symbol at its own bar price.
        return round(float(bar.close), 6)

    def _update_buy_hold_state(
        self,
        *,
        position: ManagedPosition,
        route: RouteRule,
        route_context: RouteBarContext | None,
        bar_ts: datetime,
        cross_context_lookup: Callable[[str, datetime], RouteBarContext | None] | None,
    ) -> None:
        if position.buy_hold_optimized:
            return
        if not self._has_cross_reference_rules(position):
            return
        if route_context is None:
            return
        if route_context.route.id != route.id:
            raise RuntimeError(
                "Route context mismatch while evaluating dynamic reference migration: "
                f"route_id={route.id}, context_route_id={route_context.route.id}"
            )
        if not (route_context.macro_positive and route_context.micro_positive):
            return
        if cross_context_lookup is None:
            raise RuntimeError(
                "dynamic_reference_migration buy-hold optimization requires "
                "cross_context_lookup when cross-symbol reference rules are active "
                f"(signal_id={position.signal_id}, route_id={position.route_id})"
            )
        if self._has_positive_cross_context(
            position=position,
            bar_ts=bar_ts,
            cross_context_lookup=cross_context_lookup,
        ):
            position.buy_hold_optimized = True

    def _migrate_reference_break_rules(
        self,
        *,
        position: ManagedPosition,
        bar: BarEvent,
        route: RouteRule,
        route_context: RouteBarContext | None,
        proxy_prices: dict[str, float],
        cross_context_lookup: Callable[[str, datetime], RouteBarContext | None] | None,
    ) -> None:
        has_cross_reference_rules = self._has_cross_reference_rules(position)
        if has_cross_reference_rules and cross_context_lookup is None:
            raise RuntimeError(
                "dynamic_reference_migration requires cross_context_lookup when "
                "cross-symbol reference rules are active "
                f"(signal_id={position.signal_id}, route_id={position.route_id})"
            )
        if route_context is not None and route_context.route.id != route.id:
            raise RuntimeError(
                "Route context mismatch while migrating reference levels: "
                f"route_id={route.id}, context_route_id={route_context.route.id}"
            )

        session_date = self._session_date_key(bar.ts)
        is_new_session = (
            position.last_reference_session is not None
            and session_date != position.last_reference_session
        )
        position.last_reference_session = session_date

        updated_rules: list[ReferenceBreakRule] = []
        for reference_break in position.reference_break_rules:
            candidates: list[float] = []
            if reference_break.symbol == position.symbol:
                if position.buy_hold_optimized and has_cross_reference_rules:
                    updated_rules.append(reference_break)
                    continue
                if route_context is not None:
                    candidates.append(round(float(route_context.key_sma), 6))
                if is_new_session:
                    session_level = (
                        round(float(bar.low), 6)
                        if reference_break.mode == "below"
                        else round(float(bar.high), 6)
                    )
                    candidates.append(session_level)
            else:
                if cross_context_lookup is not None:
                    cross_context = cross_context_lookup(reference_break.source_route_id, bar.ts)
                    if (
                        cross_context is not None
                        and cross_context.macro_positive
                        and cross_context.micro_positive
                    ):
                        candidates.append(round(float(cross_context.key_sma), 6))

            if not candidates:
                updated_rules.append(reference_break)
                continue

            migrated_level = self._migrate_reference_level(
                level=float(reference_break.level),
                mode=reference_break.mode,
                candidates=candidates,
            )
            if migrated_level == round(float(reference_break.level), 6):
                updated_rules.append(reference_break)
                continue
            updated_rules.append(replace(reference_break, level=migrated_level))

        position.reference_break_rules = tuple(updated_rules)
        position.current_reference_price = self._primary_reference_level(
            reference_break_rules=position.reference_break_rules,
            symbol=position.symbol,
        )

    @staticmethod
    def _migrate_reference_level(
        *,
        level: float,
        mode: Literal["below", "above"],
        candidates: list[float],
    ) -> float:
        if mode == "below":
            return round(max([level, *candidates]), 6)
        return round(min([level, *candidates]), 6)

    @staticmethod
    def _primary_reference_level(
        *,
        reference_break_rules: tuple[ReferenceBreakRule, ...],
        symbol: str,
    ) -> float | None:
        for reference_break in reference_break_rules:
            if reference_break.symbol == symbol:
                return round(float(reference_break.level), 6)
        return None

    @staticmethod
    def _session_date_key(ts: datetime) -> str:
        ts_utc = pd.Timestamp(ts)
        if ts_utc.tzinfo is None:
            ts_utc = ts_utc.tz_localize("UTC")
        else:
            ts_utc = ts_utc.tz_convert("UTC")
        return ts_utc.tz_convert("America/New_York").strftime("%Y-%m-%d")

    @staticmethod
    def _has_cross_reference_rules(position: ManagedPosition) -> bool:
        return any(
            rule.symbol != position.symbol for rule in position.reference_break_rules
        )

    @staticmethod
    def _has_positive_cross_context(
        *,
        position: ManagedPosition,
        bar_ts: datetime,
        cross_context_lookup: Callable[[str, datetime], RouteBarContext | None],
    ) -> bool:
        route_ids = sorted(
            {
                rule.source_route_id
                for rule in position.reference_break_rules
                if rule.symbol != position.symbol
            }
        )
        if not route_ids:
            return False
        for route_id in route_ids:
            context = cross_context_lookup(route_id, bar_ts)
            if context is None:
                continue
            if context.macro_positive and context.micro_positive:
                return True
        return False

    def _build_reference_break_rules(
        self,
        *,
        signal: SignalEvent,
        route: RouteRule,
        route_context: RouteBarContext | None,
        cross_context_lookup: Callable[[str, datetime], RouteBarContext | None] | None,
        opened_at: datetime,
    ) -> tuple[ReferenceBreakRule, ...]:
        if route_context is None:
            raise RuntimeError(
                "penny_reference_break requires explicit route_context at position open "
                f"(route_id={route.id}, signal_id={signal.id})"
            )
        if route_context.route.id != route.id:
            raise RuntimeError(
                "Route context mismatch while building reference breaks: "
                f"route_id={route.id}, context_route_id={route_context.route.id}"
            )

        threshold = round(float(route.stop_offset), 6)
        if threshold <= 0:
            raise RuntimeError(
                f"route.stop_offset must be > 0 for penny_reference_break (route_id={route.id})"
            )
        mode: Literal["below", "above"] = "below" if signal.side == "LONG" else "above"

        rules: list[ReferenceBreakRule] = [
            ReferenceBreakRule(
                symbol=route.symbol,
                level=round(float(route_context.key_sma), 6),
                threshold=threshold,
                mode=mode,
                source_route_id=route.id,
            )
        ]

        cross_rules = route.cross_symbol_context.rules if route.cross_symbol_context.enabled else []
        if cross_rules:
            if cross_context_lookup is None:
                raise RuntimeError(
                    "penny_reference_break requires cross_context_lookup for cross-symbol "
                    f"reference routes (route_id={route.id})"
                )
            for cross_rule in cross_rules:
                reference_context = cross_context_lookup(cross_rule.reference_route_id, opened_at)
                if reference_context is None:
                    opened_at_ts = pd.Timestamp(opened_at)
                    opened_at_iso = (
                        opened_at_ts.tz_convert("UTC").isoformat()
                        if opened_at_ts.tzinfo is not None
                        else opened_at_ts.tz_localize("UTC").isoformat()
                    )
                    raise RuntimeError(
                        "Missing cross-symbol context while opening penny_reference_break "
                        "position: route_id={} reference_route_id={} opened_at={}".format(
                            route.id,
                            cross_rule.reference_route_id,
                            opened_at_iso,
                        )
                    )
                rules.append(
                    ReferenceBreakRule(
                        symbol=reference_context.route.symbol,
                        level=round(float(reference_context.key_sma), 6),
                        threshold=threshold,
                        mode=mode,
                        source_route_id=reference_context.route.id,
                    )
                )
        return tuple(rules)

    @staticmethod
    def _compute_atr(
        route_history: pd.DataFrame,
        period: int,
    ) -> float | None:
        required_columns = {"high", "low", "close"}
        missing_columns = sorted(required_columns.difference(route_history.columns))
        if missing_columns:
            raise RuntimeError(
                "ATR dynamic stop requires route_history columns: "
                + ", ".join(missing_columns)
            )
        if len(route_history) < period + 1:
            return None

        window = route_history.iloc[-(period + 1) :]
        try:
            highs = [float(value) for value in window["high"].tolist()]
            lows = [float(value) for value in window["low"].tolist()]
            closes = [float(value) for value in window["close"].tolist()]
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "ATR dynamic stop requires numeric high/low/close values in route_history"
            ) from exc

        true_ranges: list[float] = []
        for index in range(1, len(window)):
            high = highs[index]
            low = lows[index]
            prev_close = closes[index - 1]
            true_ranges.append(
                max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close),
                )
            )

        if len(true_ranges) < period:
            return None
        return float(sum(true_ranges[-period:]) / period)

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
