#!/usr/bin/env python3
"""Atlas Macro Post-Market Wrap.

Narrative macro-only report for 16:15 ET. No individual stock tickers and no
buy/sell language. Normal runs outside the post-market gate exit silently.
Dry-run with --force prints the generated wrap and sends no Telegram.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time as time_mod
import warnings
from datetime import datetime, timedelta, time, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL.*")
import requests

SCRIPTS_DIR = os.environ.get("ATLAS_SCRIPTS_DIR") or os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
from atlas_time import is_trading_day

try:
    from atlas_notify import send_telegram as _send_telegram
except Exception:
    _send_telegram = None

ET = ZoneInfo("America/New_York")
EODHD_BASE = "https://eodhd.com/api"
HTTP_TIMEOUT = float(os.environ.get("ATLAS_MACRO_POSTMARKET_TIMEOUT", "8"))


def _strip_handoff_block(text: str) -> str:
    """Post-market macro wrap must never include the EOD handoff block."""
    marker = "🧭 ATLAS MACRO POST-MARKET"
    if marker in text and "ATLAS HANDOFF" in text.split(marker, 1)[0]:
        return marker + text.split(marker, 1)[1]
    handoff_terms = ("OPEN POSITIONS", "WATCH TOMORROW", "ENTRY TYPES", "IF SOMETHING BREAKS")
    if marker in text and all(term in text.split(marker, 1)[0] for term in handoff_terms[:2]):
        return marker + text.split(marker, 1)[1]
    return text

_ENV_PATH = os.path.expanduser("~/.hermes/profiles/atlas/.env")
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

BENZINGA_API_KEY = os.environ.get("BENZINGA_API_KEY")
EODHD_API_KEY = os.environ.get("EODHD_API_KEY") or os.environ.get("EODHD_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


def _clean_text(value: object, max_len: int = 240) -> str:
    text = re.sub(r"https?://\S+", "", str(value or "")).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:max_len]


def _strip_tickers(text: str) -> str:
    """Remove obvious exchange/ticker/company-code syntax while preserving report line breaks."""
    text = re.sub(r"\(([A-Z]{1,5})(?:\.[A-Z]{1,3})?\)", "", text)
    text = re.sub(r"\$[A-Z]{1,5}\b", "", text)
    text = re.sub(r"\b[A-Z]{1,5}:[A-Z]{1,5}\b", "", text)
    whitelist = {"S&P", "SOX", "DXY", "WTI", "NYSE", "NASDAQ", "AI", "US", "ET", "UTC", "CPI", "PCE", "FX", "VIX", "Fed", "ISM", "NFP", "ADP", "JOLTS", "PMI", "FOMC"}
    text = re.sub(
        r"\b([A-Z]{2,5})(?:'s)?\b",
        lambda m: m.group(0) if m.group(1) in whitelist else "a major company",
        text,
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _float_or_none(value: object) -> float | None:
    try:
        if value in (None, "", "NA", "N/A"):
            return None
        return float(value)
    except Exception:
        return None


def _pct_from(price: float | None, previous: float | None) -> float | None:
    if price is None or previous in (None, 0):
        return None
    return (price / previous - 1.0) * 100.0


def _fmt_num(value: object, decimals: int = 2) -> str:
    v = _float_or_none(value)
    if v is None:
        return "N/A"
    return f"{v:,.{decimals}f}"


def _fmt_pct(value: object) -> str:
    v = _float_or_none(value)
    if v is None:
        return "N/A"
    direction = "up" if v > 0.05 else ("down" if v < -0.05 else "flat")
    return f"{direction} {abs(v):.2f}%"


def _get(url: str, params: dict | None = None, timeout: float = HTTP_TIMEOUT):
    r = requests.get(url, params=params or {}, timeout=timeout, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json()


def yahoo_quote(symbol: str, label: str) -> dict:
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol, safe=""),
            params={"range": "5d", "interval": "1d"},
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        r.raise_for_status()
        result = ((r.json().get("chart") or {}).get("result") or [{}])[0]
        meta = result.get("meta") or {}
        price = _float_or_none(meta.get("regularMarketPrice"))
        previous = _float_or_none(meta.get("previousClose") or meta.get("chartPreviousClose"))
        pct = _pct_from(price, previous)
        return {"symbol": symbol, "label": label, "price": price, "previous": previous, "pct": pct, "source": "yahoo"}
    except Exception as exc:
        print(f"[macro_postmarket] Yahoo fetch failed for {label}: {type(exc).__name__}")
        return {"symbol": symbol, "label": label, "price": None, "previous": None, "pct": None, "source": "yahoo_failed"}


def eodhd_get(path: str, params: dict | None = None):
    if not EODHD_API_KEY:
        return None
    p = dict(params or {})
    p["api_token"] = EODHD_API_KEY
    p.setdefault("fmt", "json")
    try:
        return _get(f"{EODHD_BASE}{path}", p)
    except Exception as exc:
        print(f"[macro_postmarket] EODHD fetch failed for {path}: {type(exc).__name__}")
        return None


def benzinga_news(query: str = "", limit: int = 12, hours: int = 24):
    if not BENZINGA_API_KEY:
        return []
    now_utc = datetime.now(timezone.utc)
    since_utc = now_utc - timedelta(hours=hours)
    params = {
        "token": BENZINGA_API_KEY,
        "dateFrom": since_utc.astimezone(ET).date().isoformat(),
        "dateTo": now_utc.astimezone(ET).date().isoformat(),
        "pageSize": 50,
    }
    if query:
        params["search"] = query
    try:
        data = _get("https://api.benzinga.com/api/v2/news", params)
    except Exception as exc:
        print(f"[macro_postmarket] Benzinga fetch failed for {query or 'general'}: {type(exc).__name__}")
        return []
    items = data if isinstance(data, list) else (data.get("data") or data.get("articles") or [])
    out = []
    for item in items:
        title = _clean_text(item.get("title") or item.get("headline"))
        if not title:
            continue
        out.append(_strip_tickers(title))
        if len(out) >= limit:
            break
    return out


def market_snapshot() -> dict:
    return {
        "S&P 500": yahoo_quote("^GSPC", "S&P 500"),
        "Nasdaq 100": yahoo_quote("^NDX", "Nasdaq 100"),
        "Dow Jones Industrial Average": yahoo_quote("^DJI", "Dow Jones Industrial Average"),
        "Russell 2000": yahoo_quote("^RUT", "Russell 2000"),
    }


def sector_snapshot() -> dict:
    sectors = {
        "Technology": "XLK",
        "Communication Services": "XLC",
        "Consumer Discretionary": "XLY",
        "Industrials": "XLI",
        "Financials": "XLF",
        "Health Care": "XLV",
        "Consumer Staples": "XLP",
        "Utilities": "XLU",
        "Energy": "XLE",
        "Materials": "XLB",
        "Real Estate": "XLRE",
    }
    quotes = {label: yahoo_quote(symbol, label) for label, symbol in sectors.items()}
    ranked = sorted(quotes.items(), key=lambda kv: (_float_or_none(kv[1].get("pct")) is None, -(_float_or_none(kv[1].get("pct")) or -999)))
    return {"all": quotes, "leaders": ranked[:3], "laggards": list(reversed(ranked[-3:]))}


def bonds_fx_commodities_snapshot() -> dict:
    ten = yahoo_quote("^TNX", "US 10Y yield")
    two = yahoo_quote("^IRX", "3M Treasury yield")
    dxy = yahoo_quote("DX-Y.NYB", "Dollar Index")
    oil = yahoo_quote("CL=F", "WTI crude oil")
    curve = None
    if ten.get("price") is not None and two.get("price") is not None:
        curve = ten["price"] - two["price"]
    return {"US 10Y yield": ten, "3M Treasury yield": two, "10Y_minus_3M": curve, "Dollar Index": dxy, "WTI crude oil": oil}


def sentiment_snapshot() -> dict:
    vix = yahoo_quote("^VIX", "VIX")
    high_yield = yahoo_quote("HYG", "high-yield credit proxy")
    investment_grade = yahoo_quote("LQD", "investment-grade credit proxy")
    gainers = []
    losers = []
    try:
        # Public Massive entitlement may vary; failures do not block the macro wrap.
        base = os.environ.get("MASSIVE_BASE", "https://api.massive.com")
        key = os.environ.get("MASSIVE_API_KEY")
        if key:
            gainers = (_get(f"{base}/v2/snapshot/locale/us/markets/stocks/gainers", {"apiKey": key}) or {}).get("tickers") or []
            losers = (_get(f"{base}/v2/snapshot/locale/us/markets/stocks/losers", {"apiKey": key}) or {}).get("tickers") or []
    except Exception as exc:
        print(f"[macro_postmarket] breadth fetch failed: {type(exc).__name__}")
    concentration = "broad" if len(gainers) > len(losers) * 1.25 else ("narrow/defensive" if len(losers) > len(gainers) * 1.25 else "mixed")
    return {"VIX": vix, "high_yield_credit": high_yield, "investment_grade_credit": investment_grade, "advancers": len(gainers), "decliners": len(losers), "breadth": concentration}


def catalysts_snapshot() -> dict:
    return {"macro_news": benzinga_news("Fed CPI PCE jobs inflation geopolitical oil dollar yield Treasury", limit=12, hours=24)}


def _format_economic_event(item: dict) -> str:
    name = _clean_text(item.get("type") or item.get("event") or item.get("name") or "")
    period = _clean_text(item.get("period") or "")
    when = _clean_text(item.get("date") or item.get("datetime") or "")
    estimate = item.get("estimate")
    previous = item.get("previous")
    details = []
    if period:
        details.append(period)
    if estimate not in (None, "", "NA"):
        details.append(f"est {estimate}")
    elif previous not in (None, "", "NA"):
        details.append(f"prev {previous}")
    suffix = f" ({', '.join(details)})" if details else ""
    return f"{when} {name}{suffix}".strip()


def next_week_events_snapshot() -> dict:
    today = datetime.now(ET).date()
    days_ahead = (7 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 3
    start = today + timedelta(days=days_ahead)
    end = start + timedelta(days=4)
    macro = eodhd_get("/economic-events", {"from": start.isoformat(), "to": end.isoformat(), "limit": 100, "country": "US"})
    events = []
    if isinstance(macro, list):
        us_items = [item for item in macro if item.get("country") == "US"]
        priority_terms = [
            "Non Farm Payrolls", "Nonfarm Payrolls Private", "Unemployment Rate", "Initial Jobless Claims",
            "ADP Employment Change", "JOLTs Job Openings", "ISM Manufacturing PMI", "Consumer Confidence",
            "Fed Balance Sheet", "CPI", "PCE",
        ]
        selected = []
        for term in priority_terms:
            for item in us_items:
                if term.lower() in str(item.get("type") or "").lower() and item not in selected:
                    selected.append(item)
                    break
        if not selected:
            priority = re.compile(r"PCE|CPI|ISM|Non.?Farm|NFP|Payroll|Unemployment|JOLTs|Jobless|ADP|PMI|Consumer Confidence|Fed", re.I)
            selected = [item for item in us_items if priority.search(str(item.get("type") or ""))][:10] or us_items[:8]
        events = [_format_economic_event(item) for item in selected[:10] if _format_economic_event(item)]
    fed = [event for event in events if re.search(r"Fed|FOMC|Powell|Waller|Williams|Kashkari|Barkin|Goolsbee|Daly|Logan|Bowman|Jefferson|Cook", event, re.I)]
    earnings_raw = benzinga_news("earnings calendar next week reports before open after close", limit=12, hours=24)
    earnings = [item for item in earnings_raw if re.search(r"earnings|guidance|reports|results", item, re.I)][:5]
    return {"date_range": f"{start.isoformat()} to {end.isoformat()}", "economic_events": events, "earnings": earnings, "fed_speakers": fed}


def collect_raw_context() -> dict:
    started = time_mod.perf_counter()
    ctx = {
        "as_of_et": datetime.now(ET).isoformat(timespec="seconds"),
        "market": market_snapshot(),
        "catalysts": catalysts_snapshot(),
        "sectors": sector_snapshot(),
        "bonds_fx_commodities": bonds_fx_commodities_snapshot(),
        "sentiment": sentiment_snapshot(),
        "next_week": next_week_events_snapshot(),
    }
    ctx["collection_seconds"] = round(time_mod.perf_counter() - started, 2)
    return ctx


def _scrub_internal_language(text: str) -> str:
    replacements = {
        "rows were returned": "headlines were light",
        "0 rows": "a quiet tape",
        "data source": "market feed",
        "API": "feed",
        "JSON": "feed",
        "variable": "market",
        "proxy counts": "breadth",
        "economic events are scheduled": "the calendar is active",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"\b\d+\s+rows?\b", "a light headline set", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+on\s+\d{4}-\d{2}-\d{2}\b", "", text)
    text = re.sub(r"\s+with the S&P 500\s+(?:up|down)\s+\d+(?:\.\d+)?%\s*(?=[.!?])", "", text, flags=re.IGNORECASE)
    return text.replace("▉", "").rstrip()


def _ensure_numeric_sentences(text: str, ctx: dict) -> str:
    """Ensure narrative sentences carry at least one visible market number without adding dates."""
    sp = ((ctx.get("market") or {}).get("S&P 500") or {}).get("pct")
    anchor = f" with the S&P 500 {_fmt_pct(sp)}"
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("🧭") or re.match(r"^\d+\.\s+", stripped):
            out.append(line)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", stripped)
        fixed = []
        for sentence in sentences:
            if sentence and not re.search(r"\d", sentence):
                sentence = sentence.rstrip(".") + f"{anchor}."
            fixed.append(sentence)
        out.append(" ".join(fixed))
    return "\n".join(out).strip()


def _next_week_sentence(ctx: dict) -> str:
    nw = ctx.get("next_week") or {}
    events = (nw.get("economic_events") or [])
    fed = (nw.get("fed_speakers") or [])[:1]
    earnings = (nw.get("earnings") or [])[:1]
    if not events and not fed and not earnings:
        return "The calendar is light next week — focus shifts to technicals and any weekend geopolitical developments."
    wanted = ["Non Farm Payrolls", "ADP Employment Change", "JOLTs Job Openings", "ISM Manufacturing PMI", "Initial Jobless Claims", "Unemployment Rate"]
    picks = []
    for term in wanted:
        for event in events:
            if term.lower() in event.lower() and event not in picks:
                picks.append(event)
                break
    if not picks:
        picks = events[:4]
    parts = ["specific data releases including " + "; ".join(picks[:5])]
    if fed:
        parts.append("Fed item " + fed[0])
    if earnings:
        parts.append("earnings headline " + earnings[0])
    return "Into Monday, the focus shifts to " + ", plus ".join(parts) + ", with traders watching whether those catalysts confirm or reverse today's macro tone."


def _ensure_complete_report(text: str, ctx: dict) -> str:
    marker_numbered = "6. Into Monday"
    marker_plain = "Into Monday"
    fallback = f"{marker_numbered}\n\n{_next_week_sentence(ctx)}"
    marker = marker_numbered if marker_numbered in text else (marker_plain if marker_plain in text else None)
    if marker is None:
        return f"{text}\n\n{fallback}".rstrip()
    head, tail = text.split(marker, 1)
    body = tail.strip()
    if len(body) < 40 or not re.search(r"[.!?]['\"]?$", body):
        return f"{head.rstrip()}\n\n{fallback}".rstrip()
    return text.rstrip()


def fallback_narrative(ctx: dict) -> str:
    market = ctx.get("market") or {}
    sp = market.get("S&P 500", {})
    ndx = market.get("Nasdaq 100", {})
    dow = market.get("Dow Jones Industrial Average", {})
    sectors = ctx.get("sectors") or {}
    leaders = sectors.get("leaders") or []
    laggards = sectors.get("laggards") or []
    bfc = ctx.get("bonds_fx_commodities") or {}
    sent = ctx.get("sentiment") or {}
    leader_txt = ", ".join([f"{label} {_fmt_pct(data.get('pct'))}" for label, data in leaders[:2]]) or "leadership was limited"
    laggard_txt = ", ".join([f"{label} {_fmt_pct(data.get('pct'))}" for label, data in laggards[:2]]) or "laggards were limited"
    lines = [
        f"🧭 ATLAS MACRO POST-MARKET — {datetime.now(ET).strftime('%b %-d, %Y · %I:%M %p ET')}",
        "",
        "1. Opening Headline",
        f"US equities finished with the S&P 500 {_fmt_pct(sp.get('pct'))} at {_fmt_num(sp.get('price'))}, Nasdaq 100 {_fmt_pct(ndx.get('pct'))} at {_fmt_num(ndx.get('price'))}, and Dow {_fmt_pct(dow.get('pct'))} at {_fmt_num(dow.get('price'))} as macro risk set the tone.",
        "",
        "2. What Drove It",
        f"The dominant catalyst was the day’s macro tape and rate reaction, with the 10-year yield at {_fmt_num((bfc.get('US 10Y yield') or {}).get('price'))}% shaping equity duration appetite.",
        "",
        "3. Sector Breakdown",
        f"Sector leadership was led by {leader_txt}, while {laggard_txt}. The spread shows whether the move leaned cyclical, defensive, or growth-led rather than stock-specific.",
        "",
        "4. Bonds, FX, Commodities",
        f"The 10-year yield closed near {_fmt_num((bfc.get('US 10Y yield') or {}).get('price'))}%, the Dollar Index sat at {_fmt_num((bfc.get('Dollar Index') or {}).get('price'))}, and WTI crude traded near ${_fmt_num((bfc.get('WTI crude oil') or {}).get('price'))}.",
        "",
        "5. Sentiment",
        f"The VIX was {_fmt_pct((sent.get('VIX') or {}).get('pct'))} at {_fmt_num((sent.get('VIX') or {}).get('price'))}, while breadth looked {sent.get('breadth', 'mixed')} with {sent.get('advancers', 0)} advancers and {sent.get('decliners', 0)} decliners.",
        "",
        "6. Into Monday",
        _next_week_sentence(ctx),
    ]
    return "\n".join(lines)


def llm_narrative(ctx: dict) -> str | None:
    if not OPENAI_API_KEY:
        return None
    prompt = (
        "Write the Atlas macro post-market wrap in Bloomberg/FT Markets Wrap style: direct, specific, professional. "
        "Use plain text only: no markdown bold, no bullets, no tables. Output exactly 6 numbered section headings using this exact format: '1. Opening Headline' through '6. Into Monday'. "
        "Use actual market numbers in every sentence where available, but do not force internal row counts or feed mechanics into prose. "
        "Each section must contain 1-3 tight sentences maximum. State cause and effect explicitly. "
        "Never mention row counts, returned rows, data sources, API fields, JSON keys, internal variable names, proxies, or setup language. "
        "If headline data is thin, write a neutral market sentence instead of reporting absence. "
        "Required order: 1 opening headline; 2 what drove it; 3 sector breakdown; 4 bonds, FX, commodities; 5 sentiment; 6 into Monday. "
        "For section 6, name actual scheduled events from the next_week calendar data: specific releases such as PCE, ISM, CPI, NFP/nonfarm payrolls, ADP, JOLTS, jobless claims, unemployment, Fed speaker names/items if available, and earnings names/headlines if available; include available times, estimates, or prior values when present. If no specific events are found, write exactly: 'The calendar is light next week — focus shifts to technicals and any weekend geopolitical developments.' "
        "No individual stock tickers. No buy/sell recommendations. Company names are allowed only when they are earnings-calendar names, not trade ideas. Raw data follows as JSON:\n"
        + json.dumps(ctx, default=str)[:14000]
    )
    system = (
        "You are a strict Bloomberg/FT market-wrap editor. The brief must read like polished market prose, not a data extraction summary. Keep the 6 numbered headings exactly as requested. "
        "Use these few-shot examples as style only, not factual data. "
        "Opening style: 'US stocks ended lower as a late rise in Treasury yields overwhelmed early strength, leaving the S&P 500 down 0.4% and the Nasdaq 100 off 1.1%. The dominant theme was duration pressure, with growth shares lagging as the 10-year yield pushed back toward 4.37%.' "
        "Driver style: 'The catalyst was a stronger inflation print that lifted yields and reduced the odds of near-term Fed easing. That pushed the dollar higher and compressed equity multiples, hitting rate-sensitive growth sectors hardest.' "
        "Sector style: 'Technology and communication services trailed as semiconductor weakness spread through the growth complex, while energy outperformed with crude holding above $70. The split left the tape narrow rather than broadly risk-on.' "
        "Bonds/FX/commodities style: 'The 10-year yield ended near 4.37% as the front end stayed firm, keeping the curve restrictive. The Dollar Index held around 101.37, while WTI crude slipped 2.3% to $70.24 as supply concerns faded.' "
        "Sentiment style: 'The VIX rose to 18.4 as breadth weakened, showing the selloff was broader than a single-sector rotation. Credit proxies softened, pointing to a modest risk-premium rebuild rather than outright stress.' "
        "Monday style: 'Into Monday, traders will focus on ISM manufacturing, ADP employment, JOLTS job openings and nonfarm payrolls, with jobless claims and the unemployment rate shaping the next read on labor-market slack. Fed items and earnings headlines matter only if they are present in the calendar data; otherwise, the calendar is light next week — focus shifts to technicals and any weekend geopolitical developments.' "
        "Section 6 must always finish with a complete sentence ending in a period; never stop mid-sentence. Never use internal language such as rows, returned, JSON, API, source, field, variable, proxy counts, or scheduled count phrasing."
    )
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": os.environ.get("ATLAS_MACRO_LLM_MODEL", "gpt-4o"),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 1800,
            },
            timeout=25,
        )
        if r.status_code != 200:
            print(f"[macro_postmarket] LLM HTTP {r.status_code}: {r.text[:200]}")
            return None
        text = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        cleaned = _scrub_internal_language(_strip_tickers(text)) if text else None
        if cleaned:
            cleaned = _ensure_numeric_sentences(cleaned, ctx)
            cleaned = _scrub_internal_language(cleaned)
        return _ensure_complete_report(cleaned, ctx) if cleaned else None
    except Exception as exc:
        print(f"[macro_postmarket] LLM failed: {type(exc).__name__}")
        return None


def build_report(use_llm: bool = True) -> tuple[str, dict]:
    ctx = collect_raw_context()
    narrative = llm_narrative(ctx) if use_llm else None
    if not narrative:
        narrative = fallback_narrative(ctx)
    if not narrative.startswith("🧭"):
        narrative = f"🧭 ATLAS MACRO POST-MARKET — {datetime.now(ET).strftime('%b %-d, %Y · %I:%M %p ET')}\n\n{narrative}"
    narrative = _strip_handoff_block(narrative)
    return narrative, ctx


def _launchd_gate_open(now_et: datetime | None = None) -> bool:
    now_et = now_et or datetime.now(ET)
    if now_et.weekday() >= 5:
        return False
    t = now_et.time().replace(tzinfo=None)
    return time(16, 10) <= t <= time(16, 25)


def send_report(message: str) -> bool:
    if _send_telegram is None:
        print("[macro_postmarket] Telegram module unavailable; printing only")
        print(message)
        return False
    return bool(_send_telegram(message, label="macro_postmarket", parse_mode=""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atlas macro post-market wrap")
    parser.add_argument("--dry-run", action="store_true", help="Print report without Telegram send")
    parser.add_argument("--force", action="store_true", help="Bypass 16:15 ET launchd gate")
    parser.add_argument("--no-llm", action="store_true", help="Use deterministic fallback narrative")
    args = parser.parse_args(argv)

    today_et = datetime.now(ET).date()
    if not is_trading_day(today_et):
        print(f"[macro_postmarket] calendar gate closed; non-market ET day {today_et.isoformat()}; no report sent")
        return 0

    if not args.force and not _launchd_gate_open():
        return 0

    start = time_mod.perf_counter()
    message, ctx = build_report(use_llm=not args.no_llm)
    print(f"[macro_postmarket] collection_seconds={ctx.get('collection_seconds')} total_build_seconds={time_mod.perf_counter() - start:.2f}")
    if args.dry_run:
        print(message)
        print(f"[macro_postmarket] dry-run generated {len(message)} chars; Telegram not sent")
        return 0
    ok = send_report(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
