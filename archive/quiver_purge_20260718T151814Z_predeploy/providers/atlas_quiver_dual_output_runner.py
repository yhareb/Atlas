#!/usr/bin/env python3
"""Runtime safety wrapper for Quiver dual-output packet + Pulse.

Adds production activation controls around the already-approved Quiver modules:
self-lock, busy-process gates, Time Machine classification, and bounded child
runtime. This wrapper does not alter Quiver evidence, scoring, routing, Pulse
wording, decision-envelope logic, TFE integration, or authority boundaries.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import fcntl

try:
    from atlas_time import is_trading_day
except Exception:  # fail closed if calendar helper is unavailable
    is_trading_day = None

ET = ZoneInfo("America/New_York")
SCRIPTS_DIR = "/Users/yasser/scripts"
DEFAULT_ROOT = "/Users/yasser/Library/Application Support/Atlas/quiver_shadow"
DEFAULT_SIDECAR = f"{DEFAULT_ROOT}/db/quiver_sidecar.sqlite"
DEFAULT_LOCK = f"{DEFAULT_ROOT}/run/quiver_dual_output.lock"
DEFAULT_OUTBOX = "/Users/yasser/atlas_inbox"
DEFAULT_PACKET = f"{DEFAULT_OUTBOX}/quiver_engine_packet_v1.json"

BUSY_PROCESS_PATTERNS = [
    "atlas_manage.py",
    "atlas_intraday.py",
    "pre_market_report.py",
    "atlas_eod_positions.py",
    "atlas_position_evidence_orchestrator.py",
    "atlas_position_evidence_bake.py",
    "atlas_profit_protection_apply.py",
    "atlas_quiver_sidecar.py capture",
    "atlas_quiver_sidecar.py settle",
    "Atlas.*backup",
    "Atlas.*migration",
    "atlas.*backup",
    "atlas.*migration",
]

LAUNCHD_LABELS = [
    "com.atlas.intraday",
    "com.atlas.premarket",
    "com.atlas.eod_positions",
    "com.atlas.position_evidence_bake",
    "com.atlas.profit_protection_apply",
    "com.atlas.quiver.capture",
    "com.atlas.quiver.settle",
]

def _bounded_timeout_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except Exception:
        return default
    return max(1, min(value, default))


PACKET_TIMEOUT_SECONDS = _bounded_timeout_env("ATLAS_QUIVER_PACKET_TIMEOUT", 90)
PULSE_TIMEOUT_SECONDS = _bounded_timeout_env("ATLAS_QUIVER_PULSE_TIMEOUT", 60)
TOTAL_TIMEOUT_SECONDS = _bounded_timeout_env("ATLAS_QUIVER_TOTAL_TIMEOUT", 180)


class RuntimeAbort(Exception):
    pass


class TotalTimeout(RuntimeAbort):
    pass


def log_line(message: str) -> None:
    print(f"{datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def _total_timeout_handler(signum: int, frame: Any) -> None:
    raise TotalTimeout("QUIVER_DUAL_OUTPUT_TIMEOUT total_runtime_exceeded")


def is_nyse_session(day: date | None = None) -> tuple[bool, str]:
    day = day or datetime.now(ET).date()
    if day.weekday() >= 5:
        return False, "WEEKEND"
    if is_trading_day is None:
        return False, "CALENDAR_UNKNOWN"
    try:
        if not bool(is_trading_day(day)):
            return False, "NYSE_HOLIDAY"
    except Exception:
        return False, "CALENDAR_UNKNOWN"
    return True, "TRADING_DAY"


class SelfLock:
    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self.fp = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fp = open(self.path, "a+")
        try:
            fcntl.flock(self.fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeAbort(f"QUIVER_SKIP_BUSY_LOCK_HELD path={self.path}")
        self.fp.seek(0)
        self.fp.truncate()
        self.fp.write(json.dumps({"pid": os.getpid(), "started_at": datetime.now().isoformat()}) + "\n")
        self.fp.flush()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.fp is not None:
            try:
                fcntl.flock(self.fp.fileno(), fcntl.LOCK_UN)
            finally:
                self.fp.close()
                self.fp = None
        return False


def run_cmd(args: list[str], timeout: int, step: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    try:
        cp = subprocess.run(
            args,
            timeout=timeout,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeAbort(f"QUIVER_DUAL_OUTPUT_TIMEOUT step={step} seconds={timeout}") from exc
    if cp.returncode != 0:
        raise RuntimeAbort(f"QUIVER_DUAL_OUTPUT_CHILD_FAILED step={step} returncode={cp.returncode} stderr={cp.stderr[-300:]}")
    return cp


def classify_time_machine() -> tuple[str, str]:
    forced = os.environ.get("ATLAS_QUIVER_TEST_TM_STATE")
    if forced:
        return forced.upper(), "forced_test_state"
    try:
        cp = subprocess.run(["/usr/bin/tmutil", "status"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    except Exception as exc:
        return "UNKNOWN", f"tmutil_error:{type(exc).__name__}"
    text = (cp.stdout or "") + "\n" + (cp.stderr or "")
    if "Running = 1" in text:
        return "ACTIVE", "tmutil Running=1"
    if "Running = 0" in text:
        return "CLEAR", "tmutil Running=0"
    return "UNKNOWN", "tmutil_running_state_missing"


def classify_process_pattern(pattern: str) -> tuple[str, str]:
    forced = os.environ.get("ATLAS_QUIVER_TEST_BUSY_STATE")
    if forced:
        parts = forced.split(":", 1)
        state = parts[0].upper()
        name = parts[1] if len(parts) > 1 else pattern
        if name == pattern or name == "ALL":
            return state, "forced_test_state"
    try:
        cp = subprocess.run(["/usr/bin/pgrep", "-fl", pattern], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
    except Exception as exc:
        return "UNKNOWN", f"pgrep_error:{type(exc).__name__}"
    lines = []
    for line in (cp.stdout or "").splitlines():
        if str(os.getpid()) in line:
            continue
        if "atlas_quiver_dual_output_runner.py" in line:
            continue
        lines.append(line)
    if lines:
        return "ACTIVE", "; ".join(lines[:3])
    if cp.returncode in (0, 1):
        return "CLEAR", "no_matching_process"
    return "UNKNOWN", f"pgrep_returncode={cp.returncode}"


def classify_launchd_label(label: str) -> tuple[str, str]:
    forced = os.environ.get("ATLAS_QUIVER_TEST_LAUNCHD_STATE")
    if forced:
        parts = forced.split(":", 1)
        state = parts[0].upper()
        name = parts[1] if len(parts) > 1 else label
        if name == label or name == "ALL":
            return state, "forced_test_state"
    try:
        uid = str(os.getuid())
        cp = subprocess.run(["/bin/launchctl", "print", f"gui/{uid}/{label}"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
    except Exception as exc:
        return "UNKNOWN", f"launchctl_error:{type(exc).__name__}"
    text = (cp.stdout or "") + "\n" + (cp.stderr or "")
    if cp.returncode != 0 and ("Could not find service" in text or "No such process" in text):
        return "CLEAR", "label_not_loaded"
    if "state = running" in text:
        return "ACTIVE", "launchd state=running"
    if cp.returncode == 0:
        return "CLEAR", "launchd not running"
    return "UNKNOWN", f"launchctl_returncode={cp.returncode}"


def run_busy_gates() -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    tm_state, tm_detail = classify_time_machine()
    results.append({"gate": "TimeMachine", "state": tm_state, "detail": tm_detail})
    for pat in BUSY_PROCESS_PATTERNS:
        state, detail = classify_process_pattern(pat)
        results.append({"gate": f"process:{pat}", "state": state, "detail": detail})
    for label in LAUNCHD_LABELS:
        state, detail = classify_launchd_label(label)
        results.append({"gate": f"launchd:{label}", "state": state, "detail": detail})
    return results


def assert_gates_clear(gates: list[dict[str, str]]) -> None:
    blockers = [g for g in gates if g.get("state") != "CLEAR"]
    if blockers:
        raise RuntimeAbort("QUIVER_SKIP_BUSY_OR_UNKNOWN " + json.dumps(blockers, sort_keys=True))


def verify_sidecar_read_only(path: str) -> dict[str, str]:
    p = Path(path)
    if not p.exists():
        raise RuntimeAbort(f"QUIVER_SIDECAR_MISSING path={p}")
    uri = "file:" + str(p.resolve()) + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if str(integrity).lower() != "ok":
            raise RuntimeAbort(f"QUIVER_SIDECAR_INTEGRITY_FAILED result={integrity}")
        return {"path": str(p), "integrity": str(integrity)}
    finally:
        conn.close()


def packet_command(sidecar: str, outbox: str) -> list[str]:
    override = os.environ.get("ATLAS_QUIVER_PACKET_CMD")
    if override:
        return shlex.split(override)
    code = (
        "from atlas_quiver_engine_packet import build_packet, validate_packet, write_packet_outputs; "
        "import json, sys; "
        "packet=build_packet(sys.argv[1]); "
        "ok,reason=validate_packet(packet); "
        "assert ok, reason; "
        "paths=write_packet_outputs(packet, sys.argv[2]); "
        "print(json.dumps({'packet_digest':packet.get('packet_digest'),'freshness_state':packet.get('freshness_state'),'paths':paths}, sort_keys=True))"
    )
    return [sys.executable, "-c", code, sidecar, outbox]


def pulse_command(sidecar: str, outbox: str, dry_run: bool) -> list[str]:
    override = os.environ.get("ATLAS_QUIVER_PULSE_CMD")
    if override:
        return shlex.split(override)
    cmd = [sys.executable, f"{SCRIPTS_DIR}/atlas_quiver_pulse.py", "--sidecar", sidecar, "--outbox", outbox]
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def validate_packet_file(packet_path: str) -> dict[str, Any]:
    p = Path(packet_path)
    if not p.exists():
        raise RuntimeAbort(f"QUIVER_PACKET_MISSING path={p}")
    payload = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    freshness = payload.get("freshness_state")
    health = (payload.get("source_health") or {}).get("status")
    if freshness != "FRESH" or health != "PASS":
        raise RuntimeAbort(f"QUIVER_PACKET_UNHEALTHY freshness={freshness} health={health}")
    return {"packet_digest": payload.get("packet_digest"), "freshness_state": freshness, "source_health": health}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to Pulse; no real Telegram send.")
    parser.add_argument("--sidecar", default=os.environ.get("ATLAS_QUIVER_SIDECAR", DEFAULT_SIDECAR))
    parser.add_argument("--outbox", default=os.environ.get("ATLAS_QUIVER_OUTBOX", DEFAULT_OUTBOX))
    parser.add_argument("--packet", default=os.environ.get("ATLAS_QUIVER_PACKET", DEFAULT_PACKET))
    parser.add_argument("--lock", default=os.environ.get("ATLAS_QUIVER_LOCK", DEFAULT_LOCK))
    parser.add_argument("--force-session", action="store_true", help="Test only: bypass NYSE session gate.")
    args = parser.parse_args(argv)

    signal.signal(signal.SIGALRM, _total_timeout_handler)
    signal.alarm(TOTAL_TIMEOUT_SECONDS)
    try:
        session_ok, reason = is_nyse_session()
        if not args.force_session and not session_ok:
            log_line(f"QUIVER_SKIP_NON_TRADING_DAY reason={reason}")
            return 0
        with SelfLock(args.lock):
            gates = run_busy_gates()
            log_line("QUIVER_BUSY_GATES " + json.dumps(gates, sort_keys=True))
            assert_gates_clear(gates)
            sidecar_state = verify_sidecar_read_only(args.sidecar)
            log_line("QUIVER_SIDECAR_READ_ONLY " + json.dumps(sidecar_state, sort_keys=True))
            packet_cp = run_cmd(packet_command(args.sidecar, args.outbox), PACKET_TIMEOUT_SECONDS, "packet_generation")
            if packet_cp.stdout.strip():
                log_line("QUIVER_PACKET_GENERATED " + packet_cp.stdout.strip().splitlines()[-1])
            packet_state = validate_packet_file(args.packet)
            log_line("QUIVER_PACKET_VALID " + json.dumps(packet_state, sort_keys=True))
            pulse_cp = run_cmd(pulse_command(args.sidecar, args.outbox, args.dry_run), PULSE_TIMEOUT_SECONDS, "pulse_generation_delivery")
            if pulse_cp.stdout.strip():
                log_line("QUIVER_PULSE_DONE " + pulse_cp.stdout.strip().splitlines()[-1])
            log_line("QUIVER_DUAL_OUTPUT_RUNNER_STATUS PASS")
            return 0
    except TotalTimeout as exc:
        log_line(str(exc))
        return 2
    except RuntimeAbort as exc:
        log_line(str(exc))
        return 0
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
