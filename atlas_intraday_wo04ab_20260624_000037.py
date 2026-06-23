import os, sys, datetime, contextlib, io, re, time, errno, signal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import requests
from atlas_notify import send_telegram
try:
    import atlas_stream
except Exception:
    atlas_stream = None

SCRIPTS_DIR = "/Users/yasser/scripts"
sys.path.insert(0, SCRIPTS_DIR)
import atlas_db

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
ET_TZ = ZoneInfo("America/New_York")
MARKET_OPEN_ET = datetime.time(9, 30)
MARKET_CLOSE_ET = datetime.time(16, 0)


LOCK_PATH = "/tmp/atlas_intraday.lock"


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


def _register_buy_line(ticker, shares, entry):
    return f"👉 register {ticker} buy qty={shares} price=${entry:.2f}"


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


def _header_lines(summary, hold_count):
    now_et = datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%-I:%M %p")
    account = summary.get("account", {}) or {}
    macro = summary.get("macro_context") or {}
    detail = str(summary.get("regime_detail") or "")
    m = re.search(r"SPY\s+([0-9.]+)", detail)
    spy = _price(m.group(1)) if m else "N/A"
    if "RISK-ON" in detail.upper() or summary.get("regime_ok"):
        regime = "🟢 RISK-ON"
    else:
        regime = "🔴 RISK-OFF"
    macro_note = ""
    if isinstance(macro, dict) and macro.get("cautious"):
        macro_note = f" · {macro.get('note') or '⚠️ macro caution'}"
    positions = summary.get("open_positions_count", hold_count)
    return [
        f"🦅 ATLAS INTRADAY — {now_et} ET",
        f"📡 {regime} · SPY {spy}{macro_note}",
        f"💰 Equity {_money(account.get('equity'))} · Cash {_money(account.get('cash'))} · {positions} positions",
    ]


def _actions_lines(buys, sells):
    buys = _unique(buys)
    sells = _unique(sells)
    lines = ["", "━━━ ACTIONS ━━━"]
    if buys:
        lines.append(f"🛒 BUY ({len(buys)}) — engine wants in")
        for b in buys:
            ticker = str(b.get("ticker") or b.get("symbol") or "?").upper()
            entry = _num(b.get("entry"))
            stop = _num(b.get("stop"))
            target = _num(b.get("target"))
            shares = int(_num(b.get("shares")))
            cost = _num(b.get("cost"), entry * shares)
            risk = b.get("risk_pct")
            win_pct = ((target - entry) / entry * 100) if entry else 0
            loss_pct = ((entry - stop) / entry * 100) if entry else 0
            risk_txt = "N/A" if risk in (None, "") else f"{_num(risk):.1f}%"
            lines += [
                "",
                f"🟢 {ticker:<5} buy {_price(entry)} · stop {_price(stop)} · target {_price(target)} · {risk_txt} risk",
                f"   ~{_money(cost)} · win +{win_pct:.0f}% / loss −{loss_pct:.0f}%",
                f"   {_register_buy_line(ticker, shares, entry)}",
            ]
    else:
        lines.append("🛒 BUY: none this cycle")
    if sells:
        lines.append(f"💰 SELL ({len(sells)}) — engine exiting")
        for s in sells:
            ticker = str(s.get("ticker") or "?").upper()
            shares = int(_num(s.get("qty") or s.get("shares")))
            entry = _num(s.get("entry"))
            out = _num(s.get("price"))
            proceeds = shares * out
            pnl = (out - entry) * shares
            roi = ((out - entry) / entry * 100) if entry else 0
            icon = "✅" if pnl >= 0 else "❌"
            lines += [
                "",
                f"🔴 {ticker:<5} sell ~{_money(proceeds)} · {_price(entry)} → {_price(out)}  {_fmt_pct(roi, signed=True)} ({_signed_money(pnl)}) {icon}",
                f"   💡 {_short_reason(s.get('reason'))}",
                f"   {_register_sell_line(ticker, shares, out)}",
            ]
    else:
        lines.append("💰 SELL: none — holding all")
    return lines


def _pending_confirmation_lines():
    rows = atlas_db.get_pending_fill_trades()
    if not rows:
        return ["", "━━━ 🔔 CONFIRM AT BROKER (0) ━━━", "✅ none"]
    lines = ["", f"━━━ 🔔 CONFIRM AT BROKER ({len(rows)}) ━━━", ""]
    for row in rows:
        ticker = str(row.get("ticker") or "?").upper()
        entry = _num(row.get("entry_price"))
        stop = _num(row.get("stop_loss"))
        target = _num(row.get("target_price"))
        shares = int(_num(row.get("quantity")))
        risk_pct = row.get("risk_pct")
        risk_txt = "N/A" if risk_pct in (None, "") else f"{_num(risk_pct):.1f}%"
        lines += [
            f"⏳ {ticker:<5} buy {_price(entry)} · stop {_price(stop)} · target {_price(target)} · {risk_txt} risk",
            f"   {_register_buy_line(ticker, shares, entry)}",
            "",
        ]
    return lines


def _holding_lines(summary):
    holds = _unique([r for r in summary.get("exit_results", []) or [] if r.get("action") == "HOLD"])
    lines = ["", f"━━━ 💼 HOLDING ({len(holds)}) ━━━"]
    if not holds:
        lines.append("📭 none")
        return lines
    for h in holds:
        ticker = str(h.get("ticker") or "?").upper()
        shares = int(_num(h.get("qty")))
        entry = _num(h.get("entry"))
        now = _num(h.get("last"))
        value = shares * now
        pnl = (now - entry) * shares
        roi = ((now - entry) / entry * 100) if entry else 0
        icon = "🟢" if pnl >= 0 else "🔴"
        lines += [
            "",
            f"{icon} {ticker:<5} ~{_money(value)}  {_price(entry)} → {_price(now)}  {_fmt_pct(roi, signed=True)} ({_signed_money(pnl)})",
            f"   🛑 {_price(h.get('stop'))}  🎯 {_price(h.get('target'))}",
        ]
    return lines


def _waiting_lines(high):
    waits = _unique([h for h in high if str(h.get("action", "")).upper() == "WAIT" and "PULLBACK" in str(h.get("reason", "")).upper()])
    lines = ["", f"━━━ 🎣 WAITING FOR DIP ({len(waits)}) ━━━", ""]
    if not waits:
        lines.append("✅ none")
        return lines
    for h in waits:
        ticker = str(h.get("ticker") or "?").upper()
        score = h.get("score") or "?/4"
        now = h.get("price")
        if now is None:
            m = re.search(r"price \$([0-9.]+)", str(h.get("reason", "")))
            now = m.group(1) if m else None
        pct = h.get("pct_over_ema")
        if pct is None:
            m = re.search(r"\+([0-9.]+)%", str(h.get("reason", "")))
            pct = m.group(1) if m else 0
        limit = h.get("entry")
        lines += [
            f"🔸 {ticker:<5} buy {_price(limit)} · now {_price(now)} (+{_num(pct):.0f}%)",
            f"   {_quality_tags(h, score)}",
            "",
        ]
    return lines


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
        lines += [f"{i}. {str(h.get('ticker')).upper():<5} +{_num(pct):.0f}% over EMA", ""]
    return lines


def _watch_lines(summary):
    watch = []
    for t in summary.get("watch_2", []) or []:
        s = str(t).upper()
        if s and s not in {"SPY", "QQQ", "DIA"}:
            watch.append(s)
    return ["", "👀 Watching: " + (" · ".join(dict.fromkeys(watch)) if watch else "none")]


def _news_lines(summary):
    candidate_tickers = {str(x.get("ticker", "")).upper() for x in summary.get("high_candidates", []) or []}
    candidate_tickers |= {str(x.get("ticker", "")).upper() for x in summary.get("exit_results", []) or []}
    candidate_tickers |= {str(x.get("ticker", x.get("symbol", ""))).upper() for x in summary.get("buys", []) or []}
    news = []
    for c in summary.get("catalysts", []) or []:
        t = str(c.get("ticker", "")).upper()
        if t and t not in {"SPY", "QQQ", "DIA"} and (not candidate_tickers or t in candidate_tickers):
            news.append(f"{t} — {_short_reason(c.get('reason', 'Recent news'))}")
    news = list(dict.fromkeys(news))
    if not news:
        return []
    lines = ["", f"━━━ 📰 NEWS ({len(news)}) ━━━", ""]
    for i, item in enumerate(news, 1):
        lines += [f"{i}. {item}", ""]
    return lines


def _build_report(summary):
    buys = summary.get("buys", []) or []
    sells = [r for r in summary.get("exit_results", []) or [] if r.get("action") == "SELL"]
    high = summary.get("high_candidates", []) or []
    holds = _unique([r for r in summary.get("exit_results", []) or [] if r.get("action") == "HOLD"])
    hold_count = len(holds)
    waiting_count = len(_unique([h for h in high if str(h.get("action", "")).upper() == "WAIT" and "PULLBACK" in str(h.get("reason", "")).upper()]))
    pending_count = len(atlas_db.get_pending_fill_trades())

    lines = _header_lines(summary, hold_count)
    lines += _actions_lines(buys, sells)
    lines += _pending_confirmation_lines()
    lines += _holding_lines(summary)
    lines += _waiting_lines(high)
    lines += _gates_lines(high)
    lines += _watch_lines(summary)
    lines += _news_lines(summary)
    confirm_bit = f" · {pending_count} to confirm" if pending_count else ""
    lines += ["", f"🏁 Bought {len(_unique(buys))} · Sold {len(_unique(sells))} · Holding {hold_count} · {waiting_count} armed{confirm_bit}"]
    return "\n".join(lines)

def run_intraday():
    now = datetime.datetime.now()
    print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] Atlas intraday loop starting...")

    lock_fd = _acquire_run_lock()
    if lock_fd is None:
        print(f"[intraday] overlap guard: another atlas_intraday run is still active ({LOCK_PATH}); exiting cleanly.")
        return {"skipped": True, "reason": "previous intraday run still active"}
    try:
        return _run_intraday_locked(now)
    finally:
        _release_run_lock(lock_fd)


def _run_intraday_locked(now):
    ok, gate_detail = is_market_hours()
    if not ok:
        print(f"[intraday] market-hours gate: {gate_detail}; exiting cleanly with no scan/trade/Telegram.")
        return {"skipped": True, "reason": gate_detail}
    print(f"[intraday] market-hours gate: {gate_detail}")

    stream_status = None
    if atlas_stream is not None:
        try:
            stream_status = atlas_stream.start_background(max_reconnects=3)
            print(f"[intraday] stream status: {stream_status}")
        except Exception as e:
            stream_status = {"started": False, "fallback": True, "reason": str(e)[:160]}
            print(f"[intraday] stream unavailable; polling continues: {e}")

    import atlas_manage
    args = SimpleNamespace(tickers=[], file=None, live=True, exits_only=False, json=False)
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
        summary = atlas_manage.run(args)

    out = stdout_buf.getvalue()
    err = stderr_buf.getvalue()
    if out:
        print(out, end="" if out.endswith("\n") else "\n")
    if err:
        print("Errors/Warnings:", err)

    if not isinstance(summary, dict):
        print("WARNING: Could not get structured intraday summary; not asserting an action.")
        summary = getattr(atlas_manage, "LAST_RUN_SUMMARY", {}) or {}
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

    try:
        ok = send_telegram(report_msg)
        print(f"[intraday] telegram report success={ok}")
    except Exception as e:
        print(f"[intraday] telegram report failed (non-fatal): {e}")


if __name__ == "__main__":
    run_intraday()
