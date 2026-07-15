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
SOURCE_LEDGER = "[LEDGER]"
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


def normalize_price_source(source: Any, *, value: Any = None, fallback_value: Any = None) -> str:
    """Compact display badge for provider/cache/fallback values; pure formatting."""
    raw = str(source or "").strip().lower()
    if "fallback" in raw:
        return SOURCE_FALLBACK
    if "cache" in raw or "stale" in raw:
        return SOURCE_CACHE
    if "provider" in raw or "live" in raw or "massive" in raw or "polygon" in raw or "eodhd" in raw or "yahoo" in raw:
        return SOURCE_PROVIDER
    if value in (None, ""):
        return SOURCE_FALLBACK
    if fallback_value not in (None, "") and value == fallback_value:
        return SOURCE_FALLBACK
    return SOURCE_PROVIDER


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
        pa = row.get("price_authority") if isinstance(row.get("price_authority"), dict) else None
        if pa is None:
            current = _get(row, "current_price", "now", "last_price", default=entry)
            current_source = _get(row, "current_price_source", default=SOURCE_FALLBACK if current == entry else SOURCE_PROVIDER)
            pa = {"display_price": current, "source_label": current_source, "is_valuation_valid": not (current_source == SOURCE_FALLBACK and current == entry), "reason": "legacy_visibility_fields"}
        current = pa.get("display_price")
        current_source = pa.get("source_label") or SOURCE_FALLBACK
        stop = _get(row, "stop_loss", "stop")
        target = _get(row, "target_price", "target")
        lines += [
            f"{idx}. {ticker} {SOURCE_DB}",
            f"   Qty {SOURCE_DB} {_qty(qty)}",
            f"   💵 Entry {SOURCE_DB} {_price(entry)}",
        ]
        if pa.get("is_valuation_valid"):
            lines.append(f"   👀 Now {current_source} {_price(current)}")
        else:
            lines.append(f"   👀 Now {PRICE_UNAVAILABLE} {SOURCE_FALLBACK}/reference only (entry {_price(entry)})")
        lines += [
            f"   🚦 Stop {SOURCE_DB}/{SOURCE_TFE} {_price(stop)}",
            f"   🎯 Target {SOURCE_DB}/{SOURCE_TFE} {_price(target)}",
        ]
        if row.get("final_action"):
            lines.append(f"   🧭 Final Action [HOLDINGS_MERGED_ACTION]: {row.get('final_action')}")
        if row.get("stop_status"):
            lines.append(f"   🛑 Stop Status [LIFECYCLE]: {row.get('stop_status')}")
        if isinstance(pa, dict) and (pa.get("timestamp") or pa.get("session")):
            lines.append(f"   🕐 Quote [PROVIDER]: {pa.get('timestamp') or 'timestamp unavailable'} · {pa.get('session') or 'session unknown'}")
        lines.append("")
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



def normalize_open_position_rows(open_rows=None, price_lookup=None) -> list[dict[str, Any]]:
    """Normalize OPEN rows for authority rendering; optional price_lookup is read-only."""
    out = []
    for row in open_rows or []:
        row = dict(row or {})
        ticker = _ticker(row)
        entry = _get(row, "entry_price", "entry", "price")
        provider_price = None
        if callable(price_lookup):
            try:
                provider_price = price_lookup(ticker)
            except Exception:
                provider_price = None
        cached_price = _get(row, "current_price", "now", "last_price", default=None)
        cached_ts = _get(row, "current_price_at", "last_price_at", "price_timestamp", default=None)
        pa = row.get("price_authority") or resolve_price_authority(
            ticker,
            entry,
            provider_price=provider_price,
            provider_source="price_lookup" if provider_price not in (None, "") else None,
            cached_price=cached_price,
            cached_timestamp=cached_ts,
        )
        current = pa.get("display_price")
        source = pa.get("source_label")
        out.append({
            "ticker": ticker,
            "entry_price": entry,
            "current_price": current,
            "current_price_source": source,
            "price_authority": pa,
            "stop_loss": _get(row, "stop_loss", "stop"),
            "target_price": _get(row, "target_price", "target"),
            "quantity": _get(row, "quantity", "shares", "qty"),
        })
    return out


def pending_exposure_compact_lines(pending_rows=None) -> list[str]:
    rows = [dict(r or {}) for r in (pending_rows or [])]
    lines = ["", f"━━━ ⏳ PENDING BROKER / CASH EXPOSURE ({len(rows)}) ━━━"]
    if not rows:
        lines.append("✅ none")
        return lines
    for row in rows:
        lines.append(f"⚠️ {_ticker(row)} {SOURCE_DB}/{SOURCE_BROKER}/{SOURCE_LEDGER if 'SOURCE_LEDGER' in globals() else '[LEDGER]'} · broker_confirmed: NO · cash_credit: NO")
    return lines


# ---------------------------------------------------------------------------
# P0X-2 central report price / valuation authority
# ---------------------------------------------------------------------------
PRICE_UNAVAILABLE = "PRICE_UNAVAILABLE"
PRICE_SOURCE_UNAVAILABLE = "UNAVAILABLE"
DEFAULT_CACHE_MAX_AGE_SECONDS = 15 * 60


def _parse_authority_ts(value: Any):
    if value in (None, ""):
        return None
    try:
        from datetime import datetime, timezone
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _age_seconds(value: Any) -> float | None:
    ts = _parse_authority_ts(value)
    if ts is None:
        return None
    try:
        from datetime import datetime, timezone
        return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
    except Exception:
        return None


def _valid_price(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        v = float(value)
        return v if v > 0 else None
    except Exception:
        return None


def _same_price(a: Any, b: Any) -> bool:
    av = _valid_price(a)
    bv = _valid_price(b)
    return av is not None and bv is not None and abs(av - bv) < 0.005


def resolve_price_authority(
    ticker: str,
    entry_price: Any,
    provider_price: Any = None,
    provider_source: str | None = None,
    provider_timestamp: Any = None,
    cached_price: Any = None,
    cached_timestamp: Any = None,
    max_cache_age_seconds: int = DEFAULT_CACHE_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Resolve display vs valuation price for reports only; no DB/provider/Telegram side effects."""
    ticker = str(ticker or "?").upper()
    entry = _valid_price(entry_price)
    provider = _valid_price(provider_price)
    cache = _valid_price(cached_price)
    cache_age = _age_seconds(cached_timestamp)
    provider_age = _age_seconds(provider_timestamp)
    if provider is not None:
        return {
            "ticker": ticker,
            "display_price": provider,
            "valuation_price": provider,
            "source_class": "PROVIDER",
            "source_label": SOURCE_PROVIDER,
            "provider": provider_source or "provider",
            "timestamp": provider_timestamp,
            "age_seconds": provider_age,
            "is_valuation_valid": True,
            "reason": "provider_price_valid",
        }
    cache_is_fresh = cache is not None and cached_timestamp not in (None, "") and cache_age is not None and cache_age <= max_cache_age_seconds
    cache_is_entry_clone = cache is not None and entry is not None and _same_price(cache, entry)
    if cache_is_fresh and not cache_is_entry_clone:
        return {
            "ticker": ticker,
            "display_price": cache,
            "valuation_price": cache,
            "source_class": "CACHE",
            "source_label": SOURCE_CACHE,
            "provider": "timestamped_cache",
            "timestamp": cached_timestamp,
            "age_seconds": cache_age,
            "is_valuation_valid": True,
            "reason": "fresh_timestamped_cache_valid",
        }
    reason = "entry_reference_only"
    if cache is None and provider is None:
        reason = "provider_and_cache_missing"
    elif cache_is_entry_clone:
        reason = "cached_price_equals_entry_reference_only"
    elif cache is not None and not cache_is_fresh:
        reason = "cache_missing_timestamp_or_stale"
    return {
        "ticker": ticker,
        "display_price": entry,
        "valuation_price": None,
        "source_class": "FALLBACK" if entry is not None else PRICE_SOURCE_UNAVAILABLE,
        "source_label": SOURCE_FALLBACK if entry is not None else "[UNAVAILABLE]",
        "provider": None,
        "timestamp": cached_timestamp or provider_timestamp,
        "age_seconds": cache_age,
        "is_valuation_valid": False,
        "reason": reason,
    }


def valuation_excluded_tickers(rows: Iterable[dict] | None) -> list[str]:
    out = []
    for row in rows or []:
        pa = (row or {}).get("price_authority") or {}
        ticker = str((row or {}).get("ticker") or (row or {}).get("symbol") or pa.get("ticker") or "?").upper()
        if pa and not pa.get("is_valuation_valid"):
            out.append(ticker)
    return sorted(set(out))
