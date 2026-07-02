#!/usr/bin/env python3
"""Canonical Atlas report block renderers.

Pure formatting module: no DB calls, no price fetching, no Telegram, no provider calls.
The initial shapes are extracted from atlas_intraday.py canonical renderers.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

RVOL_DISPLAY_THRESHOLD = 1.5

try:
    from atlas_symbol_meta import ticker_label
except Exception:  # pragma: no cover - staging fallback only
    def ticker_label(ticker, item=None):
        return str(ticker or "?").upper()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _price(value: Any) -> str:
    if value in (None, ""):
        return "N/A"
    return f"${_num(value):,.2f}"


def _money(value: Any) -> str:
    if value in (None, ""):
        return "N/A"
    return f"${_num(value):,.0f}"


def _signed_money(value: Any) -> str:
    n = _num(value)
    sign = "+" if n >= 0 else "−"
    return f"{sign}${abs(n):,.0f}"


def _fmt_pct(value: Any, signed: bool = False, decimals: int = 0) -> str:
    n = _num(value)
    sign = "+" if signed and n >= 0 else ("−" if signed and n < 0 else "")
    return f"{sign}{abs(n):.{decimals}f}%" if signed else f"{n:.{decimals}f}%"


def _row_value(row: Any, *names: str, default: Any = None) -> Any:
    if row is None:
        return default
    for name in names:
        if isinstance(row, dict) and row.get(name) not in (None, ""):
            return row.get(name)
        if not isinstance(row, dict) and hasattr(row, name):
            value = getattr(row, name)
            if value not in (None, ""):
                return value
    return default


def _row_ticker(row: Any) -> str:
    return str(_row_value(row, "ticker", "symbol", default="") or "").upper()


def _ticker_label(ticker: str, item: Any | None = None) -> str:
    if isinstance(item, dict):
        return ticker_label(ticker, item=item)
    return ticker_label(ticker, item={"ticker": ticker})


def _unique(items: Iterable[Any] | None, key: str = "ticker") -> list[Any]:
    out, seen = [], set()
    for item in items or []:
        val = _row_ticker(item) if key == "ticker" else _row_value(item, key, default=None)
        if val in seen:
            continue
        seen.add(val)
        out.append(item)
    return out


def _pillar_num(value: Any) -> int:
    match = re.search(r"(\d+)", str(value or ""))
    return int(match.group(1)) if match else 0


def _signal_pillar_text(row: Any) -> str:
    raw = _row_value(row, "score", "pillar_score", default="")
    match = re.search(r"(\d+/4)", str(raw or ""))
    return match.group(1) if match else f"{_pillar_num(raw)}/4"


def _rvol_value(row: Any) -> float | None:
    for key in ("rvol", "gap_rvol", "breakout_rvol"):
        value = _row_value(row, key, default=None)
        if value not in (None, ""):
            try:
                return float(value)
            except Exception:
                continue
    return None


def _rvol_line(row: Any, threshold: float = RVOL_DISPLAY_THRESHOLD) -> str:
    rvol = _rvol_value(row)
    if rvol is None:
        return f"   📊 RVOL N/A / {threshold:g} ❌"
    marker = "✅" if rvol >= threshold else "❌"
    return f"   📊 RVOL {rvol:g} / {threshold:g} {marker}"


def _watch_sort_value(item: Any) -> float:
    if isinstance(item, dict):
        raw = item.get("pct_over_ema")
        if raw not in (None, ""):
            try:
                return float(raw)
            except Exception:
                pass
        text = f"{item.get('reason', '')} {item.get('signal', '')}"
    else:
        text = str(item or "")
    match = re.search(r"\+([0-9.]+)%", text)
    return _num(match.group(1), 0.0) if match else 0.0


def _as_position(row: Any) -> dict[str, Any]:
    ticker = _row_ticker(row)
    entry = _row_value(row, "entry_price", "entry", "price", default=0.0)
    current = _row_value(row, "current_price", "last", "last_price", "now", default=entry)
    stop = _row_value(row, "stop_loss", "stop", default=entry)
    target = _row_value(row, "target_price", "target", default=entry)
    shares = _row_value(row, "shares", "quantity", "qty", default=0.0)
    invested = _row_value(row, "invested_capital", default=None)
    if invested is None:
        invested = _num(entry) * _num(shares)
    current_value = _row_value(row, "current_value", default=None)
    if current_value is None:
        current_value = _num(current) * _num(shares)
    pl_usd = _row_value(row, "unrealized_pl_usd", "pnl_usd", "pl_usd", default=None)
    if pl_usd is None:
        pl_usd = _num(current_value) - _num(invested)
    pl_pct = _row_value(row, "unrealized_pl_pct", "pnl_pct", "pl_pct", default=None)
    if pl_pct is None:
        pl_pct = (_num(pl_usd) / _num(invested) * 100.0) if _num(invested) else 0.0
    return {
        "ticker": ticker,
        "entry_price": _num(entry),
        "current_price": _num(current),
        "stop_loss": _num(stop),
        "target_price": _num(target),
        "shares": _num(shares),
        "invested_capital": _num(invested),
        "current_value": _num(current_value),
        "unrealized_pl_usd": _num(pl_usd),
        "unrealized_pl_pct": _num(pl_pct),
    }


def portfolio_footer(total_invested: Any, current_value: Any, blended_roi: Any | None = None) -> list[str]:
    """Canonical Atlas portfolio footer.

    If blended_roi is None, it is computed as percent ROI from invested/current.
    If blended_roi is a small absolute ratio (e.g. 0.032), pass 3.2 instead;
    the intraday canonical footer expects a percent number.
    """
    invested = _num(total_invested)
    current = _num(current_value)
    roi_pct = _num(blended_roi) if blended_roi is not None else ((current - invested) / invested * 100.0 if invested else 0.0)
    roi_dollar = current - invested
    return [
        "─────────────────────",
        f"💼 Total Invested: {_money(invested)}",
        f"📊 Current Value:  {_money(current)}",
        f"📈 Blended ROI:    {_fmt_pct(roi_pct, signed=True, decimals=1)} ({_signed_money(roi_dollar)})",
        "",
    ]


def holding_block(positions: Iterable[Any] | None, summary: dict[str, Any] | None = None) -> list[str]:
    """Canonical HOLDING block, pure formatting from passed positions."""
    trades = [_as_position(row) for row in (positions or []) if _row_ticker(row)]
    lines = ["", f"━━━ 💼 HOLDING ({len(trades)}) ━━━"]
    if not trades:
        lines.append("📭 none")
        return lines
    lines.append("")
    for i, trade in enumerate(trades, 1):
        icon = "🟢" if trade["unrealized_pl_usd"] >= 0 else "🔴"
        label = _ticker_label(trade["ticker"], {"ticker": trade["ticker"]})
        lines += [
            f"{i}. {icon} {label}",
            f"   💵 Entry {_price(trade['entry_price'])}",
            f"   👀 Now {_price(trade['current_price'])}",
            f"   🚦 Stop {_price(trade['stop_loss'])}",
            f"   🎯 Target {_price(trade['target_price'])}",
            f"   ({_fmt_pct(trade['unrealized_pl_pct'], signed=True, decimals=0)} · {_signed_money(trade['unrealized_pl_usd'])} · ~{_money(trade['current_value'])})",
            "",
        ]
    total_invested = sum(trade["invested_capital"] for trade in trades)
    current_value = sum(trade["current_value"] for trade in trades)
    lines += portfolio_footer(total_invested, current_value)
    return lines


def watch_list_block(watch_data: Any, open_tickers: Iterable[str] | None = None) -> list[str]:
    """Canonical WATCHING block with open-position exclusion, no DB calls."""
    if isinstance(watch_data, dict):
        watch_2 = [str(t).upper() for t in (watch_data.get("watch_2", []) or [])]
        high_candidates = watch_data.get("high_candidates", []) or []
    else:
        watch_2 = []
        high_candidates = list(watch_data or [])
    blocked = {"SPY", "QQQ", "DIA", ""} | {str(t or "").upper() for t in (open_tickers or [])}
    detail_by_ticker: dict[str, Any] = {}
    for item in high_candidates:
        if isinstance(item, dict):
            ticker = _row_ticker(item)
            action = str(item.get("action", "")).upper()
            if ticker and (action == "WATCH" or not action):
                detail_by_ticker[ticker] = item
        else:
            ticker = str(item or "").upper()
            if ticker:
                detail_by_ticker[ticker] = {"ticker": ticker}
    rows = []
    seen = set()
    for ticker in watch_2 + sorted(detail_by_ticker):
        ticker = str(ticker or "").upper()
        if ticker in blocked or ticker in seen:
            continue
        seen.add(ticker)
        item = detail_by_ticker.get(ticker, {"ticker": ticker})
        rows.append((_watch_sort_value(item), _ticker_label(ticker, item)))
    rows.sort(key=lambda x: x[0], reverse=True)
    lines = ["", f"━━━ 👀 WATCHING ({len(rows)}) ━━━"]
    if not rows:
        lines.append("none")
        return lines
    lines.append("")
    for i, (_, label) in enumerate(rows, 1):
        lines.append(f"{i}. {label}")
    return lines


def pullback_block(pullback_data: Iterable[Any] | None) -> list[str]:
    """Canonical WAITING FOR DIP block, pure formatting from passed rows."""
    waits = _unique([
        row for row in (pullback_data or [])
        if str(_row_value(row, "action", default="WAIT") or "WAIT").upper() == "WAIT"
        and "PULLBACK" in str(_row_value(row, "reason", default="PULLBACK") or "").upper()
    ])
    lines = ["", f"━━━ 🎣 WAITING FOR DIP ({len(waits)}) ━━━", ""]
    if not waits:
        lines.append("✅ none")
        return lines
    for i, row in enumerate(waits, 1):
        ticker = _row_ticker(row) or "?"
        label = _ticker_label(ticker, row if isinstance(row, dict) else {"ticker": ticker})
        trigger = _row_value(row, "trigger_price", "entry_price", "entry", default=None)
        current = _row_value(row, "current_price", "price", "reference_price", "last_price", default=None)
        delta = ((_num(current) - _num(trigger)) / _num(trigger) * 100.0) if _num(trigger) else 0.0
        rsi = _row_value(row, "rsi", default=None)
        macd_hist = _row_value(row, "macd_hist", default=None)
        fundamentals_ok = bool(_row_value(row, "fundamentals_ok", default=False))
        momentum_weak = bool(_row_value(row, "momentum_weak", default=False))
        no_earnings = bool(_row_value(row, "no_earnings", default=False))
        lines += [
            f"{i}. {label}",
            f"   💵 Entry {_price(trigger)}",
            f"   👀 Now {_price(current)} ({_fmt_pct(delta, signed=True, decimals=0)})",
            _rvol_line(row),
            f"   {_signal_pillar_text(row)}",
            f"   📉 RSI {_num(rsi):.0f}" if rsi is not None else "   📉 RSI N/A",
            f"   📈 MACD+ · {_num(macd_hist):.1f}" if macd_hist is not None else "   📈 MACD+ · N/A",
            "   ✅ Fundamentals" if fundamentals_ok else "   ⚠️ Momentum Weak · No Earnings" if (momentum_weak or no_earnings) else "   —",
            "",
        ]
    return lines


__all__ = ["holding_block", "watch_list_block", "pullback_block", "portfolio_footer"]
