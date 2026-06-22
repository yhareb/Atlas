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

def generate_eod_handoff():
    conn = atlas_db.get_connection()
    cursor = conn.cursor()

    today = datetime.now().strftime('%Y-%m-%d')

    cursor.execute('''
        SELECT ticker, signal
        FROM signals
        WHERE date(timestamp) = ?
        GROUP BY ticker
        HAVING max(timestamp)
    ''', (today,))

    rows = cursor.fetchall()
    conn.close()

    handoff_data = {
        "date": today,
        "BUY": [],
        "WATCH": [],
        "last_scan": datetime.now().isoformat()
    }

    for ticker, signal in rows:
        if "BUY" in signal:
            handoff_data["BUY"].append(ticker)
        elif "WATCH" in signal:
            handoff_data["WATCH"].append(ticker)

    atlas_db.update_handoff(today, handoff_data)

    print(f"[EOD Writer] Handoff saved for {today}")
    print(f"  BUY  : {handoff_data['BUY']}")
    print(f"  WATCH: {handoff_data['WATCH']}")

if __name__ == "__main__":
    generate_eod_handoff()
