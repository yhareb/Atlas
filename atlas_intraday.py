import os, sys, datetime, contextlib, io, re, time, errno, signal, threading, subprocess, sqlite3, json
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import requests
from atlas_notify import send_telegram, _admin_chat_id as _owner_chat_id
try:
    import atlas_stream
except Exception:
    atlas_stream = None

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

SCRIPTS_DIR = os.environ.get("ATLAS_SCRIPTS_DIR") or os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
import atlas_db
try:
    import atlas_rag
except Exception:
    atlas_rag = None
try:
    from atlas_perme_engine_packet import load_valid_packets as _load_engine_packets, render_report_annotations as _render_engine_packet_annotations
except Exception:
    _load_engine_packets = None
    _render_engine_packet_annotations = None

try:
    from atlas_rag_flags import annotation_for_ticker, normalize_flags
except Exception:
    annotation_for_ticker = None
    def normalize_flags(flags):
        return [str(f or "").strip().upper() for f in (flags or []) if str(f or "").strip()]
if not hasattr(atlas_db, "get_max_signal_id"):
    def _get_max_signal_id_fallback():
        conn = atlas_db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(id) FROM signals")
        row = cursor.fetchone()
        conn.close()
        return int(row[0] or 0)
    atlas_db.get_max_signal_id = _get_max_signal_id_fallback
if os.environ.get("ATLAS_STAGING_DB") or os.environ.get("ATLAS_DB"):
    atlas_db.DB_PATH = os.environ.get("ATLAS_STAGING_DB") or os.environ.get("ATLAS_DB")
from atlas_symbol_meta import ticker_label
from atlas_schemas import AtlasSignal, AtlasTrade
from atlas_report_blocks import holding_block, pullback_block, watch_list_block
from atlas_intraday_advisory import (advise as _advise_intraday, build_advisory_routing,
    naturalize as _naturalize_report, regime as _advisory_regime, signal_family)
from atlas_profit_protection_advisory import render_profit_protection_cards
try:
    from atlas_profit_protection_v2 import render_report_block_from_snapshot as _render_profit_protection_v2_block
except Exception:
    _render_profit_protection_v2_block = None
from atlas_report_authority import render_pending_broker_confirmation as _shared_pending_broker_confirmation_block, SOURCE_DB, SOURCE_TFE, SOURCE_BROKER, SOURCE_LEDGER, SOURCE_PROVIDER, SOURCE_CACHE, SOURCE_FALLBACK, SOURCE_RENDER_CALC, resolve_price_authority, valuation_excluded_tickers
_ALERT_COOLDOWN: dict = {}  # ticker -> {"ts": float, "dist": float} — cooldown state for proactive DM

_ENV_PATH = os.path.expanduser("~/.hermes/profiles/atlas/.env")
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                if not os.environ.get(_k.strip()):
                    os.environ[_k.strip()] = _v.strip()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_ALLOWED_USERS") or os.environ.get("TELEGRAM_HOME_CHANNEL")

def _env_int(name):
    try:
        value = os.environ.get(name)
        return int(value) if value not in (None, "") else None
    except Exception:
        return None


def _reports_group_chat_id():
    return os.environ.get("ATLAS_REPORTS_GROUP_CHAT_ID")


def _interday_thread_id():
    return _env_int("ATLAS_TOPIC_INTERDAY_THREAD_ID")

ET_TZ = ZoneInfo("America/New_York")
MARKET_OPEN_ET = datetime.time(9, 30)
MARKET_CLOSE_ET = datetime.time(16, 0)


LOCK_PATH = "/tmp/atlas_intraday.lock"
RVOL_DISPLAY_THRESHOLD = 1.5
BUY_NOW_MAX_SIGNAL_AGE_MINUTES = 35
STAGING_LOCK_PATH = "/tmp/atlas_intraday_staging.lock"
MAX_INTRADAY_RUNTIME_SECONDS = int(os.environ.get("ATLAS_INTRADAY_MAX_RUNTIME_SECONDS", "540"))


def _hard_timeout_handler(signum, frame):
    try:
        print(f"[intraday] HARD TIMEOUT after {MAX_INTRADAY_RUNTIME_SECONDS}s; status Telegram suppressed; exiting so launchd can run next cycle.", flush=True)
        # Status/heartbeat Telegram intentionally disabled: hard-timeout timing logic preserved.
        time.sleep(2)
    except Exception as e:
        print(f"[intraday] hard-timeout status failed: {e}", flush=True)
    raise SystemExit(124)


signal.signal(signal.SIGALRM, _hard_timeout_handler)


def _pid_running(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _acquire_run_lock():
    """Atomic PID-file guard. Returns fd if acquired; None if another run is active."""
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, str(os.getpid()).encode())
        return fd
    except FileExistsError:
        try:
            existing = open(LOCK_PATH).read().strip()
            if existing and not _pid_running(existing):
                os.unlink(LOCK_PATH)
                fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                os.write(fd, str(os.getpid()).encode())
                return fd
        except Exception:
            pass
        return None


def _release_run_lock(fd):
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        os.unlink(LOCK_PATH)
    except FileNotFoundError:
        pass


def _observed(day):
    if day.weekday() == 5:  # Saturday holiday observed Friday
        return day - datetime.timedelta(days=1)
    if day.weekday() == 6:  # Sunday holiday observed Monday
        return day + datetime.timedelta(days=1)
    return day


def _nth_weekday(year, month, weekday, n):
    day = datetime.date(year, month, 1)
    while day.weekday() != weekday:
        day += datetime.timedelta(days=1)
    return day + datetime.timedelta(days=7 * (n - 1))


def _last_weekday(year, month, weekday):
    day = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    while day.weekday() != weekday:
        day -= datetime.timedelta(days=1)
    return day


def _easter_date(year):
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return datetime.date(year, month, day)


def _us_market_holidays(year):
    """NYSE regular-session full holidays for market-hours gating."""
    return {
        _observed(datetime.date(year, 1, 1)),                         # New Year's Day
        _nth_weekday(year, 1, 0, 3),                                  # MLK Day
        _nth_weekday(year, 2, 0, 3),                                  # Presidents Day
        _easter_date(year) - datetime.timedelta(days=2),              # Good Friday
        _last_weekday(year, 5, 0),                                    # Memorial Day
        _observed(datetime.date(year, 6, 19)),                        # Juneteenth
        _observed(datetime.date(year, 7, 4)),                         # Independence Day
        _nth_weekday(year, 9, 0, 1),                                  # Labor Day
        _nth_weekday(year, 11, 3, 4),                                 # Thanksgiving
        _observed(datetime.date(year, 12, 25)),                       # Christmas
    }


def is_market_hours(now=None):
    """True only during US regular market hours, evaluated in America/New_York."""
    now_et = (now.astimezone(ET_TZ) if now else datetime.datetime.now(ET_TZ))
    if now_et.weekday() >= 5:
        return False, f"outside market hours — weekend ({now_et:%a %Y-%m-%d %H:%M %Z})"
    if now_et.date() in _us_market_holidays(now_et.year):
        return False, f"outside market hours — US market holiday ({now_et:%Y-%m-%d})"
    if not (MARKET_OPEN_ET <= now_et.time() <= MARKET_CLOSE_ET):
        return False, f"outside market hours — {now_et:%H:%M %Z}; regular session 09:30-16:00 ET"
    return True, f"market hours — {now_et:%a %Y-%m-%d %H:%M %Z}"


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _whole(value):
    return f"${_num(value):,.0f}"


def _pct(value):
    return f"{_num(value):+.0f}%"


def _stars(score):
    n = _pillar_num(score)
    return "⭐" * max(n, 0)


def _pillar_num(score):
    try:
        return int(str(score or "0/4").split("/")[0])
    except Exception:
        return 0


def _ordinal(n):
    nums = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣"}
    return nums.get(n, f"{n}.")


def _short_reason(reason):
    text = re.sub(r"\s+", " ", str(reason or "")).strip()
    text = text.replace("2R target", "target")
    text = text.replace("Persisted stop", "stop")
    if len(text) > 95:
        text = text[:92].rstrip() + "..."
    return text or "Atlas entry rule cleared"


def _unique(items, key="ticker"):
    out, seen = [], set()
    for item in items or []:
        t = str(item.get(key) or item.get("symbol") or "").upper()
        if not t or t in {"SPY", "QQQ", "DIA"} or t in seen:
            continue
        seen.add(t)
        out.append(item)
    return out


def _ticker_label(ticker, item=None):
    return ticker_label(ticker, item=item)


def _market_line(summary):
    macro = summary.get("macro_context") or {}
    detail = str(summary.get("regime_detail") or "")
    m = re.search(r"SPY\s+([0-9.]+)", detail)
    spy = _whole(m.group(1)) if m else "$?"
    if "WEAK" in detail.upper() or "UNKNOWN" in detail.upper() or "UNAVAILABLE" in detail.upper():
        label = "⚠️ WEAK — cautious (half size)"
    elif summary.get("regime_ok"):
        label = "🟢 RISK-ON ✅"
    else:
        label = "⚠️ WEAK — cautious (half size)"
    macro_note = f" | {macro.get('note')}" if isinstance(macro, dict) and macro.get("cautious") else ""
    return f"📡 Market: {label} (SPY {spy}){macro_note}"


def _analyst_tag(item):
    insight = item.get("analyst_insight") or {}
    rating = item.get("analyst_rating") or {}
    tag = insight.get("summary") if isinstance(insight, dict) else None
    if not tag and isinstance(rating, dict) and rating.get("pt_raised"):
        tag = rating.get("note")
    if not tag and isinstance(rating, dict) and rating.get("note"):
        tag = rating.get("note")
    return _short_reason(tag) if tag else None


def _insider_tag(item):
    insider = item.get("insider_activity") or {}
    if isinstance(insider, dict) and insider.get("hit"):
        return insider.get("note") or "🏦 insider buying"
    return None


def _macro_tag(item):
    macro = item.get("macro_context") or {}
    if isinstance(macro, dict) and macro.get("cautious"):
        return macro.get("note") or "⚠️ Fed/CPI day — cautious"
    return None


def _sentiment_tag(item):
    sent = item.get("sentiment_info") or {}
    if isinstance(sent, dict):
        return sent.get("tag")
    return None


def _atr_tag(item):
    atr = item.get("atr_info") or {}
    if isinstance(atr, dict):
        return atr.get("tag")
    return None


def _indicator_tag(item):
    ind = item.get("indicator_info") or {}
    tag = ind.get("tag") if isinstance(ind, dict) else None
    conf = item.get("indicator_confluence") or (ind.get("confluence") if isinstance(ind, dict) else {}) or {}
    note = item.get("confluence_note") or (conf.get("note") if isinstance(conf, dict) else None)
    if tag and note and note not in tag:
        return f"{tag} | {note}"
    return tag or note


def _fundamentals_tag(item):
    fundamentals = item.get("fundamentals") or {}
    if isinstance(fundamentals, dict):
        return fundamentals.get("tag") or fundamentals.get("note")
    if fundamentals:
        return str(fundamentals)
    return None


def _fda_tag(item):
    fda = item.get("fda_calendar") or {}
    if isinstance(fda, dict):
        return (item.get("fda_warning") or item.get("fda_note") or fda.get("entry_blackout_note")
                or fda.get("holding_warning_note") or fda.get("positive_outcome_note")
                or fda.get("negative_outcome_note") or fda.get("tag"))
    return item.get("fda_note")


def _earnings_tag(item):
    note = item.get("earnings_warning") or item.get("earnings_note")
    ctx = item.get("earnings_context") or {}
    if isinstance(ctx, dict):
        if ctx.get("entry_blackout"):
            return ctx.get("blackout_reason")
        if ctx.get("holding_warning"):
            return ctx.get("holding_warning_note")
        bits = []
        if ctx.get("earnings_momentum"):
            bits.append(ctx["earnings_momentum"].get("earnings_momentum_note"))
        if ctx.get("earnings_miss"):
            bits.append(ctx["earnings_miss"].get("earnings_miss_note"))
        if ctx.get("revenue_momentum"):
            bits.append(ctx["revenue_momentum"].get("revenue_momentum_note"))
        if ctx.get("revenue_miss"):
            bits.append(ctx["revenue_miss"].get("revenue_miss_note"))
        bits = [b for b in bits if b]
        if bits:
            return _short_reason(" | ".join(bits))
        if ctx.get("unknown"):
            return ctx.get("note")
    if note:
        return _short_reason(note)
    return None



def _price(value):
    if value in (None, ""):
        return "N/A"
    return f"${_num(value):,.2f}"


def _money(value):
    if value in (None, ""):
        return "N/A"
    return f"${_num(value):,.0f}"


def _signed_money(value):
    n = _num(value)
    sign = "+" if n >= 0 else "−"
    return f"{sign}${abs(n):,.0f}"


def _fmt_pct(value, signed=False, decimals=0):
    n = _num(value)
    sign = "+" if signed and n >= 0 else ("−" if signed and n < 0 else "")
    return f"{sign}{abs(n):.{decimals}f}%" if signed else f"{n:.{decimals}f}%"


def _rvol_value(item):
    if item is None:
        return None
    candidates = []
    if isinstance(item, dict):
        candidates.extend([item.get("rvol"), item.get("gap_rvol"), item.get("breakout_rvol")])
        payload = _extract_payload(item)
        if isinstance(payload, dict):
            candidates.extend([payload.get("rvol"), payload.get("gap_rvol"), payload.get("breakout_rvol")])
    else:
        for key in ("rvol", "gap_rvol", "breakout_rvol"):
            if hasattr(item, key):
                candidates.append(getattr(item, key))
    for value in candidates:
        if value not in (None, ""):
            try:
                return float(value)
            except Exception:
                continue
    return None


def _rvol_line(item, threshold=RVOL_DISPLAY_THRESHOLD):
    rvol = _rvol_value(item)
    if rvol is None:
        return f"   📊 RVOL N/A / {threshold:g} ❌"
    marker = "✅" if rvol >= threshold else "❌"
    return f"   📊 RVOL {rvol:g} / {threshold:g} {marker}"


def _register_buy_line(ticker, shares, entry):
    return f"👉 register {ticker} buy qty={shares} price=${entry:.2f} ref=<your-broker-ref>"


def _register_sell_line(ticker, shares, price):
    return f"👉 register {ticker} sell qty={shares} price=${price:.2f}"


def _condensed_fundamentals(item):
    tag = _fundamentals_tag(item)
    if not tag:
        return None
    text = str(tag)
    margin = re.search(r"fin margin\s+([+-]?[0-9.]+)%", text, re.I)
    if "weak fundamentals" in text.lower() and "neg earnings" in text.lower():
        return "⚠️ weak/no earnings"
    if margin:
        val = _num(margin.group(1))
        if val < 0:
            return "⚠️ neg margin"
        if "solid" in text.lower():
            return f"✅ fundamentals {val:.0f}%"
        return f"fundamentals {val:.0f}%"
    if "solid" in text.lower():
        return "✅ fundamentals"
    if "weak" in text.lower():
        return "⚠️ weak fundamentals"
    return _short_reason(text)


def _quality_tags(item, score=None):
    tags = []
    if score is not None:
        tags.append(f"{_pillar_num(score)}/4")
    ftag = _condensed_fundamentals(item)
    if ftag:
        tags.append(ftag)
    xtag = _indicator_tag(item)
    if xtag:
        for part in [p.strip() for p in str(xtag).split("|") if p.strip()]:
            part = part.replace("RSI ", "RSI ").replace("MACD", "MACD")
            tags.append(part)
    stag = _sentiment_tag(item)
    if stag:
        tags.append(stag)
    # Macro is shown once in the header; do not repeat Fed/CPI caution per row.
    return " · ".join(dict.fromkeys(tags)) if tags else "—"


def _trim_macro_reason(reason):
    """Sanitize macro caution text; news headlines must never appear here."""
    text = str(reason or "macro caution").strip()
    text = re.split(r";\s*(?:headlines?:)?", text, maxsplit=1, flags=re.I)[0].strip()
    if "?" in text:
        text = "macro caution"
    text = re.sub(r":\s+[A-Z][a-z].*$", "", text).strip()
    text = re.sub(r"\bRISK[-_ ](?:ON|OFF)\b", "defensive conditions", text, flags=re.I)
    if len(text) > 120:
        text = text[:120].rstrip()
    return text or "macro caution"


_PERME_RAG_FLAG_PATTERNS = (
    (re.compile(r"\bRISK[-_ ]OFF\b", re.I), lambda m: "RISK-OFF"),
    (re.compile(r"\bFED[_ -]?DAY\b", re.I), lambda m: "FED_DAY"),
    (re.compile(r"\bFOMC[_ -]?DAY\b", re.I), lambda m: "FOMC_DAY"),
    (re.compile(r"\bCPI[_ -]?DAY\b", re.I), lambda m: "CPI_DAY"),
    (re.compile(r"\bEARNINGS_RISK\s*:\s*([A-Z][A-Z0-9.]{0,9})", re.I), lambda m: f"EARNINGS_RISK: {m.group(1).upper()}"),
    (re.compile(r"\bTICKER_NOTE\s*:\s*([A-Z][A-Z0-9.]{0,9})", re.I), lambda m: f"TICKER_NOTE: {m.group(1).upper()}"),
    (re.compile(r"\bSECTOR_OVERBOUGHT\s*:\s*([A-Z0-9 &._-]{2,40})", re.I), lambda m: f"SECTOR_OVERBOUGHT: {m.group(1).strip().upper()}"),
    (re.compile(r"\bSECTOR_NOTE\s*:\s*([A-Z0-9 &._-]{2,40})", re.I), lambda m: f"SECTOR_NOTE: {m.group(1).strip().upper()}"),
)


def _extract_perme_flags_from_text(text):
    flags = []
    for pattern, builder in _PERME_RAG_FLAG_PATTERNS:
        for match in pattern.finditer(str(text or "")):
            flags.append(builder(match))
    return normalize_flags(flags)


def _extract_perme_flags_from_rag_hits(rag_hits):
    flags = []
    for hit in rag_hits or []:
        if isinstance(hit, dict):
            flags.extend(_extract_perme_flags_from_text(hit.get("text") or ""))
        else:
            flags.extend(_extract_perme_flags_from_text(hit))
    return normalize_flags(flags)


_PERME_REPORT_CONTEXT = {}


def _parse_perme_generated_at(value):
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.astimezone(datetime.timezone.utc)
    except Exception:
        return None


def _latest_perme_context_status(now=None):
    path = os.environ.get("ATLAS_PERME_CONTEXT_PATH") or "/Users/yasser/atlas_inbox/latest_context.json"
    status = {"path": path, "exists": False, "stale": False, "age_minutes": None, "ttl_minutes": None, "reason": "missing"}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        status["exists"] = True
        ttl = float(data.get("ttl_minutes") or 0)
        generated = _parse_perme_generated_at(data.get("generated_at"))
        status["ttl_minutes"] = ttl
        if generated is None or ttl <= 0:
            status.update({"stale": True, "reason": "invalid generated_at/ttl"})
            return status
        now = now or datetime.datetime.now(datetime.timezone.utc)
        age = (now - generated).total_seconds() / 60.0
        status["age_minutes"] = round(age, 1)
        if age > ttl:
            status.update({"stale": True, "reason": f"age {age:.0f}m > ttl {ttl:.0f}m"})
        else:
            status.update({"stale": False, "reason": f"fresh age {age:.0f}m <= ttl {ttl:.0f}m"})
    except Exception as e:
        status.update({"stale": True, "reason": f"{type(e).__name__}: {e}"})
    return status


def _latest_processed_perme_brief_flags():
    import glob
    candidates = glob.glob("/Users/yasser/atlas_inbox/processed/perme_brief_*.md")
    if not candidates:
        return [], None
    path = max(candidates, key=lambda item: os.path.getmtime(item))
    try:
        with open(path, "r", errors="replace") as f:
            text = f.read()
        flags = _extract_perme_flags_from_text(text)
        return flags, path
    except Exception:
        return [], path


def _load_perme_flags_from_rag():
    global _PERME_REPORT_CONTEXT
    _PERME_REPORT_CONTEXT = {"stale": False, "fallback_used": False, "fallback_flags": [], "fallback_path": None, "reason": ""}
    flags = []
    if atlas_rag:
        try:
            hits = atlas_rag.query_knowledge_base("Atlas intraday macro risk regime catalyst flags", n_results=5)
            flags = _extract_perme_flags_from_rag_hits(hits)
        except Exception as e:
            print(f"[intraday] Perme RAG flag query failed: {type(e).__name__}: {e}")
            flags = []
    context_status = _latest_perme_context_status()
    if context_status.get("stale"):
        fallback_flags, fallback_path = _latest_processed_perme_brief_flags()
        flags = normalize_flags(list(flags or []) + list(fallback_flags or []))
        _PERME_REPORT_CONTEXT = {
            "stale": True,
            "fallback_used": bool(fallback_flags),
            "fallback_flags": fallback_flags or [],
            "fallback_path": fallback_path,
            "reason": context_status.get("reason") or "stale",
        }
        print(f"[intraday] Perme context stale; report-only fallback flags={fallback_flags or []}")
    else:
        _PERME_REPORT_CONTEXT = {"stale": False, "fallback_used": False, "fallback_flags": [], "fallback_path": None, "reason": context_status.get("reason") or "fresh"}
    print(f"[intraday] Perme RAG flags={flags}")
    return flags


def _perme_flags(summary=None):
    return normalize_flags((summary or {}).get("perme_flags") or [])


def _perme_annotation_line(flags, ticker, sector=None):
    if annotation_for_ticker is None:
        return None
    note = annotation_for_ticker(flags, ticker, sector=sector)
    if not note.get("has_note"):
        return None
    return f"   ⚠️ Perme: {note.get('note')}"


def _perme_header_line(flags):
    flags = normalize_flags(flags)
    global_flags = [f for f in flags if ":" not in f]
    if not global_flags:
        return None
    labels = []
    for flag in global_flags:
        if flag in {"RISK-OFF", "RISK_OFF"}:
            labels.append("macro risk-off context")
        elif flag == "FED_DAY":
            labels.append("Fed day")
        elif flag == "FOMC_DAY":
            labels.append("FOMC day")
        elif flag == "CPI_DAY":
            labels.append("CPI day")
        else:
            labels.append(flag)
    return "⚠️ Perme context: " + " · ".join(dict.fromkeys(labels))



def _perme_engine_packet_lines(summary):
    """Legacy hook retained for callers; packet/machine output is never human-rendered."""
    return []

def _perme_report_context_lines(summary):
    context = (summary or {}).get("perme_report_context") or {}
    if not context.get("stale"):
        return []
    flags = normalize_flags(context.get("fallback_flags") or _perme_flags(summary))
    sectors = []
    tickers = []
    for flag in flags:
        text = str(flag or "").strip().upper()
        if text.startswith(("SECTOR_NOTE:", "SECTOR_OVERBOUGHT:")):
            sectors.append(text.split(":", 1)[1].strip())
        elif text.startswith(("TICKER_NOTE:", "EARNINGS_RISK:")):
            tickers.append(text.split(":", 1)[1].strip())
    lines = ["⚠️ Perme context stale — using live macro fallback"]
    details = []
    if sectors:
        details.append("sectors " + ", ".join(list(dict.fromkeys(sectors))[:4]))
    if tickers:
        details.append("tickers " + ", ".join(list(dict.fromkeys(tickers))[:6]))
    if details:
        lines.append("⚠️ Perme report-only annotations: " + " · ".join(details))
    return lines


def _header_lines(summary, hold_count):
    now_et = datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%-I:%M %p")
    account = summary.get("account", {}) or {}
    macro = summary.get("macro_context") or {}
    macro_sent = summary.get("macro_sentiment") or {}
    detail = str(summary.get("regime_detail") or "")
    m = re.search(r"SPY\s+([0-9.]+)", detail)
    spy = _price(m.group(1)) if m else "N/A"
    regime_name = _advisory_regime(summary)
    regime = {"RISK-ON": "🟢 RISK-ON", "CAUTION": "🟡 CAUTION", "RISK-OFF": "🔴 RISK-OFF"}[regime_name]
    macro_note = ""
    if isinstance(macro, dict) and macro.get("cautious"):
        macro_note = f" · {macro.get('note') or '⚠️ macro caution'}"
    if isinstance(macro_sent, dict) and macro_sent.get("active", True):
        sent = str(macro_sent.get("sentiment") or "NEUTRAL").upper()
        if sent in {"CAUTION", "RISK_OFF", "RISK-OFF"}:
            reason = _trim_macro_reason(macro_sent.get("reason") or "macro caution")
            # Preserve the source fact without printing a second regime token.
            descriptor = "cautious macro sentiment" if sent == "CAUTION" else "defensive macro sentiment"
            macro_note += f" · 🧠 {descriptor}: {reason}"
    positions = summary.get("open_positions_count", hold_count)
    try:
        positions_for_valuation = _authority_open_position_rows(summary)
        valid = [p for p in positions_for_valuation if (p.get("price_authority") or {}).get("is_valuation_valid")]
        excluded = valuation_excluded_tickers(positions_for_valuation)
        invested = sum(_num(p.get("entry_price") or p.get("price")) * _num(p.get("quantity") or p.get("shares")) for p in valid)
        current_value = sum(_num((p.get("price_authority") or {}).get("valuation_price")) * _num(p.get("quantity") or p.get("shares")) for p in valid)
        roi = ((current_value - invested) / invested * 100.0) if invested else 0.0
        positions_note = " · valuation PARTIAL excl " + ",".join(excluded) if excluded else ""
    except Exception:
        roi = 0.0
        positions_note = ""
    lines = [
        f"🦅 ATLAS INTRADAY — {now_et} ET",
        f"📡 {regime} · SPY {spy}{macro_note}",
        f"💰 Equity {_money(account.get('equity'))} · Cash {_money(account.get('cash'))} · {positions} positions · ROI {_fmt_pct(roi, signed=True, decimals=1)}{positions_note}",
    ]
    perme_line = _perme_header_line(_perme_flags(summary))
    if perme_line:
        lines.append(perme_line)
    lines += _perme_report_context_lines(summary)
    return lines


def _current_cycle_buy_signals(before_id=None, minutes=15):
    """Return classifiable current-cycle advisory rows after the high-water mark."""
    db_path = getattr(atlas_db, "DB_PATH", "/Users/yasser/scripts/atlas.db")
    try:
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        if before_id:
            where_clause = """
            WHERE id > ?
              AND COALESCE(signal, '') <> ''
            """
            params = (int(before_id),)
        else:
            where_clause = """
            WHERE timestamp >= datetime('now', ?)
              AND COALESCE(signal, '') <> ''
            """
            params = (f"-{int(minutes)} minutes",)
        rows = con.execute(
            f"""
            SELECT *
            FROM signals
            {where_clause}
            ORDER BY
              CASE
                WHEN CAST(substr(COALESCE(score, '0/4'), 1, instr(COALESCE(score, '0/4'), '/') - 1) AS INTEGER) >= 4 THEN 0
                WHEN CAST(substr(COALESCE(score, '0/4'), 1, instr(COALESCE(score, '0/4'), '/') - 1) AS INTEGER) = 3 THEN 1
                ELSE 2
              END,
              ticker
            """,
            params,
        ).fetchall()
        con.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[intraday] current-cycle BUY signal query failed: {e}", flush=True)
        return []


def _pending_target_for_signal(ticker, entry):
    """Pull target from pending state when available; otherwise use 25% fallback."""
    ticker = str(ticker or "").upper()
    entry = _num(entry)
    fallback = round(entry * 1.25, 2) if entry else None
    try:
        row = atlas_db.get_pending_pullback(ticker)
    except Exception:
        row = None
    if row:
        for key in ("target", "target_price"):
            if row.get(key) not in (None, ""):
                return _num(row.get(key), fallback or 0.0)
        raw = row.get("signal_json")
        if raw:
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
                for key in ("target", "target_price"):
                    if isinstance(data, dict) and data.get(key) not in (None, ""):
                        return _num(data.get(key), fallback or 0.0)
                risk_card = data.get("risk_card") if isinstance(data, dict) else None
                if isinstance(risk_card, dict):
                    for key in ("target", "target_price"):
                        if risk_card.get(key) not in (None, ""):
                            return _num(risk_card.get(key), fallback or 0.0)
            except Exception:
                pass
    return fallback


def _risk_label_for_signal(row, summary):
    pillars = _pillar_num(row.get("score"))
    detail = str((summary or {}).get("entry_regime_detail") or (summary or {}).get("regime_detail") or "")
    macro = (summary or {}).get("macro_context") or {}
    cautious = (
        "WEAK" in detail.upper()
        or "UNKNOWN" in detail.upper()
        or "UNAVAILABLE" in detail.upper()
        or bool(macro.get("cautious") if isinstance(macro, dict) else False)
    )
    return "0.5% risk" if pillars == 3 or cautious else "1% risk"


def _row_ticker(row):
    return str((row or {}).get("ticker") or (row or {}).get("symbol") or "").upper()


def _extract_payload(row):
    row = row or {}
    payload = row.get("signal_result")
    if isinstance(payload, dict):
        return payload
    raw = row.get("signal_json")
    if raw:
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
    return {}


def _high_by_ticker(high):
    out = {}
    for item in high or []:
        if not isinstance(item, dict):
            continue
        t = _row_ticker(item)
        if t:
            out[t] = item
    return out


def _open_trades(summary=None):
    summary = summary or {}
    holds_by_ticker = {_row_ticker(h): h for h in (summary.get("exit_results", []) or []) if isinstance(h, dict) and _row_ticker(h)}
    try:
        rows = atlas_db.get_open_positions()
    except Exception:
        rows = atlas_db.get_trades(status="OPEN")

    # P0L-18 STAGING fix: get_open_positions() does NOT return the real
    # trades.id column (only ticker/quantity/entry_price/... for backward
    # compatibility with the /positions command). Previously this function
    # fell back to the enumerate() loop index as trade_id, which is NOT a
    # persistent identifier and silently mismatched dual-write bookkeeping
    # lookups (P0L-17 finding: valuation_marks attached to unrelated closed
    # lots). Resolve the REAL trades.id per ticker via get_trades(status='OPEN')
    # -- which does return a genuine id column -- and use that as the
    # authoritative trade_id. Never fall back to loop index for trade_id;
    # if a ticker's real id genuinely cannot be resolved (should not happen
    # for a currently-OPEN position), use sentinel -1 so the downstream
    # dual-write defensive guard (ticker+status match required) cleanly
    # rejects it instead of ever matching an unrelated lot.
    real_id_by_ticker = {}
    try:
        for t in (atlas_db.get_trades(status="OPEN") or []):
            t = dict(t) if not isinstance(t, dict) else t
            tk = _row_ticker(t)
            tid = t.get("id")
            if tk and tid is not None and tk not in real_id_by_ticker:
                real_id_by_ticker[tk] = int(tid)
    except Exception as e:
        print(f"[intraday] real trade-id resolution for dual-write skipped (non-fatal): {e}")

    trades = []
    for row in (rows or []):
        row = dict(row or {})
        t = _row_ticker(row)
        if not t:
            continue
        hold = holds_by_ticker.get(t, {})
        entry = row.get("entry_price") or row.get("price") or hold.get("entry") or hold.get("entry_price")
        now = hold.get("last") or hold.get("current_price") or row.get("current_price") or row.get("last") or entry
        stop = row.get("stop_loss") or hold.get("stop") or hold.get("stop_loss") or entry
        target = row.get("target_price") or hold.get("target") or hold.get("target_price") or entry
        shares = row.get("quantity") or row.get("shares") or hold.get("qty") or hold.get("shares") or 0
        # P0L-18: real trades.id only -- row's own id/trade_id if present,
        # else the resolved ticker->id map, else sentinel -1. NEVER the loop
        # index. -1 is intentionally an invalid trades.id (all real ids are
        # positive AUTOINCREMENT values) so the guard in
        # _dualwrite_valuation_mark() cannot accidentally match a real lot.
        resolved_trade_id = row.get("id") or row.get("trade_id") or real_id_by_ticker.get(t) or -1
        try:
            trades.append(AtlasTrade(
                trade_id=int(resolved_trade_id),
                ticker=t,
                broker=str(row.get("broker") or "eToro"),
                entry_price=float(entry),
                current_price=float(now),
                stop_loss=float(stop),
                target_price=float(target),
                shares=float(shares),
                manual_stop_lock=bool(int(row.get("manual_stop_lock") or 0)),
                status=str(row.get("status") or "OPEN"),
            ))
        except Exception:
            continue
    return trades


def _open_tickers(summary=None):
    return {trade.ticker.upper() for trade in _open_trades(summary)}


def _signal_pillar_text(row):
    m = re.search(r"(\d+/4)", str((row or {}).get("score") or (row or {}).get("pillar_score") or ""))
    return m.group(1) if m else f"{_pillar_num((row or {}).get('score'))}/4"


def _payload_risk_card(payload):
    rc = (payload or {}).get("risk_card")
    return rc if isinstance(rc, dict) else {}


def _live_scan_price(scan_row):
    if not isinstance(scan_row, dict):
        return None
    for key in ("live_price", "current_price", "price", "last_price"):
        val = scan_row.get(key)
        if val not in (None, ""):
            try:
                return float(val)
            except Exception:
                return None
    text = str(scan_row.get("reason") or "")
    match = re.search(r"\bprice\s+\$([0-9][0-9,]*(?:\.[0-9]+)?)", text, re.I)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except Exception:
            return None
    return None


def _signal_current_price(row, scan_row=None):
    # Prefer live Massive/API scan fields over stale pending_pullbacks.reference_price.
    for source in (scan_row or {}, row or {}):
        live = _live_scan_price(source)
        if live is not None:
            return live
    # Only final fallback; not used for BUY NOW eligibility.
    for key in ("reference_price", "trigger_price", "entry_price", "entry"):
        val = (row or {}).get(key)
        if val not in (None, ""):
            return _num(val)
    return 0.0


def _portfolio_module():
    try:
        import atlas_portfolio as port
        return port
    except Exception as e:
        print(f"[intraday] live quote/indicator bridge unavailable: {type(e).__name__}: {e}")
        return None


def _batch_live_price_map(tickers):
    """Parallel bridge for live prices used by pending pullback promotion/rendering."""
    port = _portfolio_module()
    if port is None or not hasattr(port, "_price_lookup"):
        return {}
    unique = sorted({str(t or "").upper() for t in (tickers or []) if str(t or "").strip()})
    if not unique:
        return {}
    start = time.perf_counter()
    prices = {}

    def _fetch(ticker):
        price = port._price_lookup(ticker)
        return ticker, price

    workers = min(8, max(1, len(unique)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_ticker = {executor.submit(_fetch, ticker): ticker for ticker in unique}
        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                got_ticker, price = future.result()
                if price not in (None, ""):
                    prices[got_ticker] = float(price)
            except Exception as e:
                print(f"[intraday] live price fetch warning {ticker}: {type(e).__name__}: {e}")
    print(f"[TIMING] {datetime.datetime.now().isoformat(timespec='seconds')} section=pending_live_price_map event=end elapsed={time.perf_counter() - start:.3f}s tickers={len(unique)} workers={workers}")
    return prices


def _indicator_info_map(tickers, summary=None):
    """Fetch RSI/MACD indicator payloads for report-only signal rendering."""
    summary = summary if isinstance(summary, dict) else {}
    cache = summary.setdefault("_indicator_info_map", {}) if isinstance(summary, dict) else {}
    needed = sorted({str(t or "").upper() for t in (tickers or []) if str(t or "").strip() and str(t or "").upper() not in cache})
    if needed:
        port = _portfolio_module()
        fetch = getattr(port, "check_massive_indicators", None) if port is not None else None
        if callable(fetch):
            start = time.perf_counter()

            def _fetch(ticker):
                return ticker, fetch(ticker)

            workers = min(8, max(1, len(needed)))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_ticker = {executor.submit(_fetch, ticker): ticker for ticker in needed}
                for future in as_completed(future_to_ticker):
                    ticker = future_to_ticker[future]
                    try:
                        got_ticker, info = future.result()
                        if isinstance(info, dict):
                            cache[got_ticker] = info
                    except Exception as e:
                        print(f"[intraday] indicator fetch warning {ticker}: {type(e).__name__}: {e}")
            print(f"[TIMING] {datetime.datetime.now().isoformat(timespec='seconds')} section=indicator_info_map event=end elapsed={time.perf_counter() - start:.3f}s tickers={len(needed)} workers={workers}")
    return cache


def _pending_live_price_map(rows=None, summary=None):
    summary = summary if isinstance(summary, dict) else {}
    cache = summary.setdefault("_pending_live_price_map", {}) if isinstance(summary, dict) else {}
    tickers = {_row_ticker(row) for row in (rows or []) if _row_ticker(row)}
    missing = sorted(t for t in tickers if t not in cache)
    if missing:
        cache.update(_batch_live_price_map(missing))
    return cache


def _normalize_indicator_payload(indicator):
    if isinstance(indicator, str):
        try:
            indicator = json.loads(indicator)
        except Exception:
            indicator = {}
    if not isinstance(indicator, dict):
        return {}
    out = dict(indicator)
    if out.get("macd_histogram") in (None, "") and out.get("macd_hist") not in (None, ""):
        out["macd_histogram"] = out.get("macd_hist")
    return out


def _enrich_signal_row(row, high_map=None, live_prices=None, indicator_map=None):
    row = dict(row or {})
    ticker = _row_ticker(row)
    if not ticker:
        return row
    high_map = high_map or {}
    live_prices = live_prices or {}
    indicator_map = indicator_map or {}
    live = _live_scan_price(high_map.get(ticker, {}))
    if live is None and ticker in live_prices:
        live = live_prices.get(ticker)
    if live is not None:
        row.update({"live_price": live, "current_price": live, "price": live, "last_price": live})
    payload = _extract_payload(row)
    # Priority: indicator_map (live fetch) > payload > row — indicator_map always wins if non-empty
    _ind_from_map = indicator_map.get(ticker) if indicator_map else None
    _ind_from_payload = payload.get("indicator_info") if isinstance(payload, dict) else None
    _ind_from_row = row.get("indicator_info")
    indicator = _ind_from_map or _ind_from_payload or _ind_from_row or {}
    indicator = _normalize_indicator_payload(indicator)
    for key in ("rsi", "momentum_weak", "macd_histogram", "macd_hist"):
        if key in row and row.get(key) not in (None, ""):
            indicator[key] = row.get(key)
    row["indicator_info"] = indicator  # always write back, even if empty
    return row


def _signal_from_row(row, high_map=None):
    row = dict(row or {})
    high_map = high_map or {}
    ticker = _row_ticker(row)
    if not ticker:
        return None
    scan = high_map.get(ticker, {})
    payload = _extract_payload(row)
    risk_card = _payload_risk_card(payload)
    trigger = row.get("trigger_price") or row.get("entry_price") or row.get("entry") or payload.get("trigger_price") or payload.get("entry_price") or payload.get("entry")
    current = _signal_current_price(row, scan)
    stop = row.get("stop_loss") or row.get("stop") or payload.get("stop_loss") or payload.get("stop") or risk_card.get("stop_loss")
    target = row.get("target_price") or row.get("target") or payload.get("target_price") or payload.get("target") or risk_card.get("target_price") or risk_card.get("target") or _pending_target_for_signal(ticker, trigger)
    indicator = row.get("indicator_info") or payload.get("indicator_info") or {}
    indicator = _normalize_indicator_payload(indicator)
    fundamentals = row.get("fundamentals") or payload.get("fundamentals") or {}
    ftag = str((fundamentals.get("tag") if isinstance(fundamentals, dict) else fundamentals) or "")
    reason = f"{row.get('reason','')} {row.get('signal','')} {row.get('signal_json','')} {scan.get('reason','')} {scan.get('signal','')}"
    action = str(row.get("action") or scan.get("action") or "").upper()
    pct = scan.get("pct_over_ema") if scan.get("pct_over_ema") not in (None, "") else row.get("pct_over_ema")
    try:
        pct_float = float(pct) if pct not in (None, "") else None
    except Exception:
        pct_float = None
    is_hot = ("TOO HOT" in reason.upper() or "TOO EXTENDED" in reason.upper() or (action == "SKIP" and pct_float is not None and pct_float > 10))
    try:
        sig = AtlasSignal(
            ticker=ticker,
            trigger_price=float(trigger),
            current_price=float(current),
            stop_loss=float(stop),
            target_price=float(target),
            pillar_score=_signal_pillar_text(row),
            risk_pct=float(row.get("risk_pct") or payload.get("risk_pct") or 0.5),
            rsi=indicator.get("rsi"),
            macd_hist=indicator.get("macd_histogram"),
            momentum_weak=bool(indicator.get("momentum_weak") or "momentum weak" in str(_indicator_tag(row) or "").lower()),
            fundamentals_ok=("solid" in ftag.lower() or "✅" in ftag),
            fundamentals_pct=None,
            no_earnings=("weak/no earnings" in ftag.lower() or "neg earnings" in ftag.lower()),
            neg_margin=("neg margin" in ftag.lower()),
            is_too_hot=bool(is_hot),
            pct_over_ema=pct_float,
        )
        object.__setattr__(sig, "rvol", _rvol_value(row) if _rvol_value(row) is not None else _rvol_value(scan))
        return sig
    except Exception:
        return None


def _buy_now_candidate_signal(row, high_map, live_prices=None, indicator_map=None):
    ticker = _row_ticker(row)
    scan = high_map.get(ticker, {}) if ticker else {}
    live_price = _live_scan_price(scan)
    if live_price is None and ticker:
        live_price = (live_prices or {}).get(ticker)
    if live_price is None:
        return None
    row = _enrich_signal_row(row, high_map=high_map, live_prices={ticker: live_price}, indicator_map=indicator_map)
    sig = _signal_from_row(row, high_map)
    if not sig or sig.is_too_hot or sig.pillar_score != "4/4":
        return None
    if sig.trigger_price and sig.current_price > sig.trigger_price * 1.08:
        return None
    return sig


def _parse_signal_timestamp(value):
    if value in (None, ""):
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed
    except Exception:
        return None


def _buy_now_signal_is_fresh(row, now=None, max_age_minutes=BUY_NOW_MAX_SIGNAL_AGE_MINUTES):
    ts = _parse_signal_timestamp((row or {}).get("timestamp") or (row or {}).get("signal_timestamp"))
    if ts is None:
        return False
    now = now or datetime.datetime.now()
    age = (now - ts).total_seconds() / 60.0
    return 0 <= age <= float(max_age_minutes)


def _fresh_signal_by_ticker(rows, now=None):
    fresh = {}
    for row in rows or []:
        ticker = _row_ticker(row)
        if ticker and _buy_now_signal_is_fresh(row, now=now):
            fresh.setdefault(ticker, row)
    return fresh


def _canonical_buy_now_signals(before_scan_signal_id=None, high=None, summary=None):
    summary = summary if isinstance(summary, dict) else {}
    high_map = _high_by_ticker(high)
    blocked = _open_tickers(summary)
    signals = []
    current_rows = list(_current_cycle_buy_signals(before_scan_signal_id))
    fresh_current_by_ticker = _fresh_signal_by_ticker(current_rows)
    try:
        pending_rows = list(atlas_db.get_pending_pullbacks(status="WAITING") or [])
    except Exception:
        pending_rows = []
    pending_live = _pending_live_price_map(pending_rows, summary=summary)
    indicator_map = _indicator_info_map([_row_ticker(r) for r in (current_rows + pending_rows)], summary=summary)
    for row in current_rows:
        t = _row_ticker(row)
        if t in blocked or _pillar_num((row or {}).get("score")) != 4 or (before_scan_signal_id is None and not _buy_now_signal_is_fresh(row)):
            continue
        row = _enrich_signal_row(row, high_map=high_map, live_prices=pending_live, indicator_map=indicator_map)
        sig = _buy_now_candidate_signal(row, high_map, live_prices=pending_live, indicator_map=indicator_map)
        if sig:
            signals.append(sig)
    for row in pending_rows or []:
        row = dict(row or {})
        t = _row_ticker(row)
        fresh_signal = fresh_current_by_ticker.get(t)
        if t in blocked or _pillar_num(row.get("score")) != 4 or not _pending_pullback_visible_in_status(row) or not fresh_signal:
            continue
        row.setdefault("timestamp", fresh_signal.get("timestamp"))
        row.setdefault("signal_timestamp", fresh_signal.get("timestamp"))
        row = _enrich_signal_row(row, high_map=high_map, live_prices=pending_live, indicator_map=indicator_map)
        sig = _buy_now_candidate_signal(row, high_map, live_prices=pending_live, indicator_map=indicator_map)
        if sig:
            signals.append(sig)
    dedup = {}
    for sig in signals:
        dedup.setdefault(sig.ticker, sig)
    return sorted(dedup.values(), key=lambda sig: (-_sentiment_score_value({"ticker": sig.ticker}), sig.ticker))[:5]


def _waiting_pullback_tickers():
    try:
        return {
            _row_ticker(row)
            for row in (atlas_db.get_pending_pullbacks(status="WAITING") or [])
            if _row_ticker(row)
        }
    except Exception:
        return set()


def _top_pick_rsi_momentum_suppressed(row, sig):
    if not sig or sig.rsi is None:
        return False
    warning_text = str((row or {}).get("warnings") or "")
    payload = _extract_payload(row)
    if isinstance(payload, dict):
        warning_text += " " + str(payload.get("warnings") or "")
    return "MOMENTUM WEAK" in warning_text.upper() and float(sig.rsi) > 70.0


def _advisory_now(summary):
    value = (summary or {}).get("advisory_as_of")
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else datetime.datetime.now(datetime.timezone.utc)
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc)


def _report_gates(row, sig, now):
    """Construct report gates only from renderer-known facts; no DB schema field."""
    ts = _parse_signal_timestamp(row.get("timestamp") or row.get("signal_timestamp"))
    now_naive = now.astimezone().replace(tzinfo=None) if now.tzinfo else now
    age = (now_naive - ts).total_seconds() / 60.0 if ts else None
    rvol = getattr(sig, "rvol", None) if sig else _rvol_value(row)
    trigger = sig.trigger_price if sig else _num(row.get("trigger_price") or row.get("entry_price"), 0)
    current = sig.current_price if sig else _num(row.get("current_price") or row.get("price"), 0)
    # If no price pair is available, do not invent a failed level. Existing
    # renderer eligibility remains authoritative; when both values exist, gate it.
    eligible = True if not (trigger and current) else bool(trigger * 0.97 <= current <= trigger * 1.08)
    return {
        "current_vs_trigger_eligible": eligible,
        "data_timestamp_valid": age is not None and 0 <= age <= BUY_NOW_MAX_SIGNAL_AGE_MINUTES,
        "rvol_eligible": rvol is not None and rvol >= RVOL_DISPLAY_THRESHOLD,
        "too_hot_false": bool(sig) and not sig.is_too_hot,
    }


def _current_cycle_advisory_decisions(before_scan_signal_id=None, high=None, summary=None):
    """Single immutable-cycle collection used by both TOP PICKS and WAIT."""
    summary = summary if isinstance(summary, dict) else {}
    high_map = _high_by_ticker(high)
    rows = list(_current_cycle_buy_signals(before_scan_signal_id))
    indicator_map = _indicator_info_map([_row_ticker(row) for row in rows], summary=summary)
    now = _advisory_now(summary)
    decisions = []
    for raw in rows:
        raw_fields = {key: raw.get(key) for key in ("signal", "score", "pillars", "timestamp")}
        row = {**dict(raw), **high_map.get(_row_ticker(raw), {}), **raw_fields}
        # Persisted signals encode Relative Strength as human text, commonly
        # "YES (...)" or "NO (...)". Translate that sourced fact into an
        # explicit report-level gate while preserving the raw field verbatim.
        rs_text = str(row.get("relative_strength") or "").strip().upper()
        if "relative_strength_pass" not in row and rs_text:
            if rs_text.startswith("YES"):
                row["relative_strength_pass"] = True
            elif rs_text.startswith("NO"):
                row["relative_strength_pass"] = False
        row = _enrich_signal_row(row, high_map=high_map, indicator_map=indicator_map)
        sig = _signal_from_row(row, high_map)
        if sig:
            row.update({"rvol": getattr(sig, "rvol", None), "rsi": sig.rsi,
                        "momentum_weak": sig.momentum_weak})
        row["mandatory_report_gates"] = _report_gates(row, sig, now)
        row.setdefault("data_source", row.get("source") or "current-cycle signal")
        decisions.append((_advise_intraday(row, now=now), row, sig))
    return tuple(decisions)


def _current_cycle_advisory_routing(before_scan_signal_id=None, high=None, summary=None,
                                    buy_now_tickers=None, decisions=None):
    """Build the sole report routing authority from one enriched cycle snapshot."""
    summary = summary if isinstance(summary, dict) else {}
    decisions = decisions if decisions is not None else _current_cycle_advisory_decisions(
        before_scan_signal_id, high, summary)
    rows = [row for _decision, row, _sig in decisions]
    return build_advisory_routing(
        rows, now=_advisory_now(summary), buy_now_tickers=buy_now_tickers or (),
        open_tickers=_open_tickers(summary), pending_tickers=_waiting_pullback_tickers(),
    )


def _canonical_top_pick_signals(before_scan_signal_id=None, high=None, summary=None, buy_now_tickers=None, decisions=None):
    summary = summary if isinstance(summary, dict) else {}
    decisions = decisions if decisions is not None else _current_cycle_advisory_decisions(before_scan_signal_id, high, summary)
    excluded = _open_tickers(summary) | _waiting_pullback_tickers()
    signals = [sig for decision, row, sig in decisions
               if sig and decision.top_pick and decision.ticker not in excluded]
    return sorted({s.ticker: s for s in signals}.values(), key=lambda sig: (-_pillar_num(sig.pillar_score), sig.ticker))[:5]

def _signal_sort_key(row):
    ticker = str((row or {}).get("ticker") or "").upper()
    pillars = _pillar_num((row or {}).get("score"))
    return (-pillars, ticker)


def _pending_signal_payload(ticker):
    try:
        row = atlas_db.get_pending_pullback(str(ticker or "").upper())
    except Exception:
        row = None
    raw = (row or {}).get("signal_json")
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _sentiment_score_value(row):
    data = row or {}
    payload = _pending_signal_payload(data.get("ticker"))
    candidates = [data.get("sentiment_info"), payload.get("sentiment_info"), data.get("gap_breakout"), payload.get("gap_breakout")]
    for sent in candidates:
        if not isinstance(sent, dict):
            continue
        for key in ("normalized", "sentiment_score", "score"):
            if sent.get(key) not in (None, ""):
                return _num(sent.get(key), 0.0)
    text = f"{data.get('warnings', '')} {payload.get('warnings', '')}"
    m = re.search(r"([+-][0-9]+(?:\.[0-9]+)?)", text)
    return _num(m.group(1), 0.0) if m else 0.0


def _risk_percent_for_signal(row, summary):
    if (row or {}).get("risk_pct") not in (None, ""):
        return f"{_num((row or {}).get('risk_pct')):.1f}%"
    return _risk_label_for_signal(row or {}, summary or {}).replace(" risk", "")


def _buy_now_line(sig, summary=None):
    ticker = sig.ticker if isinstance(sig, AtlasSignal) else _row_ticker(sig)
    if not isinstance(sig, AtlasSignal):
        sig = _signal_from_row(sig, {})
    if not sig:
        return ""
    label = _ticker_label(ticker, {"ticker": ticker})
    lines = [
        f"⚡ {label}",
        f"   👀 Now {_price(sig.current_price)}",
        f"   💲 Entry {_price(sig.trigger_price)}",
        f"   🚦 Stop {_price(sig.stop_loss)}",
        f"   🎯 Target {_price(sig.target_price)}",
        _rvol_line(sig),
        f"   {sig.pillar_score} · {sig.risk_pct:.1f}%",
    ]
    ann = _perme_annotation_line(_perme_flags(summary), ticker)
    if ann:
        lines.append(ann)
    return "\n".join(lines)


def _buy_now_rows(before_scan_signal_id=None, high=None, summary=None):
    return _canonical_buy_now_signals(before_scan_signal_id, high=high, summary=summary)


def _buy_now_tickers(before_scan_signal_id=None, high=None, summary=None):
    return {sig.ticker for sig in _buy_now_rows(before_scan_signal_id, high=high, summary=summary)}


def _buy_now_lines(summary=None, before_scan_signal_id=None, high=None):
    rows = _buy_now_rows(before_scan_signal_id, high=high, summary=summary)
    lines = ["━━━ 🟢 BUY NOW ━━━"]
    if not rows:
        lines.append("none")
        lines.append("")
        return lines
    lines.append("")
    for sig in rows[:5]:
        lines.append(_buy_now_line(sig, summary or {}))
        lines.append("")
    return lines


def _action_buy_line(sig, summary=None):
    if not isinstance(sig, AtlasSignal):
        sig = _signal_from_row(sig, {})
    if not sig:
        return ""
    label = _ticker_label(sig.ticker, {"ticker": sig.ticker})
    return (
        f"{label}\n"
        f"   💵 Entry {_price(sig.trigger_price)}\n"
        f"   👀 Now {_price(sig.current_price)} ({_fmt_pct(((sig.current_price - sig.trigger_price) / sig.trigger_price * 100.0) if sig.trigger_price else 0.0, signed=True, decimals=0)})\n"
        f"   {sig.pillar_score}\n"
        f"   📉 RSI {sig.rsi:.0f}" if sig.rsi is not None else f"{label}\n   💵 Entry {_price(sig.trigger_price)}\n   👀 Now {_price(sig.current_price)}\n   {sig.pillar_score}"
    )


def _decision_card_lines(decision):
    raw = decision.raw
    return [
        decision.ticker,
        f"   TFE CLASSIFICATION: {raw.get('signal')} · score {raw.get('score')} · pillars {raw.get('pillars')} · timestamp {raw.get('timestamp')}",
        f"   ACTION NOW: {decision.action_now}",
        "   WHY: " + "; ".join(decision.why),
        "   BLOCKERS: " + ("; ".join(decision.blockers) if decision.blockers else "none"),
        f"   DATA FRESHNESS: {decision.freshness}",
        "",
    ]


def _actions_lines(buys, sells, summary=None, before_scan_signal_id=None, high=None, buy_now_tickers=None, decisions=None, routing=None):
    routing = routing or _current_cycle_advisory_routing(before_scan_signal_id, high, summary, buy_now_tickers, decisions)
    picks = routing.top_picks
    lines = ["", f"━━━ 🔥 TOP PICKS ({len(picks)}) ━━━", ""]
    if not picks:
        return lines + ["none", ""]
    for decision in picks:
        lines += _decision_card_lines(decision)
    return lines


def _advisory_action_lines(before_scan_signal_id=None, high=None, summary=None, decisions=None, routing=None):
    """Render qualified WAIT from the same canonical route used by TOP PICKS."""
    routing = routing or _current_cycle_advisory_routing(before_scan_signal_id, high, summary, None, decisions)
    waits = routing.qualified_wait
    lines = ["", f"━━━ TECHNICALLY QUALIFIED — WAIT ({len(waits)}) ━━━", ""]
    if not waits:
        return lines + ["none", ""]
    for decision in waits:
        lines += _decision_card_lines(decision)
    return lines


_ALERT_CATALYST_TERMS = (
    "earnings", "guidance", "downgrade", "upgrade", "merger", "acquisition", "lawsuit", "recall",
    "fda", "investigation", "resignation", "restatement", "profit warning", "outage", "breach",
    "strike", "layoff", "spinoff", "activist", "antitrust", "halt", "delisting", "fraud", "sec probe",
)


def _alert_reason_text(row):
    return str((row or {}).get("reason") or "")


def _alert_is_stop_proximity(row):
    """True when the alert reason explicitly reports proximity to the stop level."""
    text = _alert_reason_text(row).lower()
    return "within" in text and "of stop" in text


def _alert_has_ticker_catalyst(row):
    """True when the alert reason contains a ticker/sector-specific catalyst keyword.

    Purely a text classification over the already-computed `reason` string; does not
    call any provider, does not change scoring/strategy, and does not read protected files.
    """
    text = _alert_reason_text(row).lower()
    return any(term in text for term in _ALERT_CATALYST_TERMS)


def _alert_is_generic_macro(row):
    """True when the alert is only generic macro-caution boilerplate (FOMC/CPI/NFP + weak RVOL/RSI)."""
    text = _alert_reason_text(row).lower()
    if not text.startswith("macro stress:"):
        return False
    if _alert_has_ticker_catalyst(row):
        return False
    return True


def _alert_perme_high_match(row, summary):
    """True when a Perme engine packet with severity HIGH names this ticker (annotation-only lookup)."""
    ticker = _row_ticker(row)
    if not ticker or _load_engine_packets is None:
        return False
    path = os.environ.get("ATLAS_PERME_ENGINE_PACKET_PATH") or "/Users/yasser/atlas_inbox/perme_engine_packet_v1.jsonl"
    try:
        packets, _errors = _load_engine_packets(path)
    except Exception:
        return False
    for p in packets or []:
        if str((p or {}).get("severity") or "").upper() != "HIGH":
            continue
        packet_tickers = {str(t).upper() for t in ((p or {}).get("tickers") or [])}
        if ticker in packet_tickers:
            return True
    return False


def classify_alert_severity(row, summary=None):
    """Classify an exit_results row into a notification-severity bucket.

    Presentation/notification routing only — does not alter `action`, `reason`,
    `recommendation`, stops, targets, or any value produced by atlas_portfolio.run_exits().
    Priority order: SELL > stop-proximity POSITION_RISK > Perme-HIGH REVIEW_NOW >
    ticker-catalyst REVIEW_NOW > generic-macro MACRO_WATCH > POSITION_RISK (safe default).
    """
    action = str((row or {}).get("action") or "").upper()
    if action == "SELL":
        return "SELL_ALERT"
    if action != "ALERT":
        return None
    if _alert_is_stop_proximity(row):
        return "POSITION_RISK"
    if _alert_perme_high_match(row, summary):
        return "REVIEW_NOW"
    if _alert_has_ticker_catalyst(row):
        return "REVIEW_NOW"
    if _alert_is_generic_macro(row):
        return "MACRO_WATCH"
    return "POSITION_RISK"


def _alert_card_lines(a):
    ticker = _row_ticker(a) or "?"
    label = _ticker_label(ticker, a)
    last = _num(a.get("last") or a.get("current_price") or a.get("price"))
    stop = _num(a.get("stop") or a.get("stop_loss"))
    gap = last - stop  # positive = above stop, negative = below stop
    gap_str = f"{'+' if gap >= 0 else '−'}${abs(gap):,.2f}"
    # Build short macro label from clean reason (already stripped by portfolio patch)
    raw_reason = str(a.get("reason") or "")
    # reason is now e.g. "MACRO STRESS: RISK_OFF; NFP; RSI 44 weak"
    # Extract the factors after "MACRO STRESS: " as a compact label
    macro_label = re.sub(r"^MACRO STRESS:\s*", "", raw_reason, flags=re.I).strip()
    # Replace semicolons with · for compact display, cap at 60 chars
    macro_label = re.sub(r"\s*;\s*", " · ", macro_label)
    if len(macro_label) > 60:
        macro_label = macro_label[:60].rstrip(" ·")
    if not macro_label:
        macro_label = "macro stress"
    recommendation = a.get("recommendation") or "HOLD"
    # Strip icon prefix if recommendation already contains one (e.g. "🔴 SELL NOW — ...")
    rec_clean = re.sub(r"^[^\w]+", "", recommendation).strip()
    rec_clean = re.split(r"\s*[—–-]\s*", rec_clean)[0].strip()
    rec_icon = {"SELL NOW": "🔴", "TIGHTEN STOP": "🟡", "HOLD": "🟢"}.get(rec_clean, "⚠️")
    return [
        f"⚠️  {label}",
        f"   📍 {_price(last)} → stop {_price(stop)} ({gap_str})",
        f"   🌐 {macro_label}",
        f"   {rec_icon} {rec_clean}",
        "",
    ]


def _position_risk_alert_lines(summary):
    """Render the ━━━ ⚠️ POSITION RISK ALERTS ━━━ section for stop-proximity ALERT rows only.

    Compact 4-line card:
      ⚠️  TICKER (Company Name)
         📍 $X.XX → stop $X.XX (−$X.XX)
         🌐 RISK_OFF · NFP
         🟡 TIGHTEN STOP
    """
    alerts = [r for r in (summary.get("exit_results") or []) if classify_alert_severity(r, summary) == "POSITION_RISK"]
    if not alerts:
        return []
    lines = ["", "━━━ ⚠️ POSITION RISK ALERTS ━━━", ""]
    for a in alerts:
        lines += _alert_card_lines(a)
    return lines


def _review_now_lines(summary):
    """Render the ━━━ 🔎 REVIEW NOW ━━━ section for Perme-HIGH or ticker-catalyst ALERT rows."""
    alerts = [r for r in (summary.get("exit_results") or []) if classify_alert_severity(r, summary) == "REVIEW_NOW"]
    if not alerts:
        return []
    lines = ["", "━━━ 🔎 REVIEW NOW ━━━", ""]
    for a in alerts:
        lines += _alert_card_lines(a)
    return lines


def _macro_watch_lines(summary):
    """Render the ━━━ 🌐 MACRO WATCH ━━━ section for generic macro-caution ALERT rows.

    Report-body only — never included in the proactive DM path.
    """
    alerts = [r for r in (summary.get("exit_results") or []) if classify_alert_severity(r, summary) == "MACRO_WATCH"]
    if not alerts:
        return []
    lines = ["", "━━━ 🌐 MACRO WATCH ━━━", ""]
    for a in alerts:
        ticker = _row_ticker(a) or "?"
        label = _ticker_label(ticker, a)
        raw_reason = str(a.get("reason") or "")
        macro_label = re.sub(r"^MACRO STRESS:\s*", "", raw_reason, flags=re.I).strip()
        macro_label = re.sub(r"\s*;\s*", " · ", macro_label)
        if len(macro_label) > 100:
            macro_label = macro_label[:100].rstrip(" ·")
        lines += [f"🌐 {label} — {macro_label or 'macro caution'}", ""]
    return lines


def _sell_now_lines(summary):
    sells = [r for r in (summary.get("exit_results", []) or []) if str(r.get("action") or "").upper() == "SELL"]
    lines = ["", "━━━ 🔴 SELL NOW ━━━", ""]
    if not sells:
        lines.append("✅ none — holding all")
        lines.append("")
        return lines
    for s in sells:
        ticker = _row_ticker(s) or "?"
        label = _ticker_label(ticker, s)
        entry = _num(s.get("entry"))
        now = _num(s.get("price") or s.get("last"))
        shares = _num(s.get("qty") or s.get("shares"))
        gain = (now - entry) * shares
        roi = ((now - entry) / entry * 100.0) if entry else 0.0
        reason = _short_reason(s.get("reason"))
        lines += [
            f"🚨 {label}",
            f"   👀 Now {_price(now)}",
            f"   💲 Entry {_price(entry)}",
            f"   {reason}",
            f"   {_fmt_pct(roi, signed=True, decimals=0)} ({_signed_money(gain)})",
            f"   💰 Invested {_money(entry * shares)} · Gain {_signed_money(gain)}",
            "",
        ]
    return lines


def _pending_entry_current_price(ticker, row):
    row = row or {}
    for key in ("live_price", "current_price", "price", "last_price"):
        if key not in row or row.get(key) in (None, ""):
            continue
        raw = str(row.get(key))
        try:
            val = float(raw)
        except Exception:
            val = None
        if val is not None:
            return val
    try:
        import atlas_portfolio as port
        return _num(port._price_lookup(ticker))
    except Exception:
        return None


def _pending_entry_lines():
    rows = atlas_db.get_pending_fill_trades()
    if not rows:
        return ["", "━━━ ⏳ PENDING ENTRIES (0) ━━━", "✅ none"]
    lines = ["", f"━━━ ⏳ PENDING ENTRIES ({len(rows)}) ━━━", ""]
    for row in rows:
        ticker = str(row.get("ticker") or "?").upper()
        trigger = _num(row.get("entry_price"))
        current = _pending_entry_current_price(ticker, row)
        stop = _num(row.get("stop_loss"))
        target = _num(row.get("target_price"))
        risk_pct = row.get("risk_pct")
        risk_txt = "N/A" if risk_pct in (None, "") else f"{_num(risk_pct):.1f}%"
        label = _ticker_label(ticker, row)
        if current is not None and trigger is not None and current <= trigger:
            status = f"🟢 {label} · trigger {_price(trigger)} · now {_price(current)} · stop {_price(stop)} · target {_price(target)} · {risk_txt} risk — actionable now"
        else:
            status = f"⏳ {label} · trigger {_price(trigger)} · now {_price(current)} · stop {_price(stop)} · target {_price(target)} · {risk_txt} risk — wait, buy only if pulls back to {_price(trigger)}"
        lines += [status, ""]
    return lines



def _authority_open_position_rows(summary=None):
    summary = summary if isinstance(summary, dict) else {}
    holds_by_ticker = {_row_ticker(h): h for h in (summary.get("exit_results", []) or []) if isinstance(h, dict) and _row_ticker(h)}
    try:
        rows = atlas_db.get_open_positions()
    except Exception:
        rows = atlas_db.get_trades(status="OPEN")
    out = []
    for row in rows or []:
        row = dict(row or {})
        ticker = _row_ticker(row)
        entry = row.get("entry_price") or row.get("price")
        hold = holds_by_ticker.get(ticker, {})
        provider_price = hold.get("last") or hold.get("current_price")
        cached_price = row.get("current_price") or row.get("last_price")
        cached_ts = row.get("last_price_at") or row.get("current_price_at")
        pa = resolve_price_authority(ticker, entry, provider_price=provider_price, provider_source="intraday_cycle" if provider_price not in (None, "") else None, cached_price=cached_price, cached_timestamp=cached_ts)
        item = dict(row)
        item.update({"ticker": ticker, "entry_price": entry, "current_price": pa.get("display_price"), "current_price_source": pa.get("source_label"), "price_authority": pa})
        for flag in ("manual_override", "stop_breached", "system_wanted", "risk", "broker_sell_submitted"):
            if flag in hold:
                item[flag] = hold.get(flag)
        try:
            if atlas_db.has_active_manual_hold_override(trade_id=item.get("id") or item.get("trade_id"), ticker=ticker):
                item["manual_override"] = True
                item["system_wanted"] = item.get("system_wanted") or "SELL"
                item["risk"] = item.get("risk") or "HIGH"
                item["broker_sell_submitted"] = bool(item.get("broker_sell_submitted", False))
                try:
                    item["stop_breached"] = float(item.get("current_price") or 0) <= float(item.get("stop_loss") or 0)
                except Exception:
                    item["stop_breached"] = bool(item.get("stop_breached", True))
        except Exception:
            pass
        out.append(item)
    return out

def _holding_lines(summary):
    summary = summary if isinstance(summary, dict) else {}
    positions = _authority_open_position_rows(summary)
    return holding_block(positions, summary or {})


def _profit_protection_lines(summary):
    """Render deterministic advisory-only profit protection cards after HOLDING."""
    summary = summary if isinstance(summary, dict) else {}
    positions = _authority_open_position_rows(summary)
    def _label(ticker):
        return _ticker_label(ticker, {"ticker": ticker})
    return render_profit_protection_cards(positions, ticker_label=_label)


def _profit_protection_v2_lines(summary=None):
    """Advisory-only Profit Protection v2 block. Fail-closed: report continues if evidence is missing."""
    if _render_profit_protection_v2_block is None:
        return []
    try:
        block = _render_profit_protection_v2_block()
    except Exception as exc:
        print(f"[intraday] profit protection v2 warning: {type(exc).__name__}: {exc}")
        return ["", "PROFIT PROTECTION v2 — ADVISORY ONLY", "DATA REVIEW: unavailable; rest of report continues", ""]
    return ([""] + block.splitlines() + [""]) if block else []


def _pending_broker_confirmation_lines(summary=None):
    """P0M-1 READ-ONLY report section. Equivalent pending-state coverage to
    shared authority helper; report-only and no strategy/TFE/DB mutation."""
    try:
        rows = atlas_db.get_pending_broker_confirmation_trades()
    except Exception as exc:
        print(f"[intraday] pending-confirmation lookup warning: {exc}")
        return []
    if not rows:
        return []
    lines = ["", f"━━━ ⏳ SELL TRIGGERED / BROKER CONFIRMATION PENDING ({len(rows)}) ━━━", ""]
    for row in rows:
        ticker = str(row.get("ticker") or "?").upper()
        exit_price = _num(row.get("exit_price"))
        stop = _num(row.get("stop_loss"))
        exit_at = row.get("exit_at") or "N/A"
        entry = _num(row.get("entry_price"))
        qty = _num(row.get("quantity"))
        pnl = (exit_price - entry) * qty if entry and exit_price else 0.0
        pnl_pct = ((exit_price - entry) / entry * 100.0) if entry else 0.0
        lines.append(
            f"⚠️ {ticker}\n"
            f"   🚦 Exit trigger {SOURCE_DB}: {_price(exit_price)} (stop {SOURCE_DB}/{SOURCE_TFE} {_price(stop)})\n"
            f"   🕐 Triggered {SOURCE_DB}: {exit_at}\n"
            f"   📊 Est. P/L {SOURCE_RENDER_CALC}: {_signed_money(pnl)} ({_fmt_pct(pnl_pct, signed=True, decimals=1)})\n"
            f"   broker_confirmed {SOURCE_BROKER}: NO\n"
            f"   cash_credit {SOURCE_DB}: NO"
        )
        lines.append("")
    return lines

def _gap_breakout_lines(summary):
    items = []
    for source in ((summary.get("buys", []) or []), (summary.get("high_candidates", []) or [])):
        for item in source:
            if str(item.get("entry_type") or "").upper() == "GAP_UP_BREAKOUT":
                items.append(item)
    items = _unique(items)
    lines = ["", f"━━━ 🚀 GAP-UP BREAKOUTS ({len(items)}) ━━━", ""]
    if not items:
        lines.append("✅ none")
        return lines
    for item in items:
        ticker = str(item.get("ticker") or item.get("symbol") or "?").upper()
        gap = _num(item.get("gap_pct"))
        rvol = _num(item.get("gap_rvol") or item.get("rvol"))
        label = _ticker_label(ticker, item)
        lines.append(
            f"🔹 {label} | Gap +{gap:.1f}% | RVOL {rvol:.1f}x | entry {_price(item.get('entry'))} | stop {_price(item.get('stop'))} | target {_price(item.get('target'))}"
        )
    return lines


def _intraday_breakout_lines(summary):
    items = []
    for source in ((summary.get("buys", []) or []), (summary.get("high_candidates", []) or [])):
        for item in source:
            if str(item.get("entry_type") or "").upper() == "INTRADAY_BREAKOUT_CONTINUATION":
                items.append(item)
    items = _unique(items)
    lines = ["", f"━━━ 📈 INTRADAY BREAKOUTS ({len(items)}) ━━━", ""]
    if not items:
        lines.append("✅ none")
        return lines
    for item in items:
        ticker = str(item.get("ticker") or item.get("symbol") or "?").upper()
        label = _ticker_label(ticker, item)
        rvol = _num(item.get("breakout_rvol") or item.get("rvol"))
        suffix = ""
        if item.get("sector_sweep"):
            suffix = f" | sweep {item.get('sector_sweep_trigger') or '?'}"
        lines.append(
            f"🔷 {label} | break {_price(item.get('breakout_level'))} | RVOL {rvol:.1f}x | entry {_price(item.get('entry'))} | stop {_price(item.get('stop'))} | target {_price(item.get('target'))}{suffix}"
        )
    return lines


def _too_hot_tickers(high):
    hot = set()
    for h in high or []:
        if not isinstance(h, dict):
            continue
        ticker = str(h.get("ticker") or "").upper()
        if not ticker:
            continue
        reason = str(h.get("reason", "")).upper()
        action = str(h.get("action", "")).upper()
        if action == "SKIP" and (reason.startswith("TOO EXTENDED") or "TOO HOT" in reason):
            hot.add(ticker)
            continue
        raw_pct = h.get("pct_over_ema")
        try:
            pct = float(raw_pct) if raw_pct not in (None, "") else None
        except Exception:
            pct = None
        if action == "SKIP" and pct is not None and pct > 10:
            hot.add(ticker)
    return hot


def _buy_now_deferred_wait_rows(high=None, summary=None):
    summary = summary if isinstance(summary, dict) else {}
    high_map = _high_by_ticker(high)
    blocked = _open_tickers(summary)
    existing = set()
    waits = []
    try:
        pending_rows = list(atlas_db.get_pending_pullbacks(status="WAITING") or [])
    except Exception:
        pending_rows = []
    pending_live = _pending_live_price_map(pending_rows, summary=summary)
    indicator_map = _indicator_info_map([_row_ticker(row) for row in pending_rows], summary=summary)
    for row in pending_rows or []:
        row = _enrich_signal_row(row, high_map=high_map, live_prices=pending_live, indicator_map=indicator_map)
        ticker = _row_ticker(row)
        if not ticker or ticker in blocked or ticker in existing or _pillar_num(row.get("score")) != 4:
            continue
        if not _pending_pullback_visible_in_status(row):
            continue
        trigger = row.get("trigger_price") or row.get("entry_price") or row.get("entry")
        live = _live_scan_price(row) or _live_scan_price(high_map.get(ticker, {}))
        stale = False
        try:
            trigger_float = float(trigger) if trigger not in (None, "") else None
            stale = live is not None and trigger_float is not None and live > trigger_float * 1.08
        except Exception:
            stale = False
        if live is None or stale:
            wait_row = dict(row)
            wait_row.pop("reference_price", None)
            wait_row.update({
                "action": "WAIT",
                "reason": "PULLBACK — BUY NOW requires live price and <=8% above trigger",
                "entry": trigger,
                "entry_price": trigger,
                "current_price": live,
                "price": live,
            })
            waits.append(wait_row)
    return waits


def _waiting_lines(high, suppress_tickers=None, summary=None):
    summary = summary if isinstance(summary, dict) else {}
    deferred_waits = _buy_now_deferred_wait_rows(high, summary=summary)
    high = deferred_waits + list(high or [])
    try:
        pending_rows = list(atlas_db.get_pending_pullbacks(status="WAITING") or [])
    except Exception:
        pending_rows = []
    pending_live = _pending_live_price_map(pending_rows, summary=summary)
    indicator_map = _indicator_info_map([_row_ticker(row) for row in pending_rows], summary=summary)
    # Build a lookup map: ticker -> persisted pending_pullbacks row (for signal_json merge)
    pending_by_ticker = {}
    for _pr in pending_rows:
        _t = _row_ticker(_pr)
        if _t:
            pending_by_ticker[_t] = dict(_pr)
    high_map = _high_by_ticker(high)
    # Merge persisted signal_json indicator_info into each high row before enrichment
    merged_high = []
    for h in high:
        h = dict(h)
        _t = _row_ticker(h)
        if _t and _t in pending_by_ticker:
            _persisted = pending_by_ticker[_t]
            _raw_json = _persisted.get("signal_json")
            if _raw_json:
                try:
                    _payload = json.loads(_raw_json) if isinstance(_raw_json, str) else _raw_json
                    if isinstance(_payload, dict) and _payload.get("indicator_info"):
                        # Use explicit assignment (not setdefault) — DB row may have indicator_info=None which setdefault will not overwrite
                        if not h.get("indicator_info"):
                            h["indicator_info"] = _payload["indicator_info"]
                    # Inject top-level rvol from signal_json into the row (rvol lives outside indicator_info)
                    if isinstance(_payload, dict) and _payload.get("rvol") is not None:
                        if not h.get("rvol"):
                            h["rvol"] = _payload["rvol"]
                except Exception:
                    pass
        merged_high.append(h)
    high = [_enrich_signal_row(h, high_map=high_map, live_prices=pending_live, indicator_map=indicator_map) for h in merged_high]
    hot_tickers = _too_hot_tickers(high)
    suppress_tickers = {str(t or "").upper() for t in (suppress_tickers or set())} | _open_tickers(summary)
    waits = _unique([
        h for h in high
        if str(h.get("action", "")).upper() == "WAIT"
        and "PULLBACK" in str(h.get("reason", "")).upper()
        and _row_ticker(h) not in hot_tickers
        and _row_ticker(h) not in suppress_tickers
    ])
    # Also include pending_rows tickers that did NOT appear in the scan (not in waits)
    waits_tickers = {_row_ticker(h) for h in waits}
    for _pr in pending_rows:
        _pt = _row_ticker(_pr)
        if _pt and _pt not in waits_tickers and _pt not in suppress_tickers and _pt not in hot_tickers:
            _pr_row = dict(_pr)
            # Inject live price if available
            if _pt in pending_live:
                _pr_row.update({"current_price": pending_live[_pt], "price": pending_live[_pt]})
            # Inject indicator_map data directly
            _ind = indicator_map.get(_pt)
            if isinstance(_ind, dict):
                _pr_row["indicator_info"] = _ind
                if _ind.get("rsi") is not None:
                    _pr_row["rsi"] = _ind["rsi"]
                if _ind.get("macd_histogram") is not None:
                    _pr_row["macd_hist"] = _ind["macd_histogram"]
                elif _ind.get("macd_hist") is not None:
                    _pr_row["macd_hist"] = _ind["macd_hist"]
            waits.append(_pr_row)
            waits_tickers.add(_pt)

    rows = []
    for h in waits:
        row = dict(h)
        sig = _signal_from_row(row, _high_by_ticker(high))
        if sig:
            # If sig.rsi is None (ticker not in high_candidates, only in pending_pullbacks),
            # fall back to indicator_map which was built from pending_rows tickers
            _ticker = _row_ticker(row)
            _ind_fallback = indicator_map.get(_ticker) if (sig.rsi is None and _ticker) else {}
            _rsi = sig.rsi if sig.rsi is not None else (_ind_fallback.get("rsi") if isinstance(_ind_fallback, dict) else None)
            _macd = sig.macd_hist if sig.macd_hist is not None else (_ind_fallback.get("macd_histogram") or _ind_fallback.get("macd_hist") if isinstance(_ind_fallback, dict) else None)
            row.update({
                "trigger_price": sig.trigger_price,
                "entry_price": sig.trigger_price,
                "current_price": sig.current_price,
                "price": sig.current_price,
                "score": sig.pillar_score,
                "rsi": _rsi,
                "macd_hist": _macd,
                "fundamentals_ok": sig.fundamentals_ok,
                "momentum_weak": sig.momentum_weak,
                "no_earnings": sig.no_earnings,
                "rvol": _rvol_value(row),
            })
        else:
            row.setdefault("current_price", row.get("price") or row.get("reference_price"))
        rows.append(row)

    # Sort waits hottest-to-coldest: RVOL descending, then RSI descending
    def _sort_key(row):
        try:
            rvol = float(row.get("rvol") or 0)
        except Exception:
            rvol = 0.0
        try:
            rsi = float(row.get("rsi") or 0)
        except Exception:
            rsi = 0.0
        return (rvol, rsi)

    rows.sort(key=_sort_key, reverse=True)
    # Fix #35: hide tickers with no indicator data at all (both RSI and MACD None)
    rows = [r for r in rows if not (r.get("rsi") is None and r.get("macd_hist") is None)]
    return pullback_block(rows)

def _gates_lines(high):
    hot = _unique([h for h in high if str(h.get("action", "")).upper() == "SKIP" and str(h.get("reason", "")).startswith("TOO EXTENDED")])
    lines = ["", f"━━━ 🚦 TOO HOT ({len(hot)}) ━━━"]
    if not hot:
        lines.append("none")
        return lines
    lines.append("")
    for i, h in enumerate(hot, 1):
        m = re.search(r"\+([0-9.]+)%", str(h.get("reason", "")))
        pct = m.group(1) if m else h.get("pct_over_ema", 0)
        label = _ticker_label(str(h.get('ticker')).upper(), h)
        lines += [f"{i}. {label} +{_num(pct):.0f}% over EMA", ""]
    return lines


def _watch_sort_value(item):
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
    m = re.search(r"\+([0-9.]+)%", text)
    return _num(m.group(1), 0.0) if m else 0.0


def _intraday_diagnostic_lines(summary, before_scan_signal_id=None, high=None, buy_now_tickers=None):
    lines = []
    summary = summary if isinstance(summary, dict) else {}
    routing = summary.get("advisory_routing_diagnostics") or {}
    excluded = routing.get("exclusion_reasons") or {}
    blocked = [f"{ticker} ({reason})" for ticker, reason in sorted(excluded.items())]
    if routing:
        counts = routing.get("counts") or {}
        equation = (
            f"Current BUY-family {routing.get('current_buy_family_count', 0)} = "
            f"BUY NOW {counts.get('buy_now', 0)} + TOP PICKS {counts.get('top_picks', 0)} + "
            f"QUALIFIED WAIT {counts.get('qualified_wait', 0)} + EXCLUDED {counts.get('explicitly_excluded', 0)}"
        )
        if not routing.get("equation_holds"):
            raise AssertionError("current-cycle BUY-family diagnostic equation failed")
    else:
        equation = None
    open_tickers = _open_tickers(summary)
    watch_2 = [str(t).upper() for t in (summary.get("watch_2", []) or []) if str(t or "").strip()]
    detail_watch = []
    for item in summary.get("high_candidates", []) or []:
        if isinstance(item, dict) and str(item.get("action", "")).upper() == "WATCH":
            ticker = _row_ticker(item)
            if ticker:
                detail_watch.append(ticker)
    rendered_pool = [t for t in dict.fromkeys(watch_2 + sorted(set(detail_watch))) if t not in open_tickers]
    cap = max(1, int(summary.get("watching_cap", 15) or 15))
    omitted = rendered_pool[cap:]
    if routing:
        lines += ["", "━━━ 🧪 REPORT DIAGNOSTICS ━━━", equation]
        if blocked:
            lines.append(f"Explicitly excluded: {', '.join(blocked[:6])}" + (f" +{len(blocked)-6} more" if len(blocked) > 6 else ""))
    if omitted:
        if not lines:
            lines += ["", "━━━ 🧪 REPORT DIAGNOSTICS ━━━"]
        lines.append(f"WATCH omitted by {cap}-item cap: {', '.join(omitted)}")
    return lines


def _watch_lines(summary):
    watch_2 = [str(t).upper() for t in (summary.get("watch_2", []) or [])]
    detail_by_ticker = {}
    for item in summary.get("high_candidates", []) or []:
        if not isinstance(item, dict):
            continue
        ticker = _row_ticker(item)
        if ticker and str(item.get("action", "")).upper() == "WATCH":
            detail_by_ticker[ticker] = item
    watch_rows = []
    for ticker in watch_2 + sorted(detail_by_ticker):
        watch_rows.append(detail_by_ticker.get(ticker, {"ticker": ticker, "action": "WATCH"}))
    return watch_list_block({"watch_2": watch_2, "high_candidates": watch_rows}, open_tickers=_open_tickers(summary), cap=summary.get("watching_cap", 15))

def _news_lines(summary):
    candidate_tickers = {str(x.get("ticker", "")).upper() for x in summary.get("high_candidates", []) or []}
    candidate_tickers |= {str(x.get("ticker", "")).upper() for x in summary.get("exit_results", []) or []}
    candidate_tickers |= {str(x.get("ticker", x.get("symbol", ""))).upper() for x in summary.get("buys", []) or []}
    news = []
    for c in summary.get("catalysts", []) or []:
        t = str(c.get("ticker", "")).upper()
        if t and t not in {"SPY", "QQQ", "DIA"} and (not candidate_tickers or t in candidate_tickers):
            news.append(f"{_ticker_label(t, c)} — {_short_reason(c.get('reason', 'Recent news'))}")
    news = list(dict.fromkeys(news))
    if not news:
        return []
    lines = ["", f"━━━ 📰 NEWS ({len(news)}) ━━━", ""]
    for i, item in enumerate(news, 1):
        lines += [f"{i}. {item}", ""]
    return lines


def _build_report(summary):
    summary = summary or {}
    buys = summary.get("buys", []) or []
    sells = [r for r in summary.get("exit_results", []) or [] if r.get("action") == "SELL"]
    high = summary.get("high_candidates", []) or []
    holds = _unique([r for r in summary.get("exit_results", []) or [] if r.get("action") == "HOLD"])
    hold_count = len(holds)
    waiting_count = len(_unique([h for h in high if str(h.get("action", "")).upper() == "WAIT" and "PULLBACK" in str(h.get("reason", "")).upper()]))
    pending_count = len(atlas_db.get_pending_fill_trades())

    before_scan_signal_id = summary.get("_before_scan_signal_id")
    advisory_decisions = _current_cycle_advisory_decisions(before_scan_signal_id, high=high, summary=summary)
    buy_now_tickers = _buy_now_tickers(before_scan_signal_id, high=high, summary=summary)
    advisory_routing = _current_cycle_advisory_routing(
        before_scan_signal_id, high=high, summary=summary,
        buy_now_tickers=buy_now_tickers, decisions=advisory_decisions)
    summary["advisory_routing_diagnostics"] = advisory_routing.diagnostics()
    # Current-cycle WATCH belongs only to the watch path; preserve existing watch inputs.
    summary["watch_2"] = list(dict.fromkeys(
        [str(t).upper() for t in (summary.get("watch_2") or [])] +
        [decision.ticker for decision in advisory_routing.watch]))
    lines = _header_lines(summary, hold_count)
    lines += _sell_now_lines(summary)
    lines += _position_risk_alert_lines(summary)
    lines += _review_now_lines(summary)
    lines += _macro_watch_lines(summary)
    lines += _holding_lines(summary)
    lines += _profit_protection_lines(summary)
    lines += _profit_protection_v2_lines(summary)
    lines += _pending_broker_confirmation_lines(summary)
    lines += _buy_now_lines(summary, before_scan_signal_id, high=high)
    lines += _actions_lines(buys, sells, summary, before_scan_signal_id, high=high, buy_now_tickers=buy_now_tickers, decisions=advisory_decisions, routing=advisory_routing)
    lines += _advisory_action_lines(before_scan_signal_id, high=high, summary=summary, decisions=advisory_decisions, routing=advisory_routing)
    lines += _waiting_lines(high, suppress_tickers=buy_now_tickers, summary=summary)
    lines += _gap_breakout_lines(summary)
    lines += _intraday_breakout_lines(summary)
    lines += _gates_lines(high)
    lines += _watch_lines(summary)
    lines += _intraday_diagnostic_lines(summary, before_scan_signal_id=before_scan_signal_id, high=high, buy_now_tickers=buy_now_tickers)
    return _naturalize_report("\n".join(lines))


def _pending_price_positive(value):
    try:
        return float(value) > 0
    except Exception:
        return False


def _pending_pullback_has_valid_prices(row):
    row = row or {}
    payload = _extract_payload(row)
    trigger = row.get("trigger_price") or payload.get("trigger_price")
    entry = row.get("entry_price") or row.get("entry") or payload.get("entry_price") or payload.get("entry") or trigger
    return _pending_price_positive(trigger) and _pending_price_positive(entry)


def _pending_pullback_visible_in_status(row):
    row = row or {}
    if not _pending_pullback_has_valid_prices(row):
        return False
    text = " ".join(str(row.get(k) or "") for k in ("status", "signal", "signal_json"))
    if "TOO HOT" in text.upper() or "TOO EXTENDED" in text.upper():
        return False
    raw_pct = row.get("pct_over_ema")
    try:
        pct = float(raw_pct) if raw_pct not in (None, "") else None
    except Exception:
        pct = None
    # The quick scan-start status intentionally avoids provider calls; suppress rows
    # whose stored pullback state already proves the ticker is >10% extended/hot.
    return not (pct is not None and pct > 10)


def _ensure_trade_price_cache_columns():
    try:
        conn = atlas_db.get_connection()
        cur = conn.cursor()
        cols = {row[1] for row in cur.execute("PRAGMA table_info(trades)").fetchall()}
        for col, ddl in {
            "current_price": "ALTER TABLE trades ADD COLUMN current_price REAL",
            "last_price": "ALTER TABLE trades ADD COLUMN last_price REAL",
            "last_price_at": "ALTER TABLE trades ADD COLUMN last_price_at DATETIME",
        }.items():
            if col not in cols:
                cur.execute(ddl)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[intraday] trade price cache migration skipped: {e}")


def _cache_open_trade_prices(trades):
    if not trades:
        return
    _ensure_trade_price_cache_columns()
    try:
        conn = atlas_db.get_connection()
        cur = conn.cursor()
        for trade in trades:
            cur.execute(
                """
                UPDATE trades
                   SET current_price=?, last_price=?, last_price_at=datetime('now'), updated_at=datetime('now')
                 WHERE ticker=? AND status='OPEN'
                """,
                (float(trade.current_price), float(trade.current_price), trade.ticker.upper()),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[intraday] trade price cache update skipped: {e}")

    # P0L-9/P0L-10 STAGING dual-write: valuation_marks, fired only AFTER the
    # legacy price-cache write above has already committed. Never fatal -- a
    # failure here cannot undo or block the legacy cache write. P0L-10
    # hardening: missing price_source is NEVER defaulted to live_provider.
    # If the caller (trade object) does not explicitly set price_source, we
    # pass None through so _dualwrite_valuation_mark() applies its own
    # conservative 'stale_cache' + is_fallback=1 default and logs a WARN
    # invariant -- silence must never be mistaken for a live quote.
    for trade in trades:
        price_source = getattr(trade, "price_source", None)  # None if caller never set it
        is_fallback = getattr(trade, "is_fallback", None)
        atlas_db._bk_safe(
            atlas_db._dualwrite_valuation_mark,
            trade.ticker.upper(), float(trade.current_price), price_source, is_fallback,
            legacy_trades_id=getattr(trade, "trade_id", None) or getattr(trade, "id", None),
        )


def _cached_open_trade_prices():
    _ensure_trade_price_cache_columns()
    try:
        conn = atlas_db.get_connection()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT ticker, current_price, last_price
              FROM trades
             WHERE status='OPEN'
            """
        ).fetchall()
        conn.close()
        return {str(r["ticker"] or "").upper(): dict(r) for r in rows}
    except Exception:
        return {}


def _quick_status_portfolio_footer(open_rows):
    cached_prices = _cached_open_trade_prices()
    total_invested = 0.0
    current_value = 0.0
    for row in open_rows or []:
        ticker = str(row.get("ticker") or "").upper()
        shares = _num(row.get("quantity") or row.get("shares"), 0.0)
        entry = _num(row.get("entry_price") or row.get("price"), 0.0)
        cached = cached_prices.get(ticker, {})
        pa = resolve_price_authority(ticker, entry, cached_price=cached.get("current_price") or cached.get("last_price"), cached_timestamp=cached.get("last_price_at"))
        if pa.get("is_valuation_valid"):
            total_invested += entry * shares
            current_value += _num(pa.get("valuation_price")) * shares
    blended_roi_dollar = current_value - total_invested
    blended_roi_pct = (blended_roi_dollar / total_invested * 100.0) if total_invested else 0.0
    return [
        "─────────────────────",
        f"💼 Total Invested {SOURCE_RENDER_CALC}: {_money(total_invested)}",
        f"📊 Current Value {SOURCE_RENDER_CALC}:  {_money(current_value)}",
        f"📈 Blended ROI {SOURCE_RENDER_CALC}:    {_fmt_pct(blended_roi_pct, signed=True, decimals=1)} ({_signed_money(blended_roi_dollar)})",
    ]


def _quick_status_report(reason="scan in progress"):
    """Fast no-provider Telegram body for long scans/overlap. Avoids price APIs."""
    open_rows = atlas_db.get_open_positions()
    pending_rows = [
        row for row in atlas_db.get_pending_pullbacks(status="WAITING")
        if _pending_pullback_visible_in_status(row)
    ]
    fill_rows = atlas_db.get_pending_fill_trades()
    lines = [
        f"⏳ ATLAS INTRADAY STATUS — {reason}",
        "",
        f"💼 Holding: {len(open_rows)}",
    ]
    for row in open_rows:
        t = str(row.get("ticker") or "?").upper()
        lines.append(f"   • {t} entry {_price(row.get('price') or row.get('entry_price'))} stop {_price(row.get('stop_loss'))}")
    if open_rows:
        lines += ["", *_quick_status_portfolio_footer(open_rows)]
    if fill_rows:
        lines += ["", f"🔔 Confirm at broker: {len(fill_rows)}"]
        for row in fill_rows[:4]:
            t = str(row.get("ticker") or "?").upper()
            lines.append(f"   • {t} buy {_price(row.get('entry_price'))}")
    lines += ["", f"🎣 Waiting for dip: {len(pending_rows)}"]
    for row in pending_rows[:8]:
        t = str(row.get("ticker") or "?").upper()
        lines.append(f"   • {t} trigger {_price(row.get('trigger_price'))}")
    lines += ["", "Full scan still running; this status is intentionally no-provider/no-handoff."]
    return "\n".join(lines)

def _send_telegram_async(message, label="atlas"):
    """Spawn an independent sender so Telegram/network latency cannot block scan/import."""
    msg_path = f"/tmp/atlas_intraday_msg_{os.getpid()}_{int(time.time() * 1000)}.txt"
    with open(msg_path, "w") as f:
        f.write(str(message or ""))
    code = (
        "import os,sys; sys.path.insert(0, '/Users/yasser/scripts'); "
        "from atlas_notify import send_telegram; "
        "p=sys.argv[1]; label=sys.argv[2]; "
        "msg=open(p).read(); "
        "ok=send_telegram(msg,label=label,parse_mode='',print_fallback=True); "
        "print(f'[{label}] subprocess_send_ok={ok}'); "
        "os.unlink(p) if os.path.exists(p) else None"
    )
    subprocess.Popen(
        [sys.executable, "-c", code, msg_path, label],
        stdout=open("/Users/yasser/scripts/atlas_intraday.log", "a"),
        stderr=open("/Users/yasser/scripts/atlas_intraday.err.log", "a"),
        close_fds=True,
    )
    return None


def run_intraday():
    cli_force = "--force" in sys.argv
    cli_live = "--live" in sys.argv
    explicit_dry_run = "--dry-run" in sys.argv
    cli_dry_run = explicit_dry_run or (cli_force and not cli_live)
    if cli_dry_run and not cli_live:
        global LOCK_PATH
        LOCK_PATH = os.environ.get("ATLAS_INTRADAY_LOCK_PATH") or STAGING_LOCK_PATH
    now = datetime.datetime.now()
    print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] Atlas intraday loop starting...")
    if cli_force and cli_dry_run and not cli_live:
        print("[intraday] --force without --live: verification dry-run enforced; production DB writes and Telegram sends suppressed")
        print(f"[intraday] dry-run lock path: {LOCK_PATH}")
    elif cli_force and cli_live:
        print("[intraday] --force --live: live forced run enabled; DB writes and Telegram sends allowed")

    # Market hours gate — skip on weekends and NYSE holidays unless --force is passed
    if not cli_force:
        _mh_ok, _mh_reason = is_market_hours()
        if not _mh_ok:
            print(f"[intraday] {_mh_reason} — skipping run")
            return {"skipped": True, "reason": _mh_reason}

    lock_fd = _acquire_run_lock()
    if lock_fd is None:
        print(f"[intraday] overlap guard: another atlas_intraday run is still active ({LOCK_PATH}); sending status and exiting cleanly.")
        try:
            if not cli_dry_run:
                _quick_status_report("previous scan still running")
                # Status/heartbeat Telegram intentionally disabled: overlap logic preserved.
                print("[intraday] overlap status telegram suppressed")
            else:
                print("[intraday] dry-run: overlap status telegram suppressed")
        except Exception as e:
            print(f"[intraday] overlap status telegram failed (non-fatal): {e}")
        return {"skipped": True, "reason": "previous intraday run still active"}
    try:
        signal.alarm(MAX_INTRADAY_RUNTIME_SECONDS)
        return _run_intraday_locked(now, force=cli_force, dry_run=cli_dry_run)
    finally:
        signal.alarm(0)
        _release_run_lock(lock_fd)




def _make_prescan_timing_wrapper(label, func):
    def _wrapped(*args, **kwargs):
        section = "pre_scan_market_scout_candidates" if label == "market_scout_candidates" else f"pre_scan_{label}"
        start = time.perf_counter()
        print(f"[TIMING] {datetime.datetime.now().isoformat(timespec='seconds')} section={section} event=start")
        try:
            return func(*args, **kwargs)
        finally:
            print(f"[TIMING] {datetime.datetime.now().isoformat(timespec='seconds')} section={section} event=end elapsed={time.perf_counter() - start:.3f}s")
    return _wrapped


def _install_prescan_timing(atlas_manage):
    """Temporarily instrument major atlas_manage pre-scan blocks without changing strategy logic."""
    patches = []

    def patch_attr(obj, attr, label):
        try:
            original = getattr(obj, attr)
        except Exception:
            return
        if not callable(original):
            return
        setattr(obj, attr, _make_prescan_timing_wrapper(label, original))
        patches.append((obj, attr, original))

    patch_attr(getattr(atlas_manage, "acct", None), "get_account_summary", "account_summary")
    patch_attr(getattr(atlas_manage, "port", None), "run_exits", "run_exits")
    patch_attr(atlas_manage, "check_regime", "regime_check")
    patch_attr(atlas_manage, "check_macro_context", "macro_context")
    patch_attr(atlas_manage, "load_candidates", "market_scout_candidates")
    patch_attr(getattr(atlas_manage, "atlas_db", None), "get_pending_pullbacks", "pending_pullbacks_query")
    patch_attr(getattr(atlas_manage, "atlas_db", None), "get_ema_retry_candidates", "ema_retry_query")
    patch_attr(getattr(atlas_manage, "atlas_db", None), "get_trades", "held_trades_query")

    def restore():
        for obj, attr, original in reversed(patches):
            try:
                setattr(obj, attr, original)
            except Exception:
                pass

    return restore

def _run_intraday_locked(now, force=False, dry_run=False):
    ok, gate_detail = is_market_hours()
    if not ok and not force:
        print(f"[intraday] market-hours gate: {gate_detail}; exiting cleanly with no scan/trade/Telegram.")
        return {"skipped": True, "reason": gate_detail}
    if not ok and force:
        print(f"[intraday] market-hours gate bypassed by --force: {gate_detail}")
    else:
        print(f"[intraday] market-hours gate: {gate_detail}")
    try:
        if not dry_run:
            _quick_status_report("scan starting")
            # Status/heartbeat Telegram intentionally disabled: scan-start logic preserved.
            print("[intraday] start status telegram suppressed")
        else:
            print("[intraday] dry-run: start status telegram suppressed")
    except Exception as e:
        print(f"[intraday] start status telegram failed (non-fatal): {e}")

    stream_status = None
    if False and atlas_stream is not None:
        try:
            stream_status = atlas_stream.start_background(max_reconnects=3)
            print(f"[intraday] stream status: {stream_status}")
        except Exception as e:
            stream_status = {"started": False, "fallback": True, "reason": str(e)[:160]}
            print(f"[intraday] stream unavailable; polling continues: {e}")

    import atlas_manage
    staging_db = os.environ.get("ATLAS_STAGING_DB") or os.environ.get("ATLAS_DB")
    force_dryrun_temp_db = None
    production_db = os.path.realpath("/Users/yasser/scripts/atlas.db")
    env_db_is_production = bool(staging_db) and os.path.realpath(staging_db) == production_db
    if force and dry_run and (not staging_db or env_db_is_production):
        try:
            import shutil
            source_db = staging_db or getattr(atlas_db, "DB_PATH", "/Users/yasser/scripts/atlas.db")
            force_dryrun_temp_db = f"/tmp/atlas_intraday_force_dryrun_{os.getpid()}.db"
            shutil.copy2(source_db, force_dryrun_temp_db)
            staging_db = force_dryrun_temp_db
            print(f"[intraday] forced dry-run DB isolated: {source_db} -> {staging_db}")
        except Exception as e:
            force_dryrun_temp_db = None
            print(f"[intraday] forced dry-run DB isolation failed; aborting before scan: {e}")
            return {"skipped": True, "reason": "forced dry-run DB isolation failed"}
    if staging_db:
        try:
            atlas_db.DB_PATH = staging_db
            if hasattr(atlas_manage, "atlas_db"):
                atlas_manage.atlas_db.DB_PATH = staging_db
            if hasattr(atlas_manage, "acct"):
                atlas_manage.acct.DB_PATH = staging_db
            if hasattr(atlas_manage, "port"):
                if hasattr(atlas_manage.port, "atlas_db"):
                    atlas_manage.port.atlas_db.DB_PATH = staging_db
                if hasattr(atlas_manage.port, "acct"):
                    atlas_manage.port.acct.DB_PATH = staging_db
        except Exception as e:
            print(f"[intraday] staging DB override warning: {e}")
    # Report-first safety: the full intraday Telegram report must be generated from
    # the base scan before sector-sweep peer enrichment can consume the launchd
    # window. This does not modify sector-sweep logic; it disables the sweep trigger
    # for this report-producing run so peer enrichment can be run later/skipped.
    restore_sector_sweep_trigger = None
    if os.environ.get("ATLAS_INTRADAY_REPORT_FIRST", "1") != "0":
        try:
            original_sector_sweep_trigger = getattr(atlas_manage.port, "sector_catalyst_sweep_trigger", None)
            if callable(original_sector_sweep_trigger):
                restore_sector_sweep_trigger = original_sector_sweep_trigger
                atlas_manage.port.sector_catalyst_sweep_trigger = lambda *args, **kwargs: None
                print("[intraday] report-first mode: sector sweep peer enrichment deferred until after Telegram report")
        except Exception as e:
            print(f"[intraday] report-first sector-sweep deferral unavailable (non-fatal): {e}")
    args = SimpleNamespace(tickers=[], file=None, live=not dry_run, exits_only=False, json=False)
    perme_flags = _load_perme_flags_from_rag()
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    scan_done = {"done": False}

    def _send_interim_report_if_slow():
        if scan_done.get("done"):
            return
        try:
            if not dry_run:
                interim = _quick_status_report("full scan still running >180s")
                # Heartbeat Telegram intentionally disabled: keep timing/report build, suppress noisy send.
                print("[intraday] interim heartbeat telegram suppressed")
            else:
                print("[intraday] dry-run: interim telegram suppressed")
        except Exception as e:
            print(f"[intraday] interim heartbeat handling failed (non-fatal): {e}")

    try:
        _before_scan_signal_id = atlas_db.get_max_signal_id()
        print(f"[intraday] signal high-water before scan id={_before_scan_signal_id}")
    except Exception as e:
        _before_scan_signal_id = 0
        print(f"[intraday] signal high-water capture failed; falling back to 15m window: {e}")

    interim_timer = threading.Timer(180.0, _send_interim_report_if_slow)
    interim_timer.daemon = True
    interim_timer.start()
    restore_prescan_timing = _install_prescan_timing(atlas_manage)
    try:
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            summary = atlas_manage.run(args)
    finally:
        try:
            restore_prescan_timing()
        except Exception:
            pass
        scan_done["done"] = True
        try:
            interim_timer.cancel()
        except Exception:
            pass

    out = stdout_buf.getvalue()
    err = stderr_buf.getvalue()
    if out:
        print(out, end="" if out.endswith("\n") else "\n")
    if err:
        print("Errors/Warnings:", err)

    if not isinstance(summary, dict):
        print("WARNING: Could not get structured intraday summary; not asserting an action.")
        summary = getattr(atlas_manage, "LAST_RUN_SUMMARY", {}) or {}
    summary["_before_scan_signal_id"] = _before_scan_signal_id
    summary["perme_flags"] = perme_flags
    summary["perme_report_context"] = dict(_PERME_REPORT_CONTEXT)
    if stream_status is not None:
        summary["stream_status"] = stream_status

    buys = summary.get("buys", []) or []
    sells = summary.get("sells", []) or []
    if buys or sells:
        print(f"Result: ACTION - {len(buys)} BUY(S), {len(sells)} SELL(S). See Vault.")
    else:
        print("Result: DO NOTHING. No new buys, no exits this cycle.")

    report_msg = _build_report(summary)
    print("\n[intraday] telegram report body begin")
    print(report_msg)
    print("[intraday] telegram report body end")

    # P0L-9/P0L-10 STAGING dual-write: report_snapshots. Preserves the exact
    # report text as rendered (no re-derivation), independent of send
    # outcome. Fired AFTER the report text is finalized, never fatal -- a
    # failure here can never block or alter the Telegram send below.
    # P0L-10 hardening: inputs_manifest_json now includes price_source and
    # is_fallback for every priced (open-position) ticker line, sourced from
    # the most recent valuation_marks row per ticker -- never inferred or
    # defaulted to live_provider here either.
    def _bk_emit_report_snapshot(cur):
        import hashlib as _hashlib
        raw_sha = _hashlib.sha256(report_msg.encode("utf-8")).hexdigest()
        priced_tickers = {}
        try:
            open_trades_rows = cur.execute(
                "SELECT id, ticker FROM trades WHERE status='OPEN'"
            ).fetchall()
            for trade_id, ticker in open_trades_rows:
                vm_row = cur.execute(
                    """SELECT vm.price_source, vm.is_fallback, vm.price_decimal_text
                       FROM valuation_marks vm
                       JOIN position_lots pl ON pl.id = vm.lot_id
                       WHERE pl.legacy_trades_id = ?
                       ORDER BY vm.id DESC LIMIT 1""",
                    (trade_id,),
                ).fetchone()
                if vm_row:
                    priced_tickers[str(ticker).upper()] = {
                        "price_source": vm_row[0],
                        "is_fallback": bool(vm_row[1]),
                        "price_decimal_text": vm_row[2],
                    }
                else:
                    # No valuation_marks row exists at all for this ticker this
                    # cycle -- explicitly record as unknown/fallback, never
                    # silently omit it or imply a live price was used.
                    priced_tickers[str(ticker).upper()] = {
                        "price_source": "unknown_no_mark",
                        "is_fallback": True,
                        "price_decimal_text": None,
                    }
        except Exception as e:
            print(f"[dual_write] report snapshot price-provenance manifest build skipped: {e}")

        inputs_manifest = {
            "buy_count": len(summary.get("buys", []) or []),
            "sell_count": len([r for r in (summary.get("exit_results") or []) if r.get("action") == "SELL"]),
            "high_candidate_count": len(summary.get("high_candidates", []) or []),
            "dry_run": bool(dry_run),
            "priced_tickers": priced_tickers,
        }
        cur.execute(
            """INSERT INTO report_snapshots
               (report_type, generated_at, raw_body_text, raw_body_sha256,
                inputs_manifest_json, dry_run)
               VALUES (?,?,?,?,?,?)""",
            ("intraday", atlas_db._now(), report_msg, raw_sha,
             __import__("json").dumps(inputs_manifest), 1 if dry_run else 0),
        )

    atlas_db._bk_safe(_bk_emit_report_snapshot)

    try:
        if not dry_run:
            # P0I-2: consolidated main report send to Atlas DM/admin route only;
            # group/topic vars no longer used here. Proactive ALERT/SELL DM below is unchanged.
            ok = send_telegram(
                report_msg,
                chat_id=_owner_chat_id(),
                message_thread_id=None,
            )
            print(f"[intraday] telegram report success={ok}")
            # Proactive DM for urgent position alerts
            alerts = [r for r in (summary.get("exit_results") or []) if str(r.get("action") or "").upper() in ("ALERT", "SELL")]
            if alerts:
                import time as _time
                _now = _time.time()
                try:
                    open_tickers = {str(p.get("ticker") or "").upper() for p in (atlas_db.get_open_positions() or [])}
                except Exception:
                    open_tickers = None  # unknown — do not incorrectly exclude if lookup fails
                dm_parts = []
                for a in alerts:
                    ticker = a.get("ticker", "?")
                    action_str = str(a.get("action", "?")).upper()
                    # Re-check ALERT rows are still OPEN before proactive DM send (closes race
                    # where a later stop-hit SELL in the same cycle already closed the ticker).
                    # SELL rows are exempt: run_exits() closes the position as part of producing
                    # this exact SELL row, so it is expected to be absent from get_open_positions().
                    if action_str != "SELL" and open_tickers is not None and str(ticker).upper() not in open_tickers:
                        print(f"[intraday] proactive DM skip {ticker}: no longer OPEN")
                        continue
                    # Generic macro-caution ALERT rows are MACRO WATCH — report-only, no DM.
                    severity = classify_alert_severity(a, summary)
                    if severity == "MACRO_WATCH":
                        print(f"[intraday] proactive DM skip {ticker}: classified MACRO_WATCH (generic macro caution)")
                        continue
                    # SELL always fires immediately — no cooldown
                    if action_str == "SELL":
                        dm_parts.append(a)
                        continue
                    # ALERT: 60-minute cooldown, reset if price moves >0.5% closer to stop
                    last = float(a.get("last") or 0)
                    stop = float(a.get("stop") or 0)
                    current_dist = (last - stop) / stop if stop else 1.0
                    cd = _ALERT_COOLDOWN.get(ticker)
                    if cd:
                        mins_since = (_now - cd["ts"]) / 60
                        dist_worsened = cd["dist"] - current_dist
                        if mins_since < 60 and dist_worsened < 0.005:
                            print(f"[intraday] ALERT cooldown active for {ticker} ({mins_since:.0f}m since last DM)")
                            continue
                    _ALERT_COOLDOWN[ticker] = {"ts": _now, "dist": current_dist}
                    dm_parts.append(a)
                if dm_parts:
                    dm_lines = ["🚨 POSITION ALERT — immediate review required\n"]
                    for a in dm_parts:
                        ticker = a.get("ticker", "?")
                        action_str = a.get("action", "?")
                        reason = a.get("reason") or ""
                        dm_lines.append(f"{action_str}  {ticker}: {reason[:200]}")
                    dm_msg = "\n".join(dm_lines)
                    try:
                        owner_chat_id = _owner_chat_id()
                        if owner_chat_id:
                            ok_dm = send_telegram(dm_msg, chat_id=owner_chat_id)
                            print(f"[intraday] proactive DM sent success={ok_dm}")
                    except Exception as _e:
                        print(f"[intraday] proactive DM error: {_e}")
        else:
            print("[intraday] dry-run: final telegram send suppressed")
            print("[intraday] telegram report success=True")
    except Exception as e:
        print(f"[intraday] telegram report failed (non-fatal): {e}")

    if force_dryrun_temp_db:
        try:
            os.unlink(force_dryrun_temp_db)
            print(f"[intraday] forced dry-run temp DB removed: {force_dryrun_temp_db}")
        except Exception as e:
            print(f"[intraday] forced dry-run temp DB cleanup warning: {e}")


if __name__ == "__main__":
    run_intraday()
