#!/usr/bin/env python3
"""Atlas hourly/half-hour API audit report.

Stage-only Fix #10 artifact. Reads Atlas operational logs and, when available,
the Atlas ops API audit table. No trading decisions are made here.
"""
import argparse
import datetime as _dt
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

SCRIPTS_DIR = Path(os.environ.get("ATLAS_SCRIPTS_DIR", "/Users/yasser/scripts"))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

ET = ZoneInfo("America/New_York")
PROVIDERS = ("Massive", "Benzinga", "EODHD", "Perme")
LOG_FILES = (
    "atlas_intraday.log",
    "atlas_intraday.err.log",
    "pre_market_report_launchd.log",
    "pre_market_report_launchd.err.log",
    "market_scout.log",
    "market_scout.err.log",
    "atlas_audit_report.log",
    "atlas_audit_report.err.log",
    "atlas_daily.log",
    "atlas_daily.err.log",
    "atlas_ingest.log",
    "atlas_ingest.err.log",
)
ERROR_WORDS = re.compile(r"\b(error|failed|failure|exception|traceback|timeout|http\s+[45]\d\d|status[= ]+[45]\d\d)\b", re.I)
OK_WORDS = re.compile(r"\b(http\s+2\d\d|status[= ]+2\d\d|ok=True|success|sent)\b", re.I)
HTTP_STATUS = re.compile(r"(?:HTTP\s*|status[= ]+|http_status[= ]+)([1-5]\d\d)", re.I)
LATENCY = re.compile(r"(?:latency_ms|elapsed_ms|response_ms)[=:\s]+([0-9]+(?:\.[0-9]+)?)", re.I)
API_HINT = re.compile(r"(massive\.com|polygon\.io|benzinga\.com|eodhd\.com|perme|api[_ -]?call|_audit_get|requests\.)", re.I)
ATLASOPS_ENV = Path("/Users/yasser/.hermes/profiles/atlasops/.env")


def _env_file_values(path):
    values = {}
    if not path.exists():
        return values
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _chunks(message, limit=3800):
    text = str(message or "")
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < 1000:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    chunks.append(text)
    return chunks


def send_atlasops_audit_telegram(message, label="atlas_api_audit", parse_mode=""):
    """Send audit reports through the AtlasOps bot only; never atlas_notify/Atlas bot."""
    values = _env_file_values(ATLASOPS_ENV)
    bot_token = values.get("TELEGRAM_BOT_TOKEN")
    chat_id = values.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print(f"[{label}] telegram skipped: atlasops TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID unset")
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    sent = 0
    for chunk in _chunks(message):
        payload = {"chat_id": chat_id, "text": chunk}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        try:
            resp = requests.post(url, json=payload, timeout=(5, 25))
            if resp.status_code != 200:
                print(f"[{label}] telegram failed HTTP {resp.status_code}")
                return False
            sent += 1
        except Exception as exc:
            print(f"[{label}] telegram failed: {type(exc).__name__}")
            return False
    print(f"[{label}] telegram sent via atlasops bot: chunks={sent}")
    return True


def _now_et():
    return _dt.datetime.now(ET)


def _parse_args():
    p = argparse.ArgumentParser(description="Atlas API audit report")
    p.add_argument("--window-minutes", type=int, default=30)
    p.add_argument("--dry-run", action="store_true", help="print only; suppress Telegram send")
    p.add_argument("--no-send", action="store_true", help="print only; suppress Telegram send")
    p.add_argument("--allow-outside-market-window", action="store_true", help="skip ET weekday/time gate")
    return p.parse_args()


def _inside_report_window(now=None):
    now = now or _now_et()
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=9, minute=30, second=0, microsecond=0)
    end = now.replace(hour=16, minute=30, second=0, microsecond=0)
    return start <= now <= end


def _provider_from_text(text):
    t = str(text or "")
    low = t.lower()
    if "massive" in low or "polygon.io" in low:
        return "Massive"
    if "benzinga" in low:
        return "Benzinga"
    if "eodhd" in low:
        return "EODHD"
    if "perme" in low:
        return "Perme"
    return None


def _redact(text):
    text = str(text or "").replace("\n", " ")
    text = re.sub(r"(api[_-]?key|api_token|token|authorization|password|secret)=([^&\s]+)", r"\1=****", text, flags=re.I)
    text = re.sub(r"Bearer\s+[A-Za-z0-9._:-]+", "Bearer ****", text, flags=re.I)
    text = re.sub(r"[A-Za-z0-9_=-]{32,}", lambda m: "****" + m.group(0)[-4:], text)
    return text[:180]


def _status_ok(status):
    try:
        s = int(status)
        return 200 <= s < 400
    except Exception:
        return None


def _blank_summary():
    return {
        "total": 0,
        "success": 0,
        "failure": 0,
        "by_provider": Counter({p: 0 for p in PROVIDERS}),
        "success_by_provider": Counter({p: 0 for p in PROVIDERS}),
        "failure_by_provider": Counter({p: 0 for p in PROVIDERS}),
        "latency_ms": [],
        "errors": [],
        "sources": set(),
    }


def _merge(dst, src):
    dst["total"] += src["total"]
    dst["success"] += src["success"]
    dst["failure"] += src["failure"]
    dst["by_provider"].update(src["by_provider"])
    dst["success_by_provider"].update(src["success_by_provider"])
    dst["failure_by_provider"].update(src["failure_by_provider"])
    dst["latency_ms"].extend(src["latency_ms"])
    dst["errors"].extend(src["errors"])
    dst["sources"].update(src["sources"])


def _query_audit_table(window_minutes):
    out = _blank_summary()
    try:
        import atlas_audit  # existing operational audit utility
        conn = atlas_audit._connect()
    except Exception:
        return out
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT provider, file_path, function_name, endpoint, http_status, latency_ms, ok, error
                FROM ops_api_calls
                WHERE ts >= now() - (%s || ' minutes')::interval
                ORDER BY ts DESC
                LIMIT 500
                """,
                (int(window_minutes),),
            )
            rows = cur.fetchall()
        out["sources"].add("ops_api_calls")
        for row in rows:
            provider, file_name, func, endpoint, status, latency, ok, err = row
            provider = provider if provider in PROVIDERS else _provider_from_text(endpoint) or _provider_from_text(file_name) or "Other"
            out["total"] += 1
            out["by_provider"][provider] += 1
            if latency not in (None, ""):
                try:
                    out["latency_ms"].append(float(latency))
                except Exception:
                    pass
            ok_bool = bool(ok) if ok is not None else _status_ok(status)
            if ok_bool:
                out["success"] += 1
                out["success_by_provider"][provider] += 1
            else:
                out["failure"] += 1
                out["failure_by_provider"][provider] += 1
                detail = err or f"{provider} HTTP {status} {file_name or ''}.{func or ''} {endpoint or ''}"
                out["errors"].append(_redact(detail))
    except Exception as e:
        out["errors"].append(_redact(f"ops_api_calls query failed: {e}"))
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


def _read_recent_tail(path, max_bytes=250_000):
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            return f.read().decode("utf-8", errors="ignore").splitlines()
    except Exception:
        return []


def _line_timestamp_in_window(line, cutoff):
    # If no parseable timestamp exists, exclude the line — do not include stale lines as "best effort".
    patterns = (
        r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]",
        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})",
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",
    )
    for pat in patterns:
        m = re.search(pat, line)
        if not m:
            continue
        raw = m.group(1).replace("T", " ")
        try:
            dt = _dt.datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                # Naive timestamp — compare directly against naive cutoff.
                return dt >= cutoff.replace(tzinfo=None)
            return dt.astimezone(ET) >= cutoff
        except Exception:
            pass
    return False


def _parse_logs(window_minutes):
    out = _blank_summary()
    cutoff = _now_et() - _dt.timedelta(minutes=int(window_minutes))
    seen_errors = set()
    for name in LOG_FILES:
        path = SCRIPTS_DIR / name
        if not path.exists():
            continue
        out["sources"].add(name)
        for line in _read_recent_tail(path):
            if not line or not _line_timestamp_in_window(line, cutoff):
                continue
            provider = _provider_from_text(line)
            if not provider and not API_HINT.search(line):
                continue
            provider = provider or "Other"
            status_m = HTTP_STATUS.search(line)
            latency_m = LATENCY.search(line)
            is_error = bool(ERROR_WORDS.search(line))
            is_ok = bool(OK_WORDS.search(line))
            if status_m:
                ok = _status_ok(status_m.group(1))
                is_ok = ok is True
                is_error = ok is False
            if provider in PROVIDERS:
                out["total"] += 1
                out["by_provider"][provider] += 1
                if latency_m:
                    try:
                        out["latency_ms"].append(float(latency_m.group(1)))
                    except Exception:
                        pass
                if is_error:
                    out["failure"] += 1
                    out["failure_by_provider"][provider] += 1
                    red = _redact(line)
                    if red not in seen_errors:
                        out["errors"].append(red)
                        seen_errors.add(red)
                else:
                    # Log files often only emit failures explicitly; provider/API lines
                    # without an error marker are counted as successful operational calls.
                    out["success"] += 1
                    out["success_by_provider"][provider] += 1
    return out


def _build_report(summary, window_minutes):
    now = _now_et()
    avg = statistics.mean(summary["latency_ms"]) if summary["latency_ms"] else None
    status_icon = "✅" if summary["failure"] == 0 else "⚠️"
    lines = [
        f"🛰️ ATLAS API AUDIT — {now:%H:%M ET}",
        f"{status_icon} Window: last {int(window_minutes)}m · Sources: {len(summary['sources'])}",
        "",
        "━━━ 📡 CALLS ━━━",
        f"🔢 Total: {summary['total']}",
        f"✅ Success: {summary['success']}",
        f"❌ Failure: {summary['failure']}",
        f"⏱️ Avg latency: {avg:.0f} ms" if avg is not None else "⏱️ Avg latency: N/A",
        "",
        "━━━ 🧭 PROVIDERS ━━━",
    ]
    for p in PROVIDERS:
        total = summary["by_provider"].get(p, 0)
        ok = summary["success_by_provider"].get(p, 0)
        bad = summary["failure_by_provider"].get(p, 0)
        icon = "✅" if bad == 0 else "⚠️"
        lines.append(f"{icon} {p}: {total} calls · {ok} ok · {bad} fail")
    lines += ["", "━━━ 🚨 ERRORS ━━━"]
    errors = [_redact(e) for e in summary["errors"] if str(e or "").strip()]
    if not errors:
        lines.append("✅ none")
    else:
        for err in list(dict.fromkeys(errors))[:6]:
            lines.append(f"• {err}")
    return "\n".join(lines)


def main():
    args = _parse_args()
    if not args.allow_outside_market_window and not _inside_report_window():
        msg = f"[atlas_api_audit] outside ET report window; no send ({_now_et():%Y-%m-%d %H:%M ET})"
        print(msg)
        return 0
    summary = _blank_summary()
    _merge(summary, _query_audit_table(args.window_minutes))
    _merge(summary, _parse_logs(args.window_minutes))
    report = _build_report(summary, args.window_minutes)
    print(report)
    if args.dry_run or args.no_send:
        print("\n[atlas_api_audit] dry-run/no-send: Telegram suppressed")
        return 0
    ok = send_atlasops_audit_telegram(report, label="atlas_api_audit", parse_mode="")
    print(f"[atlas_api_audit] telegram_sent={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
