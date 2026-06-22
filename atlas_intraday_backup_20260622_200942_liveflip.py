import os, sys, datetime, contextlib, io, re, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import requests

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


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[intraday] telegram report skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID unset")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = []
    text = message
    while len(text) > 3800:
        cut = text.rfind("\n", 0, 3800)
        if cut < 1000:
            cut = 3800
        chunks.append(text[:cut])
        text = text[cut:].lstrip()
    chunks.append(text)
    message_ids = []
    max_attempts = int(os.environ.get("ATLAS_TELEGRAM_ATTEMPTS", "3"))
    timeout = float(os.environ.get("ATLAS_TELEGRAM_TIMEOUT", "25"))
    backoffs = [2, 5]
    for idx, chunk in enumerate(chunks, 1):
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "Markdown"}
        last_error = None
        for attempt in range(1, max_attempts + 1):
            try:
                r = requests.post(url, json=payload, timeout=(5, timeout))
                if r.status_code != 200:
                    raise RuntimeError(f"Telegram HTTP {r.status_code}: {r.text[:300]}")
                data = r.json()
                if not data.get("ok"):
                    raise RuntimeError(f"Telegram rejected chunk {idx}: {data}")
                message_id = data.get("result", {}).get("message_id")
                message_ids.append(message_id)
                print(f"[intraday] telegram chunk {idx}/{len(chunks)} sent on attempt {attempt}: message_id={message_id}")
                break
            except Exception as e:
                last_error = e
                if attempt >= max_attempts:
                    raise RuntimeError(f"Telegram chunk {idx}/{len(chunks)} failed after {max_attempts} attempts: {e}")
                delay = backoffs[min(attempt - 1, len(backoffs) - 1)]
                print(f"[intraday] telegram chunk {idx}/{len(chunks)} attempt {attempt} failed: {e}; retrying in {delay}s")
                time.sleep(delay)
        else:
            raise RuntimeError(f"Telegram chunk {idx}/{len(chunks)} failed: {last_error}")
    print(f"[intraday] telegram report sent: chunks={len(chunks)} message_ids={message_ids}")
    return True


def _money(value):
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "n/a"


def _fmt_sells(sells):
    if not sells:
        return "none"
    lines = []
    for s in sells:
        lines.append(f"{s.get('ticker','?')} x{s.get('qty','?')} @ {s.get('price','?')} — {s.get('reason','')}")
    return "\n".join(lines)


def _fmt_buys(buys):
    if not buys:
        return "none"
    lines = []
    for b in buys:
        ticker = b.get("ticker") or b.get("symbol") or "?"
        shares = b.get("shares", "?")
        entry = b.get("entry", "?")
        reason = b.get("reason", "")
        lines.append(f"{ticker} {shares} sh @ {entry} — {reason}")
    return "\n".join(lines)


def _as_float(value):
    try:
        return float(value)
    except Exception:
        return None


def _fmt_dollars(value):
    value = _as_float(value)
    return "n/a" if value is None else f"${value:,.2f}"


def _explain_no_buy(ticker, score, reason):
    reason = (reason or "No buy conditions met").strip()
    m = re.search(r"Extended:\s*close\s*([0-9.]+)\s*>\s*10-EMA\s*([0-9.]+)\s*\+2%", reason, re.I)
    if m:
        price = float(m.group(1))
        ema = float(m.group(2))
        pct = ((price / ema) - 1.0) * 100.0 if ema else 0.0
        trigger = ema * 1.02
        return (f"⏸️ NO BUY — {ticker} ({score}): too extended, price ${price:,.2f} "
                f"= +{pct:.0f}% over 10-EMA ${ema:,.2f}. Buy trigger ≈ ${trigger:,.2f}.")
    if "insufficient" in reason.lower() and "ema" in reason.lower():
        return (f"⏸️ NO BUY — {ticker} ({score}): insufficient EMA10 data, so the pullback entry trigger "
                f"cannot be calculated yet. Buy trigger: wait for valid 10-EMA data.")
    if "risk-off" in reason.lower() or "regime" in reason.lower():
        return (f"⏸️ NO BUY — {ticker} ({score}): regime gate is risk-off. "
                f"Buy trigger: wait for RISK-ON regime and normal entry rules.")
    return f"⏸️ NO BUY — {ticker} ({score}): {reason}. Buy trigger: wait for the entry rule to clear."


def _fmt_top_candidate(h):
    ticker = h.get("ticker", "?")
    score = h.get("score", "?")
    action = str(h.get("action", "")).upper()
    reason = h.get("reason", "")
    if action == "BUY":
        return (f"🟢 BUY — {ticker} ({score}): entry {_fmt_dollars(h.get('entry'))}, "
                f"stop {_fmt_dollars(h.get('stop'))}, size {_fmt_dollars(h.get('cost'))}.")
    if action == "WAIT" and "WAITING FOR PULLBACK" in str(reason):
        return f"⏳ {reason}"
    if action == "SKIP" and str(reason).startswith("TOO EXTENDED"):
        return f"🚀 {reason}"
    if action == "EXPIRE" or "PULLBACK EXPIRED" in str(reason):
        return f"⌛ {reason}"
    return _explain_no_buy(ticker, score, reason)


def _build_report(summary):
    now_et = datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%H:%M")
    account = summary.get("account", {}) or {}
    regime = "RISK-ON" if summary.get("regime_ok") else "RISK-OFF"
    regime_detail = summary.get("regime_detail", "n/a")
    buys = summary.get("buys", []) or []
    sells = summary.get("sells", []) or []
    result = "ACTION" if (buys or sells) else "DO NOTHING"

    lines = [
        f"🦅 *Atlas Intraday — {now_et} ET*",
        f"*Regime:* {regime} ({regime_detail})",
        f"*Account:* equity {_money(account.get('equity'))}, cash {_money(account.get('cash'))}, open positions {summary.get('open_positions_count', 0)}",
        "",
        "*🟢 BUY executed:*",
        _fmt_buys(buys),
        "",
        "*🔴 SELL executed:*",
        _fmt_sells(sells),
        "",
        "*⭐ Top candidates:*",
    ]

    high = summary.get("high_candidates", []) or []
    if high:
        for h in high:
            lines.append(_fmt_top_candidate(h))
    else:
        lines.append("none")

    expired_pullbacks = summary.get("expired_pullbacks", []) or []
    if expired_pullbacks:
        lines += ["", "*⌛ Pullbacks expired:*"]
        for e in expired_pullbacks:
            lines.append(e.get("reason", ""))

    lines += ["", "*⚪ WATCH (2/4):*"]
    watch_2 = summary.get("watch_2", []) or []
    lines.append(", ".join(watch_2) if watch_2 else "none")

    lines += ["", "*🧠 Catalysts firing:*"]
    catalysts = summary.get("catalysts", []) or []
    if catalysts:
        for c in catalysts:
            lines.append(f"{c.get('ticker','?')} — {c.get('reason','Recent news')}")
    else:
        lines.append("none")

    lines += ["", f"*Result:* {result}"]
    return "\n".join(lines)


def run_intraday():
    now = datetime.datetime.now()
    print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] Atlas intraday loop starting...")

    import atlas_manage
    args = SimpleNamespace(tickers=[], file=None, live=False, exits_only=False, json=False)
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
