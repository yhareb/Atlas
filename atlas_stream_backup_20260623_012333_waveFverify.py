"""Optional Massive stock WebSocket helper for Atlas.

Safety doctrine:
- Disabled instantly with ATLAS_STREAMING_ENABLED=0/false/off.
- Subscribes only armed pullback tickers + current holdings.
- Stream never places orders. It only emits an evaluate-now flag callback.
- Polling remains source of truth. Any stream problem logs fallback and returns.
"""
from __future__ import annotations

import base64, json, os, socket, ssl, struct, threading, time
import sys
sys.path.insert(0, "/Users/yasser/scripts")

import atlas_db
from atlas_engine import MASSIVE_API_KEY

WS_URL_HOST = "socket.massive.com"
WS_PATH = "/stocks"
DEFAULT_BACKOFF_SECONDS = 5
STALE_SECONDS = 30


def streaming_enabled():
    raw = os.environ.get("ATLAS_STREAMING_ENABLED", "1").strip().lower()
    return raw not in {"0", "false", "off", "no", "disabled"}


def symbols_to_watch():
    symbols = set()
    try:
        for row in atlas_db.get_pending_pullbacks(status="WAITING"):
            t = str(row.get("ticker") or "").upper()
            if t:
                symbols.add(t)
    except Exception as e:
        print(f"[atlas_stream] pending symbol load failed; polling continues: {e}")
    try:
        for row in atlas_db.get_open_positions():
            t = str(row.get("ticker") or "").upper()
            if t:
                symbols.add(t)
    except Exception as e:
        print(f"[atlas_stream] holding symbol load failed; polling continues: {e}")
    return sorted(symbols)


def _ws_key():
    return base64.b64encode(os.urandom(16)).decode()


def _encode_frame(text):
    data = text.encode("utf-8")
    mask = os.urandom(4)
    length = len(data)
    if length < 126:
        header = struct.pack("!BB", 0x81, 0x80 | length)
    elif length < 65536:
        header = struct.pack("!BBH", 0x81, 0x80 | 126, length)
    else:
        header = struct.pack("!BBQ", 0x81, 0x80 | 127, length)
    return header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data))


def _recv_exact(sock, n):
    out = b""
    while len(out) < n:
        chunk = sock.recv(n - len(out))
        if not chunk:
            raise EOFError("websocket closed")
        out += chunk
    return out


def _read_frame(sock):
    h = _recv_exact(sock, 2)
    opcode = h[0] & 0x0F
    length = h[1] & 0x7F
    masked = h[1] & 0x80
    if length == 126:
        length = struct.unpack("!H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(sock, 8))[0]
    mask = _recv_exact(sock, 4) if masked else b""
    payload = _recv_exact(sock, length) if length else b""
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    if opcode == 8:
        raise EOFError("websocket close frame")
    return payload.decode("utf-8", "replace")


def _connect_and_auth(timeout=8):
    raw = socket.create_connection((WS_URL_HOST, 443), timeout=timeout)
    sock = ssl.create_default_context().wrap_socket(raw, server_hostname=WS_URL_HOST)
    sock.settimeout(timeout)
    req = (
        f"GET {WS_PATH} HTTP/1.1\r\n"
        f"Host: {WS_URL_HOST}\r\n"
        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {_ws_key()}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(req.encode("utf-8"))
    resp = b""
    while b"\r\n\r\n" not in resp:
        resp += sock.recv(4096)
    if b"101" not in resp.split(b"\r\n", 1)[0]:
        raise RuntimeError(resp.decode("utf-8", "replace")[:200])
    sock.sendall(_encode_frame(json.dumps({"action": "auth", "params": MASSIVE_API_KEY})))
    auth_ok = False
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = _read_frame(sock)
        try:
            parsed = json.loads(msg)
        except Exception:
            parsed = []
        rows = parsed if isinstance(parsed, list) else [parsed]
        for row in rows:
            if isinstance(row, dict) and row.get("status") == "auth_success":
                auth_ok = True
                break
        if auth_ok:
            break
    if not auth_ok:
        raise RuntimeError("websocket auth failed")
    return sock


def _aggregate_price(row):
    if not isinstance(row, dict):
        return None
    if row.get("ev") not in {"A", "AM"}:
        return None
    for key in ("c", "p", "vw"):
        try:
            val = row.get(key)
            if val is not None:
                return float(val)
        except Exception:
            pass
    return None


def stream_once(symbols=None, on_evaluate=None, timeout_seconds=20, simulate_drop=False):
    """Run one bounded stream session. Returns a status dict; never raises."""
    if not streaming_enabled():
        return {"enabled": False, "fallback": False, "reason": "feature flag off"}
    symbols = sorted(set(symbols or symbols_to_watch()))
    if not symbols:
        return {"enabled": True, "fallback": False, "reason": "no armed pullbacks/holdings", "symbols": []}
    if simulate_drop:
        print("[atlas_stream] simulated stream drop; fallback to polling")
        return {"enabled": True, "fallback": True, "reason": "simulated drop", "symbols": symbols}
    if not MASSIVE_API_KEY:
        print("[atlas_stream] missing API key; fallback to polling")
        return {"enabled": True, "fallback": True, "reason": "missing api key", "symbols": symbols}
    try:
        sock = _connect_and_auth()
        params = ",".join([f"A.{s}" for s in symbols] + [f"AM.{s}" for s in symbols])
        sock.sendall(_encode_frame(json.dumps({"action": "subscribe", "params": params})))
        started = last_msg = time.time()
        events = 0
        while time.time() - started < timeout_seconds:
            if time.time() - last_msg > STALE_SECONDS:
                raise TimeoutError("stale websocket heartbeat")
            try:
                msg = _read_frame(sock)
            except socket.timeout:
                continue
            last_msg = time.time()
            try:
                parsed = json.loads(msg)
            except Exception:
                continue
            rows = parsed if isinstance(parsed, list) else [parsed]
            for row in rows:
                price = _aggregate_price(row)
                sym = str(row.get("sym") or "").upper() if isinstance(row, dict) else ""
                if sym and price is not None:
                    events += 1
                    if on_evaluate:
                        on_evaluate({"ticker": sym, "price": price, "source": "stream", "row": row})
        try:
            sock.close()
        except Exception:
            pass
        return {"enabled": True, "fallback": False, "reason": "completed", "symbols": symbols, "events": events}
    except Exception as e:
        print(f"[atlas_stream] stream failed; fallback to polling: {e}")
        return {"enabled": True, "fallback": True, "reason": str(e)[:160], "symbols": symbols}


def start_background(symbols=None, on_evaluate=None, max_reconnects=3, backoff_seconds=DEFAULT_BACKOFF_SECONDS):
    if not streaming_enabled():
        print("[atlas_stream] disabled by ATLAS_STREAMING_ENABLED; polling only")
        return {"started": False, "reason": "feature flag off"}
    symbols = sorted(set(symbols or symbols_to_watch()))
    if not symbols:
        return {"started": False, "reason": "no symbols"}

    def _runner():
        attempt = 0
        while max_reconnects is None or attempt < max_reconnects:
            result = stream_once(symbols=symbols, on_evaluate=on_evaluate, timeout_seconds=3600)
            if result.get("fallback"):
                print(f"[atlas_stream] polling fallback active; reconnecting in {backoff_seconds}s")
                time.sleep(backoff_seconds)
                attempt += 1
                continue
            break
    thread = threading.Thread(target=_runner, name="atlas_stream", daemon=True)
    thread.start()
    print(f"[atlas_stream] background stream started for {','.join(symbols)}")
    return {"started": True, "symbols": symbols}
