import os
import sys
import time
import requests

_ENV_PATH = os.path.expanduser("~/.hermes/profiles/atlas/.env")
_ENV_VALUES = {}
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                _k = _k.strip()
                _v = _v.strip()
                _ENV_VALUES[_k] = _v
                os.environ.setdefault(_k, _v)

# Expected Atlas Telegram destination. TELEGRAM_CHAT_ID_EXPECTED in .env is the source of truth.
TELEGRAM_CHAT_ID_EXPECTED_DEFAULT = ""


def _cfg(key, default=None, prefer_env_file=True):
    """Return config, preferring Atlas .env for Telegram routing to avoid launchd/env drift."""
    if prefer_env_file and key in _ENV_VALUES and str(_ENV_VALUES.get(key, "")).strip():
        return str(_ENV_VALUES[key]).strip()
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


def send_telegram(message, label="atlas", parse_mode="Markdown", print_fallback=True, chat_id=None, message_thread_id=None):
    """Robust non-fatal Telegram sender: 3 attempts, 5s connect / 25s read, 2s/5s backoff."""
    token = _bot_token()
    chat = str(chat_id).strip() if chat_id not in (None, "") else _chat_id()
    print(f"[atlas_notify] routing: chat_id_arg_set={chat_id not in (None, '')} resolved_chat_set={bool(chat)} thread_set={message_thread_id is not None}", file=sys.stderr)
    if not token or not chat:
        print(f"[{label}] telegram skipped: TELEGRAM_BOT_TOKEN or chat id unset")
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


def send_message(message, label="atlas", parse_mode="Markdown", print_fallback=True, chat_id=None, message_thread_id=None):
    """Compatibility alias for callers that expect send_message()."""
    return send_telegram(message, label=label, parse_mode=parse_mode, print_fallback=print_fallback, chat_id=chat_id, message_thread_id=message_thread_id)
