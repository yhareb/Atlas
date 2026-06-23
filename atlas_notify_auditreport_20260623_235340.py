import os
import time
import requests

_ENV_PATH = os.path.expanduser("~/.hermes/profiles/atlas/.env")
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())


def _chat_id():
    return (os.environ.get("TELEGRAM_CHAT_ID")
            or os.environ.get("TELEGRAM_ALLOWED_USERS")
            or os.environ.get("TELEGRAM_HOME_CHANNEL"))


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


def send_telegram(message, label="atlas", parse_mode="Markdown", print_fallback=True):
    """Robust non-fatal Telegram sender: 3 attempts, 5s connect / 25s read, 2s/5s backoff."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = _chat_id()
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
    for idx, chunk in enumerate(_chunks(message), 1):
        payload = {"chat_id": chat, "text": chunk, "parse_mode": parse_mode}
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                r = requests.post(url, json=payload, timeout=(5, timeout))
                if r.status_code != 200:
                    err_text = r.text[:300]
                    if r.status_code == 400 and parse_mode and "can't parse entities" in err_text:
                        plain_payload = {"chat_id": chat, "text": chunk}
                        r = requests.post(url, json=plain_payload, timeout=(5, timeout))
                        if r.status_code == 200:
                            data = r.json()
                            if data.get("ok"):
                                msg_id = data.get("result", {}).get("message_id")
                                sent_ids.append(msg_id)
                                print(f"[{label}] telegram chunk {idx}/{len(_chunks(message))} sent plain-text after Markdown parse failure on attempt {attempt}: message_id={msg_id}")
                                break
                    raise RuntimeError(f"Telegram HTTP {r.status_code}: {err_text}")
                data = r.json()
                if not data.get("ok"):
                    raise RuntimeError(f"Telegram rejected chunk {idx}: {data}")
                msg_id = data.get("result", {}).get("message_id")
                sent_ids.append(msg_id)
                print(f"[{label}] telegram chunk {idx}/{len(_chunks(message))} sent on attempt {attempt}: message_id={msg_id}")
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
