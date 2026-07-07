# P0I-1 — Telegram Routing Consolidation Audit (READ-ONLY)

**Date:** 2026-07-07
**Status:** AUDIT_COMPLETE_READ_ONLY
**Scope:** Read-only. No patches, no deploys, no env/scheduler/DB/strategy/TFE changes. No Telegram values printed — env var **names** only.

## Goal
Prepare a safe plan to route Atlas reports back to Atlas DM only and later retire group topics.

## 1–2. Report Route Matrix (env var names only)

| # | Sender | Route mechanism | Env vars used |
|---|--------|------------------|---------------|
| 1 | `pre_market_report.py` | `send_telegram()` → explicit `chat_id`/`message_thread_id` | `ATLAS_REPORTS_GROUP_CHAT_ID`, `ATLAS_TOPIC_PREMARKET_THREAD_ID` |
| 2 | `atlas_macro_premarket.py` | `send_report()` → no explicit chat_id → falls through to `atlas_notify._chat_id()` default | `TELEGRAM_CHAT_ID` → `TELEGRAM_ALLOWED_USERS` → `TELEGRAM_HOME_CHANNEL` |
| 3 | `atlas_intraday.py` (main report) | explicit `chat_id`/`message_thread_id` | `ATLAS_REPORTS_GROUP_CHAT_ID`, `ATLAS_TOPIC_INTERDAY_THREAD_ID` |
| 3b | `atlas_intraday.py` (proactive ALERT/SELL DM) | `chat_id=_owner_chat_id()` → `atlas_notify._admin_chat_id()` | `TELEGRAM_ADMIN_CHAT_ID` → `TELEGRAM_FALLBACK_CHAT_ID` → `TELEGRAM_ALLOWED_USERS` → `TELEGRAM_HOME_CHANNEL` → `TELEGRAM_CHAT_ID_EXPECTED` |
| 4 | `atlas_macro_postmarket.py` | if `ATLAS_REPORTS_GROUP_CHAT_ID` set: explicit chat/thread; else falls back to `_chat_id()` default | `ATLAS_REPORTS_GROUP_CHAT_ID`, `ATLAS_TOPIC_POSTMARKET_THREAD_ID` (conditional) |
| 5 | `atlas_eod_positions.py` | `send_telegram(report, label="atlas", ...)` with no explicit chat_id → falls through to `_chat_id()` default | `TELEGRAM_CHAT_ID` → `TELEGRAM_ALLOWED_USERS` → `TELEGRAM_HOME_CHANNEL` |
| 6 | `atlas_perme.py` | owner-DM by design, separate Perme bot token | `PERME_ENV:TELEGRAM_ADMIN_CHAT_ID` → `PERME_ENV:TELEGRAM_CHAT_ID` → `ATLAS_ENV:TELEGRAM_ADMIN_CHAT_ID` |
| 7 | `atlas_api_audit.py` | dedicated AtlasOps bot, isolated from Atlas/Perme | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` read from the **AtlasOps** env file specifically (separate credential set) |

## 3. Group/Topic vs DM/Admin Classification

### Group/topic routes
- `pre_market_report.py` → `ATLAS_REPORTS_GROUP_CHAT_ID` + `ATLAS_TOPIC_PREMARKET_THREAD_ID`
- `atlas_intraday.py` (main report) → `ATLAS_REPORTS_GROUP_CHAT_ID` + `ATLAS_TOPIC_INTERDAY_THREAD_ID`
- `atlas_macro_postmarket.py` → `ATLAS_REPORTS_GROUP_CHAT_ID` + `ATLAS_TOPIC_POSTMARKET_THREAD_ID` (conditional)

### DM/admin routes
- `atlas_intraday.py` (proactive ALERT/SELL DM) → `TELEGRAM_ADMIN_CHAT_ID` chain
- `atlas_perme.py` → `TELEGRAM_ADMIN_CHAT_ID` chain, separate Perme bot
- `atlas_eod_positions.py` → implicit default `TELEGRAM_CHAT_ID` chain — **ambiguous**: neither the group/topic route nor `TELEGRAM_ADMIN_CHAT_ID`; currently resolves to the Atlas main channel default.
- `atlas_macro_premarket.py` → same implicit default chain as above
- `atlas_macro_postmarket.py` → same implicit default chain, only when `ATLAS_REPORTS_GROUP_CHAT_ID` unset
- `atlas_api_audit.py` → fully isolated AtlasOps bot/chat, out of scope for Atlas DM consolidation

**Key finding:** `atlas_notify.send_telegram()` defaults to `_chat_id()` (main Atlas channel var chain) whenever no `chat_id=` argument is passed. Several senders (`atlas_macro_premarket.py`, `atlas_eod_positions.py`) rely on this implicit fallthrough rather than an explicit DM route — this is why "DM-only" consolidation needs code review per file, not just an env flip.

## 4. Staging-Only DM-Routing Validation Plan (no real sends)

1. Copy each target sender script to `/tmp/atlas_p0i1_staging/`.
2. Stub `atlas_notify.send_telegram` (or the module-level `_send_telegram` import) with a capture-only mock recording `(message, chat_id, message_thread_id)` — zero real network calls.
3. For each report type, build a minimal synthetic `summary`/`ctx` and invoke the report's send path (`send_telegram()`/`send_report()`) through the staged module only.
4. Assert captured calls show `chat_id` resolving to the intended DM route (or `None`, proving fallthrough to `_chat_id()`/`_admin_chat_id()`) and `message_thread_id=None`.
5. Run once per report type (pre-market, macro premarket, intraday main + proactive DM, macro postmarket, EOD positions) against staged copies only — never against `/Users/yasser/scripts` originals.
6. Record a before/after route-assertion table per file; no DB writes needed since this is a pure routing-argument check.
7. No real Telegram message is sent during validation, including to Atlas DM — mock captures only.

## 5. Files / Env / Scheduler Items Requiring Approval

**Files requiring code changes to route to DM only:**
- `/Users/yasser/scripts/pre_market_report.py`
- `/Users/yasser/scripts/atlas_macro_premarket.py`
- `/Users/yasser/scripts/atlas_intraday.py`
- `/Users/yasser/scripts/atlas_macro_postmarket.py`
- `/Users/yasser/scripts/atlas_eod_positions.py`

**Env file (only if fully retiring group/topic vars, not just code-level bypass):**
- `/Users/yasser/.hermes/profiles/atlas/.env` — would need `ATLAS_REPORTS_GROUP_CHAT_ID`, `ATLAS_TOPIC_PREMARKET_THREAD_ID`, `ATLAS_TOPIC_INTERDAY_THREAD_ID`, `ATLAS_TOPIC_POSTMARKET_THREAD_ID` unset/removed.

**routing_change_requires_env: YES** — full retirement of group topics requires an env change. A code-only change (dropping `chat_id=`/`message_thread_id=` args so senders fall through to the DM default) does not strictly require an env change, but still requires Prof's explicit approval under the standing Telegram hard constraint.

## Approval Required
**YES** — per the standing Telegram hard constraint, no Telegram routing/env/scheduler change proceeds without Prof's explicit authorization.

## Production Changes
**NONE** — this audit made zero modifications to any file, env, scheduler, DB, or Telegram configuration.
