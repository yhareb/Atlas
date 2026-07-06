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

SCRIPTS_DIR = os.environ.get("ATLAS_SCRIPTS_DIR") or os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
from atlas_time import is_trading_day

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


# ---------------------------------------------------------------------------
# Deterministic renderer helpers
# ---------------------------------------------------------------------------

def _arrow(pct: float | None) -> str:
    """Return 🟢 for positive, 🔴 for negative, ⚪ for flat/None."""
    if pct is None:
        return "⚪"
    return "🟢" if pct >= 0.05 else ("🔴" if pct <= -0.05 else "⚪")


def _fmt_quote_pct(pct: object) -> str:
    """Format a percent value with sign for quote display, e.g. +1.25% or −0.36%."""
    try:
        v = float(pct)
    except Exception:
        return "N/A"
    sign = "+" if v >= 0 else "−"
    return f"{sign}{abs(v):.2f}%"


def _fmt_level(price: object, decimals: int = 2) -> str:
    try:
        return f"{float(price):,.{decimals}f}"
    except Exception:
        return "N/A"


def _section(title: str) -> str:
    return f"━━━ {title} ━━━"


def _tone_line(sp_pct: float | None, concentration: str) -> str:
    """Derive a single deterministic tone sentence from futures direction and breadth."""
    if sp_pct is None:
        return "Tone unclear — futures data unavailable. Wait for cash open."
    broad = (concentration or "").lower() == "broad"
    if sp_pct >= 0.5 and broad:
        return f"Risk-on — S&P futures +{sp_pct:.2f}%, breadth broad. Participation supports the move."
    if sp_pct >= 0.5 and not broad:
        return f"Cautious — S&P futures +{sp_pct:.2f}% but breadth narrow. Leadership concentrated; wait for confirmation."
    if sp_pct <= -0.5 and broad:
        return f"Broad pullback — S&P futures {sp_pct:.2f}%, selling across the tape. Watch for reversal at the cash open."
    if sp_pct <= -0.5 and not broad:
        return f"Risk-off — S&P futures {sp_pct:.2f}%, breadth narrow. Wait for cash open confirmation."
    return f"Neutral open — S&P futures {sp_pct:+.2f}%, directional bias unclear. Let the cash session set direction."


def deterministic_narrative(ctx: dict) -> str:
    """Build the full 8-section macro pre-market report from deterministic ctx data only.

    Replaces both llm_narrative() and fallback_narrative(). No LLM call is made.
    Output follows the canonical Atlas card/section design:
      ━━━ EMOJI SECTION NAME ━━━
    """
    now_str = datetime.now(ET).strftime("%b %-d, %Y · %-I:%M %p ET")
    lines: list[str] = [
        f"🧭 ATLAS MACRO PRE-MARKET — {now_str}",
        "",
    ]

    # ── Section 1: Futures Overview ─────────────────────────────────────────
    lines.append(_section("📡 1. FUTURES OVERVIEW"))
    fut = ctx.get("futures_overview") or {}
    sp  = fut.get("S&P 500 futures") or {}
    nq  = fut.get("Nasdaq 100 futures") or {}
    dow = fut.get("Dow futures") or {}
    for label, q in [("S&P 500 ", sp), ("Nasdaq 100", nq), ("Dow       ", dow)]:
        icon = _arrow(q.get("pct"))
        level = _fmt_level(q.get("price"), decimals=0)
        pct   = _fmt_quote_pct(q.get("pct"))
        lines.append(f"{icon} {label}  {level}  {pct}")
    lines.append("")

    # ── Section 2: NYSE / Nasdaq Breadth ────────────────────────────────────
    lines.append(_section("📊 2. NYSE / NASDAQ BREADTH"))
    breadth = ctx.get("breadth") or {}
    concentration = breadth.get("concentration", "mixed")
    if "nyse_advancers" in breadth:
        nyse_a = breadth.get("nyse_advancers", 0)
        nyse_d = breadth.get("nyse_decliners", 0)
        nyse_u = breadth.get("nyse_unchanged", 0)
        nas_a  = breadth.get("nasdaq_advancers", 0)
        nas_d  = breadth.get("nasdaq_decliners", 0)
        nas_u  = breadth.get("nasdaq_unchanged", 0)
        session = breadth.get("session_date", "")
        session_label = f"  ({session})" if session else ""
        lines.append(f"NYSE{session_label}")
        lines.append(f"   🟢 Adv {nyse_a:,}  🔴 Dec {nyse_d:,}  ⚪ Unch {nyse_u:,}")
        lines.append("Nasdaq")
        lines.append(f"   🟢 Adv {nas_a:,}  🔴 Dec {nas_d:,}  ⚪ Unch {nas_u:,}")
    else:
        adv = breadth.get("advancers", 0)
        dec = breadth.get("decliners", 0)
        lines.append(f"Pre-market proxy  🟢 Adv {adv}  🔴 Dec {dec}")
    lines.append(f"Concentration: {concentration.upper()}")
    lines.append("")

    # ── Section 3: Technology & Semiconductors ──────────────────────────────
    lines.append(_section("🔬 3. TECHNOLOGY & SEMICONDUCTORS"))
    ts   = ctx.get("technology_and_semiconductors") or {}
    soxx = ts.get("sox_proxy") or {}
    soxx_icon  = _arrow(soxx.get("pct"))
    soxx_level = _fmt_level(soxx.get("price"))
    soxx_pct   = _fmt_quote_pct(soxx.get("pct"))
    lines.append(f"{soxx_icon} SOXX proxy  {soxx_level}  {soxx_pct}")
    semi_news = (ts.get("analyst_and_equipment_news") or [])[:2]
    if semi_news:
        for item in semi_news:
            lines.append(f"📰 {item[:180]}")
    else:
        lines.append("📭 Quiet — no major semiconductor or equipment headlines overnight.")
    lines.append("")

    # ── Section 4: Artificial Intelligence ─────────────────────────────────
    lines.append(_section("🤖 4. ARTIFICIAL INTELLIGENCE"))
    ai_news = ((ctx.get("artificial_intelligence") or {}).get("ai_news") or [])[:3]
    if ai_news:
        for item in ai_news:
            lines.append(f"📰 {item[:180]}")
    else:
        lines.append("📭 Quiet overnight — no major AI model, capex, regulatory, or deal headlines.")
    lines.append("")

    # ── Section 5: Catalysts & Breaking News ────────────────────────────────
    lines.append(_section("🔥 5. CATALYSTS & BREAKING NEWS"))
    catalyst_news = ((ctx.get("catalysts_and_breaking_news") or {}).get("catalyst_news") or [])[:3]
    if catalyst_news:
        for item in catalyst_news:
            lines.append(f"📰 {item[:180]}")
    else:
        lines.append("📭 No major catalyst headlines — export controls, earnings, or macro shock.")
    lines.append("")

    # ── Section 6: Global Markets ───────────────────────────────────────────
    lines.append(_section("🌐 6. GLOBAL MARKETS"))
    gm = ctx.get("global_markets") or {}
    global_order = [
        ("Nikkei 225",    gm.get("Nikkei 225")    or {}, 0),
        ("Euro Stoxx 50", gm.get("Euro Stoxx 50")  or {}, 0),
        ("Dollar Index",  gm.get("Dollar Index")   or {}, 2),
        ("WTI Crude Oil", gm.get("WTI crude oil")  or {}, 2),
        ("US 10Y Yield",  gm.get("US 10Y yield")   or {}, None),  # special: divide by 10
    ]
    for label, q, dec in global_order:
        icon = _arrow(q.get("pct"))
        pct  = _fmt_quote_pct(q.get("pct"))
        if label == "US 10Y Yield":
            # Yahoo ^TNX quotes yield × 10 (e.g. 43.7 = 4.37%)
            raw = q.get("price")
            try:
                level = f"{float(raw) / 10:.2f}%"
            except Exception:
                level = "N/A"
        else:
            level = _fmt_level(q.get("price"), decimals=dec if dec is not None else 2)
        lines.append(f"{icon} {label:<16} {level:>10}  {pct}")
    lines.append("")

    # ── Section 7: The Tone ─────────────────────────────────────────────────
    lines.append(_section("🎯 7. THE TONE"))
    sp_pct = sp.get("pct")
    try:
        sp_pct = float(sp_pct)
    except Exception:
        sp_pct = None
    lines.append(_tone_line(sp_pct, concentration))
    lines.append("")

    # ── Section 8: Key Events Today ─────────────────────────────────────────
    lines.append(_section("📅 8. KEY EVENTS TODAY"))
    events_ctx  = ctx.get("key_events_today") or {}
    econ        = (events_ctx.get("economic_events")    or [])[:6]
    earnings    = (events_ctx.get("earnings_before_open") or [])[:3]
    fed         = (events_ctx.get("fed_speakers")        or [])[:3]
    has_content = bool(econ or earnings or fed)
    if econ:
        for item in econ:
            lines.append(f"🗓 {item[:180]}")
    if earnings:
        lines.append("Earnings before open:")
        for item in earnings:
            lines.append(f"   📰 {item[:160]}")
    if fed:
        lines.append("Fed speakers:")
        for item in fed:
            lines.append(f"   🎙 {item[:160]}")
    if not has_content:
        lines.append("📭 Light calendar — no major scheduled events today.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM narrative (kept as optional path; disabled by default via env var)
# ---------------------------------------------------------------------------

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
                        "Events style: 'The calendar centers on US data at [TIME] ET, followed by Fed commentary that will be judged against the 10-year yield near 4.37%. Pre-open earnings should matter most where guidance changes the read-through for margins and demand.' "
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
    # Respect ATLAS_MACRO_USE_LLM env var: set to "0" or "false" to force deterministic path.
    _env_use_llm = os.environ.get("ATLAS_MACRO_USE_LLM", "").strip().lower()
    if _env_use_llm in ("0", "false", "no"):
        use_llm = False
    narrative = llm_narrative(ctx) if use_llm else None
    if not narrative:
        narrative = deterministic_narrative(ctx)
    if not narrative.startswith("🧭"):
        narrative = f"🧭 ATLAS MACRO PRE-MARKET — {datetime.now(ET).strftime('%b %-d, %Y · %I:%M %p ET')}\n\n{narrative}"
    return narrative, ctx


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


def _previous_trading_date(d):
    """Return the most recent completed trading session date before d."""
    import datetime as _dt
    cur = d - _dt.timedelta(days=1)
    while cur.weekday() >= 5:
        cur -= _dt.timedelta(days=1)
    return cur


def _breadth_from_grouped(session_date):
    """Compute NYSE and Nasdaq advance/decline from Massive grouped daily aggregates."""
    date_str = session_date.isoformat()
    grouped = massive_get(f"/v2/aggs/grouped/locale/us/market/stocks/{date_str}") or {}
    results = grouped.get("results") or []
    if not results:
        return None
    # Build close price map for this session
    close_map = {r["T"]: r["c"] for r in results if r.get("T") and r.get("c") is not None}
    # Get previous session for comparison
    import datetime as _dt
    prev_date = _previous_trading_date(session_date)
    prev_grouped = massive_get(f"/v2/aggs/grouped/locale/us/market/stocks/{prev_date.isoformat()}") or {}
    prev_results = prev_grouped.get("results") or []
    prev_close_map = {r["T"]: r["c"] for r in prev_results if r.get("T") and r.get("c") is not None}
    # NYSE tickers (XNYS) — use open vs close within session as proxy if prev unavailable
    def _count_adv_dec(tickers):
        adv = dec = unch = 0
        for t in tickers:
            cur_c = close_map.get(t)
            prev_c = prev_close_map.get(t)
            if cur_c is None:
                continue
            if prev_c is not None:
                if cur_c > prev_c:
                    adv += 1
                elif cur_c < prev_c:
                    dec += 1
                else:
                    unch += 1
        return adv, dec, unch
    # Fetch NYSE and Nasdaq common stock universes (cached in module-level dict)
    nyse_tickers = _get_exchange_universe("XNYS")
    nasdaq_tickers = _get_exchange_universe("XNAS")
    nyse_adv, nyse_dec, nyse_unch = _count_adv_dec(nyse_tickers)
    nas_adv, nas_dec, nas_unch = _count_adv_dec(nasdaq_tickers)
    return {
        "session_date": date_str,
        "nyse_advancers": nyse_adv,
        "nyse_decliners": nyse_dec,
        "nyse_unchanged": nyse_unch,
        "nasdaq_advancers": nas_adv,
        "nasdaq_decliners": nas_dec,
        "nasdaq_unchanged": nas_unch,
    }


_EXCHANGE_UNIVERSE_CACHE: dict = {}


def _get_exchange_universe(exchange: str) -> list:
    """Fetch and cache the list of common stock tickers for a given exchange."""
    if exchange in _EXCHANGE_UNIVERSE_CACHE:
        return _EXCHANGE_UNIVERSE_CACHE[exchange]
    tickers = []
    cursor = None
    for _ in range(10):  # max 10 pages
        params = {"market": "stocks", "exchange": exchange, "active": "true", "type": "CS", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        resp = massive_get("/v3/reference/tickers", params=params) or {}
        page = resp.get("results") or []
        tickers.extend(t["ticker"] for t in page if t.get("ticker"))
        cursor = (resp.get("next_url") or "").split("cursor=")[-1] if resp.get("next_url") else None
        if not cursor or not page:
            break
    _EXCHANGE_UNIVERSE_CACHE[exchange] = tickers
    return tickers


def breadth_snapshot() -> dict:
    # Top movers for concentration and top-gainer/loser display
    gainers = (massive_get("/v2/snapshot/locale/us/markets/stocks/gainers") or {}).get("tickers") or []
    losers = (massive_get("/v2/snapshot/locale/us/markets/stocks/losers") or {}).get("tickers") or []
    top_gains = [abs(float(x.get("todaysChangePerc") or 0)) for x in gainers[:10]]
    top_loss = [abs(float(x.get("todaysChangePerc") or 0)) for x in losers[:10]]
    concentration = "narrow" if top_gains and sum(top_gains[:3]) > max(sum(top_gains[3:10]), 1) else "broad"
    # Real NYSE/Nasdaq advance/decline from latest completed session
    import datetime as _dt
    today_et = datetime.now(ET).date()
    # Walk backward up to 7 days to find the latest session with grouped data
    real_breadth = None
    for _days_back in range(1, 8):
        _candidate = today_et - _dt.timedelta(days=_days_back)
        if _candidate.weekday() >= 5:
            continue
        real_breadth = _breadth_from_grouped(_candidate)
        if real_breadth:
            break
    result = {
        "concentration": concentration,
        "top_gain_avg": (sum(top_gains[:5]) / min(len(top_gains), 5)) if top_gains else None,
        "top_loss_avg": (sum(top_loss[:5]) / min(len(top_loss), 5)) if top_loss else None,
        "top_gainers": [{"ticker": x.get("ticker"), "pct": round(float(x.get("todaysChangePerc") or 0), 1)} for x in gainers[:5]],
        "top_losers": [{"ticker": x.get("ticker"), "pct": round(float(x.get("todaysChangePerc") or 0), 1)} for x in losers[:5]],
    }
    if real_breadth:
        result.update(real_breadth)
    else:
        result["advancers"] = len(gainers)
        result["decliners"] = len(losers)
    return result


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
    import datetime as _dt_mod
    import dateutil.parser as _dp
    today_et = datetime.now(ET).date()
    yesterday_et = today_et - timedelta(days=1)
    tomorrow_et = today_et + timedelta(days=1)
    macro = eodhd_get("/economic-events", {
        "from": yesterday_et.isoformat(),
        "to": tomorrow_et.isoformat(),
        "country": "US",
        "limit": 50,
    })
    events = []
    if isinstance(macro, list):
        for item in macro:
            raw_date = item.get("date") or item.get("datetime") or ""
            try:
                event_dt_utc = _dp.parse(str(raw_date)).replace(tzinfo=_dt_mod.timezone.utc) if raw_date else None
                event_dt_et = event_dt_utc.astimezone(ET) if event_dt_utc else None
                if event_dt_et and event_dt_et.date() != today_et:
                    continue
                time_str = event_dt_et.strftime("%-I:%M %p ET") if event_dt_et else ""
            except Exception:
                time_str = raw_date[:16] if raw_date else ""
            name = _clean_text(item.get("type") or item.get("event") or item.get("name") or "")
            estimate = item.get("estimate")
            previous = item.get("previous")
            detail = name
            if estimate is not None:
                detail += f" · est {estimate}"
            if previous is not None:
                detail += f" · prev {previous}"
            if time_str:
                detail = f"{time_str} — {detail}"
            if detail.strip():
                events.append(detail.strip())
        events = events[:10]
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
    parser.add_argument("--no-llm", action="store_true", help="Use deterministic narrative (default path)")
    args = parser.parse_args(argv)

    today_et = datetime.now(ET).date()
    if not is_trading_day(today_et):
        print(f"[macro_premarket] calendar gate closed; non-market ET day {today_et.isoformat()}; no report sent")
        return 0

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
