import os
import sys
import time
import requests

_ENV_PATH = os.path.expanduser("~/.hermes/profiles/atlas/.env")
_ENV_VALUES = None
_ENV_LOAD_ERROR = None

# Expected Atlas Telegram destination. TELEGRAM_CHAT_ID_EXPECTED in .env is the source of truth.
TELEGRAM_CHAT_ID_EXPECTED_DEFAULT = ""


def _telegram_disabled():
    return str(os.environ.get("ATLAS_DISABLE_TELEGRAM") or "").strip().lower() in {"1", "true", "yes", "on"}


def _telegram_mocked():
    return str(os.environ.get("ATLAS_MOCK_TELEGRAM") or "").strip().lower() in {"1", "true", "yes", "on"}


def _load_env_values():
    """Lazy Atlas .env loader. Never runs at module import; never logs values."""
    global _ENV_VALUES, _ENV_LOAD_ERROR
    if _ENV_VALUES is not None:
        return _ENV_VALUES
    values = {}
    _ENV_LOAD_ERROR = None
    try:
        if os.path.exists(_ENV_PATH):
            with open(_ENV_PATH) as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line and not _line.startswith("#") and "=" in _line:
                        _k, _v = _line.split("=", 1)
                        _k = _k.strip()
                        _v = _v.strip()
                        values[_k] = _v
                        os.environ.setdefault(_k, _v)
    except Exception as exc:
        _ENV_LOAD_ERROR = type(exc).__name__
    _ENV_VALUES = values
    return _ENV_VALUES


def _cfg(key, default=None, prefer_env_file=True):
    """Return config, lazily preferring Atlas .env for real Telegram sends."""
    if prefer_env_file:
        env_values = _load_env_values()
        if key in env_values and str(env_values.get(key, "")).strip():
            return str(env_values[key]).strip()
    return str(os.environ.get(key, default or "")).strip()


def _chat_id():
    return (_cfg("TELEGRAM_CHAT_ID")
            or _cfg("TELEGRAM_ALLOWED_USERS")
            or _cfg("TELEGRAM_HOME_CHANNEL"))


def _expected_chat_id():
    return (_cfg("TELEGRAM_CHAT_ID_EXPECTED")
            or TELEGRAM_CHAT_ID_EXPECTED_DEFAULT).strip()


def _admin_chat_id():
    return (_cfg("TELEGRAM_ADMIN_CHAT_ID")
            or _cfg("TELEGRAM_FALLBACK_CHAT_ID")
            or _cfg("TELEGRAM_ALLOWED_USERS")
            or _cfg("TELEGRAM_HOME_CHANNEL")
            or _expected_chat_id())


def _bot_token():
    return _cfg("TELEGRAM_BOT_TOKEN")


def _cfg_source(*keys):
    """Return the first configured value plus its env-var name; never log values."""
    for key in keys:
        value = _cfg(key)
        if value:
            return value, key
    return "", "UNSET"


def _group_route_allowlist():
    raw = _cfg("ATLAS_TELEGRAM_GROUP_ROUTE_ALLOWLIST", prefer_env_file=False)
    return {x.strip().lower() for x in str(raw or "").split(",") if x.strip()}


def _thread_var_for_report(report_type):
    report = str(report_type or "").strip().lower()
    if report in {"pre_market", "premarket", "premarket_gaps", "pre_market_gaps"}:
        return "ATLAS_TOPIC_PREMARKET_THREAD_ID"
    if report in {"intraday", "interday"}:
        return "ATLAS_TOPIC_INTERDAY_THREAD_ID"
    if report in {"post_market", "postmarket", "eod", "eod_writer", "handoff"}:
        return "ATLAS_TOPIC_POSTMARKET_THREAD_ID"
    return "ATLAS_TOPIC_THREAD_ID"


def resolve_report_route(route="professor_dm", report_type=None):
    """Central Atlas Telegram route contract.

    Default Professor-facing route is Atlas DM/admin. Group/topic routing is
    fail-closed unless the report_type is explicitly allowlisted by name.
    Returned dict contains raw destination values for the sender, but logs must
    use only *_source fields and booleans.
    """
    route_name = str(route or "professor_dm").strip().lower()
    report = str(report_type or "atlas").strip().lower()
    if route_name in {"professor_dm", "dm", "admin", "atlas_dm"}:
        chat, source = _cfg_source(
            "TELEGRAM_ADMIN_CHAT_ID",
            "TELEGRAM_FALLBACK_CHAT_ID",
            "TELEGRAM_ALLOWED_USERS",
            "TELEGRAM_HOME_CHANNEL",
            "TELEGRAM_CHAT_ID_EXPECTED",
        )
        return {
            "route": "professor_dm",
            "chat_id": chat,
            "message_thread_id": None,
            "chat_source": source,
            "thread_source": "NONE",
            "allowed": True,
        }
    if route_name in {"approved_group_topic", "group_topic", "group"}:
        allowlist = _group_route_allowlist()
        if report not in allowlist:
            raise ValueError(f"group route not allowlisted for report_type={report or 'unknown'}")
        chat, source = _cfg_source("ATLAS_REPORTS_GROUP_CHAT_ID")
        thread_var = _thread_var_for_report(report)
        thread_value, thread_source = _cfg_source(thread_var)
        thread_id = None
        if thread_value:
            try:
                thread_id = int(thread_value)
            except Exception:
                raise ValueError(f"invalid thread id in {thread_var}")
        return {
            "route": "approved_group_topic",
            "chat_id": chat,
            "message_thread_id": thread_id,
            "chat_source": source,
            "thread_source": thread_source if thread_id is not None else "NONE",
            "allowed": True,
        }
    raise ValueError(f"unknown telegram route {route_name}")


def validate_telegram_chat(force=False, startup=False):
    """Network validation intentionally disabled.

    Atlas Telegram routing is resolved from ~/.hermes/profiles/atlas/.env.
    Do not call Telegram route-probe APIs here; network checks created false
    alarms on transient Telegram timeouts.
    """
    configured = (_chat_id() or "").strip()
    expected = _expected_chat_id()
    return {
        "ok": bool(configured),
        "chat_id_match": bool(configured and (not expected or configured == expected)),
        "configured": bool(configured),
        "expected_set": bool(expected),
        "chat_source": "atlas_env_file",
        "network_validation": "disabled",
    }


def _chunks(message, limit=3800):
    text = str(message or "")
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < 1000:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip()
    chunks.append(text)
    return chunks


def send_telegram(message, label="atlas", parse_mode="Markdown", print_fallback=True, chat_id=None, message_thread_id=None, route=None, report_type=None):
    """Robust non-fatal Telegram sender with central route contract support."""
    if _telegram_disabled() or _telegram_mocked():
        mode = "ATLAS_MOCK_TELEGRAM" if _telegram_mocked() else "ATLAS_DISABLE_TELEGRAM"
        print(f"[{label}] telegram skipped: {mode} set")
        if print_fallback:
            print(message)
        return True
    token = _bot_token()
    if route is not None:
        resolved = resolve_report_route(route=route, report_type=report_type or label)
        chat = str(resolved.get("chat_id") or "").strip()
        message_thread_id = resolved.get("message_thread_id")
        print(
            f"[atlas_notify] routing: route={resolved.get('route')} chat_source={resolved.get('chat_source')} thread_set={message_thread_id is not None} thread_source={resolved.get('thread_source')}",
            file=sys.stderr,
        )
    else:
        chat = str(chat_id).strip() if chat_id not in (None, "") else _chat_id()
        print(f"[atlas_notify] routing: route=legacy chat_id_arg_set={chat_id not in (None, '')} resolved_chat_set={bool(chat)} thread_set={message_thread_id is not None}", file=sys.stderr)
    if not token or not chat:
        missing = []
        if not token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not chat:
            missing.append("TELEGRAM_CHAT_ID/TELEGRAM_ADMIN_CHAT_ID")
        load_note = f" env_load={_ENV_LOAD_ERROR}" if _ENV_LOAD_ERROR else ""
        print(f"[{label}] telegram failed: SEND_CREDENTIALS_UNAVAILABLE missing={','.join(missing)}{load_note}")
        if print_fallback:
            print(message)
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    attempts = int(os.environ.get("ATLAS_TELEGRAM_ATTEMPTS", "3"))
    timeout = float(os.environ.get("ATLAS_TELEGRAM_TIMEOUT", "25"))
    backoffs = [2, 5]
    sent_ids = []
    msg_chunks = _chunks(message)
    for idx, chunk in enumerate(msg_chunks, 1):
        payload = {"chat_id": chat, "text": chunk}
        if message_thread_id is not None:
            payload["message_thread_id"] = int(message_thread_id)
        if parse_mode:
            payload["parse_mode"] = parse_mode
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                r = requests.post(url, json=payload, timeout=(5, timeout))
                if r.status_code != 200:
                    err_text = r.text[:300]
                    if r.status_code == 400 and parse_mode and "can't parse entities" in err_text:
                        plain_payload = {"chat_id": chat, "text": chunk}
                        if message_thread_id is not None:
                            plain_payload["message_thread_id"] = int(message_thread_id)
                        r = requests.post(url, json=plain_payload, timeout=(5, timeout))
                        if r.status_code == 200:
                            data = r.json()
                            if data.get("ok"):
                                msg_id = data.get("result", {}).get("message_id")
                                sent_ids.append(msg_id)
                                print(f"[{label}] telegram chunk {idx}/{len(msg_chunks)} sent plain-text after Markdown parse failure on attempt {attempt}: message_id={msg_id}")
                                break
                    raise RuntimeError(f"Telegram HTTP {r.status_code}: {err_text}")
                data = r.json()
                if not data.get("ok"):
                    raise RuntimeError(f"Telegram rejected chunk {idx}: {data}")
                msg_id = data.get("result", {}).get("message_id")
                sent_ids.append(msg_id)
                print(f"[{label}] telegram chunk {idx}/{len(msg_chunks)} sent on attempt {attempt}: message_id={msg_id}")
                break
            except Exception as e:
                last_error = e
                if attempt >= attempts:
                    print(f"[{label}] telegram failed after {attempts} attempts for chunk {idx}: {e}")
                    return False
                delay = backoffs[min(attempt - 1, len(backoffs) - 1)]
                print(f"[{label}] telegram chunk {idx} attempt {attempt} failed: {e}; retrying in {delay}s")
                time.sleep(delay)
        else:
            print(f"[{label}] telegram failed: {last_error}")
            return False
    print(f"[{label}] telegram report sent: chunks={len(sent_ids)} message_ids={sent_ids}")
    return True


def send_message(message, label="atlas", parse_mode="Markdown", print_fallback=True, chat_id=None, message_thread_id=None, route=None, report_type=None):
    """Compatibility alias for callers that expect send_message()."""
    return send_telegram(message, label=label, parse_mode=parse_mode, print_fallback=print_fallback, chat_id=chat_id, message_thread_id=message_thread_id, route=route, report_type=report_type)


def send_professor_media(media_path, caption, *, sender=None):
    """Send one Professor-DM image; receipts never contain routing values."""
    if sender is not None:
        ok = bool(sender(str(media_path), str(caption), route="professor_dm",
                         report_type="broker_registration_review"))
        return {"delivered": ok, "route": "professor_dm",
                "routing_variable": "TELEGRAM_ADMIN_CHAT_ID", "mocked": True}
    if _telegram_disabled() or _telegram_mocked():
        return {"delivered": True, "route": "professor_dm",
                "routing_variable": "TELEGRAM_ADMIN_CHAT_ID", "mocked": True}
    token = _bot_token()
    resolved = resolve_report_route("professor_dm", "broker_registration_review")
    chat = str(resolved.get("chat_id") or "").strip()
    if not token or not chat:
        return {"delivered": False, "route": "professor_dm",
                "routing_variable": "TELEGRAM_ADMIN_CHAT_ID", "error": "SEND_CREDENTIALS_UNAVAILABLE"}
    try:
        with open(media_path, "rb") as fh:
            response = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": chat, "caption": str(caption)[:1024]}, files={"photo": fh}, timeout=(5, 25))
        ok = response.status_code == 200 and bool(response.json().get("ok"))
        return {"delivered": ok, "route": "professor_dm",
                "routing_variable": "TELEGRAM_ADMIN_CHAT_ID", "mocked": False}
    except Exception as exc:
        return {"delivered": False, "route": "professor_dm",
                "routing_variable": "TELEGRAM_ADMIN_CHAT_ID", "error": type(exc).__name__}
