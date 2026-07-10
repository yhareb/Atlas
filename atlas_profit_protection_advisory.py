#!/usr/bin/env python3
"""Deterministic profit-protection advisory cards.

Staging-only helper for P0P1. Pure calculations; no DB writes, no Telegram,
no broker actions, no Fat Engine/protected imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ProfitProtectionCard:
    ticker: str
    current_price: float
    entry_price: float
    open_gain_pct: float
    current_db_stop: float
    target_price: float
    distance_to_target_pct: float
    distance_to_stop_pct: float
    suggested_trailing_stop: float | None
    trim_level: float | None
    invalidation_level: float | None
    action: str
    reason: str
    advisory_only: bool = True


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace("$", "").replace(",", ""))
    except Exception:
        return default


def _money(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


def _pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else "−"
    return f"{sign}{abs(value):.1f}%"


def compute_profit_protection(position: dict[str, Any]) -> ProfitProtectionCard | None:
    """Compute one advisory card from already-normalized holding fields."""
    ticker = str(position.get("ticker") or "").upper().strip()
    entry = _num(position.get("entry_price") or position.get("entry"))
    current = _num(position.get("current_price") or position.get("last") or position.get("now"))
    stop = _num(position.get("stop_loss") or position.get("stop"))
    target = _num(position.get("target_price") or position.get("target"))
    price_authority = position.get("price_authority") if isinstance(position.get("price_authority"), dict) else {}
    valuation_valid = position.get("valuation_valid")
    if valuation_valid is None and price_authority:
        valuation_valid = bool(price_authority.get("is_valuation_valid"))
    if not ticker or entry is None or current is None or stop is None or target is None:
        return None
    if entry <= 0 or current <= 0 or stop <= 0 or target <= 0:
        return None
    if valuation_valid is False:
        return None

    open_gain_pct = (current - entry) / entry * 100.0
    distance_to_target_pct = (target - current) / current * 100.0
    distance_to_stop_pct = (current - stop) / current * 100.0
    target_progress = (current - entry) / (target - entry) if target > entry else 0.0

    breakeven_plus_2 = entry * 1.02
    half_gain_stop = entry + 0.50 * (current - entry)
    eight_pct_trail = current * 0.92
    suggested = max(stop, breakeven_plus_2, half_gain_stop, eight_pct_trail)
    if suggested >= current:
        suggested_valid: float | None = None
        invalidation: float | None = stop
    else:
        suggested_valid = suggested
        invalidation = max(stop, suggested * 0.98)
    trim_level = target * 0.97 if target > 0 else None

    if invalidation is not None and current <= invalidation:
        action = "EXIT REVIEW"
        reason = "price near advisory invalidation"
    elif current <= stop:
        action = "EXIT REVIEW"
        reason = "price at or below current DB stop"
    elif open_gain_pct >= 8.0 and (distance_to_target_pct <= 10.0 or target_progress >= 0.80):
        action = "TRIM REVIEW"
        reason = "gain above 8% and near target"
    elif open_gain_pct >= 8.0:
        action = "PROTECT PROFIT"
        reason = "gain above 8%; DB stop remains far below current price"
    elif open_gain_pct > 0 and distance_to_stop_pct >= 15.0:
        action = "PROTECT PROFIT"
        reason = "positive position with wide distance to DB stop"
    else:
        action = "HOLD"
        reason = "profit-protection trigger not active"

    return ProfitProtectionCard(
        ticker=ticker,
        current_price=current,
        entry_price=entry,
        open_gain_pct=open_gain_pct,
        current_db_stop=stop,
        target_price=target,
        distance_to_target_pct=distance_to_target_pct,
        distance_to_stop_pct=distance_to_stop_pct,
        suggested_trailing_stop=suggested_valid,
        trim_level=trim_level,
        invalidation_level=invalidation,
        action=action,
        reason=reason,
    )


def render_profit_protection_cards(positions: Iterable[dict[str, Any]], ticker_label=None) -> list[str]:
    """Render advisory section for positions whose action is not HOLD."""
    cards = []
    for position in positions or []:
        card = compute_profit_protection(dict(position or {}))
        if card and card.action != "HOLD":
            cards.append(card)
    if not cards:
        return []

    lines = ["", "━━━ 🛡️ PROFIT PROTECTION — ADVISORY ONLY ━━━", ""]
    for i, card in enumerate(cards, 1):
        label = ticker_label(card.ticker) if callable(ticker_label) else card.ticker
        lines += [
            f"{i}. {label}",
            f"   👀 Current {_money(card.current_price)}",
            f"   💵 Entry {_money(card.entry_price)} · Open gain {_pct(card.open_gain_pct)}",
            f"   🚦 Current DB stop {_money(card.current_db_stop)} · distance {card.distance_to_stop_pct:.1f}%",
            f"   🎯 Target {_money(card.target_price)} · distance {card.distance_to_target_pct:.1f}%",
            f"   🛡️ Suggested advisory stop {_money(card.suggested_trailing_stop)} — advisory only, no DB update",
            f"   ✂️ Trim review {_money(card.trim_level)} — advisory only",
            f"   ❌ Invalidation {_money(card.invalidation_level)}",
            f"   Action: {card.action}",
            "",
        ]
    return lines


__all__ = ["ProfitProtectionCard", "compute_profit_protection", "render_profit_protection_cards"]
