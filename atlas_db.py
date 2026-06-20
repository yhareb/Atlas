import sqlite3
import json
import os
from datetime import datetime

DB_PATH = "/Users/yasser/scripts/atlas.db"

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            ticker TEXT,
            signal TEXT,
            score INTEGER,
            rvol REAL,
            entry_price REAL,
            stop_loss REAL,
            max_loss_per_share REAL,
            atr REAL,
            trend_stack TEXT,
            relative_strength TEXT,
            volume TEXT,
            catalyst TEXT,
            warnings TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            ticker TEXT,
            action TEXT,
            price REAL,
            quantity INTEGER,
            status TEXT DEFAULT 'OPEN'
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS handoff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE,
            data TEXT
        )
    ''')

    conn.commit()
    conn.close()

def log_signal(ticker, signal, score, rvol, entry_price, stop_loss,
               max_loss_per_share, atr, trend_stack, relative_strength,
               volume, catalyst, warnings):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO signals (ticker, signal, score, rvol, entry_price,
            stop_loss, max_loss_per_share, atr, trend_stack,
            relative_strength, volume, catalyst, warnings)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (ticker, signal, score, rvol, entry_price, stop_loss,
          max_loss_per_share, atr, trend_stack, relative_strength,
          volume, catalyst, warnings))
    conn.commit()
    conn.close()

def log_position(ticker, action, price, quantity=0, status='OPEN'):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO positions (ticker, action, price, quantity, status)
        VALUES (?, ?, ?, ?, ?)
    ''', (ticker, action, price, quantity, status))
    conn.commit()
    conn.close()

def get_open_positions():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT ticker, action, price, quantity, timestamp
        FROM positions WHERE status = 'OPEN'
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [{'ticker': r[0], 'action': r[1], 'price': r[2],
             'quantity': r[3], 'timestamp': r[4]} for r in rows]

def update_handoff(date_str, data_dict):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO handoff (date, data) VALUES (?, ?)
        ON CONFLICT(date) DO UPDATE SET data=excluded.data
    ''', (date_str, json.dumps(data_dict)))
    conn.commit()
    conn.close()

def get_handoff(date_str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT data FROM handoff WHERE date = ?', (date_str,))
    row = cursor.fetchone()
    conn.close()
    return json.loads(row[0]) if row else None

if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
