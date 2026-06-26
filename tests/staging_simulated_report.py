#!/usr/bin/env python3
"""Staging no-send report smoke test."""
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

SCRIPTS = Path('/Users/yasser/scripts')
PROD_DB = SCRIPTS / 'atlas.db'
STAGING_DB = Path(os.environ.get('ATLAS_STAGING_DB', '/tmp/atlas_staging.db'))
sys.path.insert(0, str(SCRIPTS))


def _counts(path):
    con = sqlite3.connect(str(path)); cur = con.cursor(); out = {}
    for table in ('pending_pullbacks','trades','ema_retry_candidates','signals','handoff'):
        try:
            cur.execute(f'SELECT COUNT(*) FROM {table}')
            out[table] = int(cur.fetchone()[0])
        except Exception as exc:
            out[table] = f'ERR:{exc}'
    con.close(); return out


def main():
    shutil.copy2(PROD_DB, STAGING_DB)
    os.environ['ATLAS_DB'] = str(STAGING_DB)
    os.environ['ATLAS_DISABLE_TELEGRAM'] = '1'
    os.environ['ATLAS_MOCK_TELEGRAM'] = '1'
    live_before = _counts(PROD_DB)
    staging_before = _counts(STAGING_DB)

    import atlas_db
    atlas_db.DB_PATH = str(STAGING_DB)
    try:
        import atlas_notify
        atlas_notify.send_telegram = lambda msg, *a, **k: print(f'[MOCK_TELEGRAM] {len(str(msg))} chars') or True
        atlas_notify.send_message = atlas_notify.send_telegram
    except Exception:
        pass
    import pre_market_report
    pre_market_report.send_telegram = lambda msg, *a, **k: print(f'[MOCK_TELEGRAM] {len(str(msg))} chars') or True
    msg = pre_market_report.generate_pre_market_report(send=False)
    live_after = _counts(PROD_DB)
    staging_after = _counts(STAGING_DB)
    result = {
        'message_chars': len(str(msg or '')),
        'live_counts_unchanged': live_before == live_after,
        'staging_counts_unchanged': staging_before == staging_after,
        'telegram_mocked': True,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result['live_counts_unchanged'] else 3

if __name__ == '__main__':
    raise SystemExit(main())
