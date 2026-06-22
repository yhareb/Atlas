"""
morning_briefing.py
Runs at 9:00am ET every trading day.
Reads the latest handoff from atlas.db and sends a morning
summary card to Telegram.
"""

import os
import sys
import requests
from datetime import datetime, timedelta

sys.path.insert(0, "/Users/yasser/scripts")
import atlas_db

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Morning Briefing] Telegram env vars not set. Printing to stdout:")
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10 )
        if response.status_code == 200:
            print("[Morning Briefing] Sent to Telegram.")
        else:
            print(f"[Morning Briefing] Telegram error: {response.status_code} {response.text}")
    except Exception as e:
        print(f"[Morning Briefing] Failed: {e}")

def generate_morning_briefing():
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

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
