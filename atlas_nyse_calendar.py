"""Governed NYSE calendar evidence interface; no network access."""
from __future__ import annotations
try:
 from atlas_holding_state_schema import digest
except ImportError:
 def digest(value):
  import hashlib, json
  return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def calendar_evidence(session,status='OPEN',overrides=()):
 value={'session':str(session),'status':status,'overrides':list(overrides)};value['digest']=digest(value);return value

# ---- V1 PLATFORM BASELINE COMPATIBILITY (additive; V2/V3 bindings win) ----
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import calendar, hashlib, json
ET = ZoneInfo('America/New_York')
POLICY_VERSION = 'nyse_calendar.v2'

def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d + timedelta(days=7 * (n - 1))

def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month, calendar.monthrange(year, month)[1])
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d

def _easter(year: int) -> date:
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
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)

def full_holidays(year: int) -> set[date]:
    holidays = {_observed(date(year, 1, 1)), _nth_weekday(year, 1, 0, 3), _nth_weekday(year, 2, 0, 3), _easter(year) - timedelta(days=2), _last_weekday(year, 5, 0), _observed(date(year, 6, 19)), _observed(date(year, 7, 4)), _nth_weekday(year, 9, 0, 1), _nth_weekday(year, 11, 3, 4), _observed(date(year, 12, 25))}
    next_obs = _observed(date(year + 1, 1, 1))
    if next_obs.year == year:
        holidays.add(next_obs)
    return holidays

def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in full_holidays(d.year)

def early_close_days(year: int) -> set[date]:
    out = set()
    thanksgiving = _nth_weekday(year, 11, 3, 4)
    fri = thanksgiving + timedelta(days=1)
    if is_trading_day(fri):
        out.add(fri)
    xmas_eve = date(year, 12, 24)
    if is_trading_day(xmas_eve):
        out.add(xmas_eve)
    july4 = date(year, 7, 4)
    candidate = july4 - timedelta(days=1)
    while not is_trading_day(candidate):
        candidate -= timedelta(days=1)
    if candidate.weekday() < 5 and (july4 - candidate).days <= 3:
        out.add(candidate)
    return out

def session_schedule(d: date) -> dict:
    if not is_trading_day(d):
        return {'date': d.isoformat(), 'is_trading_day': False, 'holiday': d in full_holidays(d.year), 'early_close': False, 'open': None, 'close': None}
    close_t = time(13, 0) if d in early_close_days(d.year) else time(16, 0)
    op = datetime.combine(d, time(9, 30), ET)
    cl = datetime.combine(d, close_t, ET)
    return {'date': d.isoformat(), 'is_trading_day': True, 'holiday': False, 'early_close': close_t.hour == 13, 'open': op.isoformat(), 'close': cl.isoformat(), 'open_utc': op.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'), 'close_utc': cl.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')}

def classify_session(now: datetime) -> dict:
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    et = now.astimezone(ET)
    sched = session_schedule(et.date())
    if not sched['is_trading_day']:
        state = 'CLOSED'
    else:
        t = et.timetz().replace(tzinfo=None)
        close_t = datetime.fromisoformat(sched['close']).timetz().replace(tzinfo=None)
        if t < time(4, 0):
            state = 'CLOSED'
        elif t < time(9, 30):
            state = 'PRE_MARKET'
        elif t < close_t:
            state = 'REGULAR'
        elif t < time(20, 0):
            state = 'AFTER_MARKET'
        else:
            state = 'CLOSED'
    return {'policy_version': POLICY_VERSION, 'now_utc': now.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'), 'now_et': et.isoformat(), 'session': state, 'schedule': sched}

def latest_completed_session(now: datetime) -> str:
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    et = now.astimezone(ET)
    d = et.date()
    sched = session_schedule(d)
    if not sched['is_trading_day'] or now < datetime.fromisoformat(sched['close']).astimezone(timezone.utc):
        d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d.isoformat()

def completed_session_expiry(since: datetime, sessions: int=2) -> str:
    since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    d = since.astimezone(ET).date()
    n = 0
    while n < sessions:
        d += timedelta(days=1)
        if is_trading_day(d):
            n += 1
    return datetime.fromisoformat(session_schedule(d)['close']).astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

def session_schedule_governed(d: date, *, override_authority: dict | None=None) -> dict:
    base = session_schedule(d)
    auth = override_authority or {'authority_state': 'RULE_DEFAULT', 'override': None, 'calendar_blocker': False}
    if auth.get('calendar_blocker') or auth.get('authority_state') == 'DATA_INCOMPLETE':
        return {**base, 'authority_state': 'DATA_INCOMPLETE', 'calendar_blocker': True, 'authority_reason': auth.get('reason') or 'CALENDAR_AUTHORITY_BLOCKER', 'calendar_digest': hashlib.sha256(json.dumps({'base': base, 'authority': auth}, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()}
    ov = auth.get('override') if auth.get('authority_state') == 'OVERRIDE_ACTIVE' else None
    out = dict(base)
    out.update({'authority_state': auth.get('authority_state', 'RULE_DEFAULT'), 'calendar_blocker': False, 'override_digest': (ov or {}).get('override_digest')})
    if ov and ov.get('closure_type') == 'FULL_CLOSE':
        out.update({'is_trading_day': False, 'holiday': False, 'emergency_closure': True, 'early_close': False, 'open': None, 'close': None, 'open_utc': None, 'close_utc': None})
    elif ov and ov.get('closure_type') == 'EARLY_CLOSE':
        close_t = time.fromisoformat(ov['early_close_time_et'])
        op = datetime.combine(d, time(9, 30), ET)
        cl = datetime.combine(d, close_t, ET)
        out.update({'is_trading_day': True, 'holiday': False, 'emergency_closure': True, 'early_close': True, 'open': op.isoformat(), 'close': cl.isoformat(), 'open_utc': op.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'), 'close_utc': cl.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')})
    out['calendar_digest'] = hashlib.sha256(json.dumps(out, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()
    return out

def completed_session_expiry_governed(since: datetime, sessions: int=2, *, authority_lookup=None) -> str:
    since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    d = since.astimezone(ET).date()
    n = 0
    while n < sessions:
        d += timedelta(days=1)
        auth = authority_lookup(d) if authority_lookup else None
        s = session_schedule_governed(d, override_authority=auth)
        if s.get('calendar_blocker'):
            raise ValueError('CALENDAR_AUTHORITY_BLOCKER')
        if s.get('is_trading_day'):
            n += 1
    return datetime.fromisoformat(s['close']).astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

def adapter_record(now: datetime) -> dict:
    payload = {'classification': classify_session(now), 'latest_completed_session': latest_completed_session(now), 'calendar': 'NYSE_RULES_TIMEZONE_AWARE', 'timezone': 'America/New_York'}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'adapter_schema_version': 'atlas_nyse_calendar.v2', 'source_timestamp': payload['classification']['now_utc'], 'freshness': 'FRESH', 'validity': 'VALID', 'rejection_reason': None, 'digest': digest, 'payload': payload}
__all__ = ['ET', 'POLICY_VERSION', 'full_holidays', 'early_close_days', 'is_trading_day', 'session_schedule', 'session_schedule_governed', 'classify_session', 'latest_completed_session', 'completed_session_expiry', 'completed_session_expiry_governed', 'adapter_record']

# Complete additive V1+V2/V3 public surface.
__all__ = sorted(n for n in globals() if not n.startswith("_"))
