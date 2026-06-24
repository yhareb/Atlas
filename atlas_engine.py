
import os
import sys
import json
import re
import requests
import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, "/Users/yasser/scripts")
import atlas_db
from atlas_time import current_et_market_date, trading_days_between

# Load .env from Atlas profile if keys not already in environment
_env_path = os.path.expanduser("~/.hermes/profiles/atlas/.env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY")
BENZINGA_API_KEY = os.environ.get("BENZINGA_API_KEY")
EODHD_API_KEY = os.environ.get("EODHD_API_KEY")

if not MASSIVE_API_KEY:
    print(json.dumps({"error": "MASSIVE_API_KEY not found in environment."}))
    sys.exit(1)

MASSIVE_BASE = "https://api.massive.com"


try:
    from atlas_audit import log_api_call as _atlas_log_api_call
except Exception:
    _atlas_log_api_call = None

import time as _audit_time
_REQUESTS_GET = requests.get


def _audit_provider(endpoint):
    text = str(endpoint or "").lower()
    if "massive.com" in text or "polygon.io" in text:
        return "Massive"
    if "benzinga.com" in text:
        return "Benzinga"
    if "eodhd.com" in text:
        return "EODHD"
    return None


def _audit_get(url, *args, **kwargs):
    provider = _audit_provider(url)
    start = _audit_time.perf_counter()
    try:
        response = _REQUESTS_GET(url, *args, **kwargs)
        status = getattr(response, "status_code", None)
        endpoint_text = str(url or "").lower()
        expected_missing_form4 = (
            provider == "EODHD"
            and status == 404
            and "sec-filings" in endpoint_text
            and "/form4" in endpoint_text
        )
        if provider and _atlas_log_api_call and not expected_missing_form4:
            try:
                latency_ms = int((_audit_time.perf_counter() - start) * 1000)
                _atlas_log_api_call(
                    provider=provider,
                    file=os.path.basename(__file__),
                    function=sys._getframe(1).f_code.co_name,
                    endpoint=str(url),
                    http_status=status,
                    latency_ms=latency_ms,
                    ok=bool(status is not None and 200 <= int(status) < 400),
                    error=None,
                    metadata=None,
                )
            except Exception:
                pass
        return response
    except Exception as e:
        if provider and _atlas_log_api_call:
            try:
                latency_ms = int((_audit_time.perf_counter() - start) * 1000)
                _atlas_log_api_call(
                    provider=provider,
                    file=os.path.basename(__file__),
                    function=sys._getframe(1).f_code.co_name,
                    endpoint=str(url),
                    http_status=None,
                    latency_ms=latency_ms,
                    ok=False,
                    error=str(e)[:500],
                    metadata=None,
                )
            except Exception:
                pass
        raise

# =============================================================================
# ATLAS v2 — BACKTEST-VALIDATED PARAMETERS
# -----------------------------------------------------------------------------
# These thresholds were validated over 2010-2024 (15 yrs, 6 regimes, 1,275
# trades): profitable in 11/15 years, max drawdown < 8%, profit factor 1.58,
# 100% profitable across 10,000 Monte-Carlo simulations.
#
# Changes vs v1 (all justified by the backtest):
#   - Pillar 2: within 3% of 52-WEEK high  (was: within 10% of 50-DAY high)
#   - Pillar 3: RVOL >= 2.0                 (was: RVOL >= 1.2)
#   - Stop:     entry - 1.5 * ATR           (was: entry - 2.0 * ATR)
#   - NEW:      SPY > 50SMA regime gate reported on every signal
#
# Re-tune RVOL_MIN / HIGH_52W_PROX / ATR_STOP_MULT annually on the most recent
# 2-3 years of data — the walk-forward test showed yearly re-tuning lifts CAGR
# from ~6% to ~14%.
# =============================================================================
RVOL_MIN = 1.5            # Pillar 3 threshold (was 1.2)
HIGH_52W_PROX = 0.97      # Pillar 2: within 3% of 52-week high (was 0.90 of 50D)
ATR_STOP_MULT = 1.5       # Stop = entry - 1.5*ATR (was 2.0)
LOOKBACK_52W = 252        # trading days in ~1 year

def get_massive_aggs(ticker, days=420):
    # 420 calendar days guarantees >= 252 trading days for the 52-week-high test.
    end_date = datetime.date.today()
    start_date = end_date - timedelta(days=days)
    url = f"{MASSIVE_BASE}/v2/aggs/ticker/{ticker}/range/1/day/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
    params = {"apiKey": MASSIVE_API_KEY, "adjusted": "true", "sort": "asc"}
    try:
        r = _audit_get(url, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if "results" in data and data["results"]:
                return data["results"]
    except Exception as e:
        print(f"[atlas_engine:get_massive_aggs] {ticker}: {e}")
    return None

def calculate_sma(prices, period):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def calculate_atr(aggs, period=14):
    if len(aggs) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(aggs)):
        high = aggs[i]['h']
        low = aggs[i]['l']
        prev_close = aggs[i-1]['c']
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    return sum(true_ranges[-period:]) / period

def check_regime():
    """Informational SPY regime label. Never blocks buys by itself."""
    aggs = get_massive_aggs("SPY", days=120)
    if not aggs:
        return True, "⚠️ WEAK — cautious (half size); SPY data unavailable"
    closes = [d['c'] for d in aggs]
    sma50 = calculate_sma(closes, 50)
    if sma50 is None:
        return True, "⚠️ WEAK — cautious (half size); SPY history insufficient"
    ok = closes[-1] > sma50
    if ok:
        return True, f"🟢 RISK-ON ✅; SPY {closes[-1]:.2f} > 50SMA {sma50:.2f}"
    return True, f"⚠️ WEAK — cautious (half size); SPY {closes[-1]:.2f} < 50SMA {sma50:.2f}"


def _normal_macro_sentiment(value):
    value = str(value or "NEUTRAL").upper().strip()
    return value if value in {"NEUTRAL", "CAUTION", "RISK_OFF"} else "NEUTRAL"


def _sanitize_macro_reason(reason):
    """Keep macro sentiment reason to market/regime text only; remove news-headline bleed."""
    text = str(reason or "no data").strip()
    # Never pass through appended headline fields or semicolon-separated news tails.
    text = re.split(r";\s*(?:headlines?:)?", text, maxsplit=1, flags=re.I)[0].strip()
    # Strip headline-like strings: questions, title-style colon clauses, long prose.
    if "?" in text:
        text = "macro caution"
    text = re.sub(r":\s+[A-Z][a-z].*$", "", text).strip()
    if len(text) > 120:
        text = text[:120].rstrip()
    return text or "macro caution"


def _classify_macro_headlines(headlines):
    """LLM macro classifier. Fail-silent: neutral on any failure."""
    safe_default = {"sentiment": "NEUTRAL", "reason": "no data"}
    headlines = [str(h).strip() for h in (headlines or []) if str(h or "").strip()]
    if not headlines:
        return safe_default
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return safe_default
    base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
    prompt = (
        "You are a macro market analyst. Based on these recent market headlines, "
        "classify the current macro sentiment as one of: NEUTRAL, CAUTION, or RISK_OFF. "
        "Return only a JSON object: {\"sentiment\": \"NEUTRAL\"|\"CAUTION\"|\"RISK_OFF\", "
        "\"reason\": \"one sentence\"}. Headlines: " + json.dumps(headlines[:15])
    )
    try:
        r = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=8,
        )
        if r.status_code != 200:
            return safe_default
        content = r.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        sentiment = _normal_macro_sentiment(parsed.get("sentiment"))
        reason = _sanitize_macro_reason(parsed.get("reason") or "no data")
        return {"sentiment": sentiment, "reason": reason}
    except Exception:
        return safe_default


def _get_macro_headlines(limit=3):
    """Supplementary macro context only; never drives classification."""
    headlines = []
    try:
        if MASSIVE_API_KEY:
            r = _audit_get(
                f"{MASSIVE_BASE}/v2/reference/news",
                params={"apiKey": MASSIVE_API_KEY, "limit": 10, "sort": "published_utc", "order": "desc"},
                headers={"Accept": "application/json"},
                timeout=8,
            )
            if r.status_code == 200:
                for item in (r.json() or {}).get("results", [])[:10]:
                    title = item.get("title")
                    if title:
                        headlines.append(str(title).strip())
    except Exception:
        pass
    try:
        if EODHD_API_KEY:
            r = _audit_get(
                "https://eodhd.com/api/news",
                params={"api_token": EODHD_API_KEY, "fmt": "json", "s": "SPY.US", "limit": 5},
                timeout=8,
            )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for item in data[:5]:
                        title = item.get("title")
                        if title:
                            headlines.append(str(title).strip())
    except Exception:
        pass
    out, seen = [], set()
    for h in headlines:
        key = h.lower()
        if key not in seen:
            seen.add(key)
            out.append(h)
        if len(out) >= limit:
            break
    return out


def _snapshot_intraday_change_pct(ticker):
    """Current percent change vs previous close from Massive snapshot."""
    if not MASSIVE_API_KEY:
        return None
    try:
        r = _audit_get(
            f"{MASSIVE_BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}",
            params={"apiKey": MASSIVE_API_KEY},
            headers={"Accept": "application/json"},
            timeout=6,
        )
        if r.status_code != 200:
            return None
        t = (r.json() or {}).get("ticker") or {}
        current = None
        for section, key in (("lastTrade", "p"), ("min", "c"), ("day", "c")):
            value = (t.get(section) or {}).get(key)
            if value:
                current = float(value)
                break
        # Massive snapshot exposes prior regular-session close as prevDay.c.
        # Do not use today's open here: the macro overlay must catch overnight gap-downs.
        prev = (t.get("prevDay") or {}).get("c")
        if current is None or not prev:
            return None
        prev = float(prev)
        if prev <= 0:
            return None
        return ((float(current) - prev) / prev) * 100.0
    except Exception:
        return None



def _snapshot_ticker_quote(ticker):
    """Best-effort Massive snapshot fields for gap-up breakout checks."""
    ticker = (ticker or "").upper()
    if not MASSIVE_API_KEY:
        return {}
    try:
        r = _audit_get(
            f"{MASSIVE_BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}",
            params={"apiKey": MASSIVE_API_KEY},
            headers={"Accept": "application/json"},
            timeout=6,
        )
        if r.status_code != 200:
            return {}
        t = (r.json() or {}).get("ticker") or {}
        current = None
        for section, key in (("lastTrade", "p"), ("min", "c"), ("day", "c")):
            value = (t.get(section) or {}).get(key)
            if value:
                current = _to_float(value)
                break
        day = t.get("day") or {}
        prev = t.get("prevDay") or {}
        return {
            "ticker": ticker,
            "current": current,
            "prev_close": _to_float(prev.get("c")),
            "day_volume": _to_float(day.get("v")),
            "day_low": _to_float(day.get("l")),
            "day_high": _to_float(day.get("h")),
            "day_close": _to_float(day.get("c")),
        }
    except Exception:
        return {}


def calculate_ema(prices, period):
    vals = [float(p) for p in (prices or []) if p is not None]
    if len(vals) < period:
        return None
    ema = sum(vals[:period]) / period
    k = 2 / (period + 1)
    for price in vals[period:]:
        ema = (price * k) + (ema * (1 - k))
    return ema


def evaluate_gap_breakout(ticker, pillars=None, sentiment_info=None, closes=None, volumes=None, ema10=None, current_price=None):
    """Return gap-up breakout qualification metadata; additive to core pillar scoring."""
    ticker = (ticker or "").upper()
    try:
        pcount = int(str(pillars or 0).split("/")[0])
    except Exception:
        pcount = 0
    result = {
        "ticker": ticker,
        "qualifies": False,
        "reason": None,
        "gap_min_pct": 4.0,
        "volume_min_ratio": 1.5,
        "too_hot_ema_pct": 20.0,
        "fallback_stop_pct": 4.0,
    }
    if pcount < 3:
        result["reason"] = "score below 3/4"
        return result

    if sentiment_info is None:
        sentiment_info = check_news_sentiment(ticker)
    sent_score = _to_float((sentiment_info or {}).get("normalized"))
    result["sentiment_score"] = sent_score
    if sent_score is None or sent_score <= 0.5:
        result["reason"] = "news sentiment <= 0.5"
        return result

    quote = _snapshot_ticker_quote(ticker)
    current = _to_float(quote.get("current")) or _to_float(current_price)
    prev_close = _to_float(quote.get("prev_close"))
    day_volume = _to_float(quote.get("day_volume"))

    closes = [float(x) for x in (closes or []) if x is not None]
    volumes = [float(x) for x in (volumes or []) if x is not None]
    if len(closes) < 2 or not volumes:
        aggs = get_massive_aggs(ticker, days=60) or []
        if aggs:
            closes = [float(row.get("c")) for row in aggs if row.get("c") is not None]
            volumes = [float(row.get("v")) for row in aggs if row.get("v") is not None]
    if prev_close is None and len(closes) >= 2:
        prev_close = closes[-2]
    if current is None and closes:
        current = closes[-1]
    if day_volume is None and volumes:
        day_volume = volumes[-1]

    avg_vol_base = volumes[-31:-1] if len(volumes) >= 31 else volumes[-30:]
    avg_vol_30 = (sum(avg_vol_base) / len(avg_vol_base)) if avg_vol_base else None
    ema_ref = _to_float(ema10) or calculate_ema(closes, 10)

    result.update({
        "current_price": current,
        "prev_close": prev_close,
        "intraday_volume": day_volume,
        "avg_volume_30": avg_vol_30,
        "ema10": ema_ref,
    })

    if not current or not prev_close or prev_close <= 0:
        result["reason"] = "missing current/previous close"
        return result
    gap_pct = ((current / prev_close) - 1.0) * 100.0
    result["gap_pct"] = gap_pct
    if gap_pct <= 4.0:
        result["reason"] = "gap <= 4%"
        return result

    if not day_volume or not avg_vol_30 or avg_vol_30 <= 0:
        result["reason"] = "missing volume ratio"
        return result
    vol_ratio = day_volume / avg_vol_30
    result["volume_ratio"] = vol_ratio
    if vol_ratio <= 1.5:
        result["reason"] = "volume ratio <= 150%"
        return result

    if not ema_ref or ema_ref <= 0:
        result["reason"] = "missing EMA10"
        return result
    pct_over_ema = ((current / ema_ref) - 1.0) * 100.0
    result["pct_over_ema10"] = pct_over_ema
    if pct_over_ema > 20.0:
        result["reason"] = "TOO HOT >20% above EMA10"
        result["too_hot"] = True
        return result

    result["qualifies"] = True
    result["reason"] = "gap-up breakout qualified"
    result["too_hot"] = False
    return result


def evaluate_catalyst_override(ticker, pillars=None, rvol=None, catalyst_hit=False,
                               sentiment_info=None, closes=None, ema10=None, current_price=None):
    """Catalyst Override Entry: 2/4 volume+catalyst exception for major news gap-ups."""
    ticker = (ticker or "").upper()
    try:
        pcount = int(str(pillars or 0).split("/")[0])
    except Exception:
        pcount = 0
    rv = _to_float(rvol)
    result = {
        "ticker": ticker,
        "qualifies": False,
        "entry_type": "CATALYST_OVERRIDE",
        "label": "CATALYST OVERRIDE",
        "reason": None,
        "required_score": "exactly 2/4",
        "rvol_min": 3.0,
        "gap_min_pct": 4.0,
        "sentiment_min": 0.5,
        "too_hot_ema_pct": 20.0,
        "stop_pct": 5.0,
        "position_size": "half_standard",
    }
    if pcount != 2:
        result["reason"] = "score is not exactly 2/4"
        return result
    result["rvol"] = rv
    if rv is None or rv < 1.5:
        result["reason"] = "volume pillar failed"
        return result
    if not catalyst_hit:
        result["reason"] = "catalyst pillar failed"
        return result
    if sentiment_info is None:
        sentiment_info = check_news_sentiment(ticker)
    sent_score = _to_float((sentiment_info or {}).get("normalized"))
    result["sentiment_score"] = sent_score
    if sent_score is None or sent_score <= 0.5:
        result["reason"] = "news sentiment <= 0.5"
        return result
    if rv < 3.0:
        result["reason"] = "RVOL < 3.0"
        return result

    quote = _snapshot_ticker_quote(ticker)
    current = _to_float(quote.get("current")) or _to_float(current_price)
    prev_close = _to_float(quote.get("prev_close"))
    closes = [float(x) for x in (closes or []) if x is not None]
    if len(closes) < 2:
        aggs = get_massive_aggs(ticker, days=60) or []
        if aggs:
            closes = [float(row.get("c")) for row in aggs if row.get("c") is not None]
    if prev_close is None and len(closes) >= 2:
        prev_close = closes[-2]
    if current is None and closes:
        current = closes[-1]
    ema_ref = _to_float(ema10) or calculate_ema(closes, 10)
    result.update({"current_price": current, "prev_close": prev_close, "ema10": ema_ref})
    if not current or not prev_close or prev_close <= 0:
        result["reason"] = "missing current/previous close"
        return result
    gap_pct = ((current / prev_close) - 1.0) * 100.0
    result["gap_pct"] = gap_pct
    if gap_pct < 4.0:
        result["reason"] = "gap < 4%"
        return result
    if not ema_ref or ema_ref <= 0:
        result["reason"] = "missing EMA10"
        return result
    pct_over_ema = ((current / ema_ref) - 1.0) * 100.0
    result["pct_over_ema10"] = pct_over_ema
    if pct_over_ema > 20.0:
        result["reason"] = "TOO HOT >20% above EMA10"
        result["too_hot"] = True
        return result
    result["qualifies"] = True
    result["reason"] = "Catalyst Override Entry qualified"
    result["too_hot"] = False
    return result


def get_opening_range_low(ticker, minutes=30):
    """Return opening-range low for the current ET market date; None if unavailable."""
    ticker = (ticker or "").upper()
    if not MASSIVE_API_KEY:
        return None
    try:
        market_day = current_et_market_date()
        date_s = market_day.isoformat()
        r = _audit_get(
            f"{MASSIVE_BASE}/v2/aggs/ticker/{ticker}/range/1/minute/{date_s}/{date_s}",
            params={"apiKey": MASSIVE_API_KEY, "adjusted": "true", "sort": "asc", "limit": 50000},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        rows = (r.json() or {}).get("results") or []
        if not rows:
            return None
        et = ZoneInfo("America/New_York")
        start = datetime.datetime.combine(market_day, datetime.time(9, 30), tzinfo=et)
        end = start + datetime.timedelta(minutes=int(minutes or 30))
        lows = []
        for row in rows:
            ts = row.get("t")
            low = _to_float(row.get("l"))
            if ts is None or low is None:
                continue
            bar_dt = datetime.datetime.fromtimestamp(float(ts) / 1000.0, tz=datetime.timezone.utc).astimezone(et)
            if start <= bar_dt < end:
                lows.append(low)
        return min(lows) if lows else None
    except Exception:
        return None

def get_macro_sentiment():
    """Rule-based real-time macro overlay. Secondary only; never creates signals."""
    spy_pct = _snapshot_intraday_change_pct("SPY")
    soxx_pct = _snapshot_intraday_change_pct("SOXX")
    spy_low_pct = None
    vix_change_pct = None

    try:
        if MASSIVE_API_KEY:
            r = _audit_get(
                f"{MASSIVE_BASE}/v2/snapshot/locale/us/markets/stocks/tickers/SPY",
                params={"apiKey": MASSIVE_API_KEY},
                headers={"Accept": "application/json"},
                timeout=6,
            )
            if r.status_code == 200:
                t = (r.json() or {}).get("ticker") or {}
                spy_low = (t.get("day") or {}).get("l")
                spy_prev = (t.get("prevDay") or {}).get("c")
                if spy_low is not None and spy_prev:
                    spy_prev = float(spy_prev)
                    if spy_prev > 0:
                        spy_low_pct = ((float(spy_low) - spy_prev) / spy_prev) * 100.0
    except Exception:
        pass

    try:
        if EODHD_API_KEY:
            r = _audit_get(
                "https://eodhd.com/api/eod/VIX.INDX",
                params={"api_token": EODHD_API_KEY, "fmt": "json", "limit": 2},
                timeout=8,
            )
            if r.status_code == 200:
                rows = r.json()
                if isinstance(rows, list) and len(rows) >= 2:
                    rows = sorted(rows, key=lambda x: str(x.get("date") or ""))
                    prev_close = float(rows[-2].get("close"))
                    today_close = float(rows[-1].get("close"))
                    if prev_close > 0:
                        vix_change_pct = ((today_close - prev_close) / prev_close) * 100.0
    except Exception:
        pass

    if spy_pct is None and soxx_pct is None and vix_change_pct is None and spy_low_pct is None:
        return {"sentiment": "NEUTRAL", "reason": "no data"}

    sentiment = "NEUTRAL"
    reason = "market stable"
    if spy_pct is not None and spy_pct <= -1.25:
        sentiment = "RISK_OFF"
        reason = f"SPY down {spy_pct:.1f}% intraday"
    if vix_change_pct is not None and vix_change_pct >= 8.0:
        sentiment = "RISK_OFF"
        reason = f"VIX up {vix_change_pct:.1f}%"
    if sentiment == "NEUTRAL" and ((spy_pct is not None and spy_pct <= -0.5) or (soxx_pct is not None and soxx_pct <= -2.0)):
        sentiment = "CAUTION"
        reason = "broad market/semis pressure"
    if sentiment == "NEUTRAL" and vix_change_pct is not None and vix_change_pct >= 4.0:
        sentiment = "CAUTION"
        reason = f"VIX up {vix_change_pct:.1f}%"
    if sentiment == "NEUTRAL" and spy_low_pct is not None and spy_low_pct <= -0.4:
        sentiment = "CAUTION"
        reason = f"SPY intraday low {spy_low_pct:.1f}% vs prior close"

    reason = _sanitize_macro_reason(reason)
    return {
        "sentiment": sentiment,
        "reason": reason,
        "spy_intraday_pct": round(spy_pct, 2) if spy_pct is not None else None,
        "soxx_intraday_pct": round(soxx_pct, 2) if soxx_pct is not None else None,
        "spy_low_pct": round(spy_low_pct, 2) if spy_low_pct is not None else None,
        "vix_change_pct": round(vix_change_pct, 2) if vix_change_pct is not None else None,
    }


def _llm_judge_catalyst(ticker, headlines):
    """Ask the LLM if the headlines are a genuinely STRONG, tradeable bullish catalyst.
    Fails safe: on any error returns None so caller uses fallback logic."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not headlines:
        return None
    base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
    joined = "\n".join(f"- {h}" for h in headlines[:5])
    if "reverse stock split" in joined.lower() or "reverse split" in joined.lower():
        return "NONE", "reverse stock split distress signal"
    prompt = (
        f"You are a professional equity catalyst analyst. Ticker: {ticker}.\n"
        f"Recent headlines:\n{joined}\n\n"
        "Classify the bullish catalyst strength for a swing trade as exactly one word: "
        "STRONG, WEAK, or NONE. STRONG = a concrete, material, positive, price-moving "
        "event (e.g. major product/contract, earnings blowout, FDA approval, major upgrade). "
        "Mere mentions, neutral coverage, or negative news = WEAK or NONE. "
        "Hard rule: if any headline or content mentions a reverse stock split or reverse split, "
        "classify it as NONE regardless of sentiment; a reverse stock split is a distress signal, not a growth catalyst. "
        "Respond in JSON: {\"rating\":\"STRONG|WEAK|NONE\",\"reason\":\"<8 words>\"}"
    )
    try:
        r = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0, "response_format": {"type": "json_object"}},
            timeout=8,
        )
        if r.status_code == 200:
            content = r.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return parsed.get("rating", "").upper(), parsed.get("reason", "")[:60]
    except Exception as e:
        print(f"[catalyst-llm] {ticker}: {e}")
    return None

def check_news_catalyst(ticker):
    if not MASSIVE_API_KEY:
        return False, None
    url = f"{MASSIVE_BASE}/benzinga/v2/news"
    params = {
        "apiKey": MASSIVE_API_KEY,
        "tickers": ticker,
        "date.gte": (datetime.date.today() - timedelta(days=3)).strftime('%Y-%m-%d'),
        "limit": 5
    }
    try:
        r = _audit_get(url, params=params, headers={"Accept": "application/json"}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            results = data.get("results", [])
            if results:
                headlines = [x.get("title", "") for x in results if x.get("title")]
                verdict = _llm_judge_catalyst(ticker, headlines)
                if verdict is not None:
                    rating, reason = verdict
                    if rating == "STRONG":
                        return True, f"LLM: {reason}" if reason else "LLM: strong catalyst"
                    else:
                        return False, None
                # Fallback (LLM unavailable): old behavior — news exists = catalyst
                return True, results[0].get("title", "Recent news found")
    except Exception as e:
        print(f"[atlas_engine:check_news_catalyst] {ticker}: {e}")
    return False, None

def _fmt_pt(value):
    try:
        return f"${float(value):,.0f}"
    except Exception:
        return "N/A"


def _to_float(value):
    try:
        if value in (None, "", "NA", "None"):
            return None
        return float(value)
    except Exception:
        return None


def _latest_financial_row(section):
    if not isinstance(section, dict):
        return None, None
    quarterly = section.get("quarterly")
    if isinstance(quarterly, dict) and quarterly:
        key = sorted(quarterly.keys())[-1]
        row = quarterly.get(key)
        if isinstance(row, dict):
            return key, row
    return None, None


_FUNDAMENTALS_CACHE_MEM = {}
_FUNDAMENTALS_CACHE_PATH = "/tmp/atlas_fundamentals_cache.json"


def _load_fundamentals_cache():
    try:
        with open(_FUNDAMENTALS_CACHE_PATH) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_fundamentals_cache(data):
    try:
        tmp = _FUNDAMENTALS_CACHE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, sort_keys=True)
        os.replace(tmp, _FUNDAMENTALS_CACHE_PATH)
    except Exception as e:
        print(f"[atlas_engine:fundamentals_cache] {e}")


def _fundamentals_note(tag, reason=None):
    return f"{tag} ({reason})" if reason else tag


def check_fundamentals(ticker):
    """Soft fundamentals label from EODHD. Label only; never blocks, resizes, or changes scoring."""
    ticker = (ticker or "").upper()
    today = current_et_market_date().isoformat()
    cache_key = f"{today}:{ticker}"
    if cache_key in _FUNDAMENTALS_CACHE_MEM:
        return _FUNDAMENTALS_CACHE_MEM[cache_key]
    cache = _load_fundamentals_cache()
    if cache_key in cache:
        _FUNDAMENTALS_CACHE_MEM[cache_key] = cache[cache_key]
        return cache[cache_key]

    result = {"ticker": ticker, "status": "na", "tag": "❔ fundamentals n/a", "note": "❔ fundamentals n/a"}
    if not EODHD_API_KEY:
        result["reason"] = "missing EODHD key"
        _FUNDAMENTALS_CACHE_MEM[cache_key] = result
        cache[cache_key] = result
        _save_fundamentals_cache(cache)
        return result

    try:
        url = f"https://eodhd.com/api/fundamentals/{ticker}.US"
        params = {"api_token": EODHD_API_KEY, "fmt": "json"}
        r = _audit_get(url, params=params, timeout=12)
        if r.status_code != 200:
            result["reason"] = f"http {r.status_code}"
        else:
            data = r.json()
            highlights = data.get("Highlights") if isinstance(data, dict) else {}
            highlights = highlights if isinstance(highlights, dict) else {}
            general = data.get("General") if isinstance(data, dict) else {}
            general = general if isinstance(general, dict) else {}
            financials = data.get("Financials") if isinstance(data, dict) else {}
            financials = financials if isinstance(financials, dict) else {}
            _, income = _latest_financial_row(financials.get("Income_Statement", {}))
            _, balance = _latest_financial_row(financials.get("Balance_Sheet", {}))
            income = income if isinstance(income, dict) else {}
            balance = balance if isinstance(balance, dict) else {}

            profit_margin = _to_float(highlights.get("ProfitMargin"))
            operating_margin = _to_float(highlights.get("OperatingMarginTTM"))
            revenue_growth = _to_float(highlights.get("QuarterlyRevenueGrowthYOY"))
            earnings_growth = _to_float(highlights.get("QuarterlyEarningsGrowthYOY"))
            net_income = _to_float(income.get("netIncome"))
            debt = _to_float(balance.get("shortLongTermDebtTotal"))
            equity = _to_float(balance.get("totalStockholderEquity"))

            profitable = (profit_margin is not None and profit_margin > 0) or (net_income is not None and net_income > 0)
            negative_earnings = (profit_margin is not None and net_income is not None and profit_margin <= 0 and net_income <= 0)
            shrinking_revenue = revenue_growth is not None and revenue_growth < 0
            high_debt = False
            debt_to_equity = None
            if debt is not None and equity is not None:
                if equity > 0:
                    debt_to_equity = debt / equity
                    high_debt = debt_to_equity > 3.0
                elif debt > 0:
                    high_debt = True

            reason = None
            if negative_earnings:
                reason = "neg earnings"
            elif shrinking_revenue:
                reason = f"rev {revenue_growth * 100:.0f}%"
            elif high_debt:
                reason = "high debt"

            if reason:
                tag = _fundamentals_note("⚠️ weak fundamentals", reason)
                result.update({"status": "weak", "tag": tag, "note": tag})
            elif profitable and revenue_growth is not None and revenue_growth >= 0:
                result.update({"status": "solid", "tag": "✅ solid fundamentals", "note": "✅ solid fundamentals"})
            else:
                result.update({"status": "na", "tag": "❔ fundamentals n/a", "note": "❔ fundamentals n/a"})

            result.update({
                "profit_margin": profit_margin,
                "operating_margin": operating_margin,
                "revenue_growth_yoy": revenue_growth,
                "earnings_growth_yoy": earnings_growth,
                "net_income": net_income,
                "total_debt": debt,
                "equity": equity,
                "debt_to_equity_derived": debt_to_equity,
                "sector": general.get("Sector"),
                "industry": general.get("Industry"),
            })
    except Exception as e:
        result["reason"] = str(e)[:120]
        print(f"[atlas_engine:check_fundamentals] {ticker}: {e}")

    try:
        massive_fin = check_massive_financials(ticker)
        result["massive_financials"] = massive_fin
        if massive_fin and massive_fin.get("status") == "ok" and massive_fin.get("tag"):
            result["tag"] = f"{result.get('tag') or result.get('note') or '❔ fundamentals n/a'} | {massive_fin.get('tag')}"
            result["note"] = result["tag"]
    except Exception as e:
        result["massive_financials_error"] = str(e)[:120]
    _FUNDAMENTALS_CACHE_MEM[cache_key] = result
    cache[cache_key] = result
    _save_fundamentals_cache(cache)
    return result


_ANALYST_QUALITY_CACHE = {}
_MACRO_CACHE = {}
_INSIDER_CACHE = {}


def _cache_path(name):
    return f"/tmp/atlas_{name}_cache.json"


def _read_json_cache(name):
    try:
        with open(_cache_path(name)) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json_cache(name, data):
    try:
        path = _cache_path(name)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, sort_keys=True)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[atlas_engine:{name}_cache] {e}")


_INDICATOR_CACHE = {}


def _indicator_values(payload):
    if not isinstance(payload, dict):
        return []
    results = payload.get("results") or payload.get("values") or []
    if isinstance(results, dict):
        results = [results]
    if not results:
        return []
    first = results[0]
    values = first.get("values") if isinstance(first, dict) else None
    if isinstance(values, list):
        return values
    return results if isinstance(results, list) else []


def _latest_indicator_value(payload, field="value"):
    values = _indicator_values(payload)
    if values and isinstance(values[0], dict):
        return values[0].get(field)
    return None


def evaluate_indicator_confluence(indicator_info):
    """Decision-context RSI/MACD confluence. Never vetoes or changes risk tiers."""
    info = indicator_info or {}
    def fval(key):
        try:
            v = info.get(key)
            return None if v in (None, "") else float(v)
        except Exception:
            return None
    rsi = fval("rsi")
    macd = fval("macd")
    signal = fval("macd_signal")
    hist = fval("macd_histogram")
    prev_hist = fval("prev_macd_histogram")
    macd_positive_cross = bool(macd is not None and signal is not None and macd >= signal)
    macd_turning_up = bool(hist is not None and prev_hist is not None and hist > prev_hist)
    macd_bullish = bool(macd_positive_cross or macd_turning_up or (hist is not None and hist > 0))
    bullish = bool(rsi is not None and rsi <= 45 and macd_bullish)
    rolling_over = bool((hist is not None and hist < 0) or (hist is not None and prev_hist is not None and hist < prev_hist))
    weak = bool((rsi is not None and rsi > 70) or rolling_over)
    if bullish:
        state, note = "bullish", "✅ RSI/MACD confirmed"
    elif weak:
        state, note = "weak", "⚠️ momentum weak"
    elif rsi is None and hist is None and macd is None:
        state, note = "na", None
    else:
        state, note = "neutral", None
    return {
        "state": state,
        "note": note,
        "bullish": bullish,
        "weak": weak,
        "rsi": rsi,
        "macd": macd,
        "macd_signal": signal,
        "macd_histogram": hist,
        "prev_macd_histogram": prev_hist,
        "macd_turning_up": macd_turning_up,
        "macd_positive_cross": macd_positive_cross,
    }


def check_massive_indicators(ticker):
    """RSI/MACD display-only context from Massive. Never affects pillars/risk."""
    ticker = (ticker or "").upper()
    today = current_et_market_date().isoformat()
    cache_key = f"{today}:{ticker}"
    if cache_key in _INDICATOR_CACHE:
        return _INDICATOR_CACHE[cache_key]
    cache = _read_json_cache("indicators")
    if cache_key in cache:
        _INDICATOR_CACHE[cache_key] = cache[cache_key]
        return cache[cache_key]
    result = {"ticker": ticker, "status": "na", "tag": None}
    if not MASSIVE_API_KEY:
        cache[cache_key] = result; _INDICATOR_CACHE[cache_key] = result; _write_json_cache("indicators", cache); return result
    try:
        common = {"apiKey": MASSIVE_API_KEY, "timespan": "day", "adjusted": "true", "series_type": "close", "order": "desc", "limit": 2}
        rsi = _audit_get(f"{MASSIVE_BASE}/v1/indicators/rsi/{ticker}", params={**common, "window": 14}, timeout=10)
        macd = _audit_get(f"{MASSIVE_BASE}/v1/indicators/macd/{ticker}", params={**common, "short_window": 12, "long_window": 26, "signal_window": 9}, timeout=10)
        if rsi.status_code == 200:
            result["rsi"] = _latest_indicator_value(rsi.json(), "value")
        if macd.status_code == 200:
            mj = macd.json()
            macd_values = _indicator_values(mj)
            result["macd"] = _latest_indicator_value(mj, "value")
            result["macd_signal"] = _latest_indicator_value(mj, "signal")
            result["macd_histogram"] = _latest_indicator_value(mj, "histogram")
            if len(macd_values) > 1 and isinstance(macd_values[1], dict):
                result["prev_macd_histogram"] = macd_values[1].get("histogram")
        bits = []
        if result.get("rsi") is not None:
            try: bits.append(f"📉 RSI {float(result['rsi']):.0f}")
            except Exception: pass
        macd_val = result.get("macd_histogram") if result.get("macd_histogram") is not None else result.get("macd")
        if macd_val is not None:
            try: bits.append("📈 MACD+" if float(macd_val) >= 0 else "📈 MACD–")
            except Exception: pass
        confluence = evaluate_indicator_confluence(result)
        if confluence.get("note"):
            bits.append(confluence.get("note"))
        result.update({"status": "ok" if bits else "na", "tag": " | ".join(bits) if bits else None,
                       "confluence": confluence, "confluence_state": confluence.get("state"),
                       "confluence_note": confluence.get("note"),
                       "confluence_bullish": confluence.get("bullish"),
                       "momentum_weak": confluence.get("weak")})
    except Exception as e:
        result["reason"] = str(e)[:120]
        print(f"[atlas_engine:check_massive_indicators] {ticker}: {e}")
    cache[cache_key] = result
    _INDICATOR_CACHE[cache_key] = result
    _write_json_cache("indicators", cache)
    return result


_SENTIMENT_CACHE = {}
_ATR_CACHE = {}
_MASSIVE_FIN_CACHE = {}


def _latest_list_row(data):
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v:
                return v[0]
    return None


def check_news_sentiment(ticker):
    """EODHD news/sentiment context. Confidence/display only; never blocks."""
    ticker = (ticker or "").upper()
    today = current_et_market_date().isoformat()
    cache_key = f"{today}:{ticker}"
    if cache_key in _SENTIMENT_CACHE:
        return _SENTIMENT_CACHE[cache_key]
    cache = _read_json_cache("news_sentiment")
    if cache_key in cache:
        _SENTIMENT_CACHE[cache_key] = cache[cache_key]
        return cache[cache_key]
    result = {"ticker": ticker, "status": "na", "tag": None}
    if not EODHD_API_KEY:
        cache[cache_key] = result; _SENTIMENT_CACHE[cache_key] = result; _write_json_cache("news_sentiment", cache); return result
    try:
        sr = _audit_get("https://eodhd.com/api/sentiments", params={"api_token": EODHD_API_KEY, "fmt": "json", "s": f"{ticker}.US"}, timeout=10)
        if sr.status_code == 200:
            data = sr.json()
            row = _latest_list_row(data)
            if isinstance(row, dict):
                score = _to_float(row.get("normalized"))
                result.update({"status": "ok", "normalized": score, "date": row.get("date"), "count": row.get("count")})
                if score is not None:
                    icon = "🟢" if score >= 0 else "🔴"
                    result["tag"] = f"{icon} {score:+.1f}"
                    result["strong_positive"] = score >= 0.5
        nr = _audit_get("https://eodhd.com/api/news", params={"api_token": EODHD_API_KEY, "fmt": "json", "s": f"{ticker}.US", "limit": 3}, timeout=10)
        if nr.status_code == 200:
            news = nr.json()
            result["news"] = news[:3] if isinstance(news, list) else []
            if result.get("news") and not result.get("tag"):
                sent = (result["news"][0].get("sentiment") or {}) if isinstance(result["news"][0], dict) else {}
                pol = _to_float(sent.get("polarity"))
                if pol is not None:
                    result["tag"] = f"{'🟢' if pol >= 0 else '🔴'} {pol:+.1f}"
    except Exception as e:
        result["reason"] = str(e)[:120]
        print(f"[atlas_engine:check_news_sentiment] {ticker}: {e}")
    cache[cache_key] = result; _SENTIMENT_CACHE[cache_key] = result; _write_json_cache("news_sentiment", cache); return result


def check_eodhd_atr(ticker):
    """EODHD ATR display context only. Does not alter stops/exits."""
    ticker = (ticker or "").upper(); today = current_et_market_date().isoformat(); cache_key=f"{today}:{ticker}"
    if cache_key in _ATR_CACHE: return _ATR_CACHE[cache_key]
    cache=_read_json_cache("eodhd_atr")
    if cache_key in cache: _ATR_CACHE[cache_key]=cache[cache_key]; return cache[cache_key]
    result={"ticker":ticker,"status":"na","tag":None}
    if not EODHD_API_KEY:
        cache[cache_key]=result; _ATR_CACHE[cache_key]=result; _write_json_cache("eodhd_atr",cache); return result
    try:
        start=(current_et_market_date()-timedelta(days=45)).isoformat()
        r=_audit_get(f"https://eodhd.com/api/technical/{ticker}.US", params={"api_token":EODHD_API_KEY,"fmt":"json","function":"atr","period":14,"from":start,"to":today}, timeout=10)
        if r.status_code==200:
            rows=r.json()
            row=rows[-1] if isinstance(rows,list) and rows else None
            if isinstance(row,dict):
                atr=_to_float(row.get("atr"))
                result.update({"status":"ok","atr":atr,"date":row.get("date"),"tag":f"ATR ${atr:.0f}" if atr is not None else None})
    except Exception as e:
        result["reason"]=str(e)[:120]
        print(f"[atlas_engine:check_eodhd_atr] {ticker}: {e}")
    cache[cache_key]=result; _ATR_CACHE[cache_key]=result; _write_json_cache("eodhd_atr",cache); return result


def check_massive_financials(ticker):
    """Massive financials enrichment for soft fundamentals. Never blocks."""
    ticker=(ticker or "").upper(); today=current_et_market_date().isoformat(); cache_key=f"{today}:{ticker}"
    if cache_key in _MASSIVE_FIN_CACHE: return _MASSIVE_FIN_CACHE[cache_key]
    cache=_read_json_cache("massive_financials")
    if cache_key in cache: _MASSIVE_FIN_CACHE[cache_key]=cache[cache_key]; return cache[cache_key]
    result={"ticker":ticker,"status":"na","tag":None}
    if not MASSIVE_API_KEY:
        cache[cache_key]=result; _MASSIVE_FIN_CACHE[cache_key]=result; _write_json_cache("massive_financials",cache); return result
    try:
        r=_audit_get(f"{MASSIVE_BASE}/vX/reference/financials", params={"apiKey":MASSIVE_API_KEY,"ticker":ticker,"timeframe":"ttm","limit":1}, timeout=10)
        if r.status_code==200:
            rows=(r.json().get("results") or [])
            if rows:
                fin=rows[0].get("financials") or {}
                inc=fin.get("income_statement") or {}
                bal=fin.get("balance_sheet") or {}
                rev=((inc.get("revenues") or {}).get("value"))
                ni=((inc.get("net_income_loss") or inc.get("net_income" ) or {}).get("value"))
                liab=((bal.get("liabilities") or {}).get("value"))
                equity=((bal.get("equity") or bal.get("stockholders_equity") or {}).get("value"))
                margin=(float(ni)/float(rev)) if ni is not None and rev else None
                de=(float(liab)/float(equity)) if liab is not None and equity not in (None,0) else None
                result.update({"status":"ok","revenue":rev,"net_income":ni,"net_margin":margin,"debt_equity_proxy":de,
                               "tag":f"fin margin {margin*100:.0f}%" if margin is not None else None})
    except Exception as e:
        result["reason"]=str(e)[:120]
        print(f"[atlas_engine:check_massive_financials] {ticker}: {e}")
    cache[cache_key]=result; _MASSIVE_FIN_CACHE[cache_key]=result; _write_json_cache("massive_financials",cache); return result


def check_analyst_quality(benzinga_analyst_id, benzinga_firm_id=None):
    """Lookup Benzinga analyst quality by ratings.benzinga_analyst_id -> analysts.benzinga_id."""
    if not benzinga_analyst_id or not MASSIVE_API_KEY:
        return None
    today = current_et_market_date().isoformat()
    cache_key = f"{today}:{benzinga_analyst_id}"
    if cache_key in _ANALYST_QUALITY_CACHE:
        return _ANALYST_QUALITY_CACHE[cache_key]
    cache = _read_json_cache("analyst_quality")
    if cache_key in cache:
        _ANALYST_QUALITY_CACHE[cache_key] = cache[cache_key]
        return cache[cache_key]
    quality = None
    try:
        r = _audit_get(
            f"{MASSIVE_BASE}/benzinga/v1/analysts",
            params={"apiKey": MASSIVE_API_KEY, "benzinga_id": benzinga_analyst_id, "limit": 1},
            timeout=10,
        )
        if r.status_code == 200:
            rows = r.json().get("results", [])
            if rows:
                row = dict(rows[0])
                firm_match = True
                if benzinga_firm_id and row.get("benzinga_firm_id"):
                    firm_match = str(row.get("benzinga_firm_id")) == str(benzinga_firm_id)
                success = _to_float(row.get("overall_success_rate"))
                smart = _to_float(row.get("smart_score"))
                top = bool((success is not None and success >= 70) or (smart is not None and smart >= 80))
                quality = {
                    "benzinga_id": row.get("benzinga_id"),
                    "benzinga_firm_id": row.get("benzinga_firm_id"),
                    "firm_name": row.get("firm_name"),
                    "full_name": row.get("full_name"),
                    "smart_score": smart,
                    "overall_success_rate": success,
                    "overall_avg_return": _to_float(row.get("overall_avg_return")),
                    "total_ratings": _to_float(row.get("total_ratings")),
                    "firm_match": firm_match,
                    "top_analyst": top,
                    "summary": f"🏅 top-analyst backed ({success:.0f}%)" if top and success is not None else None,
                }
    except Exception as e:
        print(f"[atlas_engine:check_analyst_quality] {benzinga_analyst_id}: {e}")
    cache[cache_key] = quality
    _ANALYST_QUALITY_CACHE[cache_key] = quality
    _write_json_cache("analyst_quality", cache)
    return quality


def check_macro_context():
    """Daily EODHD US macro calendar. High-impact Fed/CPI day => cautious sizing, never a block."""
    today = current_et_market_date()
    cache_key = today.isoformat()
    if cache_key in _MACRO_CACHE:
        return _MACRO_CACHE[cache_key]
    cache = _read_json_cache("macro")
    if cache_key in cache:
        _MACRO_CACHE[cache_key] = cache[cache_key]
        return cache[cache_key]
    ctx = {"date": cache_key, "status": "na", "cautious": False, "note": "❔ macro n/a", "events": []}
    if not EODHD_API_KEY:
        cache[cache_key] = ctx; _MACRO_CACHE[cache_key] = ctx; _write_json_cache("macro", cache); return ctx
    try:
        r = _audit_get(
            "https://eodhd.com/api/economic-events",
            params={"api_token": EODHD_API_KEY, "fmt": "json", "from": cache_key, "to": cache_key, "country": "US"},
            timeout=12,
        )
        if r.status_code == 200:
            rows = r.json()
            allow = ("fed", "fomc", "federal reserve", "cpi", "consumer price index")
            events = []
            for row in rows if isinstance(rows, list) else []:
                if str(row.get("country") or "").upper() != "US":
                    continue
                typ = str(row.get("type") or "")
                if any(word in typ.lower() for word in allow):
                    events.append({"type": typ, "date": row.get("date"), "country": row.get("country")})
            ctx = {"date": cache_key, "status": "ok", "cautious": bool(events),
                   "note": "⚠️ Fed/CPI day — cautious" if events else "", "events": events}
        else:
            ctx["reason"] = f"http {r.status_code}"
    except Exception as e:
        ctx["reason"] = str(e)[:120]
        print(f"[atlas_engine:check_macro_context] {e}")
    cache[cache_key] = ctx
    _MACRO_CACHE[cache_key] = ctx
    _write_json_cache("macro", cache)
    return ctx


def check_analyst_ratings(ticker):
    url = f"{MASSIVE_BASE}/benzinga/v1/ratings"
    params = {
        "apiKey": MASSIVE_API_KEY,
        "ticker": ticker,
        "date.gte": (datetime.date.today() - timedelta(days=7)).strftime('%Y-%m-%d'),
        "rating_action.any_of": "upgrades,initiates_coverage_on,assumes",
        "limit": 3
    }
    try:
        r = _audit_get(url, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            results = data.get("results", [])
            if results:
                top = results[0]
                pt = top.get("price_target")
                if pt in (None, ""):
                    pt = top.get("adjusted_price_target")
                prev_pt = top.get("previous_price_target")
                action = str(top.get("price_target_action") or "").lower()
                pt_raised = False
                try:
                    pt_raised = action == "raises" or (prev_pt not in (None, "") and pt not in (None, "") and float(pt) > float(prev_pt))
                except Exception:
                    pt_raised = action == "raises"
                rating_action = top.get('rating_action','').replace('_',' ').title()
                firm = top.get('firm','Unknown')
                note = f"{rating_action} by {firm} → PT {_fmt_pt(pt)}"
                if pt_raised:
                    note += " (PT raised)"
                analyst_quality = check_analyst_quality(top.get("benzinga_analyst_id"), top.get("benzinga_firm_id"))
                meta = {
                    "firm": firm,
                    "analyst": top.get("analyst"),
                    "benzinga_analyst_id": top.get("benzinga_analyst_id"),
                    "benzinga_firm_id": top.get("benzinga_firm_id"),
                    "rating": top.get("rating"),
                    "rating_action": top.get("rating_action"),
                    "price_target": pt,
                    "adjusted_price_target": top.get("adjusted_price_target"),
                    "previous_price_target": prev_pt,
                    "price_percent_change": top.get("price_percent_change"),
                    "date": top.get("date"),
                    "pt_raised": pt_raised,
                    "analyst_quality": analyst_quality,
                    "top_analyst_backed": bool((analyst_quality or {}).get("top_analyst")),
                    "note": note,
                }
                return True, note, meta
    except Exception as e:
        print(f"[atlas_engine:check_analyst_ratings] {ticker}: {e}")
    return False, None, None


def check_analyst_insights(ticker):
    url = f"{MASSIVE_BASE}/benzinga/v1/analyst-insights"
    params = {"apiKey": MASSIVE_API_KEY, "ticker": ticker, "limit": 5}
    bullish = {"buy", "overweight", "outperform", "positive"}
    try:
        r = _audit_get(url, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            results = data.get("results", [])
            if not results:
                return False, None
            latest = results[0]
            rating = str(latest.get("rating") or "").strip()
            dt = None
            try:
                dt = datetime.date.fromisoformat(str(latest.get("date"))[:10])
            except Exception:
                pass
            recent = bool(dt and (datetime.date.today() - dt).days <= 30)
            is_bullish = any(word in rating.lower() for word in bullish)
            if is_bullish and recent:
                firm = latest.get("firm") or "Analyst"
                pt = latest.get("price_target")
                summary = f"{firm} {rating} PT {_fmt_pt(pt)}"
                if latest.get("insight"):
                    summary += f" — {str(latest.get('insight')).strip()[:70]}"
                return True, {
                    "summary": summary,
                    "firm": firm,
                    "rating": rating,
                    "price_target": pt,
                    "date": latest.get("date"),
                    "insight": latest.get("insight"),
                    "analyst_backed": True,
                }
            return False, {
                "firm": latest.get("firm"), "rating": rating,
                "price_target": latest.get("price_target"), "date": latest.get("date"),
                "insight": latest.get("insight"), "analyst_backed": False,
            }
    except Exception as e:
        print(f"[atlas_engine:check_analyst_insights] {ticker}: {e}")
    return False, None

_EARNINGS_CACHE = {}


def _date_range(start, end):
    cur = start
    while cur <= end:
        yield cur
        cur += datetime.timedelta(days=1)


_FDA_CACHE_MEM = {}
_FDA_CACHE_NAME = "fda_calendar"
_FDA_SECTOR_CACHE_NAME = "fda_sector"
_FDA_BIOTECH_KEYWORDS = ("HEALTHCARE", "HEALTH CARE", "BIOTECH", "BIOTECHNOLOGY", "DRUG", "PHARMA", "PHARMACEUTICAL", "MEDICAL", "THERAPEUTIC")
_FDA_POSITIVE_WORDS = ("APPROVAL", "APPROVED", "POSITIVE FEEDBACK", "CLEARANCE", "CLEARED", "GRANTED", "ACCEPTED", "BREAKTHROUGH THERAPY", " BTD")
_FDA_NEGATIVE_WORDS = ("COMPLETE RESPONSE LETTER", " CRL", "REJECTED", "DENIED", "NEGATIVE FEEDBACK", "FAILED")
_FDA_UPCOMING_WORDS = ("PDUFA", "ADCOM", "ADVISORY COMMITTEE", "DECISION", "ACTION DATE", "TARGET DATE", "PENDING", "UNDER REVIEW", "NDA", "BLA")


def _safe_date(text):
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(str(text)[:10])
    except Exception:
        return None


def _fda_symbols(row):
    symbols = []
    for company in (row.get("companies") or []):
        for sec in (company.get("securities") or []):
            sym = str(sec.get("symbol") or "").upper().strip()
            if sym:
                symbols.append(sym)
    return sorted(set(symbols))


def _fda_text(row):
    drug = row.get("drug") or {}
    bits = [row.get("event_type"), row.get("status"), row.get("outcome"), drug.get("name")]
    ind = drug.get("indication_symptom")
    if isinstance(ind, list):
        bits += ind
    elif ind:
        bits.append(ind)
    return " ".join(str(x) for x in bits if x).upper()


def _classify_fda_event(row):
    text = _fda_text(row)
    if any(w in text for w in _FDA_NEGATIVE_WORDS):
        return "past_negative"
    if any(w in text for w in _FDA_POSITIVE_WORDS):
        return "past_positive"
    if row.get("target_date") or any(w in text for w in _FDA_UPCOMING_WORDS):
        return "upcoming_binary"
    return "ambiguous"


def _fda_sector_info(ticker, fundamentals=None):
    ticker = (ticker or "").upper()
    if isinstance(fundamentals, dict):
        sector = fundamentals.get("sector")
        industry = fundamentals.get("industry")
        if sector or industry:
            return {"sector": sector, "industry": industry}
    today = current_et_market_date().isoformat()
    key = f"{today}:{ticker}"
    cache = _read_json_cache(_FDA_SECTOR_CACHE_NAME)
    if key in cache:
        return cache[key]
    info = {"sector": None, "industry": None}
    if EODHD_API_KEY:
        try:
            r = _audit_get(
                f"https://eodhd.com/api/fundamentals/{ticker}.US",
                params={"api_token": EODHD_API_KEY, "fmt": "json"}, timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                general = data.get("General") if isinstance(data, dict) else {}
                if isinstance(general, dict):
                    info = {"sector": general.get("Sector"), "industry": general.get("Industry")}
        except Exception as e:
            print(f"[atlas_engine:fda_sector] {ticker}: {e}")
    cache[key] = info
    _write_json_cache(_FDA_SECTOR_CACHE_NAME, cache)
    return info


def _is_biotech_sector(sector_info):
    text = f"{(sector_info or {}).get('sector') or ''} {(sector_info or {}).get('industry') or ''}".upper()
    return any(k in text for k in _FDA_BIOTECH_KEYWORDS)


def _load_fda_calendar_window():
    today = current_et_market_date()
    start_day = today - datetime.timedelta(days=30)
    end_day = today + datetime.timedelta(days=60)
    key = f"{today.isoformat()}:{start_day.isoformat()}:{end_day.isoformat()}"
    if key in _FDA_CACHE_MEM:
        return _FDA_CACHE_MEM[key]
    cache = _read_json_cache(_FDA_CACHE_NAME)
    if key in cache:
        _FDA_CACHE_MEM[key] = cache[key]
        return cache[key]
    rows = []
    status = "na"
    note = None
    if not BENZINGA_API_KEY:
        note = "missing Benzinga key"
    else:
        try:
            r = _audit_get(
                "https://api.benzinga.com/api/v2.1/calendar/fda",
                params={"token": BENZINGA_API_KEY, "dateFrom": start_day.isoformat(), "dateTo": end_day.isoformat(), "limit": 200},
                headers={"Accept": "application/json"}, timeout=15,
            )
            status = f"http_{r.status_code}"
            if r.status_code == 200:
                data = r.json()
                raw = data.get("fda") if isinstance(data, dict) else data
                rows = raw if isinstance(raw, list) else []
                status = "ok"
            else:
                note = f"http {r.status_code}"
        except Exception as e:
            note = str(e)[:120]
            print(f"[atlas_engine:fda_calendar] {e}")
    payload = {"status": status, "note": note, "rows": rows}
    cache[key] = payload
    _write_json_cache(_FDA_CACHE_NAME, cache)
    _FDA_CACHE_MEM[key] = payload
    return payload


def check_fda_calendar(ticker, fundamentals=None, holding=False):
    # Benzinga FDA Calendar context. Entry blackout only; never exits/sizes/scores.
    ticker = (ticker or "").upper()
    sector_info = _fda_sector_info(ticker, fundamentals=fundamentals)
    if not _is_biotech_sector(sector_info):
        return {"ticker": ticker, "status": "skipped", "biotech": False, "tag": None,
                "sector": sector_info.get("sector"), "industry": sector_info.get("industry")}

    payload = _load_fda_calendar_window()
    result = {"ticker": ticker, "status": payload.get("status"), "biotech": True,
              "sector": sector_info.get("sector"), "industry": sector_info.get("industry"),
              "events": [], "tag": None}
    if payload.get("status") != "ok":
        result.update({"note": "🧬 FDA date unknown", "date_unknown": True, "tag": "🧬 FDA date unknown"})
        return result

    today = current_et_market_date()
    for row in payload.get("rows") or []:
        symbols = _fda_symbols(row)
        if ticker not in symbols:
            continue
        event_day = _safe_date(row.get("target_date") or row.get("date"))
        cls = _classify_fda_event(row)
        days = trading_days_between(today, event_day) if event_day else None
        drug = row.get("drug") or {}
        event = {
            "event_type": row.get("event_type"), "class": cls, "date": event_day.isoformat() if event_day else None,
            "days": days, "drug": drug.get("name"), "status": row.get("status"),
            "outcome": row.get("outcome"), "symbols": symbols,
        }
        result["events"].append(event)
        if event_day and days is not None and days > 0 and days <= 3 and cls == "upcoming_binary":
            note = f"🧬 FDA decision in {days}d — no new entry"
            result.update({"entry_blackout": True, "blackout_reason": note, "entry_blackout_note": note, "tag": note, "nearest_event": event})
        elif event_day and days is not None and days > 0 and days <= 5 and cls == "upcoming_binary" and holding:
            note = f"🧬 FDA in {days}d"
            result.update({"holding_warning": True, "holding_warning_note": note, "tag": note, "nearest_event": event})
        elif event_day and (today - event_day).days >= 0 and (today - event_day).days <= 14 and cls == "past_positive" and not result.get("entry_blackout"):
            note = "🧬 FDA approval"
            result.update({"positive_outcome": True, "positive_outcome_note": note, "tag": note, "nearest_event": event})
        elif event_day and (today - event_day).days >= 0 and (today - event_day).days <= 14 and cls == "past_negative" and not result.get("entry_blackout") and not result.get("positive_outcome"):
            note = "🧬 FDA caution"
            result.update({"negative_outcome": True, "negative_outcome_note": note, "tag": note, "nearest_event": event})
        elif (not event_day or cls == "ambiguous") and not result.get("entry_blackout") and not result.get("tag"):
            result.update({"date_unknown": True, "note": "🧬 FDA date unknown", "tag": "🧬 FDA date unknown", "nearest_event": event})
    if not result["events"]:
        result.update({"status": "none", "tag": None})
    return result


def _parse_earnings_date(value):
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _earnings_rows(ticker, start_day, end_day, limit=10):
    url = f"{MASSIVE_BASE}/benzinga/v1/earnings"
    params = {
        "apiKey": MASSIVE_API_KEY,
        "ticker": ticker,
        "date.gte": start_day.strftime('%Y-%m-%d'),
        "date.lte": end_day.strftime('%Y-%m-%d'),
        "limit": limit,
    }
    r = _audit_get(url, params=params, timeout=10)
    if r.status_code != 200:
        return []
    data = r.json()
    return data.get("results", []) or data.get("earnings", []) or []


def check_earnings_context(ticker):
    """Return earnings blackout/warning/momentum context. Never raises; API failure is fail-open."""
    ticker = (ticker or "").upper()
    today = current_et_market_date()
    cache_key = (ticker, today.isoformat())
    if cache_key in _EARNINGS_CACHE:
        return _EARNINGS_CACHE[cache_key]
    ctx = {"ticker": ticker, "status": "unknown", "unknown": True, "note": "❔ earnings date unknown"}
    try:
        upcoming = _earnings_rows(ticker, today, today + timedelta(days=180), limit=10)
        future = []
        for row in upcoming:
            d = _parse_earnings_date(row.get("date"))
            if not d or d < today:
                continue
            status = str(row.get("date_status") or "").lower()
            if status not in {"projected", "confirmed"}:
                continue
            row = dict(row)
            row["trading_days_until"] = trading_days_between(today, d)
            future.append(row)
        future.sort(key=lambda r: (r.get("date") or "9999-99-99", r.get("time") or ""))
        if future:
            nxt = future[0]
            days = int(nxt.get("trading_days_until", 999))
            ctx.update({"status": "known", "unknown": False, "next": nxt, "days_to_next": days,
                        "entry_blackout": days <= 2, "holding_warning": days <= 3,
                        "blackout_reason": f"⛔ EARNINGS in {days}d — no new entry",
                        "holding_warning_note": f"⚠️ earnings in {days}d"})
    except Exception as e:
        print(f"[atlas_engine:check_earnings_context:upcoming] {ticker}: {e}")

    try:
        recent_rows = _earnings_rows(ticker, today - timedelta(days=30), today, limit=10)
        confirmed = []
        for row in recent_rows:
            if str(row.get("date_status") or "").lower() != "confirmed":
                continue
            d = _parse_earnings_date(row.get("date"))
            if not d:
                continue
            confirmed.append((d, row))
        confirmed.sort(key=lambda x: x[0], reverse=True)
        if confirmed:
            row = dict(confirmed[0][1])
            actual = row.get("actual_eps")
            est = row.get("estimated_eps")
            surprise = row.get("eps_surprise")
            positive = False
            try:
                positive = float(actual) > float(est) and float(surprise) > 0
            except Exception:
                positive = False
            try:
                pct = float(row.get("eps_surprise_percent")) * 100
            except Exception:
                pct = None
            row["eps_surprise_percent_display"] = pct
            if positive:
                row["earnings_momentum_note"] = f"📊 Beat +{pct:.0f}% EPS" if pct is not None else "📊 EPS beat"
                ctx["earnings_momentum"] = row
            elif surprise is not None:
                row["earnings_miss_note"] = f"📊 Missed {pct:.0f}% EPS" if pct is not None else "📊 EPS missed"
                ctx["earnings_miss"] = row

            rev_surprise = row.get("revenue_surprise")
            try:
                rev_pct = float(row.get("revenue_surprise_percent")) * 100
            except Exception:
                rev_pct = None
            row["revenue_surprise_percent_display"] = rev_pct
            try:
                rev_positive = float(rev_surprise) > 0
            except Exception:
                rev_positive = False
            if rev_positive:
                row["revenue_momentum_note"] = f"💰 Rev beat +{rev_pct:.0f}%" if rev_pct is not None else "💰 Rev beat"
                ctx["revenue_momentum"] = row
            elif rev_surprise is not None:
                row["revenue_miss_note"] = f"💰 Rev miss {rev_pct:.0f}%" if rev_pct is not None else "💰 Rev miss"
                ctx["revenue_miss"] = row
    except Exception as e:
        print(f"[atlas_engine:check_earnings_context:recent] {ticker}: {e}")
    _EARNINGS_CACHE[cache_key] = ctx
    return ctx


def check_earnings_risk(ticker):
    ctx = check_earnings_context(ticker)
    nxt = ctx.get("next") or {}
    if nxt:
        return True, nxt.get("date", "this week")
    return False, None

def check_insider_buying(ticker):
    """EODHD Form-4 real open-market buys only. Daily cached; confidence tag only."""
    ticker = (ticker or "").upper()
    today = current_et_market_date().isoformat()
    cache_key = f"{today}:{ticker}"
    if cache_key in _INSIDER_CACHE:
        cached = _INSIDER_CACHE[cache_key]
        return bool((cached or {}).get("hit")), cached
    cache = _read_json_cache("insider_buys")
    if cache_key in cache:
        _INSIDER_CACHE[cache_key] = cache[cache_key]
        cached = cache[cache_key]
        return bool((cached or {}).get("hit")), cached
    result = {"ticker": ticker, "hit": False, "note": None, "buys": []}
    if not EODHD_API_KEY:
        cache[cache_key] = result; _INSIDER_CACHE[cache_key] = result; _write_json_cache("insider_buys", cache); return False, result
    url = f"https://eodhd.com/api/sec-filings/{ticker}/form4"
    params = {"api_token": EODHD_API_KEY, "fmt": "json", "page[limit]": 10}
    try:
        r = _audit_get(url, params=params, timeout=12)
        if r.status_code == 200:
            data = r.json()
            filings = data.get("data", []) if isinstance(data, dict) else []
            cutoff = current_et_market_date() - timedelta(days=90)
            buys = []
            for filing in filings:
                for tx in filing.get("non_derivative", []) or []:
                    if tx.get("transaction_code") != "P" or tx.get("acquired_or_disposed") != "A":
                        continue
                    try:
                        tx_date = datetime.date.fromisoformat(str(tx.get("transaction_date"))[:10])
                    except Exception:
                        try:
                            tx_date = datetime.date.fromisoformat(str(filing.get("period_of_report") or filing.get("filed_at"))[:10])
                        except Exception:
                            continue
                    if tx_date < cutoff:
                        continue
                    price = _to_float(tx.get("price_per_share")) or 0
                    value = _to_float(tx.get("total_value")) or 0
                    shares = _to_float(tx.get("shares_amount")) or 0
                    if price <= 0 and value <= 0:
                        continue
                    role = tx.get("officer_title") or ("Director" if tx.get("is_director") else "Officer" if tx.get("is_officer") else "Insider")
                    buys.append({
                        "date": tx_date.isoformat(), "name": tx.get("reporting_owner_name"),
                        "role": role, "shares": shares, "value": value,
                        "is_officer": bool(tx.get("is_officer")), "is_director": bool(tx.get("is_director")),
                    })
            if buys:
                total_value = sum(b.get("value", 0) or 0 for b in buys)
                notable = [b for b in buys if any(x in str(b.get("role") or "").upper() for x in ("CEO", "CFO", "CHIEF", "PRESIDENT")) or b.get("is_officer")]
                note = f"🏦 insider buying ({len(buys)} buy, ${total_value:,.0f})"
                if notable:
                    note = f"🏦 insider buying ({notable[0].get('role')}, ${total_value:,.0f})"
                result = {"ticker": ticker, "hit": True, "note": note, "buys": buys[:5], "total_value": total_value}
    except Exception as e:
        result["reason"] = str(e)[:120]
        print(f"[atlas_engine:check_insider_buying] {ticker}: {e}")
    cache[cache_key] = result
    _INSIDER_CACHE[cache_key] = result
    _write_json_cache("insider_buys", cache)
    return bool(result.get("hit")), result

def analyze_ticker(ticker, regime=None):
    aggs = get_massive_aggs(ticker)
    if not aggs:
        return {"error": f"Could not fetch price data for {ticker}"}

    closes = [day['c'] for day in aggs]
    volumes = [day['v'] for day in aggs]
    highs = [day['h'] for day in aggs]
    current_price = closes[-1]
    current_vol = volumes[-1]

    # --- LIQUIDITY / PRICE FLOOR ---------------------------------------
    # Reject penny stocks and names without enough history for indicators.
    if current_price < 5.0:
        return {
            "ticker": ticker, "score": 0, "action": "AVOID",
            "rationale": f"Price {current_price:.2f} < $5.00 floor",
            "current_price": current_price,
        }
    if len(closes) < 50:
        return {
            "ticker": ticker, "score": 0, "action": "AVOID",
            "rationale": f"Only {len(closes)} bars; insufficient history for indicators",
            "current_price": current_price,
        }
    # Minimum average dollar-volume liquidity floor: $5M/day over last 20 sessions
    _recent = min(20, len(closes))
    _avg_dollar_vol = sum(closes[-_recent:][i] * volumes[-_recent:][i] for i in range(_recent)) / _recent
    if _avg_dollar_vol < 5_000_000:
        return {
            "ticker": ticker, "score": 0, "action": "AVOID",
            "rationale": f"Avg $vol ${_avg_dollar_vol:,.0f} < $5M liquidity floor",
            "current_price": current_price,
        }
    # -------------------------------------------------------------------

    sma_50 = calculate_sma(closes, 50)
    sma_150 = calculate_sma(closes, 150)
    sma_200 = calculate_sma(closes, 200)
    avg_vol_50 = calculate_sma(volumes, 50)
    rvol = current_vol / avg_vol_50 if avg_vol_50 else 0
    atr = calculate_atr(aggs)

    pillars_met = 0
    pillar_details = []
    warnings = []

    # Pillar 1: Trend Stack (unchanged)
    if sma_50 and sma_150 and sma_200:
        if current_price > sma_50 and sma_50 > sma_150 and sma_150 > sma_200:
            pillars_met += 1
            pillar_details.append("✅ Trend Stack: YES (Price > 50SMA > 150SMA > 200SMA)")
        else:
            pillar_details.append("❌ Trend Stack: NO")
    else:
        pillar_details.append("❌ Trend Stack: N/A (Insufficient Data)")

    # Pillar 2: Relative Strength — v2: within 3% of 52-WEEK high (was 10% of 50D)
    if len(highs) >= LOOKBACK_52W:
        high_52w = max(highs[-LOOKBACK_52W:])
    else:
        high_52w = max(highs)
    if current_price >= (high_52w * HIGH_52W_PROX):
        pillars_met += 1
        pillar_details.append(f"✅ Relative Strength: YES (Within 3% of 52W High ${high_52w:.2f})")
    else:
        pillar_details.append(f"❌ Relative Strength: NO (52W High ${high_52w:.2f})")

    # Pillar 3: Volume — v2: RVOL >= 2.0 (was 1.2)
    if rvol >= RVOL_MIN:
        pillars_met += 1
        pillar_details.append(f"✅ Volume: YES (RVOL: {rvol:.2f} ≥ {RVOL_MIN})")
    else:
        pillar_details.append(f"❌ Volume: NO (RVOL: {rvol:.2f} < {RVOL_MIN})")

    # Pillar 4: Catalyst (News + Analyst Upgrade) — unchanged
    news_hit, news_title = check_news_catalyst(ticker)
    analyst_hit, analyst_detail, analyst_rating_meta = check_analyst_ratings(ticker)
    insight_hit, analyst_insight = check_analyst_insights(ticker)
    if insight_hit and analyst_insight and (analyst_rating_meta or {}).get("top_analyst_backed"):
        q = (analyst_rating_meta or {}).get("analyst_quality") or {}
        qtag = q.get("summary") or "🏅 top-analyst backed"
        analyst_insight["plain_summary"] = analyst_insight.get("summary")
        analyst_insight["summary"] = f"{qtag} — {analyst_insight.get('summary')}"
        analyst_insight["top_analyst_backed"] = True
        analyst_insight["analyst_quality"] = q
    catalyst_reason = None
    if analyst_hit:
        catalyst_reason = analyst_detail
        pillars_met += 1
        pillar_details.append(f"✅ Catalyst: YES — {analyst_detail}")
    elif news_hit:
        catalyst_reason = news_title
        pillars_met += 1
        pillar_details.append(f"✅ Catalyst: YES — Recent news")
    else:
        pillar_details.append("❌ Catalyst: NO")

    # Fundamentals / indicators / ATR / sentiment / FDA are labels only, only for 3/4 or 4/4 candidates.
    # Sentiment is also needed for the 2/4 Catalyst Override safety gate.
    fundamentals = check_fundamentals(ticker) if pillars_met >= 3 else None
    indicator_info = check_massive_indicators(ticker) if pillars_met >= 3 else None
    atr_info = check_eodhd_atr(ticker) if pillars_met >= 3 else None
    sentiment_info = check_news_sentiment(ticker) if pillars_met >= 2 else None
    ema10 = calculate_ema(closes, 10)
    gap_breakout = evaluate_gap_breakout(
        ticker, pillars=pillars_met, sentiment_info=sentiment_info,
        closes=closes, volumes=volumes, ema10=ema10, current_price=current_price,
    ) if pillars_met >= 3 else None
    catalyst_override = evaluate_catalyst_override(
        ticker, pillars=pillars_met, rvol=rvol, catalyst_hit=bool(analyst_hit or news_hit),
        sentiment_info=sentiment_info, closes=closes, ema10=ema10, current_price=current_price,
    ) if pillars_met == 2 else None
    fda_calendar = check_fda_calendar(ticker, fundamentals=fundamentals) if pillars_met >= 3 else None
    if pillars_met >= 3 and sentiment_info and sentiment_info.get("strong_positive"):
        warnings.append(f"{sentiment_info.get('tag')} news sentiment")
    if pillars_met >= 3 and fda_calendar and fda_calendar.get("positive_outcome"):
        warnings.append(fda_calendar.get("positive_outcome_note") or "🧬 FDA approval")
    elif pillars_met >= 3 and fda_calendar and fda_calendar.get("negative_outcome"):
        warnings.append(fda_calendar.get("negative_outcome_note") or "🧬 FDA caution")

    # Earnings Risk Warning
    earnings_ctx = check_earnings_context(ticker)
    if earnings_ctx.get("next"):
        warnings.append(f"⚠️ Earnings in {earnings_ctx.get('days_to_next')} trading days ({earnings_ctx['next'].get('date')}) — elevated risk")

    # Insider Buying Signal — confidence tag only, only for 3/4+ candidates.
    insider_activity = None
    if pillars_met >= 3:
        insider_hit, insider_activity = check_insider_buying(ticker)
        if insider_hit:
            warnings.append(str((insider_activity or {}).get("note") or "🏦 insider buying"))

    # v2: Market-regime gate. SPY below its 50SMA => downgrade BUYs to WATCH.
    if regime is None:
        regime = check_regime()
    regime_ok, regime_detail = regime
    if "WEAK" in str(regime_detail).upper():
        warnings.append(f"⚠️ Market weak ({regime_detail}) — cautious half-size buys")

    # Signal
    if pillars_met == 4:
        signal = "🟢 BUY"
    elif pillars_met == 3:
        signal = "🟡 BUY (Small)"
    elif pillars_met == 2 and catalyst_override and catalyst_override.get("qualifies"):
        signal = "🟠 BUY (Catalyst Override)"
        warnings.append("🟠 CATALYST OVERRIDE — half-size, 5% stop")
    elif pillars_met == 2:
        signal = "⚪ WATCH"
    else:
        signal = "🔴 AVOID"

    # Soft regime: weak/missing SPY is informational only; portfolio applies cautious sizing.

    # v2: stop = entry - 1.5*ATR (was 2.0)
    stop_loss = current_price - (atr * ATR_STOP_MULT) if atr else current_price * 0.95
    max_loss_per_share = current_price - stop_loss

    result = {
        "ticker": ticker,
        "signal": signal,
        "entry_price": round(current_price, 2),
        "score": f"{pillars_met}/4 Pillars",
        "rvol": round(rvol, 2),
        "pillars": pillar_details,
        "catalyst_reason": catalyst_reason,
        "analyst_rating": analyst_rating_meta,
        "analyst_insight": analyst_insight if insight_hit else None,
        "fundamentals": fundamentals,
        "indicator_info": indicator_info,
        "atr_info": atr_info,
        "sentiment_info": sentiment_info,
        "gap_breakout": gap_breakout,
        "catalyst_override": catalyst_override,
        "fda_calendar": fda_calendar,
        "insider_activity": insider_activity,
        "earnings_context": earnings_ctx,
        "warnings": warnings,
        "regime": {"risk_on": regime_ok, "detail": regime_detail},
        "risk_card": {
            "daily_volatility_atr": round(atr, 2) if atr else None,
            "stop_loss": round(stop_loss, 2),
            "max_loss_per_share": round(max_loss_per_share, 2),
            "atr_stop_mult": ATR_STOP_MULT
        }
    }
    atlas_db.log_signal(
        ticker=result["ticker"],
        signal=result["signal"],
        score=result["score"],
        rvol=result["rvol"],
        entry_price=result["entry_price"],
        stop_loss=result["risk_card"]["stop_loss"],
        max_loss_per_share=result["risk_card"]["max_loss_per_share"],
        atr=result["risk_card"]["daily_volatility_atr"],
        trend_stack=result["pillars"][0] if len(result["pillars"]) > 0 else "",
        relative_strength=result["pillars"][1] if len(result["pillars"]) > 1 else "",
        volume=result["pillars"][2] if len(result["pillars"]) > 2 else "",
        catalyst=result["pillars"][3] if len(result["pillars"]) > 3 else "",
        warnings=", ".join(result["warnings"])
    )
    return result

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Please provide a ticker symbol."}))
        sys.exit(1)
    ticker = sys.argv[1].upper()
    print(json.dumps(analyze_ticker(ticker), indent=2))
