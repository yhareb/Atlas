"""Governed calendar override normalization; staging only."""
from __future__ import annotations
from atlas_holding_state_schema import digest
def normalize_overrides(rows):return sorted((dict(r) for r in (rows or [])),key=lambda r:(str(r.get('session')),str(r.get('reason'))))
def override_digest(rows):return digest(normalize_overrides(rows))

# ---- V1 PLATFORM BASELINE COMPATIBILITY (additive; V2/V3 bindings win) ----
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
import hashlib, json, sqlite3
from zoneinfo import ZoneInfo
SCHEMA_VERSION = 'atlas_calendar_override.v1'
ET = ZoneInfo('America/New_York')
REQUIRED = ('authoritative_source_name', 'source_reference', 'effective_date', 'closure_type', 'announced_at', 'expires_at', 'reason', 'entered_by', 'approved_by', 'source_digest')

def stable(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), default=str)

def _dt(v):
    try:
        x = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        return (x if x.tzinfo else x.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except Exception:
        return None

def validate_override(raw: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    x = dict(raw or {})
    errors = []
    for k in REQUIRED:
        if x.get(k) in (None, ''):
            errors.append('MISSING_' + k.upper())
    if x.get('closure_type') not in {'FULL_CLOSE', 'EARLY_CLOSE'}:
        errors.append('CLOSURE_TYPE_INVALID')
    try:
        date.fromisoformat(str(x.get('effective_date')))
    except Exception:
        errors.append('EFFECTIVE_DATE_INVALID')
    announced = _dt(x.get('announced_at'))
    expires = _dt(x.get('expires_at'))
    if not announced:
        errors.append('ANNOUNCED_AT_INVALID')
    if not expires:
        errors.append('EXPIRES_AT_INVALID')
    elif expires < now.astimezone(timezone.utc):
        errors.append('OVERRIDE_EXPIRED')
    if not str(x.get('approved_by') or '').strip():
        errors.append('OVERRIDE_UNAPPROVED')
    if not str(x.get('source_digest') or '').strip():
        errors.append('SOURCE_DIGEST_MISSING')
    if x.get('closure_type') == 'EARLY_CLOSE':
        try:
            t = time.fromisoformat(str(x.get('early_close_time_et')))
            x['early_close_time_et'] = t.strftime('%H:%M:%S')
        except Exception:
            errors.append('EARLY_CLOSE_TIME_INVALID')
    identity = {k: x.get(k) for k in REQUIRED}
    identity['early_close_time_et'] = x.get('early_close_time_et')
    x['schema_version'] = SCHEMA_VERSION
    x['override_digest'] = digest(identity)
    return {'validity': 'VALID' if not errors else 'REJECTED', 'rejection_reason': ';'.join(errors) if errors else None, 'override': x}

class OverrideLedger:

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        return c

    def _init(self):
        c = self.connect()
        c.execute('CREATE TABLE IF NOT EXISTS calendar_override_audit(\n   audit_id TEXT PRIMARY KEY,schema_version TEXT NOT NULL,override_digest TEXT NOT NULL UNIQUE,\n   authoritative_source_name TEXT NOT NULL,source_reference TEXT NOT NULL,effective_date TEXT NOT NULL,\n   closure_type TEXT NOT NULL,early_close_time_et TEXT,announced_at TEXT NOT NULL,expires_at TEXT NOT NULL,\n   reason TEXT NOT NULL,entered_by TEXT NOT NULL,approved_by TEXT NOT NULL,source_digest TEXT NOT NULL,\n   override_json TEXT NOT NULL,recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        c.execute('CREATE TABLE IF NOT EXISTS calendar_override_events(\n   event_id TEXT PRIMARY KEY,schema_version TEXT NOT NULL,event_type TEXT NOT NULL,\n   override_digest TEXT NOT NULL,prior_event_id TEXT,reason TEXT NOT NULL,entered_by TEXT NOT NULL,\n   approved_by TEXT NOT NULL,source_reference TEXT NOT NULL,source_digest TEXT NOT NULL,\n   effective_at TEXT NOT NULL,event_digest TEXT NOT NULL UNIQUE,event_json TEXT NOT NULL,\n   recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        c.commit()
        c.close()

    def ingest(self, raw: dict[str, Any], *, now: datetime) -> dict[str, Any]:
        v = validate_override(raw, now=now)
        if v['validity'] != 'VALID':
            return {'status': 'REJECTED', **v}
        x = v['override']
        aid = digest({'event': 'CALENDAR_OVERRIDE_INGESTED', 'override_digest': x['override_digest']})
        c = self.connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM calendar_override_audit WHERE override_digest=?', (x['override_digest'],)).fetchone():
                c.commit()
                return {'status': 'IDEMPOTENT_NO_OP', 'audit_id': aid, 'override': x}
            c.execute('INSERT INTO calendar_override_audit(audit_id,schema_version,override_digest,authoritative_source_name,source_reference,effective_date,closure_type,early_close_time_et,announced_at,expires_at,reason,entered_by,approved_by,source_digest,override_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (aid, SCHEMA_VERSION, x['override_digest'], x['authoritative_source_name'], x['source_reference'], x['effective_date'], x['closure_type'], x.get('early_close_time_et'), x['announced_at'], x['expires_at'], x['reason'], x['entered_by'], x['approved_by'], x['source_digest'], stable(x)))
            c.commit()
            return {'status': 'INSERTED', 'audit_id': aid, 'override': x}
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def reverse(self, override_digest: str, *, reason: str, entered_by: str, approved_by: str, source_reference: str, source_digest: str, effective_at: str) -> dict[str, Any]:
        if not all((str(x or '').strip() for x in [override_digest, reason, entered_by, approved_by, source_reference, source_digest, effective_at])):
            return {'status': 'REJECTED', 'reason': 'REVERSAL_FIELDS_INCOMPLETE'}
        if not _dt(effective_at):
            return {'status': 'REJECTED', 'reason': 'REVERSAL_EFFECTIVE_AT_INVALID'}
        c = self.connect()
        try:
            if not c.execute('SELECT 1 FROM calendar_override_audit WHERE override_digest=?', (override_digest,)).fetchone():
                return {'status': 'REJECTED', 'reason': 'OVERRIDE_NOT_FOUND'}
            obj = {'schema_version': SCHEMA_VERSION, 'event_type': 'OVERRIDE_REVERSED', 'override_digest': override_digest, 'reason': reason, 'entered_by': entered_by, 'approved_by': approved_by, 'source_reference': source_reference, 'source_digest': source_digest, 'effective_at': effective_at}
            event_digest = digest(obj)
            event_id = digest({'event': 'OVERRIDE_REVERSED', 'event_digest': event_digest})
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM calendar_override_events WHERE event_digest=?', (event_digest,)).fetchone():
                c.commit()
                return {'status': 'IDEMPOTENT_NO_OP', 'event_id': event_id, 'event_digest': event_digest}
            c.execute('INSERT INTO calendar_override_events(event_id,schema_version,event_type,override_digest,prior_event_id,reason,entered_by,approved_by,source_reference,source_digest,effective_at,event_digest,event_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (event_id, SCHEMA_VERSION, 'OVERRIDE_REVERSED', override_digest, None, reason, entered_by, approved_by, source_reference, source_digest, effective_at, event_digest, stable(obj)))
            c.commit()
            return {'status': 'INSERTED', 'event_id': event_id, 'event_digest': event_digest}
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def active_for_date(self, d: date, *, now: datetime) -> dict[str, Any]:
        c = self.connect()
        rows = [dict(r) for r in c.execute('SELECT override_json FROM calendar_override_audit WHERE effective_date=? ORDER BY audit_id', (d.isoformat(),))]
        reversed_digests = {r[0] for r in c.execute("SELECT override_digest FROM calendar_override_events WHERE event_type='OVERRIDE_REVERSED' AND effective_at<=?", (now.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),))}
        c.close()
        rows = [r for r in rows if json.loads(r['override_json']).get('override_digest') not in reversed_digests]
        valid = []
        rejected = []
        for r in rows:
            x = json.loads(r['override_json'])
            v = validate_override(x, now=now)
            (valid if v['validity'] == 'VALID' else rejected).append(v)
        if not valid:
            return {'authority_state': 'RULE_DEFAULT', 'override': None, 'rejected': rejected, 'calendar_blocker': False}
        digests = {v['override']['override_digest'] for v in valid}
        meanings = {(v['override']['closure_type'], v['override'].get('early_close_time_et')) for v in valid}
        if len(meanings) > 1:
            return {'authority_state': 'DATA_INCOMPLETE', 'override': None, 'rejected': rejected, 'calendar_blocker': True, 'reason': 'CONFLICTING_VALID_OVERRIDES', 'override_digests': sorted(digests)}
        return {'authority_state': 'OVERRIDE_ACTIVE', 'override': valid[0]['override'], 'rejected': rejected, 'calendar_blocker': False}

    def reconstruction_digest(self) -> str:
        c = self.connect()
        rows = {'overrides': [dict(r) for r in c.execute('SELECT * FROM calendar_override_audit ORDER BY audit_id')], 'events': [dict(r) for r in c.execute('SELECT * FROM calendar_override_events ORDER BY event_id')]}
        c.close()
        return digest(rows)
__all__ = ['SCHEMA_VERSION', 'REQUIRED', 'validate_override', 'OverrideLedger', 'digest']

# Complete additive V1+V2/V3 public surface.
__all__ = sorted(n for n in globals() if not n.startswith("_"))
