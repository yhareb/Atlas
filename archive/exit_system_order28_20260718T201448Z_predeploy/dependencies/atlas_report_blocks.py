#!/usr/bin/env python3
"""Canonical Atlas report block renderers.

Pure formatting module: no DB calls, no price fetching, no Telegram, no provider calls.
The initial shapes are extracted from atlas_intraday.py canonical renderers.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

try:
    from atlas_report_authority import normalize_price_source as _authority_normalize_price_source
except Exception:
    def _authority_normalize_price_source(source, *, value=None, fallback_value=None):
        return source or ("[FALLBACK]" if value == fallback_value else "[PROVIDER]")

# Shared human renderers translate authority classes at their own boundary.  The
# underlying authority module keeps its diagnostic labels for non-human consumers.
_HUMAN_SOURCE_LABELS = {
    "[DB]": "Recorded", "DB": "Recorded",
    "[TFE]": "TFE", "TFE": "TFE",
    "[PROVIDER]": "Market data", "PROVIDER": "Market data",
    "[CACHE]": "Cached market data", "CACHE": "Cached market data",
    "[FALLBACK]": "Reference", "FALLBACK": "Reference",
    "[RENDER-CALC]": "Calculated", "RENDER-CALC": "Calculated",
}

def _human_source_label(source: Any) -> str:
    text = str(source or "").strip()
    return _HUMAN_SOURCE_LABELS.get(text.upper(), text or "Market data")

def normalize_price_source(source, *, value=None, fallback_value=None):
    raw = _authority_normalize_price_source(source, value=value, fallback_value=fallback_value)
    return _human_source_label(raw)

SOURCE_DB="Recorded"; SOURCE_TFE="TFE"; SOURCE_PROVIDER="Market data"; SOURCE_CACHE="Cached market data"; SOURCE_FALLBACK="Reference"; SOURCE_RENDER_CALC="Calculated"

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
    shares = _row_value(row, "shares", "quantity", "qty", default=0.0)
    pa = _row_value(row, "price_authority", default=None)
    if not isinstance(pa, dict):
        current_raw = _row_value(row, "current_price", "last", "last_price", "now", default=entry)
        src = normalize_price_source(_row_value(row, "current_price_source", "price_source", default=None), value=current_raw, fallback_value=entry)
        pa = {
            "display_price": current_raw,
            "valuation_price": None if src == SOURCE_FALLBACK and _num(current_raw) == _num(entry) else current_raw,
            "source_label": src,
            "source_class": src.strip("[]"),
            "is_valuation_valid": not (src == SOURCE_FALLBACK and _num(current_raw) == _num(entry)),
            "reason": "legacy_price_fields",
        }
    current = pa.get("display_price")
    valuation_valid = bool(pa.get("is_valuation_valid"))
    valuation_price = pa.get("valuation_price") if valuation_valid else None
    stop = _row_value(row, "stop_loss", "stop", default=entry)
    target = _row_value(row, "target_price", "target", default=entry)
    invested = _row_value(row, "invested_capital", default=None)
    if invested is None:
        invested = _num(entry) * _num(shares)
    if valuation_valid:
        current_value = _row_value(row, "current_value", default=None)
        if current_value is None:
            current_value = _num(valuation_price) * _num(shares)
        pl_usd = _row_value(row, "unrealized_pl_usd", "pnl_usd", "pl_usd", default=None)
        if pl_usd is None:
            pl_usd = _num(current_value) - _num(invested)
        pl_pct = _row_value(row, "unrealized_pl_pct", "pnl_pct", "pl_pct", default=None)
        if pl_pct is None:
            pl_pct = (_num(pl_usd) / _num(invested) * 100.0) if _num(invested) else 0.0
    else:
        current_value = None
        pl_usd = None
        pl_pct = None
    return {
        "ticker": ticker,
        "entry_price": _num(entry),
        "current_price": _num(current) if current not in (None, "") else None,
        "current_price_source": pa.get("source_label") or SOURCE_FALLBACK,
        "price_authority": pa,
        "valuation_valid": valuation_valid,
        "stop_loss": _num(stop),
        "target_price": _num(target),
        "shares": _num(shares),
        "invested_capital": _num(invested),
        "current_value": current_value,
        "unrealized_pl_usd": pl_usd,
        "unrealized_pl_pct": pl_pct,
        "manual_override": bool(_row_value(row, "manual_override", default=False)),
        "stop_breached": bool(_row_value(row, "stop_breached", default=False)),
        "system_wanted": _row_value(row, "system_wanted", default=None),
        "risk": _row_value(row, "risk", default=None),
        "broker_sell_submitted": bool(_row_value(row, "broker_sell_submitted", default=False)),
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
        f"💼 Total Invested {SOURCE_RENDER_CALC}: {_money(invested)}",
        f"📊 Current Value {SOURCE_RENDER_CALC}:  {_money(current)}",
        f"📈 Blended ROI {SOURCE_RENDER_CALC}:    {_fmt_pct(roi_pct, signed=True, decimals=1)} ({_signed_money(roi_dollar)})",
        "",
    ]


def holding_block(positions: Iterable[Any] | None, summary: dict[str, Any] | None = None) -> list[str]:
    """Canonical HOLDING block with P0X-2 valuation-safe totals."""
    trades = [_as_position(row) for row in (positions or []) if _row_ticker(row)]
    lines = ["", f"━━━ 💼 HOLDING ({len(trades)}) ━━━"]
    if not trades:
        lines.append("📭 none")
        return lines
    lines.append("")
    for i, trade in enumerate(trades, 1):
        icon = "🟢" if (trade["unrealized_pl_usd"] or 0) >= 0 else "🔴"
        label = _ticker_label(trade["ticker"], {"ticker": trade["ticker"]})
        lines += [
            f"{i}. {icon} {label}",
            f"   💵 Entry {SOURCE_DB} {_price(trade['entry_price'])}",
        ]
        if trade["valuation_valid"]:
            lines += [
                f"   👀 Now {trade['current_price_source']} {_price(trade['current_price'])}",
                f"   🚦 Stop {SOURCE_DB}/{SOURCE_TFE} {_price(trade['stop_loss'])}",
                f"   🎯 Target {SOURCE_DB}/{SOURCE_TFE} {_price(trade['target_price'])}",
                f"   {SOURCE_RENDER_CALC} ({_fmt_pct(trade['unrealized_pl_pct'], signed=True, decimals=0)} · {_signed_money(trade['unrealized_pl_usd'])} · ~{_money(trade['current_value'])})",
            ]
            if trade.get("manual_override") and trade.get("stop_breached"):
                lines += [
                    "   ⚠️ MANUAL OVERRIDE — STOP BREACHED — HIGH RISK",
                    f"   System wanted: {trade.get('system_wanted') or 'SELL'}",
                    "   Professor override: HOLD",
                    f"   Broker sell placed: {'YES' if trade.get('broker_sell_submitted') else 'NO'}",
                    "   Broker confirmation pending: NO",
                ]
            lines.append("")
        else:
            reason = (trade.get("price_authority") or {}).get("reason") or "price_unavailable"
            lines += [
                f"   👀 Now PRICE_UNAVAILABLE {SOURCE_FALLBACK}/reference only (entry {_price(trade['entry_price'])})",
                f"   🚦 Stop {SOURCE_DB}/{SOURCE_TFE} {_price(trade['stop_loss'])}",
                f"   🎯 Target {SOURCE_DB}/{SOURCE_TFE} {_price(trade['target_price'])}",
                f"   {SOURCE_RENDER_CALC} valuation unavailable — excluded from totals ({reason})",
                "",
            ]
    valid = [t for t in trades if t["valuation_valid"]]
    excluded = [t["ticker"] for t in trades if not t["valuation_valid"]]
    total_invested = sum(trade["invested_capital"] for trade in valid)
    current_value = sum(_num(trade["current_value"]) for trade in valid)
    if excluded:
        lines += [
            "─────────────────────",
            f"⚠️ Valuation PARTIAL {SOURCE_RENDER_CALC}: excluded {', '.join(excluded)} — price unavailable/stale",
            f"💼 Valued Invested {SOURCE_RENDER_CALC}: {_money(total_invested)}",
            f"📊 Current Value {SOURCE_RENDER_CALC}:  {_money(current_value)}",
            f"📈 Blended ROI {SOURCE_RENDER_CALC}:    {_fmt_pct(((current_value-total_invested)/total_invested*100.0) if total_invested else 0.0, signed=True, decimals=1)} ({_signed_money(current_value-total_invested)})",
            "",
        ]
    else:
        lines += portfolio_footer(total_invested, current_value)
    return lines

def watch_list_block(watch_data: Any, open_tickers: Iterable[str] | None = None, *, cap: int = 15) -> list[str]:
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
    total = len(rows)
    cap = max(1, int(cap or 15))
    shown = rows[:cap]
    omitted = total - len(shown)
    lines = ["", f"━━━ 👀 WATCHING ({len(shown)} shown of {total}) ━━━"]
    if not rows:
        lines.append("none")
        return lines
    lines.append("")
    for i, (_, label) in enumerate(shown, 1):
        lines.append(f"{i}. {label}")
    if omitted:
        omitted_names = [label for _, label in rows[cap:]]
        lines.append(f"… {omitted} omitted by {cap}-item cap: {', '.join(omitted_names)}")
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
        current_source = normalize_price_source(_row_value(row, "current_price_source", "price_source", default=None), value=current, fallback_value=_row_value(row, "reference_price", default=None))
        delta = ((_num(current) - _num(trigger)) / _num(trigger) * 100.0) if _num(trigger) else 0.0
        rsi = _row_value(row, "rsi", default=None)
        macd_hist = _row_value(row, "macd_hist", default=None)
        fundamentals_ok = bool(_row_value(row, "fundamentals_ok", default=False))
        momentum_weak = bool(_row_value(row, "momentum_weak", default=False))
        no_earnings = bool(_row_value(row, "no_earnings", default=False))
        lines += [
            f"{i}. {label}",
            f"   💵 Entry {SOURCE_DB}/{SOURCE_TFE} {_price(trigger)}",
            f"   👀 Now {current_source} {_price(current)} ({SOURCE_RENDER_CALC} {_fmt_pct(delta, signed=True, decimals=0)})",
            _rvol_line(row),
            f"   {_signal_pillar_text(row)}",
            f"   📉 RSI {_num(rsi):.0f}" if rsi is not None else "   📉 RSI N/A",
            f"   📈 MACD+ · {_num(macd_hist):.1f}" if macd_hist is not None else "   📈 MACD+ · N/A",
            "   ✅ Fundamentals" if fundamentals_ok else "   ⚠️ Momentum Weak" if momentum_weak else "   No earnings catalyst reported by source" if no_earnings else "   Earnings information missing",
            "",
        ]
    return lines


__all__ = ["holding_block", "watch_list_block", "pullback_block", "portfolio_footer"]
