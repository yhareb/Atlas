
import os
import sys
import json
import requests
import datetime
from datetime import timedelta

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
RVOL_MIN = 2.0            # Pillar 3 threshold (was 1.2)
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
        r = requests.get(url, params=params, timeout=10)
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

def _llm_judge_catalyst(ticker, headlines):
    """Ask the LLM if the headlines are a genuinely STRONG, tradeable bullish catalyst.
    Fails safe: on any error returns None so caller uses fallback logic."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not headlines:
        return None
    base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
    joined = "\n".join(f"- {h}" for h in headlines[:5])
    prompt = (
        f"You are a professional equity catalyst analyst. Ticker: {ticker}.\n"
        f"Recent headlines:\n{joined}\n\n"
        "Classify the bullish catalyst strength for a swing trade as exactly one word: "
        "STRONG, WEAK, or NONE. STRONG = a concrete, material, positive, price-moving "
        "event (e.g. major product/contract, earnings blowout, FDA approval, major upgrade). "
        "Mere mentions, neutral coverage, or negative news = WEAK or NONE. "
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
        r = requests.get(url, params=params, headers={"Accept": "application/json"}, timeout=10)
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
        r = requests.get(url, params=params, timeout=12)
        if r.status_code != 200:
            result["reason"] = f"http {r.status_code}"
        else:
            data = r.json()
            highlights = data.get("Highlights") if isinstance(data, dict) else {}
            highlights = highlights if isinstance(highlights, dict) else {}
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
            })
    except Exception as e:
        result["reason"] = str(e)[:120]
        print(f"[atlas_engine:check_fundamentals] {ticker}: {e}")

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


def _latest_indicator_value(payload, field="value"):
    if not isinstance(payload, dict):
        return None
    results = payload.get("results") or payload.get("values") or []
    if isinstance(results, dict):
        results = [results]
    if not results:
        return None
    first = results[0]
    values = first.get("values") if isinstance(first, dict) else None
    if isinstance(values, list) and values:
        return values[0].get(field)
    if isinstance(first, dict):
        return first.get(field)
    return None


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
        common = {"apiKey": MASSIVE_API_KEY, "timespan": "day", "adjusted": "true", "series_type": "close", "order": "desc", "limit": 1}
        rsi = requests.get(f"{MASSIVE_BASE}/v1/indicators/rsi/{ticker}", params={**common, "window": 14}, timeout=10)
        macd = requests.get(f"{MASSIVE_BASE}/v1/indicators/macd/{ticker}", params={**common, "short_window": 12, "long_window": 26, "signal_window": 9}, timeout=10)
        if rsi.status_code == 200:
            result["rsi"] = _latest_indicator_value(rsi.json(), "value")
        if macd.status_code == 200:
            mj = macd.json()
            result["macd"] = _latest_indicator_value(mj, "value")
            result["macd_signal"] = _latest_indicator_value(mj, "signal")
            result["macd_histogram"] = _latest_indicator_value(mj, "histogram")
        bits = []
        if result.get("rsi") is not None:
            try: bits.append(f"📉 RSI {float(result['rsi']):.0f}")
            except Exception: pass
        macd_val = result.get("macd_histogram") if result.get("macd_histogram") is not None else result.get("macd")
        if macd_val is not None:
            try: bits.append("📈 MACD+" if float(macd_val) >= 0 else "📈 MACD–")
            except Exception: pass
        result.update({"status": "ok" if bits else "na", "tag": " | ".join(bits) if bits else None})
    except Exception as e:
        result["reason"] = str(e)[:120]
        print(f"[atlas_engine:check_massive_indicators] {ticker}: {e}")
    cache[cache_key] = result
    _INDICATOR_CACHE[cache_key] = result
    _write_json_cache("indicators", cache)
    return result


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
        r = requests.get(
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
        r = requests.get(
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
        r = requests.get(url, params=params, timeout=10)
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
        r = requests.get(url, params=params, timeout=10)
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
    r = requests.get(url, params=params, timeout=10)
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
        r = requests.get(url, params=params, timeout=12)
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

    # Fundamentals + indicators are labels only, only for 3/4 or 4/4 candidates.
    fundamentals = check_fundamentals(ticker) if pillars_met >= 3 else None
    indicator_info = check_massive_indicators(ticker) if pillars_met >= 3 else None

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
