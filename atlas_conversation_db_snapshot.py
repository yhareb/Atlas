#!/usr/bin/env python3
"""Secure runtime atlas.db snapshot lifecycle for Atlas conversation TFE runs.

Staging artifact intended for production deployment with Closure v1. It creates a
per-request private SQLite snapshot using sqlite3 backup API, validates integrity
and counts, writes a non-secret manifest atomically, and deletes only within the
dedicated runtime root.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable
import hashlib, json, os, shutil, sqlite3, stat, time, uuid

CANONICAL_SOURCE_DB = Path("/Users/yasser/scripts/atlas.db")
DEFAULT_RUNTIME_ROOT = Path("/Users/yasser/Library/Application Support/Atlas/conversation_determinism/run")
REQUIRED_TABLES = (
    "trades", "signals", "pending_pullbacks", "report_snapshots", "cash_ledger", "position_lots"
)

class SnapshotError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any], mode: int = 0o600) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    os.chmod(path, mode)


def open_ro(path: Path) -> sqlite3.Connection:
    if path.is_symlink():
        raise SnapshotError("SOURCE_DB_SYMLINK_REJECTED")
    uri = "file:" + str(path.resolve()) + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=10)
    con.execute("PRAGMA query_only=ON")
    return con


def integrity(con: sqlite3.Connection) -> str:
    row = con.execute("PRAGMA integrity_check").fetchone()
    return str(row[0] if row else "missing")


def required_tables_present(con: sqlite3.Connection, required: Iterable[str] = REQUIRED_TABLES) -> list[str]:
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return [t for t in required if t not in have]


def table_counts(con: sqlite3.Connection, required: Iterable[str] = REQUIRED_TABLES) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in required:
        out[t] = int(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
    return out


def digest_counts(counts: dict[str, int]) -> str:
    payload = json.dumps(counts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def safe_request_id(value: str | None = None) -> str:
    raw = value or ("req_" + uuid.uuid4().hex)
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in raw)[:80]
    if not cleaned:
        cleaned = "req_" + uuid.uuid4().hex
    return cleaned


def ensure_private_root(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    if root.is_symlink():
        raise SnapshotError("RUNTIME_ROOT_SYMLINK_REJECTED")
    mode = stat.S_IMODE(root.stat().st_mode)
    if mode != 0o700:
        raise SnapshotError(f"RUNTIME_ROOT_MODE_INVALID:{oct(mode)}")
    return root.resolve()


def assert_inside(child: Path, root: Path) -> None:
    try:
        child.resolve().relative_to(root.resolve())
    except Exception as exc:
        raise SnapshotError("PATH_ESCAPE_REJECTED") from exc


def safe_rmtree(path: Path, root: Path) -> None:
    root_res = root.resolve()
    if not path.exists() and not path.is_symlink():
        return
    # If the entry itself is a symlink, validate the link's parent is inside the
    # runtime root, then unlink the link without resolving/following its target.
    if path.is_symlink():
        assert_inside(path.parent, root_res)
        path.unlink(missing_ok=True)
        return
    assert_inside(path, root_res)
    if path.is_file():
        path.unlink(missing_ok=True)
        return
    # Walk without following symlinks.
    for entry in path.iterdir():
        if entry.is_symlink() or entry.is_file():
            entry.unlink(missing_ok=True)
        elif entry.is_dir():
            safe_rmtree(entry, root_res)
        else:
            try:
                entry.unlink(missing_ok=True)
            except Exception:
                pass
    path.rmdir()

@dataclass(frozen=True)
class SnapshotManifest:
    runtime_request_id: str
    source_path: str
    destination_path: str
    source_sha256: str
    destination_sha256: str
    source_size: int
    destination_size: int
    source_mtime: float
    snapshot_created_at: str
    db_snapshot_method: str
    source_integrity: str
    destination_integrity: str
    table_counts: dict[str, int]
    table_count_digest: str
    runtime_dir_mode: str
    destination_mode: str
    manifest_path: str

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        # Avoid leaking full temp filesystem layout into user-facing packets.
        return {
            "runtime_request_id": d["runtime_request_id"],
            "db_snapshot_method": d["db_snapshot_method"],
            "source_db_fingerprint": d["source_sha256"],
            "snapshot_db_fingerprint": d["destination_sha256"],
            "snapshot_created_at": d["snapshot_created_at"],
            "snapshot_integrity": {"source": d["source_integrity"], "destination": d["destination_integrity"]},
            "snapshot_table_count_digest": d["table_count_digest"],
        }

class RuntimeDBSnapshotManager:
    def __init__(self, *, source_db: str | Path = CANONICAL_SOURCE_DB, runtime_root: str | Path = DEFAULT_RUNTIME_ROOT, allow_test_override: bool = False, cleanup_age_seconds: int = 6 * 3600, retain_failure_count: int = 5):
        self.source_db = Path(source_db)
        self.runtime_root = Path(runtime_root)
        self.allow_test_override = bool(allow_test_override)
        self.cleanup_age_seconds = int(cleanup_age_seconds)
        self.retain_failure_count = int(retain_failure_count)
        if self.source_db.resolve() != CANONICAL_SOURCE_DB.resolve() and not self.allow_test_override:
            raise SnapshotError("ARBITRARY_SOURCE_DB_REJECTED")
        if self.source_db.resolve() == CANONICAL_SOURCE_DB.resolve() and self.source_db.is_symlink():
            raise SnapshotError("SOURCE_DB_SYMLINK_REJECTED")

    def cleanup_abandoned(self) -> dict[str, Any]:
        root = ensure_private_root(self.runtime_root)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.cleanup_age_seconds)
        removed: list[str] = []
        retained_failures: list[Path] = []
        for item in list(root.iterdir()):
            if item.name.startswith("failure_"):
                retained_failures.append(item)
                continue
            try:
                mtime = datetime.fromtimestamp(item.stat().st_mtime, timezone.utc)
            except FileNotFoundError:
                continue
            if mtime < cutoff:
                safe_rmtree(item, root)
                removed.append(item.name)
        # Bound retained failure metadata dirs/files by mtime, never DB copies.
        retained_failures.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        for old in retained_failures[self.retain_failure_count:]:
            safe_rmtree(old, root)
            removed.append(old.name)
        return {"removed": removed, "runtime_root": str(root), "retained_failure_count": min(len(retained_failures), self.retain_failure_count)}

    def create_snapshot(self, request_id: str | None = None, acquisition_timeout: float = 20.0) -> tuple[Path, SnapshotManifest]:
        old_umask = os.umask(0o077)
        try:
            root = ensure_private_root(self.runtime_root)
            self.cleanup_abandoned()
            rid = safe_request_id(request_id)
            run_dir = root / (rid + "_" + uuid.uuid4().hex[:12])
            assert_inside(run_dir, root)
            run_dir.mkdir(mode=0o700)
            os.chmod(run_dir, 0o700)
            dest = run_dir / "atlas_snapshot.db"
            manifest_path = run_dir / "snapshot_manifest.json"
            src = self.source_db.resolve()
            if self.source_db.is_symlink():
                raise SnapshotError("SOURCE_DB_SYMLINK_REJECTED")
            started = time.time()
            while True:
                try:
                    src_con = open_ro(src)
                    break
                except sqlite3.OperationalError:
                    if time.time() - started > acquisition_timeout:
                        raise SnapshotError("SNAPSHOT_ACQUISITION_TIMEOUT")
                    time.sleep(0.05)
            try:
                src_integrity = integrity(src_con)
                if src_integrity != "ok":
                    raise SnapshotError("SOURCE_INTEGRITY_FAILED:" + src_integrity)
                missing = required_tables_present(src_con)
                if missing:
                    raise SnapshotError("SOURCE_REQUIRED_TABLES_MISSING:" + ",".join(missing))
                src_counts = table_counts(src_con)
                src_digest = digest_counts(src_counts)
                dest_con = sqlite3.connect(str(dest))
                try:
                    src_con.backup(dest_con)
                    dest_con.commit()
                finally:
                    dest_con.close()
                os.chmod(dest, 0o600)
            finally:
                src_con.close()
            dst_con = sqlite3.connect(str(dest))
            try:
                dst_integrity = integrity(dst_con)
                if dst_integrity != "ok":
                    raise SnapshotError("DESTINATION_INTEGRITY_FAILED:" + dst_integrity)
                missing = required_tables_present(dst_con)
                if missing:
                    raise SnapshotError("DESTINATION_REQUIRED_TABLES_MISSING:" + ",".join(missing))
                dst_counts = table_counts(dst_con)
            finally:
                dst_con.close()
            if dst_counts != src_counts:
                raise SnapshotError("TABLE_COUNTS_MISMATCH")
            st_src = src.stat()
            st_dst = dest.stat()
            manifest = SnapshotManifest(
                runtime_request_id=rid,
                source_path=str(CANONICAL_SOURCE_DB),
                destination_path=str(dest),
                source_sha256=sha256_file(src),
                destination_sha256=sha256_file(dest),
                source_size=st_src.st_size,
                destination_size=st_dst.st_size,
                source_mtime=st_src.st_mtime,
                snapshot_created_at=utc_now(),
                db_snapshot_method="sqlite3_backup_api_readonly_source",
                source_integrity=src_integrity,
                destination_integrity=dst_integrity,
                table_counts=src_counts,
                table_count_digest=src_digest,
                runtime_dir_mode=oct(stat.S_IMODE(run_dir.stat().st_mode)),
                destination_mode=oct(stat.S_IMODE(dest.stat().st_mode)),
                manifest_path=str(manifest_path),
            )
            atomic_write_json(manifest_path, asdict(manifest), 0o600)
            return dest, manifest
        finally:
            os.umask(old_umask)

    def cleanup_snapshot(self, db_path: Path, *, success: bool, error: str | None = None, manifest: SnapshotManifest | None = None) -> dict[str, Any]:
        root = ensure_private_root(self.runtime_root)
        run_dir = db_path.parent
        assert_inside(run_dir, root)
        evidence: dict[str, Any] | None = None
        if not success:
            evidence = {
                "runtime_request_id": manifest.runtime_request_id if manifest else run_dir.name,
                "failed_at": utc_now(),
                "error": str(error or "unknown")[:500],
                "manifest": manifest.public() if manifest else None,
            }
            failure_name = "failure_" + safe_request_id(evidence["runtime_request_id"]) + ".json"
            atomic_write_json(root / failure_name, evidence, 0o600)
        safe_rmtree(run_dir, root)
        self.cleanup_abandoned()
        return {"cleanup_status": "REMOVED", "success": success, "failure_metadata_retained": bool(evidence)}

__all__ = ["RuntimeDBSnapshotManager", "SnapshotManifest", "SnapshotError", "CANONICAL_SOURCE_DB", "DEFAULT_RUNTIME_ROOT", "REQUIRED_TABLES", "sha256_file", "table_counts", "digest_counts", "safe_rmtree"]
