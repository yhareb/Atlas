"""Operational multi-packet coordinator and atomic runtime-manifest implementation."""
from __future__ import annotations
import argparse, contextlib, fcntl, json, os, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from atlas_holding_state_schema import digest, make_receipt, verify_packet
from atlas_holding_state_authority import resolve
REQUIRED_UNITS = ('PRE_MARKET_HOLDINGS', 'INTRADAY_HOLDINGS', 'EOD_POSTMARKET_HOLDINGS', 'CONVERSATION_HOLDINGS', 'BROKER_PENDING_VISIBILITY', 'DAILY_PP_HOLDING_SECTIONS')

def _read(path):
    return json.loads(Path(path).read_text())

def _atomic(path, value, mode=292):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    (fd, tmp) = tempfile.mkstemp(prefix='.' + p.name + '.', dir=p.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, sort_keys=True, separators=(',', ':'))
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, p)
        d = os.open(p.parent, os.O_RDONLY)
        os.fsync(d)
        os.close(d)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return str(p)

def _verify_file(path, expected=None):
    p = Path(path)
    if not p.is_file():
        raise RuntimeError('RUNTIME_FILE_MISSING')
    value = _read(p)
    actual = digest(value)
    if expected and actual != expected:
        raise RuntimeError('RUNTIME_FILE_DIGEST_MISMATCH')
    return (value, actual)

def create_runtime_manifest(path, mode, units, canonical_unlocked=False, packet_path=None, receipt_path=None, current_path=None, rebuild_queue=None, packet_index=None, component_paths=None, normalized_inputs_path=None, packet_store=None, lease_path=None):
    units = tuple(sorted(units))
    if units != tuple(sorted(REQUIRED_UNITS)):
        raise RuntimeError('ALL_SIX_UNITS_REQUIRED')
    packets = {}
    for (key, p) in sorted((packet_index or ({'default': packet_path} if packet_path else {})).items()):
        (value, actual) = _verify_file(p)
        packets[str(key)] = {'path': str(Path(p).resolve()), 'digest': actual, 'packet_id': value.get('packet_id')}
    current_digest = None
    if current_path:
        (_, current_digest) = _verify_file(current_path)
    record = {'schema_version': 'atlas.runtime_manifest.v3', 'mode': mode, 'units': list(units), 'canonical_unlocked': bool(canonical_unlocked), 'packets': packets, 'default_packet_key': next(iter(packets), None), 'current': {'path': str(Path(current_path).resolve()), 'digest': current_digest} if current_path else None, 'rebuild_queue': str(rebuild_queue) if rebuild_queue else None, 'build': {'component_paths': [str(x) for x in component_paths or []], 'normalized_inputs_path': str(normalized_inputs_path) if normalized_inputs_path else None, 'packet_store': str(packet_store) if packet_store else None, 'lease_path': str(lease_path) if lease_path else None}}
    record['generation_id'] = digest(record)
    record['manifest_digest'] = digest(record)
    _atomic(path, record)
    return record

def verify_runtime_manifest(path):
    p = Path(path)
    try:
        r = _read(p)
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError('RUNTIME_MANIFEST_UNREADABLE') from e
    claimed = r.pop('manifest_digest', None)
    if not claimed or digest(r) != claimed:
        raise RuntimeError('RUNTIME_MANIFEST_TAMPERED')
    r['manifest_digest'] = claimed
    if p.stat().st_mode & 146:
        raise RuntimeError('RUNTIME_MANIFEST_MUTABLE')
    if r.get('schema_version') != 'atlas.runtime_manifest.v3':
        raise RuntimeError('RUNTIME_MANIFEST_SCHEMA_INVALID')
    if tuple(sorted(r.get('units') or ())) != tuple(sorted(REQUIRED_UNITS)):
        raise RuntimeError('ALL_SIX_UNITS_REQUIRED')
    if r.get('mode') not in ('legacy', 'shadow', 'canonical'):
        raise RuntimeError('INVALID_AUTHORITY_MODE')
    for entry in (r.get('packets') or {}).values():
        _verify_file(entry['path'], entry['digest'])
    if r.get('current'):
        _verify_file(r['current']['path'], r['current']['digest'])
    return r

def _v3_improved_verify_component_readiness(components):
    good = []
    errors = []
    for c in components or []:
        x = dict(c)
        claimed = x.pop('component_digest', None)
        if x.get('status') != 'COMPLETED':
            errors.append('COMPONENT_NOT_COMPLETED')
            continue
        if not claimed or digest(x) != claimed:
            errors.append('COMPONENT_DIGEST_INVALID')
            continue
        x['component_digest'] = claimed
        good.append(x)
    sessions = {x.get('completed_session') for x in good}
    universes = {x.get('trade_universe_digest') for x in good}
    if len(sessions) > 1:
        errors.append('COMPONENT_SESSION_MISMATCH')
    if len(universes) > 1:
        errors.append('COMPONENT_UNIVERSE_MISMATCH')
    return (good, sorted(set(errors)))

def _v3_improved_select_current_components(components):
    (good, errors) = verify_component_readiness(components)
    selected = {}
    for c in good:
        key = c['producer']
        rank = (c.get('completed_session', ''), c.get('source_timestamp', ''), c.get('component_id', ''))
        if key not in selected or rank > selected[key][0]:
            selected[key] = (rank, c)
    return ({k: v[1] for (k, v) in selected.items()}, errors)

@contextlib.contextmanager
def _v3_improved_acquire_build_lease(path, timeout=5.0):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    f = open(p, 'a+')
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('BUILD_LEASE_BUSY')
                time.sleep(0.01)
        f.seek(0)
        f.truncate()
        f.write(json.dumps({'pid': os.getpid(), 'acquired_at': datetime.now(timezone.utc).isoformat()}))
        f.flush()
        os.fsync(f.fileno())
        yield
    finally:
        try:
            fcntl.flock(f, fcntl.LOCK_UN)
        finally:
            f.close()

def _v3_improved_build_current_packets(component_paths, normalized_inputs_path, store_dir, lease_path):
    try:
        components = [_read(p) for p in component_paths]
    except (OSError, json.JSONDecodeError):
        return {'status': 'BLOCKED', 'reason_codes': ['COMPONENT_LOAD_FAILED']}
    (selected, errors) = select_current_components(components)
    if errors or set(selected) != {'DAILY', 'PP'}:
        return {'status': 'BLOCKED', 'reason_codes': sorted(set(errors + ['CANONICAL_BUILD_MISSING_OR_FAILED']))}
    normalized = _read(normalized_inputs_path)
    normalized['selected_components'] = {k: {'component_id': v['component_id'], 'component_digest': v['component_digest']} for (k, v) in selected.items()}
    with acquire_build_lease(lease_path):
        packet = resolve(normalized)
        path = Path(store_dir) / f"{packet['packet_id']}.json"
        if path.exists():
            (existing, actual) = _verify_file(path)
            if actual != digest(packet):
                raise RuntimeError('PACKET_ID_COLLISION')
            return {'status': 'IDEMPOTENT_NO_OP', 'packet_path': str(path), 'packet': existing}
        _atomic(path, packet)
        return {'status': 'BUILT', 'packet_path': str(path), 'packet': packet}

def validate_packet_load(packet, current, loaded_at=None):
    try:
        verify_packet(packet)
    except ValueError as e:
        return make_receipt({'loaded_at': loaded_at or datetime.now(timezone.utc).isoformat(), 'usability': 'BLOCKED', 'reason_codes': [str(e)], 'rebuild_required': True}, packet)
    reasons = []
    state = 'USABLE'
    provenance = packet.get('provenance') or {}
    for (key, reason) in [('trade_lot_binding_digest', 'TRADE_LOT_BINDING_CHANGED'), ('broker_lifecycle_digest', 'BROKER_LIFECYCLE_CHANGED')]:
        if current.get(key) != provenance.get(key, packet.get(key)):
            reasons.append(reason)
            state = 'BLOCKED'
    if current.get('calendar_digest') != provenance.get('governed_calendar_digest', packet.get('calendar_digest')):
        reasons.append('CALENDAR_DIGEST_CHANGED')
        state = 'BLOCKED' if current.get('calendar_authority_conflict') else ('DATA_INCOMPLETE' if state != 'BLOCKED' else state)
    freshness = current.get('component_freshness') or {}
    if current.get('component_stale') or any(str(value).upper() not in ('FRESH', 'VALID') for value in freshness.values()):
        reasons.append('COMPONENT_STALE')
        state = 'DATA_INCOMPLETE' if state != 'BLOCKED' else state
    def parse_timestamp(value):
        if not value:
            return None
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    loaded = parse_timestamp(loaded_at or datetime.now(timezone.utc).isoformat())
    freshness_expires = parse_timestamp(packet.get('freshness_expires_at'))
    if loaded and freshness_expires and loaded > freshness_expires:
        reasons.append('PACKET_FRESHNESS_EXPIRED')
        state = 'DATA_INCOMPLETE' if state != 'BLOCKED' else state
    retention_expires = parse_timestamp((packet.get('retention') or {}).get('retention_expires_at'))
    retention_valid = bool(current.get('retention_valid', True)) and not (loaded and retention_expires and loaded > retention_expires)
    return make_receipt({'loaded_at': loaded_at or datetime.now(timezone.utc).isoformat(), 'current_calendar_digest': current.get('calendar_digest'), 'current_trade_lot_binding_digest': current.get('trade_lot_binding_digest'), 'current_broker_lifecycle_digest': current.get('broker_lifecycle_digest'), 'validation_policy_version': 'atlas-load-validation.v3', 'usability': state, 'reason_codes': sorted(set(reasons)), 'rebuild_required': bool(reasons), 'price_role_usability': current.get('price_role_usability') or {'display': state != 'BLOCKED', 'valuation': state == 'USABLE', 'stop_evaluation': state == 'USABLE', 'target_evaluation': state == 'USABLE'}, 'retention_valid': retention_valid}, packet)

def load_validate(packet_path, current_path, packet_digest=None, current_digest=None):
    (p, _) = _verify_file(packet_path, packet_digest)
    (c, _) = _verify_file(current_path, current_digest)
    return (p, validate_packet_load(p, c))

def _v3_improved_request_rebuild(queue_dir, reason, identity):
    value = {'schema_version': 'atlas.build_request.v3', 'reason_codes': sorted(set(reason if isinstance(reason, list) else [reason])), 'identity': identity}
    value['request_id'] = digest(value)
    path = Path(queue_dir) / (value['request_id'] + '.json')
    if path.exists():
        return {'status': 'SUPPRESSED_DUPLICATE', 'path': str(path), 'request_id': value['request_id']}
    _atomic(path, value)
    return {'status': 'REQUESTED', 'path': str(path), 'request_id': value['request_id']}

def consume_rebuild_queue(queue_dir, manifest_path, *, now_epoch=None, lease_ttl=60.0):
    """Consume one durable request and atomically publish a new manifest generation."""
    queue = Path(queue_dir)
    queue.mkdir(parents=True, exist_ok=True)
    now = float(time.time() if now_epoch is None else now_epoch)
    for req_path in sorted(queue.glob('*.json')):
        request = _read(req_path)
        rid = request.get('request_id')
        if not rid or digest({k: v for (k, v) in request.items() if k != 'request_id'}) != rid:
            continue
        done = queue / (rid + '.done.json')
        claim = queue / (rid + '.claim.json')
        if done.exists():
            continue
        if claim.exists():
            try:
                held = _read(claim)
            except Exception:
                held = {}
            if float(held.get('expires_epoch') or 0) > now:
                continue
        _atomic(claim, {'request_id': rid, 'worker_pid': os.getpid(), 'claimed_epoch': now, 'expires_epoch': now + lease_ttl}, 292)
        manifest = verify_runtime_manifest(manifest_path)
        build = manifest.get('build') or {}
        outcome = build_current_packets(build.get('component_paths') or [], build.get('normalized_inputs_path'), build.get('packet_store'), build.get('lease_path'))
        if outcome.get('status') not in ('BUILT', 'IDEMPOTENT_NO_OP'):
            return {'status': 'BLOCKED', 'request_id': rid, 'build': outcome}
        packet = outcome['packet']
        packet_index = {k: v['path'] for (k, v) in (manifest.get('packets') or {}).items()}
        key = str(packet.get('ticker') or manifest.get('default_packet_key') or 'default')
        packet_index[key] = outcome['packet_path']
        previous = manifest['generation_id']
        published = create_runtime_manifest(manifest_path, manifest['mode'], manifest['units'], manifest.get('canonical_unlocked', False), current_path=(manifest.get('current') or {}).get('path'), rebuild_queue=queue, packet_index=packet_index, component_paths=build.get('component_paths'), normalized_inputs_path=build.get('normalized_inputs_path'), packet_store=build.get('packet_store'), lease_path=build.get('lease_path'))
        published['previous_generation_id'] = previous
        published['publication_sequence'] = int(manifest.get('publication_sequence') or 0) + 1
        published['generation_id'] = digest({k: v for (k, v) in published.items() if k not in ('manifest_digest', 'generation_id')})
        published['manifest_digest'] = digest({k: v for (k, v) in published.items() if k != 'manifest_digest'})
        _atomic(manifest_path, published)
        _atomic(done, {'request_id': rid, 'status': 'PUBLISHED', 'previous_generation_id': previous, 'generation_id': published['generation_id'], 'packet_id': packet.get('packet_id')}, 292)
        return {'status': 'PUBLISHED', 'request_id': rid, 'previous_generation_id': previous, 'generation_id': published['generation_id'], 'manifest_path': str(manifest_path)}
    return {'status': 'IDLE'}

def load_build_validate_rebuild(manifest, unit):
    packets = manifest.get('packets') or {}
    key = manifest.get('default_packet_key')
    entry = packets.get(key)
    current = manifest.get('current')
    build = manifest.get('build') or {}

    def rebuild(reason):
        if manifest.get('rebuild_queue'):
            request_rebuild(manifest['rebuild_queue'], [reason], {'unit': unit})
        empty_path = build.get('empty_open_set_packet_path')
        if empty_path:
            try:
                empty_packet, _ = _verify_file(empty_path)
                if empty_packet.get('empty_open_set') is True and empty_packet.get('open_trade_lot_count') == 0:
                    return {'status': 'IDEMPOTENT_NO_OP', 'packet_path': str(empty_path), 'packet': empty_packet}
            except RuntimeError:
                pass
        if all((build.get(x) for x in ('component_paths', 'normalized_inputs_path', 'packet_store', 'lease_path'))):
            return build_current_packets(build['component_paths'], build['normalized_inputs_path'], build['packet_store'], build['lease_path'])
        return {'status': 'BLOCKED'}
    try:
        if not entry or not current:
            raise RuntimeError('CANONICAL_BUILD_MISSING_OR_FAILED')
        (packet, receipt) = load_validate(entry['path'], current['path'], entry['digest'], current['digest'])
    except RuntimeError:
        outcome = rebuild('CANONICAL_BUILD_MISSING_OR_FAILED')
        if outcome.get('status') not in ('BUILT', 'IDEMPOTENT_NO_OP'):
            raise
        (packet, receipt) = load_validate(outcome['packet_path'], current['path'], None, current['digest'])
    if receipt.get('rebuild_required'):
        rebuild('RECEIPT_REBUILD_REQUIRED')
    return (packet, receipt)

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--build-current', action='store_true')
    ap.add_argument('--consume-rebuild-queue', action='store_true')
    ap.add_argument('--queue')
    ap.add_argument('--manifest')
    ap.add_argument('--now-epoch', type=float)
    ap.add_argument('--lease-ttl', type=float, default=60.0)
    ap.add_argument('--component', action='append', default=[])
    ap.add_argument('--inputs')
    ap.add_argument('--store')
    ap.add_argument('--lease')
    a = ap.parse_args(argv)
    if a.build_current:
        print(json.dumps(build_current_packets(a.component, a.inputs, a.store, a.lease), sort_keys=True, default=str))
        return 0
    if a.consume_rebuild_queue:
        print(json.dumps(consume_rebuild_queue(a.queue, a.manifest, now_epoch=a.now_epoch, lease_ttl=a.lease_ttl), sort_keys=True))
        return 0
    return 2
if __name__ == '__main__':
    raise SystemExit(main())
import hashlib, sqlite3, uuid
from contextlib import contextmanager
from datetime import timedelta
from typing import Any
from atlas_holding_state_schema import PACKET_SCHEMA_VERSION, RECEIPT_SCHEMA_VERSION, CANONICAL_INPUT_FIELDS, validate_packet_shape
VALIDATION_POLICY_VERSION = 'packet_load_validation.v3'
LEASE_SECONDS = 30
MAX_REBUILD_BACKOFF_SECONDS = 300

def stable_json(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'), default=str)

def _dt(x):
    if isinstance(x, datetime):
        d = x
    else:
        try:
            d = datetime.fromisoformat(str(x).replace('Z', '+00:00'))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

def _iso(d):
    return d.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

def _connect(path):
    con = sqlite3.connect(path, timeout=30, isolation_level=None)
    con.execute('pragma foreign_keys=on')
    con.executescript('create table if not exists packets(packet_id text primary key,packet_json text not null,created_at text not null);\n create table if not exists rebuild_requests(request_id text primary key,binding_digest text not null,input_digest text,reason text not null,status text not null,attempt_count integer not null,next_eligible_at text not null,request_json text not null,created_at text not null,updated_at text not null);\n create table if not exists build_leases(lease_key text primary key,owner text not null,expires_at text not null,acquired_at text not null);')
    return con

def initialize_sidecar(path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = _connect(p)
    con.close()
    return {'status': 'INITIALIZED', 'path': str(p)}

def _require_initialized(path):
    p = Path(path)
    if not p.exists():
        raise RuntimeError('SIDECAR_UNINITIALIZED')
    return p

def _canonical_manifest(trade_identity, canonical_inputs, policy_versions):
    aliases = {'canonical_levels': canonical_inputs.get('canonical_levels') or {}, 'accepted_and_rejected_provider_candidates': canonical_inputs.get('accepted_and_rejected_provider_candidates') or canonical_inputs.get('provider_candidates') or [], 'stop_target_broker_events': canonical_inputs.get('stop_target_broker_events') or [], 'selected_daily_component_id_and_digest': canonical_inputs.get('selected_daily_component_id_and_digest') or {}, 'selected_pp_component_id_and_digest': canonical_inputs.get('selected_pp_component_id_and_digest') or {}, 'quiver_raw_evidence_digest': None, 'perme_context_digest': canonical_inputs.get('perme_context_digest'), 'prior_canonical_state_digest': canonical_inputs.get('prior_canonical_state_digest'), 'governed_calendar_digest': canonical_inputs.get('governed_calendar_digest') or canonical_inputs.get('calendar_digest')}
    return {'schema_version': PACKET_SCHEMA_VERSION, 'normalized_trade_lot_identity': trade_identity, **aliases, 'policy_versions': sorted(policy_versions)}
__all__ = ['stable_json', 'digest', 'initialize_sidecar', 'verify_component_readiness', 'select_current_components', 'acquire_build_lease', 'build_current_packets', 'request_rebuild', 'validate_packet_load']
__all__ = sorted((n for n in globals() if not n.startswith('_')))

@contextmanager
def _v1_baseline_acquire_build_lease(store_path, lease_key, *, now=None, lease_seconds=LEASE_SECONDS):
    p = _require_initialized(store_path)
    now = _dt(now) or datetime.now(timezone.utc)
    owner = f'{os.getpid()}:{uuid.uuid4().hex}'
    con = _connect(p)
    try:
        deadline = time.monotonic() + 5
        while True:
            probe = datetime.now(timezone.utc) if now is None else now
            con.execute('begin immediate')
            row = con.execute('select owner,expires_at from build_leases where lease_key=?', (lease_key,)).fetchone()
            if not row or (_dt(row[1]) or probe) <= probe:
                con.execute('insert or replace into build_leases values(?,?,?,?)', (lease_key, owner, _iso(probe + timedelta(seconds=lease_seconds)), _iso(probe)))
                con.commit()
                break
            con.rollback()
            if time.monotonic() >= deadline:
                raise RuntimeError('BUILD_LEASE_BUSY')
            time.sleep(0.01)
        yield {'lease_key': lease_key, 'owner': owner}
    finally:
        try:
            con.execute('begin immediate')
            con.execute('delete from build_leases where lease_key=? and owner=?', (lease_key, owner))
            con.commit()
        except Exception:
            try:
                con.rollback()
            except Exception:
                pass
        con.close()

def acquire_build_lease(*args, **kwargs):
    """Backward-compatible overload: V2/V3 interface preferred, V1 accepted."""
    import inspect
    try:
        inspect.signature(_v3_improved_acquire_build_lease).bind(*args, **kwargs)
    except TypeError:
        return _v1_baseline_acquire_build_lease(*args, **kwargs)
    return _v3_improved_acquire_build_lease(*args, **kwargs)

def _v1_baseline_build_current_packets(*, store_path, completed_session, trade_identity, canonical_inputs, policy_versions, now=None):
    p = _require_initialized(store_path)
    now = _dt(now) or datetime.now(timezone.utc)
    universe = digest(trade_identity)
    key = completed_session + ':' + universe
    with acquire_build_lease(p, key, now=now):
        manifest = _canonical_manifest(trade_identity, canonical_inputs, policy_versions)
        cid = digest(manifest)
        pid = digest({'packet_schema_version': PACKET_SCHEMA_VERSION, 'trade_id': trade_identity.get('trade_id'), 'lot_id_or_empty': trade_identity.get('lot_id') or '', 'completed_session': completed_session, 'canonical_input_digest': cid, 'sorted_policy_versions': sorted(policy_versions)})
        con = _connect(p)
        row = con.execute('select packet_json from packets where packet_id=?', (pid,)).fetchone()
        if row:
            con.close()
            return {'status': 'IDEMPOTENT_NO_OP', 'packet': json.loads(row[0])}
        built = _iso(now)
        expiry = canonical_inputs.get('freshness_expires_at') or _iso(now + timedelta(minutes=15))
        packet = {'schema_version': PACKET_SCHEMA_VERSION, 'packet_id': pid, 'packet_digest': '', 'completed_session': completed_session, 'canonical_input_digest': cid, 'trade_identity': trade_identity, 'canonical_levels': manifest['canonical_levels'], 'provider_candidates': manifest['accepted_and_rejected_provider_candidates'], 'stop_target_broker_events': manifest['stop_target_broker_events'], 'selected_components': {'DAILY': manifest['selected_daily_component_id_and_digest'], 'PP': manifest['selected_pp_component_id_and_digest']}, 'provenance': {'quiver_raw_evidence_digest': manifest['quiver_raw_evidence_digest'], 'perme_context_digest': manifest['perme_context_digest'], 'prior_canonical_state_digest': manifest['prior_canonical_state_digest'], 'governed_calendar_digest': manifest['governed_calendar_digest'], 'trade_lot_binding_digest': canonical_inputs.get('trade_lot_binding_digest'), 'broker_lifecycle_digest': canonical_inputs.get('broker_lifecycle_digest'), 'stop_target_provenance': canonical_inputs.get('stop_target_provenance') or {}}, 'axes': canonical_inputs.get('axes') or {}, 'price_roles': canonical_inputs.get('price_roles') or {}, 'retention': canonical_inputs.get('retention') or {}, 'alert_projection': canonical_inputs.get('alert_projection') or {}, 'policy_versions': sorted(policy_versions), 'built_at': built, 'freshness_expires_at': expiry}
        packet['packet_digest'] = digest({k: v for (k, v) in packet.items() if k != 'packet_digest'})
        (ok, errors) = validate_packet_shape(packet)
        if not ok:
            con.close()
            return {'status': 'BUILD_FAILED', 'reason_codes': errors}
        con.execute('begin immediate')
        con.execute('insert into packets values(?,?,?)', (pid, stable_json(packet), built))
        con.commit()
        con.close()
        return {'status': 'INSERTED', 'packet': packet}

def build_current_packets(*args, **kwargs):
    """Backward-compatible overload: V2/V3 interface preferred, V1 accepted."""
    import inspect
    try:
        inspect.signature(_v3_improved_build_current_packets).bind(*args, **kwargs)
    except TypeError:
        return _v1_baseline_build_current_packets(*args, **kwargs)
    return _v3_improved_build_current_packets(*args, **kwargs)

def _v1_baseline_request_rebuild(store_path, reason, binding, *, input_digest=None, now=None):
    p = _require_initialized(store_path)
    now = _dt(now) or datetime.now(timezone.utc)
    bd = digest(binding)
    rid = digest({'reason': reason, 'binding': binding, 'input_digest': input_digest})
    con = _connect(p)
    latest = con.execute('select input_digest,attempt_count,next_eligible_at from rebuild_requests where binding_digest=? order by created_at desc limit 1', (bd,)).fetchone()
    if latest and latest[0] == input_digest:
        if (_dt(latest[2]) or now) > now:
            con.close()
            return {'status': 'BOUNDED_BACKOFF', 'request_id': rid, 'next_eligible_at': latest[2]}
        con.close()
        return {'status': 'NO_ELIGIBLE_NEW_INPUT', 'request_id': rid}
    attempt = latest[1] + 1 if latest else 1
    delay = min(MAX_REBUILD_BACKOFF_SECONDS, 2 ** min(attempt, 8))
    nxt = _iso(now + timedelta(seconds=delay))
    req = {'reason': reason, 'binding': binding, 'input_digest': input_digest}
    con.execute('begin immediate')
    con.execute('insert or ignore into rebuild_requests values(?,?,?,?,?,?,?,?,?,?)', (rid, bd, input_digest, reason, 'PENDING', attempt, nxt, stable_json(req), _iso(now), _iso(now)))
    inserted = con.total_changes > 0
    con.commit()
    con.close()
    return {'status': 'INSERTED' if inserted else 'IDEMPOTENT_NO_OP', 'request_id': rid, 'next_eligible_at': nxt}

def request_rebuild(*args, **kwargs):
    """Backward-compatible overload: V2/V3 interface preferred, V1 accepted."""
    import inspect
    try:
        inspect.signature(_v3_improved_request_rebuild).bind(*args, **kwargs)
    except TypeError:
        return _v1_baseline_request_rebuild(*args, **kwargs)
    return _v3_improved_request_rebuild(*args, **kwargs)

def _v1_baseline_select_current_components(cs, session, universe_digest):
    out = {}
    ineligible = []
    for c in cs or []:
        (ok, reasons) = verify_component_readiness(c, session, universe_digest)
        if not ok:
            ineligible.append({'component_id': c.get('component_id') if isinstance(c, dict) else None, 'reasons': reasons})
            continue
        producer = c.get('producer')
        if producer not in ('DAILY', 'PP'):
            ineligible.append({'component_id': c.get('component_id'), 'reasons': ['COMPONENT_PRODUCER_INVALID']})
            continue
        old = out.get(producer)
        key = lambda x: (x.get('completed_session', ''), x.get('source_timestamp', ''), x.get('component_id', ''))
        if old is None or key(c) > key(old):
            out[producer] = c
    return {'selected': out, 'ineligible': ineligible, 'complete': set(out) == {'DAILY', 'PP'}}

def select_current_components(*args, **kwargs):
    """Backward-compatible overload: V2/V3 interface preferred, V1 accepted."""
    import inspect
    try:
        inspect.signature(_v3_improved_select_current_components).bind(*args, **kwargs)
    except TypeError:
        return _v1_baseline_select_current_components(*args, **kwargs)
    return _v3_improved_select_current_components(*args, **kwargs)

def _v1_baseline_verify_component_readiness(c: dict[str, Any], session: str, universe_digest: str) -> tuple[bool, list[str]]:
    e = []
    if not isinstance(c, dict):
        return (False, ['COMPONENT_MALFORMED'])
    if not c.get('schema_version'):
        e.append('COMPONENT_SCHEMA_INVALID')
    if c.get('status') != 'COMPLETED':
        e.append('COMPONENT_NOT_COMPLETED')
    if c.get('completed_session') != session:
        e.append('COMPONENT_SESSION_MISMATCH')
    if c.get('trade_universe_digest') != universe_digest:
        e.append('COMPONENT_UNIVERSE_MISMATCH')
    body = {k: v for (k, v) in c.items() if k != 'component_digest'}
    if c.get('component_digest') != digest(body):
        e.append('COMPONENT_DIGEST_INVALID')
    if not c.get('component_id'):
        e.append('COMPONENT_ID_MISSING')
    return (not e, sorted(e))

def verify_component_readiness(*args, **kwargs):
    """Backward-compatible overload: V2/V3 interface preferred, V1 accepted."""
    import inspect
    try:
        inspect.signature(_v3_improved_verify_component_readiness).bind(*args, **kwargs)
    except TypeError:
        return _v1_baseline_verify_component_readiness(*args, **kwargs)
    return _v3_improved_verify_component_readiness(*args, **kwargs)
__all__ = sorted((n for n in globals() if not n.startswith('_')))
