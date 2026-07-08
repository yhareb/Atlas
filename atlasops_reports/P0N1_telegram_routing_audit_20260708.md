# P0N-1 — READ-ONLY Telegram Routing Audit — ATLAS HANDOFF + Pre-Market

**Date:** 2026-07-08
**Scope:** READ-ONLY audit only. No patch/deploy/env changes/Telegram test sends/strategy/scheduler changes. Telegram env values never printed — only variable names referenced per the standing hard constraint.

## 1. Root Cause: `eod_writer.py` → routes to GROUP, not DM

**Exact source of the pasted "🤖 ATLAS HANDOFF — JULY 7 → 8, 2026":**
- **Renderer:** `atlas_report_handoff.py::build_atlas_handoff_report()` — builds the message text only, has **no Telegram send call of its own** (confirmed: zero references to `send_telegram`/`chat_id`/`thread_id` in that file).
- **Sender/scheduler:** `eod_writer.py`, invoked via the Hermes `atlas` profile's own cron system (job id `bfcc04221d23`, "EOD Handoff Writer", schedule `5 0 * * 2-6`, `no_agent` script mode) — **not** launchd. Confirmed exact log match: `cron/output/bfcc04221d23/2026-07-08_00-06-10.md` contains the literal string `🤖 ATLAS HANDOFF — JULY 7 → 8, 2026` at line 24, with `telegram_send=19.62s enabled=True` at the end — this is the run that produced what Prof received.

**Routing code (`eod_writer.py` lines 39-57):**
```python
def _reports_group_chat_id():
    return os.environ.get("ATLAS_REPORTS_GROUP_CHAT_ID") or None

def _postmarket_thread_id():
    return _env_int("ATLAS_TOPIC_POSTMARKET_THREAD_ID")

def _send_report_telegram(message):
    group_chat = _reports_group_chat_id()
    if group_chat:
        return send_telegram(
            message, label="eod_writer", parse_mode="",
            chat_id=group_chat,
            message_thread_id=_postmarket_thread_id(),
        )
    return send_telegram(message, label="eod_writer", parse_mode="")
```

**This is the bug.** `eod_writer.py` explicitly prefers `ATLAS_REPORTS_GROUP_CHAT_ID` — if that variable is set (confirmed **SET, non-empty** in `~/.hermes/profiles/atlas/.env` — value not read/printed per the Telegram hard constraint), it routes to the group + `ATLAS_TOPIC_POSTMARKET_THREAD_ID` topic **instead of** the Atlas DM/admin route. It never calls `_admin_chat_id()`/DM fallback unless the group var is unset. This exactly matches Prof's report: HANDOFF landed in the group, not Atlas DM.

## 2. Pre-Market Path Audit

| Script | Telegram function | chat_id source | thread_id source | Group/topic env used? | Current route |
|---|---|---|---|---|---|
| `pre_market_report.py` | local `send_telegram()` wrapper (line 135) → `atlas_notify._send_telegram` | `_owner_chat_id()` = `atlas_notify._admin_chat_id()` | hardcoded `None` | `_reports_group_chat_id()` defined (line 129) but **explicitly noted as unused**: `"Retained for reference only; P0I-2 consolidates pre-market sends to Atlas DM. Not used by send_telegram() below."` | **Atlas DM/admin** — confirmed correct |
| `atlas_macro_premarket.py` | `_send_telegram()` (line 885) | `_owner_chat_id()` = `atlas_notify._admin_chat_id()` | hardcoded `None` | No group/topic function defined at all | **Atlas DM/admin** — confirmed correct |

Both pre-market paths are correctly DM-only right now — **Prof's suspicion about tomorrow's Pre-Market report going to the group is NOT confirmed by the code as it stands.** Tomorrow's Pre-Market report should route correctly, based on current code, *provided* the environment variables backing `_admin_chat_id()` remain as configured (not modified by this or any other task).

## 3. Other Handoff/Briefing-Adjacent Scripts Found

| Script | Telegram function | chat_id source | thread_id source | Group/topic env used? | Current route |
|---|---|---|---|---|---|
| `eod_writer.py` (sends ATLAS HANDOFF) | `_send_report_telegram()` | **`ATLAS_REPORTS_GROUP_CHAT_ID` if set, else `_admin_chat_id()` via bare `send_telegram()`** | `ATLAS_TOPIC_POSTMARKET_THREAD_ID` if group branch taken | **YES — actively used, and preferred over DM** | **⚠️ GROUP/TOPIC (confirmed bug)** |
| `atlas_macro_postmarket.py` | `send_report()` (line 509) | `_owner_chat_id()` = `_admin_chat_id()` | hardcoded `None` | `_reports_group_chat_id()`/`_postmarket_thread_id()` defined but explicitly commented **"P0I-2: consolidated to Atlas DM/admin route only; group/topic vars no longer used here."** | **Atlas DM/admin** — confirmed correct, P0I-2 fix intact |
| `atlas_intraday.py` | `send_telegram()` (via `atlas_notify`) | `_owner_chat_id()` at both call sites (lines 2479, 2536) | hardcoded `None` | `_reports_group_chat_id()`/`_interday_thread_id()` defined (lines 75-79) but **never called anywhere in the file** — dead/vestigial functions | **Atlas DM/admin** — confirmed correct |
| `atlas_eod_positions.py` | `send_telegram()` (via `atlas_notify`, line 256) | `_owner_chat_id()` | hardcoded `None` | No group/topic function defined | **Atlas DM/admin** — confirmed correct |

## 4. Env Variables Found (names only, per standing Telegram hard constraint — no values printed)

**Group/topic vars found in code:**
- `ATLAS_REPORTS_GROUP_CHAT_ID` — actively used by `eod_writer.py` (bug), defined-but-dead in `atlas_intraday.py`/`atlas_macro_postmarket.py`/`pre_market_report.py`
- `ATLAS_TOPIC_POSTMARKET_THREAD_ID` — used by `eod_writer.py` only when the group branch fires
- `ATLAS_TOPIC_INTERDAY_THREAD_ID` — defined in `atlas_intraday.py`, never called (dead)

**Admin/DM vars found in code (via `atlas_notify._admin_chat_id()`):**
- `TELEGRAM_ADMIN_CHAT_ID` (primary)
- `TELEGRAM_FALLBACK_CHAT_ID` (fallback 1)
- `TELEGRAM_ALLOWED_USERS` (fallback 2)
- `TELEGRAM_HOME_CHANNEL` (fallback 3)
- `TELEGRAM_CHAT_ID_EXPECTED` / built-in default (fallback 4, validation-only)

Confirmed present in `~/.hermes/profiles/atlas/.env` (**names only, existence checked, values never read or printed**): `ATLAS_REPORTS_GROUP_CHAT_ID` SET, `ATLAS_TOPIC_POSTMARKET_THREAD_ID` SET, `TELEGRAM_ADMIN_CHAT_ID` SET, `TELEGRAM_CHAT_ID` SET, `TELEGRAM_FALLBACK_CHAT_ID` NOT SET, `TELEGRAM_HOME_CHANNEL` SET, `TELEGRAM_ALLOWED_USERS` SET.

## 5. P0I-Routed Files — Still Intact?

**YES.** Both files explicitly touched by the earlier P0I Telegram-consolidation work remain correctly configured:
- `atlas_macro_postmarket.py` — inline comment confirms "P0I-2: consolidated to Atlas DM/admin route only; group/topic vars no longer used here." Code matches comment exactly.
- `pre_market_report.py` — inline comment confirms "P0I-2 consolidates pre-market sends to Atlas DM." Code matches comment exactly.

**`eod_writer.py` was never part of the P0I-2 scope** — it still contains its original, pre-P0I group-preferring branch, which is why it's the one file still misrouting.

## 6. Files Likely Needing a Patch

1. **`eod_writer.py`** — `_send_report_telegram()` must be changed to route to Atlas DM/admin (`_admin_chat_id()`) unconditionally, matching the pattern already used in `atlas_macro_postmarket.py`/`pre_market_report.py`. This is the confirmed root cause of the ATLAS HANDOFF group misdelivery.

No other file requires a patch based on this audit — pre-market paths are already correct, and the vestigial `_reports_group_chat_id()`/topic-id functions in `atlas_intraday.py` are dead code (never called) so they pose no live routing risk, though Prof may want them removed for cleanliness in a future low-priority cleanup pass (not urgent, not recommended as part of this fix).

---

## Return Fields

- **P0N1_STATUS:** AUDIT_COMPLETE
- **handoff_script:** Renderer: `atlas_report_handoff.py` (`build_atlas_handoff_report()`, no Telegram of its own). Sender/scheduler: `eod_writer.py`, run via Hermes `atlas` profile cron job `bfcc04221d23` ("EOD Handoff Writer", schedule `5 0 * * 2-6`) — confirmed exact match against `cron/output/bfcc04221d23/2026-07-08_00-06-10.md`
- **handoff_current_route:** ⚠️ **GROUP/TOPIC** — `eod_writer.py::_send_report_telegram()` prefers `ATLAS_REPORTS_GROUP_CHAT_ID` (confirmed SET) + `ATLAS_TOPIC_POSTMARKET_THREAD_ID`, falling back to DM only if the group var is unset. This is the confirmed bug.
- **premarket_scripts:** `pre_market_report.py`, `atlas_macro_premarket.py`
- **premarket_current_routes:** Both route to **Atlas DM/admin** correctly (`_owner_chat_id()`/`_admin_chat_id()`, `message_thread_id=None`) — group/topic code either absent or explicitly disabled per inline P0I-2 comments. Prof's suspicion about tomorrow's Pre-Market report is **not supported by current code** — should route correctly as-is.
- **group_topic_env_vars_found:** `ATLAS_REPORTS_GROUP_CHAT_ID` (actively used by eod_writer.py — the bug), `ATLAS_TOPIC_POSTMARKET_THREAD_ID` (used only when group branch fires), `ATLAS_TOPIC_INTERDAY_THREAD_ID` (dead, defined in atlas_intraday.py but never called)
- **admin_DM_env_vars_found:** `TELEGRAM_ADMIN_CHAT_ID`, `TELEGRAM_FALLBACK_CHAT_ID`, `TELEGRAM_ALLOWED_USERS`, `TELEGRAM_HOME_CHANNEL`, `TELEGRAM_CHAT_ID_EXPECTED` (via `atlas_notify._admin_chat_id()` fallback chain)
- **P0I_routes_still_intact:** YES — `atlas_macro_postmarket.py` and `pre_market_report.py` both remain correctly DM-only per their P0I-2 inline comments; `eod_writer.py` was never in P0I-2 scope and still has its original group-preferring logic
- **files_likely_need_patch:** `eod_writer.py` (the confirmed bug — `_send_report_telegram()`'s group-preferring branch)
- **patch_recommended:** YES
- **production changes:** NONE
