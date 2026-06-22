"""
morning_briefing.py
Runs at 9:00am ET every trading day.
Reads the latest handoff from atlas.db and sends a morning
summary card to Telegram.
"""

import os
import sys
from datetime import datetime, timedelta
from atlas_notify import send_telegram
from atlas_time import current_et_market_date, previous_et_trading_date_str

sys.path.insert(0, "/Users/yasser/scripts")
import atlas_db

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
    return send_telegram(message, label="morning_briefing")

def generate_morning_briefing():
    market_day = current_et_market_date()
    today = market_day.strftime('%Y-%m-%d')
    yesterday = previous_et_trading_date_str(market_day)

    data = atlas_db.get_handoff(today) or atlas_db.get_handoff(yesterday)

    header = f"🌅 *Morning Briefing — {today}*"

    if not data:
        send_telegram_message(f"{header}\n\nNo handoff data found. Clean slate — ready to scan.")
        return

    handoff_date = data.get("date", "unknown")
    buy_tickers = data.get("BUY", [])
    watch_tickers = data.get("WATCH", [])

    lines = [header, f"_Handoff from: {handoff_date}_", ""]

    if buy_tickers:
        lines.append("*Active BUY Signals:*")
        for t in buy_tickers:
            lines.append(f"  • {t}")
        lines.append("")
    else:
        lines.append("*Active BUY Signals:* None\n")

    if watch_tickers:
        lines.append("*WATCH List:*")
        for t in watch_tickers:
            lines.append(f"  • {t}")
        lines.append("")
    else:
        lines.append("*WATCH List:* None\n")

    lines.append("Ready for the open, Prof.")

    send_telegram_message("\n".join(lines))

if __name__ == "__main__":
    generate_morning_briefing()
