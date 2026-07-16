from __future__ import annotations
import json, os, sqlite3, tempfile
from pathlib import Path
from typing import Any

DB_PATH = "/Users/yasser/scripts/atlas.db"

def strict_loads(text: str) -> Any:
    def reject(value: str):
        raise ValueError(f"non-finite JSON constant: {value}")
    return json.loads(text, parse_constant=reject)

def dumps(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"

def atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
        raise

def open_trades_snapshot(db_path: str = DB_PATH) -> list[dict[str, Any]]:
    if db_path != DB_PATH:
        raise ValueError("authoritative DB path is fixed")
    uri = "file:" + db_path + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT id,ticker,status,entry_at,exit_at FROM trades WHERE status='OPEN' ORDER BY ticker,id").fetchall()
        return [dict(r) for r in rows]
    finally: con.close()
