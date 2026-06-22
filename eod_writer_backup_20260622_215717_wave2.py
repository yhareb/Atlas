"""
eod_writer.py
Runs at 4:05pm ET every trading day.
Reads today's signals from atlas.db, keeps only BUY and WATCH tickers,
and writes the handoff snapshot to the handoff table.
"""

import sys
import json
from datetime import datetime

sys.path.insert(0, "/Users/yasser/scripts")
import atlas_db
import atlas_portfolio as port

INDEX_ETF_BLOCKLIST = {"SPY", "QQQ", "DIA"}

def _score_label(score):
    try:
        return f"{int(score)}/4 Pillars"
    except Exception:
        txt = str(score or "0/4 Pillars")
        return txt if "/" in txt else f"{txt}/4 Pillars"


def _classify_signal(ticker, signal, score, rvol, entry, stop_loss, atr):
    if "BUY" not in str(signal):
        return "WATCH" if "WATCH" in str(signal) else "SKIP", str(signal)
    res = {
        "ticker": ticker,
        "signal": signal,
        "score": _score_label(score),
        "entry_price": float(entry or 0),
        "rvol": float(rvol or 0),
        "risk_card": {"stop_loss": float(stop_loss or 0), "daily_volatility_atr": float(atr or 0)},
    }
    try:
        decision = port.consider_buy(res, dry_run=True, manage_pending=False)
    except Exception as e:
        return "WATCH", f"DECISION UNAVAILABLE — {e}"
    action = decision.get("action")
    reason = decision.get("reason", "")
    if action == "BUY":
        return "BUY", reason
    if action == "WAIT":
        return "WAITING", reason
    if action == "SKIP" and str(reason).startswith("TOO EXTENDED"):
        return "TOO_EXTENDED", reason
    return "WATCH", reason


def generate_eod_handoff():
    conn = atlas_db.get_connection()
    cursor = conn.cursor()

    today = datetime.now().strftime('%Y-%m-%d')

    cursor.execute('''
        SELECT ticker, signal, score, rvol, entry_price, stop_loss, atr, timestamp
        FROM signals
        WHERE date(timestamp) = ?
        ORDER BY timestamp DESC
    ''', (today,))

    rows = cursor.fetchall()
    conn.close()

    handoff_data = {
        "date": today,
        "BUY": [],
        "WATCH": [],
        "DECISIONS": [],
        "last_scan": datetime.now().isoformat()
    }

    seen = set()
    for ticker, signal, score, rvol, entry, stop_loss, atr, _ts in rows:
        ticker = (ticker or "").upper()
        if not ticker or ticker in seen or ticker in INDEX_ETF_BLOCKLIST:
            continue
        seen.add(ticker)
        bucket, reason = _classify_signal(ticker, signal, score, rvol, entry, stop_loss, atr)
        handoff_data["DECISIONS"].append({"ticker": ticker, "decision": bucket, "reason": reason})
        if bucket == "BUY":
            handoff_data["BUY"].append(ticker)
        elif bucket in ("WATCH", "WAITING", "TOO_EXTENDED"):
            handoff_data["WATCH"].append(ticker)

    handoff_data["BUY"] = sorted(set(handoff_data["BUY"]))
    handoff_data["WATCH"] = sorted(set(handoff_data["WATCH"]))
    atlas_db.update_handoff(today, handoff_data)

    print(f"[EOD Writer] Handoff saved for {today}")
    print(f"  BUY  : {handoff_data['BUY']}")
    print(f"  WATCH: {handoff_data['WATCH']}")
    print(f"  DECISIONS: {len(handoff_data['DECISIONS'])}")

if __name__ == "__main__":
    generate_eod_handoff()
