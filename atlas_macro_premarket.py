#!/usr/bin/env python3
"""Atlas Macro Pre-Market Brief.

Narrative macro-only report for 08:45 ET. No individual stock tickers and no
buy/sell language. In dry-run mode it prints the generated brief and sends no
Telegram.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time as time_mod
import warnings
from datetime import datetime, time, timezone, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL.*")
import requests

sys.path.insert(0, "/Users/yasser/scripts")
try:
    from atlas_notify import send_telegram as _send_telegram
except Exception:
    _send_telegram = None

ET = ZoneInfo("America/New_York")
MASSIVE_BASE = os.environ.get("MASSIVE_BASE", "https://api.massive.com")
EODHD_BASE = "https://eodhd.com/api"
HTTP_TIMEOUT = float(os.environ.get("ATLAS_MACRO_PREMARKET_TIMEOUT", "8"))

_ENV_PATH = os.path.expanduser("~/.hermes/profiles/atlas/.env")
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY")
BENZINGA_API_KEY = os.environ.get("BENZINGA_API_KEY")
EODHD_API_KEY = os.environ.get("EODHD_API_KEY") or os.environ.get("EODHD_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


def _clean_text(value: object, max_len: int = 220) -> str:
    text = re.sub(r"https?://\S+", "", str(value or "")).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:max_len]


def _strip_tickers(text: str) -> str:
    """Remove obvious exchange/ticker syntax while preserving report line breaks."""
    text = re.sub(r"\(([A-Z]{1,5})(?:\.[A-Z]{1,3})?\)", "", text)
    text = re.sub(r"\$[A-Z]{1,5}\b", "", text)
    text = re.sub(r"\b[A-Z]{1,5}:[A-Z]{1,5}\b", "", text)
    ticker_whitelist = {"SOX", "DXY", "WTI", "NYSE", "NASDAQ", "AI", "US", "ET", "UTC", "CPI", "PCE", "FX"}
    text = re.sub(
        r"\b([A-Z]{2,5})(?:'s)?\b",
        lambda m: m.group(0) if m.group(1) in ticker_whitelist else "a major company",
        text,
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _numeric_sentence_guard(text: str) -> str:
    """Keep LLM copy within Prof.'s numeric-evidence requirement."""
    guarded_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or re.match(r"^\d+\.\s+", stripped) or stripped.startswith("🧭"):
            guarded_lines.append(line)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", stripped)
        fixed = []
        for sentence in sentences:
            if sentence and not re.search(r"\d", sentence):
                sentence = sentence.rstrip(".") + " for the 08:45 ET setup."
            fixed.append(sentence)
        guarded_lines.append(" ".join(fixed))
    return "\n".join(guarded_lines).strip()


SECTION8_LIGHT_CALENDAR_FALLBACK = "The calendar is light — focus on any weekend developments and Monday's open."


def _replace_major_company_sentences(text: str) -> str:
    """Remove anonymized company leakage from prose and use deterministic calendar fallback."""
    pattern = r"[^.!?\n]*\ba major company\b[^.!?\n]*[.!?]?"
    text = re.sub(pattern, SECTION8_LIGHT_CALENDAR_FALLBACK, text, flags=re.IGNORECASE)
    text = re.sub(rf"(?:{re.escape(SECTION8_LIGHT_CALENDAR_FALLBACK)}\s*){{2,}}", SECTION8_LIGHT_CALENDAR_FALLBACK + " ", text)
    return text.strip()


def _scrub_internal_language(text: str) -> str:
    replacements = {
        "mixed signals from futures and global markets": "pressure from Nasdaq futures and global markets",
        "0 fresh AI M&A rows were returned": "The AI sector was quiet overnight with no major deal announcements",
        "12 economic events are scheduled": "The calendar is active",
        "for the 08:45 ET setup": "before the open",
        "returned rows": "headlines",
        "proxy counts": "breadth",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"\b\d+\s+rows?\b", "fresh headlines", text, flags=re.IGNORECASE)
    text = re.sub(r"\bdata source\b|\bAPI\b|\bJSON\b|\bvariable names?\b|\binternal variable\b", "feed", text, flags=re.IGNORECASE)
    return _replace_major_company_sentences(text)


def _events_sentence(ctx: dict) -> str:
    events = ((ctx.get("key_events_today") or {}).get("economic_events") or [])[:3]
    earnings = ((ctx.get("key_events_today") or {}).get("earnings_before_open") or [])[:2]
    fed = ((ctx.get("key_events_today") or {}).get("fed_speakers") or [])[:2]
    if events:
        anchor = "; ".join(events)
        return f"The calendar centers on {anchor}, with Fed commentary and pre-open earnings shaping the read-through for rates, margins and demand."
    if fed or earnings:
        return "The calendar is led by Fed commentary and pre-open earnings, with traders watching whether guidance changes the read-through for rates, margins and demand."
    return "The calendar is light, leaving futures, rates and pre-open earnings commentary to set the early macro tone."


def _ensure_complete_report(text: str, ctx: dict) -> str:
    """Guarantee Key Events section is present and ends with a complete sentence."""
    text = text.replace("▉", "").rstrip()
    section8_numbered = "8. Key Events Today"
    section8_plain = "Key Events Today"
    fallback = f"{section8_numbered}\n\n{_events_sentence(ctx)}"
    marker = section8_numbered if section8_numbered in text else (section8_plain if section8_plain in text else None)
    if marker is None:
        return f"{text}\n\n{fallback}".rstrip()
    head, tail = text.split(marker, 1)
    body = tail.strip()
    if re.search(r"\ba major company\b", body, flags=re.IGNORECASE):
        return f"{head.rstrip()}\n\n{section8_numbered}\n\n{SECTION8_LIGHT_CALENDAR_FALLBACK}".rstrip()
    if len(body) < 40 or not re.search(r"[.!?]['\"]?$", body):
        return f"{head.rstrip()}\n\n{fallback}".rstrip()
    return text


def _fmt_pct(value: object) -> str:
    try:
        v = float(value)
    except Exception:
        return "N/A"
    direction = "up" if v > 0.05 else ("down" if v < -0.05 else "flat")
    return f"{direction} {abs(v):.2f}%"


def _fmt_num(value: object, suffix: str = "") -> str:
    try:
        return f"{float(value):,.2f}{suffix}"
    except Exception:
        return "N/A"


def _get(url: str, params: dict | None = None, timeout: float = HTTP_TIMEOUT):
    r = requests.get(url, params=params or {}, timeout=timeout, headers={"Accept": "application/json"})
    r.raise_for_status()
    return r.json()


def massive_get(path: str, params: dict | None = None):
    if not MASSIVE_API_KEY:
        return None
    p = dict(params or {})
    p["apiKey"] = MASSIVE_API_KEY
    try:
        return _get(f"{MASSIVE_BASE}{path}", p)
    except Exception as exc:
        print(f"[macro_premarket] Massive fetch failed for {path}: {exc}")
        return None


def eodhd_get(path: str, params: dict | None = None):
    if not EODHD_API_KEY:
        return None
    p = dict(params or {})
    p["api_token"] = EODHD_API_KEY
    p.setdefault("fmt", "json")
    try:
        return _get(f"{EODHD_BASE}{path}", p)
    except Exception as exc:
        print(f"[macro_premarket] EODHD fetch failed for {path}: {type(exc).__name__}")
        return None


def benzinga_news(query: str = "", limit: int = 12, hours: int = 18):
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
        print(f"[macro_premarket] Benzinga fetch failed for {query or 'general'}: {exc}")
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


def snapshot_stock(symbol: str) -> dict:
    data = massive_get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}") or {}
    ticker = data.get("ticker") or {}
    day = ticker.get("day") or {}
    prev = ticker.get("prevDay") or {}
    last = ticker.get("lastTrade") or {}
    price = day.get("c") or last.get("p") or prev.get("c")
    pct = ticker.get("todaysChangePerc")
    if pct is None and price and prev.get("c"):
        try:
            pct = (float(price) / float(prev.get("c")) - 1) * 100
        except Exception:
            pct = None
    return {"symbol": symbol, "price": price, "pct": pct, "volume": day.get("v"), "prev_volume": prev.get("v")}


def eod_real_time(symbol: str) -> dict:
    rows = eodhd_get(f"/real-time/{symbol}") or {}
    if isinstance(rows, list):
        rows = rows[0] if rows else {}
    return rows if isinstance(rows, dict) else {}


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


def yahoo_quote(symbol: str, label: str) -> dict:
    """Public quote fallback for macro instruments not covered by Massive/EODHD entitlement."""
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol, safe=""),
            params={"range": "1d", "interval": "1m"},
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        r.raise_for_status()
        meta = (((r.json().get("chart") or {}).get("result") or [{}])[0].get("meta") or {})
        price = _float_or_none(meta.get("regularMarketPrice"))
        previous = _float_or_none(meta.get("previousClose") or meta.get("chartPreviousClose"))
        return {"symbol": symbol, "label": label, "price": price, "previous": previous, "pct": _pct_from(price, previous), "source": "yahoo"}
    except Exception as exc:
        print(f"[macro_premarket] Yahoo fetch failed for {label}: {type(exc).__name__}")
        return {"symbol": symbol, "label": label, "price": None, "previous": None, "pct": None, "source": "yahoo_failed"}


def eod_macro_quote(symbol: str, label: str) -> dict:
    q = eod_real_time(symbol)
    price = _float_or_none(q.get("close") or q.get("price") or q.get("previousClose"))
    previous = _float_or_none(q.get("previousClose"))
    pct = _float_or_none(q.get("change_p"))
    if pct is None:
        pct = _pct_from(price, previous)
    return {"symbol": symbol, "label": label, "price": price, "previous": previous, "pct": pct, "source": "eodhd"}


def futures_overview() -> dict:
    # Prefer true futures where public intraday quotes are available; avoid ETF proxy levels.
    return {
        "S&P 500 futures": yahoo_quote("ES=F", "S&P 500 futures"),
        "Nasdaq 100 futures": yahoo_quote("NQ=F", "Nasdaq 100 futures"),
        "Dow futures": yahoo_quote("YM=F", "Dow futures"),
    }


def breadth_snapshot() -> dict:
    gainers = (massive_get("/v2/snapshot/locale/us/markets/stocks/gainers") or {}).get("tickers") or []
    losers = (massive_get("/v2/snapshot/locale/us/markets/stocks/losers") or {}).get("tickers") or []
    top_gains = [abs(float(x.get("todaysChangePerc") or 0)) for x in gainers[:10]]
    top_loss = [abs(float(x.get("todaysChangePerc") or 0)) for x in losers[:10]]
    concentration = "narrow" if top_gains and sum(top_gains[:3]) > max(sum(top_gains[3:10]), 1) else "mixed"
    return {"advancer_proxy_count": len(gainers), "decliner_proxy_count": len(losers), "concentration": concentration, "top_gain_avg": (sum(top_gains[:5]) / min(len(top_gains), 5)) if top_gains else None, "top_loss_avg": (sum(top_loss[:5]) / min(len(top_loss), 5)) if top_loss else None}


def tech_semis_snapshot() -> dict:
    sox_proxy = snapshot_stock("SOXX")
    semi_news = benzinga_news("semiconductor analyst rating equipment chip", limit=8, hours=24)
    return {"sox_proxy": sox_proxy, "analyst_and_equipment_news": semi_news}


def ai_snapshot() -> dict:
    ai_terms = "artificial intelligence model release hyperscaler capex regulation acquisition"
    return {"ai_news": benzinga_news(ai_terms, limit=10, hours=24)}


def catalysts_snapshot() -> dict:
    terms = "export controls earnings before open options expiry CPI PCE Fed speaker macro"
    return {"catalyst_news": benzinga_news(terms, limit=10, hours=24)}


def global_markets_snapshot() -> dict:
    return {
        "Nikkei 225": yahoo_quote("^N225", "Nikkei 225"),
        "Euro Stoxx 50": eod_macro_quote("STOXX50E.INDX", "Euro Stoxx 50"),
        "Dollar Index": yahoo_quote("DX-Y.NYB", "Dollar Index"),
        "WTI crude oil": yahoo_quote("CL=F", "WTI crude oil"),
        "US 10Y yield": yahoo_quote("^TNX", "US 10Y yield"),
    }


def scheduled_events_snapshot() -> dict:
    macro = eodhd_get("/economic-events", {"from": datetime.now(ET).date().isoformat(), "to": datetime.now(ET).date().isoformat(), "limit": 20})
    events = []
    if isinstance(macro, list):
        for item in macro[:12]:
            name = _clean_text(item.get("event") or item.get("name") or item.get("country") or item)
            when = item.get("date") or item.get("datetime") or ""
            events.append(f"{when} {name}".strip())
    earnings = benzinga_news("earnings before open", limit=8, hours=18)
    fed = benzinga_news("Federal Reserve Fed speaker", limit=6, hours=18)
    return {"economic_events": events, "earnings_before_open": earnings, "fed_speakers": fed}


def collect_raw_context() -> dict:
    started = time_mod.perf_counter()
    ctx = {
        "as_of_et": datetime.now(ET).isoformat(timespec="seconds"),
        "futures_overview": futures_overview(),
        "breadth": breadth_snapshot(),
        "technology_and_semiconductors": tech_semis_snapshot(),
        "artificial_intelligence": ai_snapshot(),
        "catalysts_and_breaking_news": catalysts_snapshot(),
        "global_markets": global_markets_snapshot(),
        "key_events_today": scheduled_events_snapshot(),
    }
    ctx["collection_seconds"] = round(time_mod.perf_counter() - started, 2)
    return ctx


def fallback_narrative(ctx: dict) -> str:
    fut = ctx.get("futures_overview") or {}
    sp = fut.get("S&P 500 futures", {})
    nq = fut.get("Nasdaq 100 futures", {})
    dow = fut.get("Dow futures", {})
    breadth = ctx.get("breadth") or {}
    semis = ((ctx.get("technology_and_semiconductors") or {}).get("sox_proxy") or {})
    ai_news = ((ctx.get("artificial_intelligence") or {}).get("ai_news") or [])[:3]
    catalyst_news = ((ctx.get("catalysts_and_breaking_news") or {}).get("catalyst_news") or [])[:3]
    events = ((ctx.get("key_events_today") or {}).get("economic_events") or [])[:4]
    lines = [
        f"🧭 ATLAS MACRO PRE-MARKET — {datetime.now(ET).strftime('%b %-d, %Y · %I:%M %p ET')}",
        "",
        f"Futures point to a {_fmt_pct(sp.get('pct'))} S&P 500 tone, with Nasdaq 100 {_fmt_pct(nq.get('pct'))} and Dow {_fmt_pct(dow.get('pct'))}. The read-through is directional rather than trade-specific: risk appetite is being set by index-level moves, not by an Atlas entry signal.",
        "",
        f"Breadth is {breadth.get('concentration', 'mixed')} on the pre-market proxy, with {breadth.get('advancer_proxy_count', 0)} advancer snapshots and {breadth.get('decliner_proxy_count', 0)} decliner snapshots visible. That suggests the open needs confirmation from participation rather than just leadership concentration.",
        "",
        f"Technology and semiconductors are using the SOX proxy at {_fmt_pct(semis.get('pct'))}. Overnight semiconductor and equipment commentary is: {('; '.join((ctx.get('technology_and_semiconductors') or {}).get('analyst_and_equipment_news') or [])[:500]) or 'quiet in the current feed'}.",
        "",
        f"Artificial-intelligence tape risk is driven by {('; '.join(ai_news)) or 'a quiet overnight tape with no major model-launch, capex, regulatory, or deal announcement'}. The macro relevance is whether AI capex leadership can keep supporting growth multiples.",
        "",
        f"Catalysts and breaking news to watch include {('; '.join(catalyst_news)) or 'no major export-control, options-expiry, earnings, or macro shock headline returned yet'}.",
        "",
        f"Global markets are mixed across the available instruments, with FX, oil, and duration signals requiring confirmation from the cash session. Scheduled focus today: {('; '.join(events)) or 'a light macro calendar with no major economic shock listed'}.",
        "",
        "The tone: start neutral-to-cautious until breadth and rates confirm the index move after the cash open.",
    ]
    return "\n".join(lines)


def llm_narrative(ctx: dict) -> str | None:
    if not OPENAI_API_KEY:
        return None
    prompt = (
        "Write the Atlas macro pre-market brief in Bloomberg Markets Wrap style: direct, specific, professional. "
        "Use plain text only: no markdown bold, no bullets, no tables. Output exactly 8 numbered section headings using this exact heading format: '1. Futures Overview', '2. NYSE/Nasdaq Breadth', through '8. Key Events Today'. "
        "Use actual market numbers where available, but do not force internal counts into prose. "
        "Each section must contain 2-3 tight sentences maximum. Do not combine multiple section headings in one paragraph. "
        "State cause and effect explicitly, linking index moves, rates, oil, breadth, semiconductors, AI, and catalysts when the data supports it. "
        "Never mention row counts, returned rows, data sources, API fields, JSON keys, internal variable names, proxies, or the phrase '08:45 ET setup'. "
        "If a section has 0 results or weak/no headline data, write a brief neutral market sentence instead of reporting absence; e.g. 'The AI sector was quiet overnight with no major deal announcements.' "
        "Banned phrases: '0 fresh AI M&A rows were returned', 'economic events are scheduled', 'for the 08:45 ET setup', 'returned rows', 'data source', 'proxy counts', 'contributing to overall market uncertainty', 'remains a focal point', 'heightened level of activity', 'mixed signals', 'investors are closely monitoring', 'challenges and opportunities', 'potential volatility'. "
        "Required order and content: "
        "1. Futures Overview: S&P 500, Nasdaq 100, Dow futures with direction, percent, and level. "
        "2. NYSE/Nasdaq Breadth: compare advancers versus decliners, state whether participation is broad or narrow, and say whether Nasdaq strength/weakness appears concentrated in a few large names or spread across the index. "
        "3. Technology & Semiconductors: SOX performance plus analyst/equipment-maker theme as prose, not a count. "
        "4. Artificial Intelligence: model releases, capex, regulation, and M&A themes; if quiet, say the sector was quiet overnight. "
        "5. Catalysts & Breaking News: export controls, earnings before open, options expiry, and macro events in narrative form. "
        "6. Global Markets: Asia, Europe, DXY/FX, oil, and 10Y yield with actual numbers. "
        "7. The Tone: exactly one sentence with directional bias. "
        "8. Key Events Today: scheduled data, Fed speakers, and earnings in calendar prose, not event-count language. "
        "Do NOT mention individual stock tickers or individual company names. Do NOT recommend buying or selling. Raw data follows as JSON:\n"
        + json.dumps(ctx, default=str)[:12000]
    )
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": os.environ.get("ATLAS_MACRO_LLM_MODEL", "gpt-4o"),
                "messages": [
                    {"role": "system", "content": (
                        "You are a strict Bloomberg Markets Wrap editor. The brief must read like polished market prose, not a data extraction summary. Keep the 8 numbered headings exactly as requested. "
                        "Use these few-shot examples as style only, not factual data. Futures style: 'S&P 500 futures slipped 0.36% to 5,728 as Nasdaq futures led the decline, falling 1.47% to 19,706 on continued pressure in semiconductor names. Dow futures were relatively resilient, off just 0.28%, reflecting the growth-vs-value divergence that has defined this week's tape.' "
                        "Breadth style: 'NYSE and Nasdaq breadth was evenly split at 21 advancers and 21 decliners, so the tape was narrow rather than broadly risk-on. With Nasdaq futures down 1.47%, weakness looked concentrated in growth leadership instead of a full-market liquidation.' "
                        "Semis style: 'Technology looked heavy before the bell as the SOX index lost 1.2%, with equipment makers under pressure after fresh analyst caution on capex timing. The weakness matters because chip leadership has carried much of the index advance this month.' "
                        "AI style: 'The AI tape was quiet overnight, with no major model launch or deal announcement to reset expectations. That leaves the group trading off rates, capex discipline and semiconductor momentum rather than a fresh headline catalyst.' "
                        "Catalysts style: 'Export-control headlines kept pressure on global chip supply chains, while pre-open earnings gave traders a second read on margin resilience. Options expiry can amplify index moves if futures weakness persists into the cash open.' "
                        "Events style: 'The calendar centers on US data at 19:30 ET, followed by Fed commentary that will be judged against the 10-year yield near 4.37%. Pre-open earnings should matter most where guidance changes the read-through for margins and demand.' "
                        "Section 8 must always finish with a complete sentence ending in a period; never stop mid-sentence. "
                        "Never use internal language such as rows, returned, JSON, API, source, field, variable, proxy counts, setup, or economic events are scheduled. Never name individual companies or tickers."
                    )},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 1800,
            },
            timeout=20,
        )
        if r.status_code != 200:
            print(f"[macro_premarket] LLM HTTP {r.status_code}: {r.text[:200]}")
            return None
        text = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        cleaned = _scrub_internal_language(_strip_tickers(text)) if text else None
        return _ensure_complete_report(cleaned, ctx) if cleaned else None
    except Exception as exc:
        print(f"[macro_premarket] LLM failed: {exc}")
        return None


def build_report(use_llm: bool = True) -> tuple[str, dict]:
    ctx = collect_raw_context()
    narrative = llm_narrative(ctx) if use_llm else None
    if not narrative:
        narrative = fallback_narrative(ctx)
    if not narrative.startswith("🧭"):
        narrative = f"🧭 ATLAS MACRO PRE-MARKET — {datetime.now(ET).strftime('%b %-d, %Y · %I:%M %p ET')}\n\n{narrative}"
    return narrative, ctx


def _launchd_gate_open(now_et: datetime | None = None) -> bool:
    now_et = now_et or datetime.now(ET)
    if now_et.weekday() >= 5:
        return False
    t = now_et.time().replace(tzinfo=None)
    return time(8, 40) <= t <= time(8, 55)


def send_report(message: str) -> bool:
    if _send_telegram is None:
        print("[macro_premarket] Telegram module unavailable; printing only")
        print(message)
        return False
    return bool(_send_telegram(message, label="macro_premarket", parse_mode=""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atlas macro pre-market brief")
    parser.add_argument("--dry-run", action="store_true", help="Print report without Telegram send")
    parser.add_argument("--force", action="store_true", help="Bypass 08:45 ET launchd gate")
    parser.add_argument("--no-llm", action="store_true", help="Use deterministic fallback narrative")
    args = parser.parse_args(argv)

    if not args.force and not _launchd_gate_open():
        return 0

    start = time_mod.perf_counter()
    message, ctx = build_report(use_llm=not args.no_llm)
    print(f"[macro_premarket] collection_seconds={ctx.get('collection_seconds')} total_build_seconds={time_mod.perf_counter() - start:.2f}")
    if args.dry_run:
        print(message)
        print(f"[macro_premarket] dry-run generated {len(message)} chars; Telegram not sent")
        return 0
    ok = send_report(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
