import os, sys, datetime, contextlib, io, re, time, errno, signal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import requests
from atlas_notify import send_telegram

SCRIPTS_DIR = "/Users/yasser/scripts"
sys.path.insert(0, SCRIPTS_DIR)

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
    detail = str(summary.get("regime_detail") or "")
    m = re.search(r"SPY\s+([0-9.]+)", detail)
    spy = _whole(m.group(1)) if m else "$?"
    if "WEAK" in detail.upper() or "UNKNOWN" in detail.upper() or "UNAVAILABLE" in detail.upper():
        label = "⚠️ WEAK — cautious (half size)"
    elif summary.get("regime_ok"):
        label = "🟢 RISK-ON ✅"
    else:
        label = "⚠️ WEAK — cautious (half size)"
    return f"📡 Market: {label} (SPY {spy})"


def _analyst_tag(item):
    insight = item.get("analyst_insight") or {}
    rating = item.get("analyst_rating") or {}
    tag = insight.get("summary") if isinstance(insight, dict) else None
    if not tag and isinstance(rating, dict) and rating.get("pt_raised"):
        tag = rating.get("note")
    if not tag and isinstance(rating, dict) and rating.get("note"):
        tag = rating.get("note")
    return _short_reason(tag) if tag else None


def _buy_lines(buys):
    buys = _unique(buys)
    lines = ["", "🟢 BUY NOW 🛒 (orders placed this cycle)"]
    if not buys:
        lines.append("✅ No buys this cycle")
        return lines
    for i, b in enumerate(buys, 1):
        ticker = str(b.get("ticker") or b.get("symbol") or "?").upper()
        score = b.get("score") or "?/4"
        score_txt = f"{_pillar_num(score)}/4"
        entry = _num(b.get("entry"))
        stop = _num(b.get("stop"))
        target = _num(b.get("target"))
        shares = int(_num(b.get("shares")))
        cost = _num(b.get("cost"), entry * shares)
        win_dollars = max((target - entry) * shares, 0)
        loss_dollars = max((entry - stop) * shares, 0)
        win_pct = ((target - entry) / entry * 100) if entry else 0
        loss_pct = ((entry - stop) / entry * 100) if entry else 0
        rvol = b.get("rvol")
        rvol_txt = "n/a" if rvol in (None, "") else f"{_num(rvol):.1f}"
        tag = _analyst_tag(b)
        lines += [
            f"{_ordinal(i)} {ticker} {_stars(score)} {score_txt} | 📊 RVOL {rvol_txt}🔥" + (f" | 🏦 {tag}" if tag else ""),
            f"   💵 Buy {_whole(entry)}  🛑 Stop {_whole(stop)}  🎯 Target {_whole(target)}",
            f"   🟢 If WINS → +{win_pct:.0f}% (+{_whole(win_dollars)}) | 🛑 If LOSES → −{loss_pct:.0f}% (−{_whole(loss_dollars)})",
            f"   ⚖️ {shares} sh (~{_whole(cost)})",
            f"   💡 {_short_reason(b.get('reason'))}",
        ]
    return lines


def _sell_lines(sells):
    sells = _unique(sells)
    lines = ["", "🔴 SELL NOW 💰 (exits this cycle)"]
    if not sells:
        lines.append("✅ No exits — holding all")
        return lines
    for i, s in enumerate(sells, 1):
        ticker = str(s.get("ticker") or "?").upper()
        shares = int(_num(s.get("qty") or s.get("shares")))
        entry = _num(s.get("entry"))
        out = _num(s.get("price"))
        pnl = (out - entry) * shares
        roi = ((out - entry) / entry * 100) if entry else 0
        icon = "✅" if pnl >= 0 else "❌"
        sign = "+" if pnl >= 0 else "−"
        lines += [
            f"{_ordinal(i)} {ticker} — SOLD {shares} sh @ {_whole(out)}",
            f"   📥 In {_whole(entry)} → 📤 Out {_whole(out)} | 📈 ROI {roi:+.0f}% ({sign}{_whole(abs(pnl))}) {icon}",
            f"   💡 {_short_reason(s.get('reason'))}",
        ]
    return lines


def _holding_lines(summary):
    holds = _unique([r for r in summary.get("exit_results", []) or [] if r.get("action") == "HOLD"])
    lines = ["", "💼 STOCK IN HAND 📂 (open positions)"]
    if not holds:
        lines.append("📭 No open positions")
        return lines
    for h in holds:
        ticker = str(h.get("ticker") or "?").upper()
        shares = int(_num(h.get("qty")))
        entry = _num(h.get("entry"))
        now = _num(h.get("last"))
        pnl = (now - entry) * shares
        roi = ((now - entry) / entry * 100) if entry else 0
        icon = "🟢" if pnl >= 0 else "🔴"
        sign = "+" if pnl >= 0 else "−"
        lines += [
            f"{icon} {ticker} {shares} sh | In {_whole(entry)} → Now {_whole(now)} | 📈 {roi:+.0f}% ({sign}{_whole(abs(pnl))})",
            f"   🛑 Stop {_whole(h.get('stop'))}  🎯 Target {_whole(h.get('target'))}",
        ]
    return lines


def _waiting_lines(high):
    waits = _unique([h for h in high if str(h.get("action", "")).upper() == "WAIT" and "PULLBACK" in str(h.get("reason", "")).upper()])
    lines = ["", "⏳ WAITING TO BUY 🎣 (want a dip first)"]
    if not waits:
        lines.append("✅ No dip-buy orders armed")
        return lines
    for h in waits:
        score = h.get("score") or "?/4"
        score_txt = f"{_pillar_num(score)}/4"
        now = h.get("price")
        if now is None:
            m = re.search(r"price \$([0-9.]+)", str(h.get("reason", "")))
            now = m.group(1) if m else 0
        pct = h.get("pct_over_ema")
        if pct is None:
            m = re.search(r"\+([0-9.]+)%", str(h.get("reason", "")))
            pct = m.group(1) if m else 0
        tag = _analyst_tag(h)
        lines.append(f"🔸 {str(h.get('ticker')).upper()} {_stars(score)} {score_txt} — buy {_whole(h.get('entry'))} (now {_whole(now)}, 🔺{_num(pct):.0f}% high)" + (f" | 🏦 {tag}" if tag else ""))
    return lines


def _too_hot_lines(high):
    hot = _unique([h for h in high if str(h.get("action", "")).upper() == "SKIP" and str(h.get("reason", "")).startswith("TOO EXTENDED")])
    if not hot:
        return ["", "🚀 TOO HOT — SKIP 🛑: ✅ None"]
    bits = []
    for h in hot:
        m = re.search(r"\+([0-9.]+)%", str(h.get("reason", "")))
        pct = m.group(1) if m else h.get("pct_over_ema", 0)
        bits.append(f"🔥 {str(h.get('ticker')).upper()} +{_num(pct):.0f}%")
    return ["", "🚀 TOO HOT — SKIP 🛑: " + " | ".join(bits)]


def _watch_lines(summary):
    watch = []
    for t in summary.get("watch_2", []) or []:
        if str(t).upper() not in {"SPY", "QQQ", "DIA"}:
            watch.append(f"⚪ {str(t).upper()} ⭐⭐ 2/4")
    return ["", "👀 WATCHING 🔍: " + (" | ".join(dict.fromkeys(watch)) if watch else "✅ None")]


def _news_lines(summary):
    candidate_tickers = {str(x.get("ticker", "")).upper() for x in summary.get("high_candidates", []) or []}
    candidate_tickers |= {str(x.get("ticker", "")).upper() for x in summary.get("exit_results", []) or []}
    candidate_tickers |= {str(x.get("ticker", x.get("symbol", ""))).upper() for x in summary.get("buys", []) or []}
    news = []
    for c in summary.get("catalysts", []) or []:
        t = str(c.get("ticker", "")).upper()
        if t and t not in {"SPY", "QQQ", "DIA"} and (not candidate_tickers or t in candidate_tickers):
            news.append(f"🗞️ {t} — {_short_reason(c.get('reason', 'Recent news'))}")
    return ["", "🧠 NEWS 📰: " + (" | ".join(dict.fromkeys(news)) if news else "✅ No fresh candidate/holding news")]


def _build_report(summary):
    now_et = datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%-I:%M %p")
    account = summary.get("account", {}) or {}
    buys = summary.get("buys", []) or []
    sells = [r for r in summary.get("exit_results", []) or [] if r.get("action") == "SELL"]
    high = summary.get("high_candidates", []) or []
    hold_count = len(_unique([r for r in summary.get("exit_results", []) or [] if r.get("action") == "HOLD"]))
    waiting_count = len(_unique([h for h in high if str(h.get("action", "")).upper() == "WAIT" and "PULLBACK" in str(h.get("reason", "")).upper()]))

    lines = [
        f"🦅 ATLAS INTRADAY 🦅  🕐 {now_et} ET",
        _market_line(summary),
        f"💰 Account: {_whole(account.get('equity'))} 💵 | Cash: {_whole(account.get('cash'))} 💸 | Holdings: {summary.get('open_positions_count', hold_count)} 📂",
    ]
    lines += _buy_lines(buys)
    lines += _sell_lines(sells)
    lines += _holding_lines(summary)
    lines += _waiting_lines(high)
    lines += _too_hot_lines(high)
    lines += _watch_lines(summary)
    lines += _news_lines(summary)
    lines += ["", f"🏁 BOTTOM LINE: Bought {len(_unique(buys))} 🛒, Sold {len(_unique(sells))} 💰. Holding {hold_count} 📂, {waiting_count} armed for a dip 🎣."]
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
