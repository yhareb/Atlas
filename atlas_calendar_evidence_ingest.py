"""Calendar evidence normalization only; persistence belongs to coordinator."""
from __future__ import annotations
from atlas_nyse_calendar import calendar_evidence
def ingest(session,status='OPEN',overrides=()):return calendar_evidence(session,status,overrides)

# ---- V1 PLATFORM BASELINE COMPATIBILITY (additive; V2/V3 bindings win) ----
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json
from atlas_calendar_overrides import OverrideLedger
INGEST_SCHEMA = 'atlas_calendar_evidence.v1'

def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def ingest_evidence(evidence_path: str | Path, ledger_path: str | Path, *, now: datetime | None=None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    p = Path(evidence_path)
    if not p.is_file():
        return {'status': 'REJECTED', 'reason': 'EVIDENCE_FILE_MISSING'}
    raw_bytes = p.read_bytes()
    file_sha = sha_bytes(raw_bytes)
    try:
        envelope = json.loads(raw_bytes)
    except Exception:
        return {'status': 'REJECTED', 'reason': 'EVIDENCE_JSON_INVALID', 'evidence_file_sha256': file_sha}
    if envelope.get('schema_version') != INGEST_SCHEMA:
        return {'status': 'REJECTED', 'reason': 'EVIDENCE_SCHEMA_INVALID', 'evidence_file_sha256': file_sha}
    source = envelope.get('source_evidence') or {}
    override = dict(envelope.get('override') or {})
    required = ['authoritative_source_name', 'source_reference', 'retrieved_at', 'content_sha256']
    missing = [k for k in required if not source.get(k)]
    if missing:
        return {'status': 'REJECTED', 'reason': 'SOURCE_EVIDENCE_INCOMPLETE:' + ','.join(missing), 'evidence_file_sha256': file_sha}
    if source.get('content_sha256') != hashlib.sha256(str(source.get('canonical_content') or '').encode()).hexdigest():
        return {'status': 'REJECTED', 'reason': 'SOURCE_CONTENT_DIGEST_MISMATCH', 'evidence_file_sha256': file_sha}
    override['authoritative_source_name'] = source['authoritative_source_name']
    override['source_reference'] = source['source_reference']
    override['source_digest'] = source['content_sha256']
    result = OverrideLedger(ledger_path).ingest(override, now=now)
    return {'status': result['status'], 'reason': result.get('rejection_reason'), 'audit_id': result.get('audit_id'), 'override_digest': (result.get('override') or {}).get('override_digest'), 'evidence_file_sha256': file_sha, 'source_digest': source['content_sha256']}
__all__ = ['INGEST_SCHEMA', 'ingest_evidence']

# Complete additive V1+V2/V3 public surface.
__all__ = sorted(n for n in globals() if not n.startswith("_"))
