#!/usr/bin/env python3
"""Atlas report authority/provenance helpers.

Pure report visibility layer: no DB writes, no provider calls, no Telegram.
It labels source authority for rendered numbers and surfaces non-OPEN economic
exposure states that must not disappear from Professor-facing reports.
"""
from __future__ import annotations
from typing import Any, Iterable

SOURCE_TFE = "[TFE]"
SOURCE_DB = "[DB]"
SOURCE_BROKER = "[BROKER]"
SOURCE_PROVIDER = "[PROVIDER]"
SOURCE_CACHE = "[CACHE]"
SOURCE_FALLBACK = "[FALLBACK]"
SOURCE_RENDER_CALC = "[RENDER-CALC]"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _price(value: Any) -> str:
    return "N/A" if value in (None, "") else f"${_num(value):,.2f}"


def _qty(value: Any) -> str:
    try:
        return f"{float(value):g}"
    except Exception:
        return str(value or "N/A")


def _signed_money(value: Any) -> str:
    n = _num(value)
    sign = "+" if n >= 0 else "−"
    return f"{sign}${abs(n):,.0f}"


def _pct(value: Any) -> str:
    n = _num(value)
    sign = "+" if n >= 0 else "−"
    return f"{sign}{abs(n):.1f}%"


def price_with_source(value: Any, source: str) -> str:
    return f"{source} {_price(value)}"


def provider_or_fallback_price(value: Any, fallback: Any) -> tuple[Any, str]:
    if value not in (None, ""):
        return value, SOURCE_PROVIDER
    return fallback, SOURCE_FALLBACK


def _ticker(row: Any) -> str:
    if isinstance(row, dict):
        return str(row.get("ticker") or row.get("symbol") or "?").upper()
    return str(getattr(row, "ticker", "?") or "?").upper()


def _get(row: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(row, dict) and row.get(name) not in (None, ""):
            return row.get(name)
        if not isinstance(row, dict) and hasattr(row, name):
            value = getattr(row, name)
            if value not in (None, ""):
                return value
    return default


def render_open_positions(open_rows: Iterable[dict] | None) -> list[str]:
    rows = [dict(r or {}) for r in (open_rows or [])]
    lines = ["", f"━━━ 💼 OPEN POSITIONS ({len(rows)}) ━━━"]
    if not rows:
        lines.append("📭 none")
        return lines
    lines.append("")
    for idx, row in enumerate(rows, 1):
        ticker = _ticker(row)
        entry = _get(row, "entry_price", "entry", "price")
        qty = _get(row, "quantity", "shares", "qty")
        current = _get(row, "current_price", "now", "last_price", default=entry)
        current_source = _get(row, "current_price_source", default=SOURCE_FALLBACK if current == entry else SOURCE_PROVIDER)
        stop = _get(row, "stop_loss", "stop")
        target = _get(row, "target_price", "target")
        lines += [
            f"{idx}. {ticker} {SOURCE_DB}",
            f"   Qty {SOURCE_DB} {_qty(qty)}",
            f"   💵 Entry {SOURCE_DB} {_price(entry)}",
            f"   👀 Now {current_source} {_price(current)}",
            f"   🚦 Stop {SOURCE_DB}/{SOURCE_TFE} {_price(stop)}",
            f"   🎯 Target {SOURCE_DB}/{SOURCE_TFE} {_price(target)}",
            "",
        ]
    return lines


def render_pending_broker_confirmation(pending_rows: Iterable[dict] | None) -> list[str]:
    rows = [dict(r or {}) for r in (pending_rows or [])]
    lines = ["", f"━━━ ⏳ SELL TRIGGERED / BROKER CONFIRMATION PENDING ({len(rows)}) ━━━"]
    if not rows:
        lines.append("✅ none")
        return lines
    lines.append("")
    for idx, row in enumerate(rows, 1):
        ticker = _ticker(row)
        entry = _get(row, "entry_price")
        qty = _get(row, "quantity")
        exit_price = _get(row, "exit_price")
        stop = _get(row, "stop_loss")
        target = _get(row, "target_price")
        exit_at = _get(row, "exit_at", default="N/A")
        pnl = _get(row, "realized_pnl", default=None)
        pnl_pct = _get(row, "realized_pnl_pct", default=None)
        if pnl in (None, "") and entry not in (None, "") and exit_price not in (None, ""):
            pnl = (_num(exit_price) - _num(entry)) * _num(qty)
        lines += [
            f"{idx}. ⚠️ {ticker} {SOURCE_DB}",
            f"   Qty {SOURCE_DB} {_qty(qty)}",
            f"   💵 Entry {SOURCE_DB} {_price(entry)}",
            f"   🚦 Exit trigger {SOURCE_DB} {_price(exit_price)} (stop {SOURCE_DB}/{SOURCE_TFE} {_price(stop)})",
            f"   🎯 Prior target {SOURCE_DB}/{SOURCE_TFE} {_price(target)}",
            f"   🕐 Triggered {SOURCE_DB} {exit_at}",
            f"   📊 Est. P/L {SOURCE_RENDER_CALC} {_signed_money(pnl)} ({_pct(pnl_pct) if pnl_pct not in (None, '') else 'N/A'})",
            f"   broker_confirmed {SOURCE_BROKER}: NO",
            f"   cash_credit {SOURCE_DB}: NO",
            "",
        ]
    return lines


def render_cash_pending(pending_rows: Iterable[dict] | None) -> list[str]:
    rows = [dict(r or {}) for r in (pending_rows or [])]
    lines = ["", f"━━━ 💵 CASH CREDIT PENDING ({len(rows)}) ━━━"]
    if not rows:
        lines.append("✅ none")
        return lines
    lines.append("")
    for idx, row in enumerate(rows, 1):
        ticker = _ticker(row)
        exit_price = _get(row, "exit_price")
        qty = _get(row, "quantity")
        lines.append(f"{idx}. {ticker} {SOURCE_DB} · expected sell-credit not posted · qty {_qty(qty)} · exit {_price(exit_price)}")
        lines.append("")
    return lines


def render_portfolio_visibility_block(open_rows=None, pending_rows=None, include_cash_pending=True) -> list[str]:
    lines = ["", "━━━ 🧾 PORTFOLIO VISIBILITY / SOURCE AUTHORITY ━━━"]
    lines += render_open_positions(open_rows)
    lines += render_pending_broker_confirmation(pending_rows)
    if include_cash_pending:
        lines += render_cash_pending(pending_rows)
    return lines


def portfolio_context_tickers(open_rows=None, pending_rows=None) -> set[str]:
    tickers = {_ticker(r) for r in (open_rows or []) if _ticker(r) != "?"}
    tickers |= {_ticker(r) for r in (pending_rows or []) if _ticker(r) != "?"}
    return tickers
