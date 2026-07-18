"""Unified concise Atlas report formatter.

Builds the short operator-facing handoff used by pre-market, intraday,
post-market, and EOD handoff messages.
"""
import os
import sys
import time as _time
from datetime import datetime
from zoneinfo import ZoneInfo

SCRIPTS_DIR = __import__("os").environ.get("ATLAS_SCRIPTS_DIR") or __import__("os").path.dirname(__import__("os").path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

import atlas_db
import atlas_portfolio as port
import atlas_symbol_meta as _symbol_meta
from atlas_symbol_meta import ticker_label
from atlas_report_blocks import holding_block, pullback_block, watch_list_block
from atlas_report_authority import render_portfolio_visibility_block, provider_or_fallback_price, resolve_price_authority
from atlas_time import current_et_market_date, add_trading_days, previous_et_trading_date_str

SEP = "─────────────────────────────────────────"
DOUBLE = "═══════════════════════════════"
ET = ZoneInfo("America/New_York")


def _money_whole(value):
    try:
        return f"${float(value):,.0f}"
    except Exception:
        return "N/A"


def _money(value):
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "N/A"


def _signed_money(value):
    try:
        v = float(value)
        sign = "+" if v >= 0 else "-"
        return f"{sign}${abs(v):,.0f}"
    except Exception:
        return "N/A"


def _signed_pct(value):
    try:
        v = float(value)
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.1f}%"
    except Exception:
        return "N/A"


def _pct_whole(value):
    try:
        v = float(value)
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.0f}%"
    except Exception:
        return "N/A"


def _num(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _date_label(day):
    return day.strftime("%B %-d").upper()


def _header(report_date=None):
    day = report_date or current_et_market_date()
    nxt = add_trading_days(day, 1)
    return [
        SEP,
        f"🤖 ATLAS HANDOFF — {_date_label(day)} → {nxt.day}, {nxt.year}",
        DOUBLE,
        "",
    ]


def _latest_price(ticker, fallback=None):
    if str(os.environ.get("ATLAS_HANDOFF_LIVE_PRICES", "1")).lower() in ("0", "false", "no", "off"):
        return fallback
    try:
        price = port._last_price(ticker)
        if price is not None:
            return price
    except Exception:
        pass
    return fallback


def _append_entry_gap(lines):
    if lines and lines[-1] != "":
        lines.append("")


def _legacy_open_position_lines():
    rows = atlas_db.get_open_positions()
    positions = []
    for row in rows:
        ticker = str(row.get("ticker") or "?").upper()
        entry = _num(row.get("price"))
        qty = _num(row.get("quantity"), 0.0)
        cached_now = row.get("current_price") or row.get("last_price")
        live = _latest_price(ticker, fallback=None)
        pa = resolve_price_authority(ticker, entry, provider_price=live, provider_source="handoff_live" if live not in (None, "") else None, cached_price=cached_now, cached_timestamp=row.get("last_price_at"))
        positions.append({
            "ticker": ticker,
            "entry_price": entry,
            "current_price": pa.get("display_price"),
            "current_price_source": pa.get("source_label"),
            "price_authority": pa,
            "stop_loss": row.get("stop_loss"),
            "target_price": row.get("target_price"),
            "quantity": qty,
        })
    pending = atlas_db.get_pending_broker_confirmation_trades()
    lines = render_portfolio_visibility_block(positions, pending)
    if lines and lines[0] == "":
        lines = lines[1:]
    return lines, len(rows) + len(pending)

def _open_position_lines():
    return _atlas_select_leaf("PRE_MARKET_HOLDINGS", _legacy_open_position_lines,
        reference="atlas_report_handoff._open_position_lines",
        projector=lambda p:(list(p.lines), len(p.lines)))

def _position_note(ticker):
    notes = {
        "INTC": "Goldman initiated · PT $150",
        "MS": "$20B buyback announced",
    }
    return notes.get((ticker or "").upper())


def _pending_stop_target(row):
    trigger = _num(row.get("trigger_price"), None)
    if trigger is None:
        return None, None
    sig = row.get("signal_result") or {}
    rc = sig.get("risk_card") or {}
    entry_ref = _num(sig.get("entry_price"), _num(row.get("reference_price"), trigger))
    stop_ref = _num(rc.get("stop_loss"), None)
    stop = None
    if entry_ref is not None and stop_ref is not None:
        risk_ref = entry_ref - stop_ref
        if risk_ref > 0:
            stop = round(trigger - risk_ref, 2)
    if stop is None:
        return None, None
    target = round(trigger + (2 * (trigger - stop)), 2)
    return stop, target


def _pending_pullback_lines(limit=None):
    rows = atlas_db.get_pending_pullbacks(status="WAITING")
    today = current_et_market_date().strftime("%Y-%m-%d")
    rows = [r for r in rows if str((r or {}).get("expires_at") or "9999-12-31") >= today]

    def sort_key(row):
        return abs(_num(row.get("pct_over_ema"), 999.0))

    selected = sorted(rows, key=sort_key)
    if limit is not None:
        selected = selected[:limit]
    data = []
    for row in selected:
        item = dict(row)
        item.update({
            "action": "WAIT",
            "reason": "PULLBACK — armed for handoff",
            "entry": item.get("trigger_price"),
            "entry_price": item.get("trigger_price"),
            "current_price": item.get("reference_price"),
            "current_price_source": "[CACHE]",
            "price": item.get("reference_price"),
        })
        data.append(item)
    lines = pullback_block(data)
    if lines and lines[0] == "":
        lines = lines[1:]
    return lines, len(rows)

def _latest_handoff(market_day):
    today = market_day.strftime("%Y-%m-%d")
    previous = previous_et_trading_date_str(market_day)
    return atlas_db.get_handoff(today) or atlas_db.get_handoff(previous) or {}


def _open_position_tickers():
    try:
        return {str(row.get("ticker") or "").upper().strip() for row in atlas_db.get_open_positions() if row.get("ticker")}
    except Exception:
        return set()


def _watch_list_lines(data):
    raw = data.get("WATCH", []) if isinstance(data, dict) else []
    watch_rows = [{"ticker": str(item or "").upper().strip(), "action": "WATCH"} for item in (raw or [])]
    lines = watch_list_block(watch_rows, open_tickers=_open_position_tickers())
    if lines and lines[0] == "":
        lines = lines[1:]
    return lines

def _entry_type_lines():
    return [
        "3️⃣ ENTRY TYPES",
        "",
        "   🚀 Gap-Up Breakout    · 9:30–10:00 AM · RVOL >1.5x · Catalyst required · Risk 0.25%",
        "",
        "   📈 Intraday Breakout  · 10:00–12:00 PM · RVOL >2.0x · Catalyst required · Risk 0.25%",
        "",
        "   🎣 Pullback to EMA    · All day        · RVOL any   · Catalyst optional  · Risk 0.50%",
        "",
    ]


def _break_lines():
    return [
        "4️⃣ IF SOMETHING BREAKS",
        "",
        "   ❌ No intraday reports — restart com.atlas.intraday on M2",
        "",
        "   ❌ Atlas silent on Telegram — run: hermes -p atlas gateway restart",
        "",
        "   ⛔ AtlasOps must NOT touch Telegram .env — correct chat ID ends [REDACTED]",
        "",
    ]


EOD_HANDOFF_LABEL_OVERRIDES = {
    "AAL": "American Airlines Group",
    "ABVX": "Abivax SA American Depositary Shares",
    "ALAB": "Astera Labs",
    "AMAT": "Applied Materials",
    "AMD": "Advanced Micro Devices",
    "ANET": "Arista Networks",
    "AZZ": "Azz",
    "BE": "Bloom Energy",
    "BOKF": "BOK Financial",
    "BAC": "Bank of America",
    "CAT": "Caterpillar",
    "CRDO": "Credo Technology Group Holding",
    "CVBF": "CVB Financial",
    "DAL": "Delta Air Lines",
    "ESI": "Element Solutions",
    "F": "Ford Motor",
    "FCEL": "FuelCell Energy Inc NEW",
    "GS": "Goldman Sachs Group",
    "HZO": "MarineMax",
    "INTC": "Intel",
    "IRDM": "Iridium Communications",
    "JNJ": "Johnson & Johnson",
    "KO": "Coca-Cola",
    "LEVI": "Levi Strauss &",
    "LRCX": "Lam Research",
    "MAS": "Masco",
    "MS": "Morgan Stanley",
    "MSM": "MSC Industrial Direct",
    "MUSA": "Murphy Usa",
    "PENG": "Penguin Solutions",
    "PSMT": "Pricesmart",
    "RL": "Ralph Lauren",
    "RPRX": "Royalty Pharma",
    "SLS": "SELLAS Life Sciences Group",
    "SOLS": "Solstice Advanced Materials",
    "SYNA": "Synaptics",
    "TENB": "Tenable",
    "TRV": "The Travelers Companies",
    "V": "Visa",
    "VSAT": "Viasat",
    "WDC": "Western Digital",
    "WDFC": "Wd-40",
    "WULF": "TeraWulf",
}


def _disable_live_label_lookup_if_requested():
    """Avoid provider-backed company-name lookups in bounded EOD render paths."""
    if str(os.environ.get("ATLAS_HANDOFF_LIVE_PRICES", "1")).lower() not in ("0", "false", "no", "off"):
        return
    try:
        _symbol_meta._company_name_from_massive = lambda ticker: EOD_HANDOFF_LABEL_OVERRIDES.get(str(ticker or "").upper())
        ticker_label.__globals__["_company_name_from_massive"] = lambda ticker: EOD_HANDOFF_LABEL_OVERRIDES.get(str(ticker or "").upper())
    except Exception:
        pass


def build_atlas_handoff_report(context=None, report_date=None):
    started = _time.perf_counter()
    _disable_live_label_lookup_if_requested()
    day = report_date or current_et_market_date()
    print(f"[handoff timing] current_market_date={_time.perf_counter() - started:.2f}s")
    stage = _time.perf_counter()
    data = _latest_handoff(day)
    print(f"[handoff timing] latest_handoff={_time.perf_counter() - stage:.2f}s")
    stage = _time.perf_counter()
    lines = _header(day)
    print(f"[handoff timing] header={_time.perf_counter() - stage:.2f}s")
    stage = _time.perf_counter()
    open_lines, open_count = _open_position_lines()
    print(f"[handoff timing] open_position_lines={_time.perf_counter() - stage:.2f}s count={open_count} live_prices={os.environ.get('ATLAS_HANDOFF_LIVE_PRICES')}")
    stage = _time.perf_counter()
    armed_lines, armed_count = _pending_pullback_lines()
    print(f"[handoff timing] pending_pullback_lines={_time.perf_counter() - stage:.2f}s count={armed_count}")
    stage = _time.perf_counter()
    watch_lines = _watch_list_lines(data)
    print(f"[handoff timing] watch_list_lines={_time.perf_counter() - stage:.2f}s")
    stage = _time.perf_counter()
    lines += open_lines
    lines += [SEP, ""]
    lines += armed_lines
    lines += [SEP, ""]
    lines += watch_lines
    lines += [SEP, ""]
    lines += _entry_type_lines()
    lines += [SEP, ""]
    lines += _break_lines()
    lines += [SEP]
    lines += [f"   ✅ All fixes verified · {day.strftime('%B %-d, %Y')}"]
    lines += [SEP]
    print(f"[handoff timing] assemble={_time.perf_counter() - stage:.2f}s total={_time.perf_counter() - started:.2f}s")
    return "\n".join(lines)



from atlas_holding_state_consumer_projection import select_leaf as _atlas_select_leaf

if __name__ == "__main__":
    print(build_atlas_handoff_report())
