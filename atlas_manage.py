#!/usr/bin/env python3
"""
atlas_manage.py  —  Atlas v2 daily portfolio runner
============================================================================

This is the ONE command you run each day. It executes the full v2 loop in the
correct order and prints a clean, human-readable summary:

  1. ACCOUNT      ensure the account table exists; print cash / equity.
  2. EXITS FIRST  evaluate every OPEN lot against the trailing-stop /
                  time-exit rules. We sell BEFORE buying so freed cash and
                  freed position slots are available to new entries today.
  3. REGIME       check the SPY > 50SMA gate once. If risk-OFF, no new buys.
  4. SCORE        run the v2 engine over the candidate list (CLI args, a
                  --file watchlist, or the default universe) -> BUY / BUY Small.
  5. CONSIDER     for each qualifying signal, run admission + sizing +
                  pullback-to-EMA10 trigger and (unless --dry-run) open lots.
  6. SUMMARY      print everything that happened.

SAFETY
------
  - Default mode is --dry-run = OFF only when you pass --live. Without --live,
    NOTHING is written: it just shows what it WOULD do.
  - All sells/buys go through the existing atlas_db FIFO ledger (open_trade /
    close_trade). No data is ever deleted.

USAGE
-----
  python3 ~/scripts/atlas_manage.py                 # dry-run, default universe
  python3 ~/scripts/atlas_manage.py NVDA AMD PLTR   # dry-run, specific tickers
  python3 ~/scripts/atlas_manage.py --file wl.txt   # dry-run, watchlist file
  python3 ~/scripts/atlas_manage.py --live          # EXECUTE today's plan
  python3 ~/scripts/atlas_manage.py --exits-only --live   # only run exits
"""

import os
import sys
import json
import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

SCRIPTS_DIR = os.environ.get("ATLAS_SCRIPTS_DIR") or os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

import atlas_db
import atlas_account as acct
import atlas_portfolio as port
import atlas_stop_invariant_guard as stop_guard
from atlas_symbol_meta import company_name
from atlas_time import current_et_market_date_str
from atlas_engine import analyze_ticker, check_regime, check_macro_context, get_macro_sentiment
from atlas_macro_context_v1 import load_context, adapt_existing_gates, context_gate
from atlas_market_gear import build_gear_packet, header_line
try:
    import atlas_fda_calendar
except Exception:
    atlas_fda_calendar = None
try:
    from atlas_audit import log_signal as _atlas_log_signal
except Exception:
    _atlas_log_signal = None

# Default universe if the user passes no tickers. Kept small & liquid; the
# scout normally supplies the real candidates, but this gives a sane default.
DEFAULT_UNIVERSE = [
    "NVDA", "AMD", "AVGO", "SMCI", "MU",
    "AAPL", "MSFT", "GOOGL", "META", "AMZN",
    "TSLA", "NFLX", "PLTR", "SNOW", "CRWD",
    "LLY", "JPM", "COIN", "ORCL", "NOW",
]

# Provider 404 / delisted exclusions that must not enter the active scan list,
# including restart-surviving pending rows.
PERMANENT_SCAN_REMOVED_TICKERS = {"CWAN"}
SCAN_EXCLUDED_TICKERS = PERMANENT_SCAN_REMOVED_TICKERS | {"PRA", "AMED", "TTNI"}


def _filter_scan_universe(tickers):
    return [
        str(t or "").upper()
        for t in (tickers or [])
        if str(t or "").strip() and str(t or "").upper() not in SCAN_EXCLUDED_TICKERS
    ]

LINE = "=" * 68
THIN = "-" * 68
LAST_RUN_SUMMARY = {}


def _timing_log(section, event, start=None, ticker=None, extra=""):
    elapsed = "" if start is None else f" elapsed={time.perf_counter() - start:.3f}s"
    symbol = f" ticker={str(ticker).upper()}" if ticker else ""
    detail = f" {extra}" if extra else ""
    print(f"[TIMING] {datetime.now().isoformat(timespec='seconds')} section={section} event={event}{symbol}{elapsed}{detail}", flush=True)


def _analyze_ticker_worker(ticker, regime, macro_context_v1=None):
    tkr = str(ticker or "").upper()
    pillar_start = time.perf_counter()
    _timing_log("pillar_checks", "start", ticker=tkr)
    try:
        res = analyze_ticker(tkr, regime=regime, macro_context_v1=macro_context_v1)
    except TypeError:
        res = analyze_ticker(tkr)  # back-compat if regime kwarg absent
    _timing_log("pillar_checks", "end", pillar_start, tkr)
    return tkr, res


def _run_parallel_pillar_checks(tickers, regime, macro_context_v1=None, max_workers=8):
    unique = [str(t or "").upper() for t in dict.fromkeys(tickers or []) if str(t or "").strip()]
    workers = max(1, int(max_workers or 8))
    parallel_start = time.perf_counter()
    _timing_log("pillar_checks_parallel", "start", extra=f"tickers={len(unique)} workers={workers}")
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_ticker = {executor.submit(_analyze_ticker_worker, tkr, regime, macro_context_v1): tkr for tkr in unique}
        for future in as_completed(future_to_ticker):
            tkr, res = future.result()
            results[tkr] = res
    _timing_log("pillar_checks_parallel", "end", parallel_start, extra=f"tickers={len(results)} workers={workers}")
    return results


def _hdr(title):
    print(f"\n{LINE}\n  {title}\n{LINE}")


def _empty_exit_inventory_message(open_lots, guard_receipt):
    """Distinguish an empty book from OPEN lots excluded by the stop guard."""
    open_lots = list(open_lots or [])
    if not open_lots:
        return "  No open positions."
    verdicts = {int(row.get("trade_id")): row for row in (guard_receipt or {}).get("lots", [])}
    excluded = []
    for lot in open_lots:
        row = verdicts.get(int(lot.get("id"))) or {}
        if row.get("result") != "PASS":
            excluded.append(f"{str(lot.get('ticker') or '?').upper()}={row.get('result') or 'DATA_INCOMPLETE'}")
    detail = ", ".join(excluded) if excluded else "UNKNOWN"
    return f"  Open positions: {len(open_lots)} (0 exit-eligible — stop-guard excluded: {detail})"


def load_candidates(args):
    if args.tickers:
        return _filter_scan_universe(args.tickers)
    if args.file and os.path.exists(args.file):
        with open(args.file) as f:
            toks = []
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line:
                    toks += [p.strip().upper() for p in line.replace(",", " ").split()]
            return _filter_scan_universe(toks)
    # Default: reuse the SAME news-driven discovery the scout uses, so the
    # daily manager scans exactly the universe market_scout.py would. Falls
    # back to the built-in liquid list if the scout isn't importable.
    try:
        from market_scout import discover_tickers
        found = discover_tickers()
        if found:
            return _filter_scan_universe(found)
    except Exception:
        pass
    return _filter_scan_universe(DEFAULT_UNIVERSE)




def _pillar_count(score):
    try:
        return int(str(score).split("/")[0])
    except Exception:
        return 0




def _load_fda_scan_context(candidates):
    """Load FDA calendar once per scan for Stage 1 metadata-only annotation."""
    if atlas_fda_calendar is None:
        return {"active": False, "reason": "atlas_fda_calendar unavailable", "cache": {"rows": [], "index": {}}, "stats": {}}
    try:
        cache = atlas_fda_calendar.load_or_refresh_fda_cache(days=60)
        stats = dict(cache.get("stats") or {})
        stats.update(atlas_fda_calendar.get_stats())
        return {"active": True, "cache": cache, "stats": stats, "candidate_count": len(candidates or [])}
    except Exception as exc:
        return {"active": False, "reason": f"{type(exc).__name__}: {exc}", "cache": {"rows": [], "index": {}}, "stats": {}}


def _attach_fda_metadata(row, fda_context):
    """Attach FDA metadata to a candidate/report row without touching score/action fields."""
    if not isinstance(row, dict) or not isinstance(fda_context, dict) or not fda_context.get("active"):
        return row
    ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
    if not ticker or atlas_fda_calendar is None:
        return row
    metadata = {}
    if isinstance(row.get("fundamentals"), dict):
        metadata.update(row.get("fundamentals") or {})
    for key in ("sector", "industry", "type", "fda_relevant"):
        if key in row and key not in metadata:
            metadata[key] = row.get(key)
    news_text = " ".join(str(row.get(k) or "") for k in ("reason", "signal", "catalyst", "catalyst_reason"))
    fda = atlas_fda_calendar.get_fda_metadata_for_ticker(ticker, metadata=metadata, news_text=news_text, cache=fda_context.get("cache"))
    if fda:
        row.setdefault("fda_calendar_normalized", fda)
        row.setdefault("fda_relevance_reason", fda.get("fda_relevance_reason"))
    return row

def _score_text(pillars):
    try:
        return f"{int(pillars)}/4 Pillars"
    except Exception:
        return "0/4 Pillars"


def _recent_pillar_history(ticker, limit=3):
    """Read recent raw pillar scores for ticker from sqlite signals; newest first."""
    ticker = str(ticker or "").upper()
    if not ticker:
        return []
    try:
        rows = atlas_db.get_connection().execute(
            "SELECT score FROM signals WHERE ticker=? ORDER BY id DESC LIMIT ?",
            (ticker, int(limit)),
        ).fetchall()
        return [_pillar_count(row[0]) for row in rows]
    except Exception:
        return []


def _effective_pillars_with_hysteresis(ticker, raw_pillars, history=None):
    """Smooth one-pillar score flicker for report/action state.

    Operational rule implemented for the staged sprint dry-run:
    - raw >= 3 promotes/keeps TOP state.
    - first raw <= 2 immediately after TOP state holds TOP for one cycle.
    - second consecutive raw <= 2 demotes to WAITING.
    """
    raw = int(raw_pillars or 0)
    hist = list(history if history is not None else _recent_pillar_history(ticker, limit=3))
    previous = hist[0] if hist else None
    if raw >= 3:
        state = "TOP_PICKS"
        effective = raw
        reason = "promote_or_hold_top"
    elif previous is not None and previous >= 3:
        state = "TOP_PICKS"
        effective = max(3, raw)
        reason = "hold_top_one_weak_cycle"
    else:
        state = "WAITING_FOR_DIP"
        effective = raw
        reason = "demote_or_hold_waiting"
    return {
        "ticker": str(ticker or "").upper(),
        "raw_pillars": raw,
        "effective_pillars": effective,
        "state": state,
        "reason": reason,
        "previous_pillars": previous,
        "history": hist,
    }


def _scan_source(ticker, pending_scan, ema_retry_scan):
    t = (ticker or "").upper()
    if t in set(ema_retry_scan or []):
        return "ema_retry"
    if t in set(pending_scan or []):
        return "pending_pullback"
    return "normal_scan"


def _float_or_none(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _expire_stale_pending_pullbacks(pending_rows, live=False, threshold=0.07, price_lookup=None):
    """Expire WAITING pullbacks when live price is >threshold above trigger."""
    expired = []
    lookup = price_lookup or getattr(port, "_price_lookup", None)
    if not callable(lookup):
        return expired
    for row in pending_rows or []:
        ticker = str((row or {}).get("ticker") or "").upper()
        trigger = _float_or_none((row or {}).get("trigger_price"))
        if not ticker or not trigger or trigger <= 0:
            continue
        try:
            current = _float_or_none(lookup(ticker))
        except Exception as e:
            print(f"  stale-pullback expiry price unavailable {ticker}: {e}")
            continue
        if current is None or current <= 0:
            continue
        pct_above = (current - trigger) / trigger
        if pct_above > threshold:
            item = {
                "ticker": ticker,
                "action": "EXPIRE",
                "reason": f"STALE PULLBACK: current ${current:.2f} is {pct_above * 100:.1f}% above trigger ${trigger:.2f} (> {threshold * 100:.0f}%)",
                "trigger_price": trigger,
                "current_price": current,
                "pct_above_trigger": pct_above * 100,
            }
            if live:
                try:
                    atlas_db.expire_pending_pullback(ticker)
                    print(f"  ⌛ {item['reason']}")
                except Exception as e:
                    item["expire_error"] = str(e)
                    print(f"  stale-pullback expiry failed {ticker}: {e}")
            else:
                print(f"  DRY-RUN stale-pullback expiry: {item['reason']}")
            expired.append(item)
    return expired


def _load_perme_threshold_overlay(path=None, now_utc=None):
    """Return an overlay only from the strict provenance-bound contract.

    Legacy Perme prose/latest_context fields are never parsed. Missing, stale,
    malformed, conflicting, or unverifiable packets preserve exact baseline
    behavior.
    """
    overlay = {
        "active": False,
        "sentiment": "NEUTRAL",
        "global_min_pillars": 3,
        "global_min_rvol": 1.5,
        "perme_flagged_tickers": set(),
    }
    result = load_context(
        path or os.environ.get("ATLAS_MACRO_CONTEXT_V1_PATH"),
        now=now_utc,
        consumer="atlas_manage.threshold_overlay",
    )
    gates, _receipt = adapt_existing_gates(result.context, consumer="atlas_manage.threshold_overlay")
    if gates.get("perme_regime") == "RISK_OFF":
        overlay.update(active=True, sentiment="RISK_OFF", global_min_pillars=4, global_min_rvol=2.0)
    return overlay


def _float_value(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _attach_live_signal_price(decision, ticker):
    """Attach the current live price at BUY-signal time for intraday reporting."""
    if not isinstance(decision, dict):
        return decision
    live_price_start = time.perf_counter()
    _timing_log("live_price_fetch", "start", ticker=ticker)
    try:
        live_price = port._price_lookup(ticker)
    except Exception:
        live_price = None
    _timing_log("live_price_fetch", "end", live_price_start, ticker, extra=f"price={'yes' if live_price is not None else 'fallback'}")
    if live_price is None:
        live_price = decision.get("price") or decision.get("current_price") or decision.get("entry")
    decision["live_price"] = live_price
    decision.setdefault("current_price", live_price)
    return decision


def _audit_action(decision, live):
    raw = str((decision or {}).get("action") or "SKIP").upper()
    reason = str((decision or {}).get("reason") or "")
    if raw == "BUY" and live:
        return "PENDING_FILL"
    if raw == "WAIT":
        return "WAITING"
    if raw == "EXPIRE":
        return "SKIP"
    if raw == "SKIP" and reason.startswith("TOO EXTENDED"):
        return "TOO HOT"
    if raw in {"BUY", "SKIP", "BLOCK"}:
        return raw
    return "SKIP"


def _audit_signal_decision(ticker, decision, score, pillars, live, source, market_date, run_id):
    try:
        if not _atlas_log_signal:
            return
        decision = decision or {}
        _atlas_log_signal(
            ticker=(ticker or "").upper(),
            action=_audit_action(decision, live),
            reason=decision.get("reason") or decision.get("signal") or "",
            score=score,
            pillars=pillars,
            live=bool(live),
            source=source,
            entry=decision.get("entry"),
            stop=decision.get("stop"),
            target=decision.get("target"),
            market_date=market_date,
            run_id=run_id,
            metadata={"raw_action": decision.get("action"), "signal": decision.get("signal")},
        )
    except Exception:
        pass


def _catalyst_reason(res):
    reason = (res.get("catalyst_reason") or "").strip()
    if reason:
        return reason
    for pillar in res.get("pillars", []) or []:
        text = str(pillar)
        if "Catalyst:" in text and "YES" in text.upper():
            return "Recent news"
    return None

def run(args, gear_packet=None):
    global LAST_RUN_SUMMARY
    live = args.live
    mode = "LIVE — orders WILL be written" if live else "DRY-RUN — no writes"
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    market_date = current_et_market_date_str()
    LAST_RUN_SUMMARY = {"live": live, "mode": mode, "started_at": datetime.now().isoformat(), "run_id": run_id, "market_date": market_date}
    try:
        macro_sentiment = get_macro_sentiment()
    except Exception:
        macro_sentiment = {"sentiment": "NEUTRAL", "reason": "no data"}
    if not isinstance(macro_sentiment, dict):
        macro_sentiment = {"sentiment": "NEUTRAL", "reason": "no data"}
    macro_label = str(macro_sentiment.get("sentiment") or "NEUTRAL").upper()
    if macro_label not in {"NEUTRAL", "CAUTION", "RISK_OFF"}:
        macro_label = "NEUTRAL"
    macro_sentiment = dict(macro_sentiment)
    macro_sentiment["sentiment"] = macro_label
    macro_sentiment.setdefault("reason", "no data")
    macro_active = (not live) or os.environ.get("ATLAS_MACRO_SENTIMENT_LIVE_ENABLED") == "1"
    macro_sentiment["active"] = bool(macro_active)
    if live and not macro_active:
        macro_sentiment["shadow_only"] = True
    LAST_RUN_SUMMARY["macro_sentiment"] = macro_sentiment
    # V1.2 is opt-in. Missing/rejected context preserves the legacy path.
    _macro_load = load_context(os.environ.get("ATLAS_MACRO_CONTEXT_V1_PATH"), consumer="atlas_manage")
    _macro_legacy, _macro_receipt = adapt_existing_gates(_macro_load.context, consumer="atlas_manage")
    _macro_gate = context_gate(_macro_load, _macro_legacy)
    # Exactly one immutable packet is shared by all entry routes and receipts.
    if gear_packet is None:
        try:
            spy_rows = port.get_massive_aggs("SPY", days=120) or []
            closes = [r.get("c") for r in spy_rows if r.get("c") is not None]
            completed = datetime.fromtimestamp(float(spy_rows[-1]["t"])/1000, tz=timezone.utc).date().isoformat() if spy_rows and spy_rows[-1].get("t") else None
            gear_packet = build_gear_packet(spy_close=closes[-1] if closes else None, spy_closes=closes,
                spy_completed_session=completed, perme_regime=_macro_legacy.get("perme_regime"),
                perme_valid=_macro_load.context is not None, perme_packet_digest=(_macro_receipt or {}).get("digest"),
                macro_event_gate=_macro_legacy.get("macro_event_gate") or "CLEAR", computed_at=datetime.now(timezone.utc).isoformat())
        except Exception:
            gear_packet = build_gear_packet()
    LAST_RUN_SUMMARY["gear_packet"] = gear_packet
    # No legacy latest_context fallback: only the single validated object may
    # reach existing regime/event gates.
    perme_overlay = {
        "active": _macro_legacy.get("perme_regime") == "RISK_OFF",
        "sentiment": _macro_legacy.get("sentiment", "NEUTRAL"),
        "global_min_pillars": 4 if _macro_legacy.get("perme_regime") == "RISK_OFF" else 3,
        "global_min_rvol": 2.0 if _macro_legacy.get("perme_regime") == "RISK_OFF" else 1.5,
        "perme_flagged_tickers": set(),
    }
    LAST_RUN_SUMMARY["macro_context_v1_receipt"] = dict(_macro_receipt if _macro_load.context is not None else _macro_load.receipt)
    LAST_RUN_SUMMARY["perme_threshold_overlay"] = {
        "active": bool(perme_overlay.get("active")),
        "sentiment": perme_overlay.get("sentiment"),
        "global_min_pillars": perme_overlay.get("global_min_pillars"),
        "global_min_rvol": perme_overlay.get("global_min_rvol"),
        "perme_flagged_tickers": sorted(perme_overlay.get("perme_flagged_tickers") or []),
    }
    print(LINE)
    print(f"  ATLAS v2 DAILY MANAGER   {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  Mode: {mode}")
    print(f"  {header_line(gear_packet)} · digest {gear_packet.get('packet_digest')}")
    print(LINE)

    # 1. ACCOUNT ------------------------------------------------------------
    atlas_db.init_db()    # idempotent; adds pending pullback table if missing
    acct.init_account()  # idempotent; never resets
    summary = acct.get_account_summary(price_lookup=port._price_lookup)
    try:
        open_positions_count = len(atlas_db.get_open_positions())
    except Exception:
        open_positions_count = 0
    LAST_RUN_SUMMARY.update({"account": summary, "open_positions_count": open_positions_count})
    _hdr("ACCOUNT")
    print(f"  Cash available : ${summary['cash']:,.2f}")
    print(f"  Open invested  : ${summary['open_invested']:,.2f}")
    print(f"  Realized P&L   : ${summary['realized_pnl']:,.2f}")
    print(f"  Equity (MTM)   : ${summary['equity']:,.2f}")

    # Order #3: fail-closed stop invariant guard, after inventory/account and
    # strictly before any exit evaluator can observe a persisted stop.
    open_lots = atlas_db.get_trades(status="OPEN")
    atr14_by_trade = port.current_atr14_for_open_lots(open_lots)
    guard_now = datetime.now(timezone.utc)
    guard_sessions = stop_guard.allowed_session_dates(guard_now)
    guard_receipt = stop_guard.evaluate_cycle(
        db_path=atlas_db.DB_PATH, cycle_id=run_id, current_atr14=atr14_by_trade,
        allowed_broker_session_dates=guard_sessions, cycle_started_at=guard_now,
        deployment_mode="production",
    )
    LAST_RUN_SUMMARY["stop_invariant_guard"] = guard_receipt
    eligible_trade_ids = [x["trade_id"] for x in guard_receipt.get("lots", []) if x.get("result") == "PASS"]
    if live:
        stop_guard.alert_hard_violations(guard_receipt)

    # 2. EXITS FIRST --------------------------------------------------------
    _hdr("EXITS  (evaluated before any new buys)")
    exit_results = port.run_exits(dry_run=not live, macro_context_v1=_macro_legacy if _macro_load.context is not None else None,
                                  macro_context_status=_macro_gate,
                                  eligible_trade_ids=eligible_trade_ids)
    sells = [r for r in exit_results if r.get("action") == "SELL"]
    LAST_RUN_SUMMARY.update({"exit_results": exit_results, "sells": sells})
    if not exit_results:
        print(_empty_exit_inventory_message(open_lots, guard_receipt))
    for r in exit_results:
        if r["action"] == "SELL":
            print(f"  SELL  {r['ticker']:<6} x{r.get('qty','?'):<5} @ {r.get('price')}  — {r['reason']}")
        elif r["action"] == "HOLD":
            print(f"  HOLD  {r['ticker']:<6} {r['reason']}")
        else:
            print(f"  {r['action']:<5} {r['ticker']:<6} {r['reason']}")

    if args.exits_only:
        LAST_RUN_SUMMARY.update({"exits_only": True, "buys": [], "result": "ACTION" if sells else "DO NOTHING"})
        _finish(live, sells, [])
        return LAST_RUN_SUMMARY

    # 3. REGIME -------------------------------------------------------------
    _hdr("REGIME GATE")
    regime = check_regime()
    regime_ok, regime_detail = regime
    macro_label = (LAST_RUN_SUMMARY.get("macro_sentiment") or {}).get("sentiment", "NEUTRAL")
    macro_reason = (LAST_RUN_SUMMARY.get("macro_sentiment") or {}).get("reason", "no data")
    macro_active = bool((LAST_RUN_SUMMARY.get("macro_sentiment") or {}).get("active", True))
    entry_regime = regime
    if macro_active and macro_label == "RISK_OFF":
        # Secondary caution overlay only: does not change the regime gate, stops, targets, or signals.
        # atlas_portfolio.consider_buy() already treats WEAK regime detail as half-size risk.
        entry_regime = (regime_ok, f"{regime_detail} | WEAK MACRO_RISK_OFF: {macro_reason}")
    LAST_RUN_SUMMARY.update({"regime_ok": regime_ok, "regime_detail": regime_detail, "entry_regime_detail": entry_regime[1]})
    macro_ctx = check_macro_context()
    LAST_RUN_SUMMARY.update({"macro_context": macro_ctx})
    print(f"  {'RISK-ON ' if regime_ok else 'RISK-OFF'} : {regime_detail}")
    if macro_label in {"CAUTION", "RISK_OFF"}:
        if macro_active:
            risk_note = " — half-size risk" if macro_label == "RISK_OFF" else ""
        else:
            risk_note = " — shadow only; live overlay disabled pending review"
        print(f"  MACRO LLM: ⚠️ {macro_label}: {macro_reason}{risk_note}")
    if macro_ctx.get("cautious"):
        print(f"  MACRO    : {macro_ctx.get('note')} ({', '.join(e.get('type','') for e in macro_ctx.get('events', [])[:3])})")
    elif macro_ctx.get("status") == "na":
        print(f"  MACRO    : {macro_ctx.get('note')}")
    if not regime_ok:
        print("  No new positions today (SPY below 50-day SMA).")
        LAST_RUN_SUMMARY.update({"candidates": [], "scanned_count": 0, "high_candidates": [], "watch_2": [], "catalysts": [], "buys": [], "result": "ACTION" if sells else "DO NOTHING"})
        _finish(live, sells, [])
        return LAST_RUN_SUMMARY

    # 4 + 5. SCORE & CONSIDER ----------------------------------------------
    candidates = load_candidates(args)
    if _macro_load.context is not None:
        _macro_legacy, _macro_receipt = adapt_existing_gates(_macro_load.context, consumer="atlas_manage.candidate_future_admission", candidates=candidates)
        LAST_RUN_SUMMARY["macro_context_v1_receipt"] = _macro_receipt
    pending_rows = atlas_db.get_pending_pullbacks(status="WAITING")
    stale_expired_pullbacks = _expire_stale_pending_pullbacks(pending_rows, live=live)
    if stale_expired_pullbacks:
        stale_tickers = {str(r.get("ticker") or "").upper() for r in stale_expired_pullbacks}
        pending_rows = [r for r in pending_rows if str(r.get("ticker") or "").upper() not in stale_tickers]
    pending_scan = [r.get("ticker", "").upper() for r in pending_rows if r.get("ticker")]
    ema_retry_rows = atlas_db.get_ema_retry_candidates(status="WAITING")
    ema_retry_scan = [r.get("ticker", "").upper() for r in ema_retry_rows if r.get("ticker")]
    held_scan = [r.get("ticker", "").upper() for r in atlas_db.get_trades(status="OPEN") if r.get("ticker")]
    candidates = list(dict.fromkeys(pending_scan + ema_retry_scan + held_scan + [t.upper() for t in candidates]))
    excluded = set(SCAN_EXCLUDED_TICKERS)
    try:
        from market_scout import EXCLUDED_TICKERS as _SCAN_EXCLUDED_TICKERS
        excluded.update(str(t or "").upper() for t in (_SCAN_EXCLUDED_TICKERS or set()))
    except Exception:
        pass
    candidates = [t for t in candidates if str(t or "").upper() not in excluded]
    _hdr(f"SCAN & ENTRIES  ({len(candidates)} candidates)")
    buys = []
    watch = []
    expired_pullbacks = list(stale_expired_pullbacks)
    pending = []          # tickers approved this run (cap awareness)
    reserved_cash = 0.0   # cash earmarked by approved buys this run
    scanned_count = 0
    high_candidates = []
    watch_2 = []
    catalysts = []
    scan_errors = []
    sector_sweep_triggers = []
    sector_sweep_context = {}
    sector_sweep_requeued = set()
    processed_scan = set()
    idx = 0
    ticker_loop_start = time.perf_counter()
    _timing_log("ticker_loop", "start", extra=f"candidates={len(candidates)}")
    pillar_results = _run_parallel_pillar_checks(candidates, entry_regime, _macro_legacy if _macro_gate.status == "ACCEPTED" else None, max_workers=8)
    while idx < len(candidates):
        tkr = candidates[idx]
        idx += 1
        ticker_start = time.perf_counter()
        _timing_log("ticker", "start", ticker=tkr, extra=f"idx={idx}/{len(candidates)}")
        processed_scan.add(str(tkr or "").upper())
        pending_pullback_start = time.perf_counter()
        _timing_log("pending_pullback", "start", ticker=tkr)
        pending_decision = port.evaluate_pending_pullback(
            tkr, dry_run=not live, regime=entry_regime,
            pending=pending, reserved_cash=reserved_cash, gear_packet=gear_packet,
        )
        _timing_log("pending_pullback", "end", pending_pullback_start, tkr)
        if pending_decision:
            pact = pending_decision.get("action")
            pscore = pending_decision.get("score") or "?"
            _audit_signal_decision(tkr, pending_decision, pscore, _pillar_count(pscore), live, "pending_pullback", market_date, run_id)
            if pact == "BUY":
                _attach_live_signal_price(pending_decision, tkr)
                buys.append(pending_decision)
                pending.append(tkr.upper())
                reserved_cash += pending_decision["cost"]
                high_candidates.append({
                    "ticker": tkr.upper(), "score": pscore, "pillars": _pillar_count(pscore),
                    "signal": pending_decision.get("signal", ""), "action": pact,
                    "reason": pending_decision.get("reason", ""),
                    "entry": pending_decision.get("entry"), "stop": pending_decision.get("stop"),
                    "target": pending_decision.get("target"), "rvol": pending_decision.get("rvol"),
                    "live_price": pending_decision.get("live_price"),
                    "cost": pending_decision.get("cost"), "shares": pending_decision.get("shares"),
                    "analyst_rating": pending_decision.get("analyst_rating"),
                    "analyst_insight": pending_decision.get("analyst_insight"),
                    "fundamentals": pending_decision.get("fundamentals"),
                    "indicator_info": pending_decision.get("indicator_info"),
                    "atr_info": pending_decision.get("atr_info"),
                    "sentiment_info": pending_decision.get("sentiment_info"),
                    "insider_activity": pending_decision.get("insider_activity"),
                    "macro_context": pending_decision.get("macro_context"),
                    "earnings_context": pending_decision.get("earnings_context"),
                    "earnings_note": pending_decision.get("earnings_note"),
                    "earnings_blackout": pending_decision.get("earnings_blackout"),
                    "fda_calendar": pending_decision.get("fda_calendar"),
                    "fda_note": pending_decision.get("fda_note"),
                    "fda_blackout": pending_decision.get("fda_blackout"),
                })
                print(f"  BUY   {tkr:<6} {pending_decision['shares']} sh @ {pending_decision['entry']} "
                      f"(stop {pending_decision['stop']}, {pending_decision['risk_pct']:.1f}% risk, "
                      f"${pending_decision['cost']:,.0f}) — {pending_decision['reason']}")
                continue
            if pact == "EXPIRE":
                expired_pullbacks.append(pending_decision)
                print(f"  ⌛ {pending_decision['reason']}")
                continue
            if pact == "WAIT":
                watch.append(tkr.upper())
                high_candidates.append({
                    "ticker": tkr.upper(), "score": pscore, "pillars": _pillar_count(pscore),
                    "signal": "PENDING PULLBACK", "action": pact,
                    "reason": pending_decision.get("reason", ""),
                    "entry": pending_decision.get("entry"), "price": pending_decision.get("price"),
                    "pct_over_ema": pending_decision.get("pct_over_ema"),
                    "analyst_rating": pending_decision.get("analyst_rating"),
                    "analyst_insight": pending_decision.get("analyst_insight"),
                    "fundamentals": pending_decision.get("fundamentals"),
                    "indicator_info": pending_decision.get("indicator_info"),
                    "atr_info": pending_decision.get("atr_info"),
                    "sentiment_info": pending_decision.get("sentiment_info"),
                    "insider_activity": pending_decision.get("insider_activity"),
                    "macro_context": pending_decision.get("macro_context"),
                    "earnings_context": pending_decision.get("earnings_context"),
                    "earnings_note": pending_decision.get("earnings_note"),
                    "earnings_blackout": pending_decision.get("earnings_blackout"),
                    "fda_calendar": pending_decision.get("fda_calendar"),
                    "fda_note": pending_decision.get("fda_note"),
                    "fda_blackout": pending_decision.get("fda_blackout"),
                })
                print(f"  ⏳ {pending_decision['reason']}")
                continue
            if pact in ("BLOCK", "SKIP", "ERROR"):
                high_candidates.append({
                    "ticker": tkr.upper(), "score": pscore, "pillars": _pillar_count(pscore),
                    "signal": pending_decision.get("signal", ""), "action": pact,
                    "reason": pending_decision.get("reason", ""),
                    "fundamentals": pending_decision.get("fundamentals"),
                    "indicator_info": pending_decision.get("indicator_info"),
                    "atr_info": pending_decision.get("atr_info"),
                    "sentiment_info": pending_decision.get("sentiment_info"),
                    "insider_activity": pending_decision.get("insider_activity"),
                    "macro_context": pending_decision.get("macro_context"),
                    "earnings_context": pending_decision.get("earnings_context"),
                    "earnings_note": pending_decision.get("earnings_note"),
                    "earnings_blackout": pending_decision.get("earnings_blackout"),
                    "fda_calendar": pending_decision.get("fda_calendar"),
                    "fda_note": pending_decision.get("fda_note"),
                    "fda_blackout": pending_decision.get("fda_blackout"),
                })
                print(f"  {pact.lower():<5} {tkr:<6} ({pscore}) {pending_decision.get('reason','')}")
                continue

        res = pillar_results.get(tkr.upper())
        if res is None:
            # Dynamic additions, e.g. sector-sweep peers, are analyzed only if they
            # were not present in the original base batch.
            _, res = _analyze_ticker_worker(tkr, entry_regime, _macro_legacy if _macro_load.context is not None else None)
            pillar_results[tkr.upper()] = res
        if "error" in res:
            scan_errors.append({"ticker": tkr.upper(), "error": res["error"]})
            _audit_signal_decision(tkr, {"action": "SKIP", "reason": res.get("error"), "signal": res.get("signal")}, "0/4 Pillars", 0, live, _scan_source(tkr, pending_scan, ema_retry_scan), market_date, run_id)
            print(f"  ----  {tkr:<6} {res['error']}")
            continue
        scanned_count += 1
        raw_score = res.get("score", "0/4 Pillars")
        raw_pillars = _pillar_count(raw_score)
        hysteresis = _effective_pillars_with_hysteresis(tkr, raw_pillars)
        score = _score_text(hysteresis.get("effective_pillars"))
        pillars = _pillar_count(score)
        if pillars != raw_pillars:
            res = dict(res)
            res["raw_score"] = raw_score
            res["raw_pillars"] = raw_pillars
            res["score"] = score
            res["hysteresis_state"] = hysteresis
            print(f"  hysteresis {tkr:<6} raw {raw_pillars}/4 -> effective {pillars}/4 ({hysteresis.get('reason')})")
        analyst_start = time.perf_counter()
        _timing_log("analyst_ratings_check", "start", ticker=tkr)
        _timing_log("analyst_ratings_check", "end", analyst_start, tkr, extra=f"rating={res.get('analyst_rating') or 'none'}")
        news_start = time.perf_counter()
        _timing_log("news_catalyst_check", "start", ticker=tkr)
        catalyst = _catalyst_reason(res)
        _timing_log("news_catalyst_check", "end", news_start, tkr, extra=f"catalyst={'yes' if catalyst else 'no'}")
        if catalyst:
            catalysts.append({"ticker": tkr.upper(), "reason": catalyst})
        sector_sweep_start = time.perf_counter()
        _timing_log("sector_sweep_trigger", "start", ticker=tkr)
        try:
            sweep_meta = port.sector_catalyst_sweep_trigger(res)
            _timing_log("sector_sweep_trigger", "end", sector_sweep_start, tkr, extra=f"peers={len((sweep_meta or {}).get('peers') or []) if isinstance(sweep_meta, dict) else 0}")
        except Exception as e:
            sweep_meta = None
            _timing_log("sector_sweep_trigger", "end", sector_sweep_start, tkr, extra=f"error={str(e)[:80]}")
            scan_errors.append({"ticker": tkr.upper(), "error": f"sector catalyst sweep trigger failed: {e}"})
        if isinstance(sweep_meta, dict) and sweep_meta.get("peers"):
            sector_sweep_triggers.append({
                "ticker": tkr.upper(),
                "move_pct": sweep_meta.get("move_pct"),
                "rvol": sweep_meta.get("rvol"),
                "catalyst": sweep_meta.get("catalyst"),
                "peer_count": sweep_meta.get("peer_count"),
                "classification": sweep_meta.get("classification"),
            })
            queued = set(candidates)
            added_peers = []
            for peer in sweep_meta.get("peers") or []:
                peer = str(peer or "").upper()
                if not peer or peer == tkr.upper():
                    continue
                sector_sweep_context.setdefault(peer, sweep_meta)
                if peer in queued:
                    if peer in processed_scan and peer not in sector_sweep_requeued:
                        candidates.append(peer)
                        sector_sweep_requeued.add(peer)
                        added_peers.append(peer)
                    continue
                candidates.append(peer)
                queued.add(peer)
                added_peers.append(peer)
            if added_peers:
                cls = sweep_meta.get("classification") or {}
                label = cls.get("gic_subindustry") or cls.get("industry") or cls.get("sic_description") or "peer group"
                print(f"  🧲 SECTOR SWEEP {tkr:<6} +{sweep_meta.get('move_pct'):.1f}% RVOL {sweep_meta.get('rvol'):.1f}x — queued {len(added_peers)} {label} peers")
        gap_decision = None
        if tkr.upper() not in set(pending_scan):
            try:
                gap_decision = port.consider_gap_up_breakout(
                    res, dry_run=not live, regime=entry_regime,
                    pending=pending, reserved_cash=reserved_cash, gear_packet=gear_packet,
                )
            except Exception as e:
                gap_decision = {"ticker": tkr.upper(), "action": "ERROR", "reason": f"gap-up breakout check failed: {e}"}
        if isinstance(gap_decision, dict) and gap_decision.get("action") == "BUY":
            _attach_live_signal_price(gap_decision, tkr)
            gap_decision.setdefault("score", score)
            gap_decision.setdefault("signal", res.get("signal", ""))
            _audit_signal_decision(tkr, gap_decision, score, pillars, live, "gap_up_breakout", market_date, run_id)
            buys.append(gap_decision)
            pending.append(tkr.upper())
            reserved_cash += gap_decision["cost"]
            high_candidates.append({
                "ticker": tkr.upper(), "score": score, "pillars": pillars,
                "signal": res.get("signal", ""), "action": "BUY",
                "reason": gap_decision.get("reason", ""),
                "entry": gap_decision.get("entry"), "stop": gap_decision.get("stop"),
                "target": gap_decision.get("target"), "cost": gap_decision.get("cost"),
                "shares": gap_decision.get("shares"), "rvol": res.get("rvol"),
                "gap_pct": gap_decision.get("gap_pct"), "gap_rvol": gap_decision.get("gap_rvol"),
                "entry_type": "GAP_UP_BREAKOUT", "catalyst": gap_decision.get("catalyst"),
                "live_price": gap_decision.get("live_price"),
            })
            print(f"  🚀 GAP BUY {tkr:<6} {gap_decision['shares']} sh @ {gap_decision['entry']} "
                  f"(stop {gap_decision['stop']}, {gap_decision['risk_pct']:.2f}% risk, "
                  f"${gap_decision['cost']:,.0f}) — {gap_decision['reason']}")
            continue
        intraday_breakout_decision = None
        if tkr.upper() not in set(pending_scan) and tkr.upper() not in set(pending):
            try:
                intraday_breakout_decision = port.consider_intraday_breakout_continuation(
                    res, dry_run=not live, regime=entry_regime,
                    pending=pending, reserved_cash=reserved_cash, gear_packet=gear_packet,
                )
            except Exception as e:
                intraday_breakout_decision = {"ticker": tkr.upper(), "action": "ERROR", "reason": f"intraday breakout check failed: {e}"}
        if isinstance(intraday_breakout_decision, dict) and intraday_breakout_decision.get("action") == "BUY":
            _attach_live_signal_price(intraday_breakout_decision, tkr)
            intraday_breakout_decision.setdefault("score", score)
            intraday_breakout_decision.setdefault("signal", res.get("signal", ""))
            _audit_signal_decision(tkr, intraday_breakout_decision, score, pillars, live, "intraday_breakout_continuation", market_date, run_id)
            buys.append(intraday_breakout_decision)
            pending.append(tkr.upper())
            reserved_cash += intraday_breakout_decision["cost"]
            high_candidates.append({
                "ticker": tkr.upper(), "score": score, "pillars": pillars,
                "signal": res.get("signal", ""), "action": "BUY",
                "reason": intraday_breakout_decision.get("reason", ""),
                "entry": intraday_breakout_decision.get("entry"), "stop": intraday_breakout_decision.get("stop"),
                "target": intraday_breakout_decision.get("target"), "cost": intraday_breakout_decision.get("cost"),
                "shares": intraday_breakout_decision.get("shares"), "rvol": res.get("rvol"),
                "breakout_level": intraday_breakout_decision.get("breakout_level"),
                "breakout_rvol": intraday_breakout_decision.get("breakout_rvol"),
                "entry_type": "INTRADAY_BREAKOUT_CONTINUATION", "catalyst": intraday_breakout_decision.get("catalyst"),
                "live_price": intraday_breakout_decision.get("live_price"),
            })
            print(f"  📈 INTRADAY BREAKOUT {tkr:<6} {intraday_breakout_decision['shares']} sh @ {intraday_breakout_decision['entry']} "
                  f"(break {intraday_breakout_decision['breakout_level']}, stop {intraday_breakout_decision['stop']}, {intraday_breakout_decision['risk_pct']:.2f}% risk, "
                  f"${intraday_breakout_decision['cost']:,.0f}) — {intraday_breakout_decision['reason']}")
            continue
        sector_peer_decision = None
        if tkr.upper() in sector_sweep_context and tkr.upper() not in set(pending_scan) and tkr.upper() not in set(pending):
            try:
                sector_peer_decision = port.consider_sector_catalyst_peer_breakout(
                    res, sector_sweep_context.get(tkr.upper()), dry_run=not live, regime=entry_regime,
                    pending=pending, reserved_cash=reserved_cash, gear_packet=gear_packet,
                )
            except Exception as e:
                sector_peer_decision = {"ticker": tkr.upper(), "action": "ERROR", "reason": f"sector catalyst peer check failed: {e}"}
        if isinstance(sector_peer_decision, dict) and sector_peer_decision.get("action") == "CANDIDATE":
            sector_peer_decision.setdefault("score", score)
            sector_peer_decision.setdefault("signal", res.get("signal", ""))
            _audit_signal_decision(tkr, sector_peer_decision, score, pillars, live, "sector_catalyst_sweep", market_date, run_id)
            high_candidates.append({
                "ticker": tkr.upper(), "score": score, "pillars": pillars,
                "signal": res.get("signal", ""), "action": "CANDIDATE",
                "reason": sector_peer_decision.get("reason", ""),
                "entry": sector_peer_decision.get("entry"), "stop": sector_peer_decision.get("stop"),
                "target": sector_peer_decision.get("target"), "cost": sector_peer_decision.get("cost"),
                "shares": sector_peer_decision.get("shares"), "rvol": sector_peer_decision.get("breakout_rvol") or res.get("rvol"),
                "breakout_level": sector_peer_decision.get("breakout_level"),
                "breakout_rvol": sector_peer_decision.get("breakout_rvol"),
                "entry_type": "INTRADAY_BREAKOUT_CONTINUATION",
                "sector_sweep": True,
                "sector_sweep_trigger": sector_peer_decision.get("sector_sweep_trigger"),
                "sector_sweep_trigger_move_pct": sector_peer_decision.get("sector_sweep_trigger_move_pct"),
                "sector_sweep_trigger_rvol": sector_peer_decision.get("sector_sweep_trigger_rvol"),
                "catalyst": sector_peer_decision.get("sector_sweep_catalyst"),
            })
            print(f"  🧲 SECTOR CANDIDATE {tkr:<6} ({score}) RVOL {sector_peer_decision.get('breakout_rvol'):.1f}x — trigger {sector_peer_decision.get('sector_sweep_trigger')}")
            continue
        catalyst_override_ok = bool(
            pillars == 2 and isinstance(res.get("catalyst_override"), dict) and res.get("catalyst_override", {}).get("qualifies")
        )
        if pillars < 3 and not catalyst_override_ok:
            if "WATCH" in str(res.get("signal", "")).upper():
                watch.append(tkr.upper())
                if pillars == 2:
                    watch_2.append(tkr.upper())
                    high_candidates.append({
                        "ticker": tkr.upper(),
                        "score": score,
                        "pillars": pillars,
                        "signal": res.get("signal", ""),
                        "action": "WATCH",
                        "reason": res.get("signal", ""),
                        "pct_over_ema": res.get("pct_over_ema"),
                    })
            _audit_signal_decision(tkr, {"action": "SKIP", "reason": res.get("signal", ""), "signal": res.get("signal")}, score, pillars, live, _scan_source(tkr, pending_scan, ema_retry_scan), market_date, run_id)
            print(f"  skip  {tkr:<6} {res.get('signal','')}  ({score})")
            continue

        if perme_overlay.get("active"):
            flagged_tickers = set(perme_overlay.get("perme_flagged_tickers") or set())
            ticker_flagged = tkr.upper() in flagged_tickers
            min_pillars = 4 if ticker_flagged else int(perme_overlay.get("global_min_pillars") or 3)
            min_rvol = 2.0 if ticker_flagged else float(perme_overlay.get("global_min_rvol") or 1.5)
            ticker_rvol = _float_value(res.get("rvol"), default=0.0)
            if pillars < min_pillars or ticker_rvol < min_rvol:
                rag_reason = (
                    f"WAITING FOR DIP — Perme threshold needs {min_pillars}/4 + RVOL {min_rvol:.1f} "
                    f"(sentiment={perme_overlay.get('sentiment')}, pillars={pillars}, rvol={ticker_rvol:.2f})"
                )
                print(
                    f"[atlas_rag] Perme threshold: {tkr.upper()} needs {min_pillars}/4 + RVOL {min_rvol:.1f} "
                    f"(sentiment={perme_overlay.get('sentiment')}, pillars={pillars}, rvol={ticker_rvol:.2f})"
                )
                watch.append(tkr.upper())
                high_candidates.append({
                    "ticker": tkr.upper(),
                    "score": score,
                    "pillars": pillars,
                    "signal": res.get("signal", ""),
                    "action": "WAIT",
                    "reason": rag_reason,
                    "rvol": res.get("rvol"),
                    "pct_over_ema": res.get("pct_over_ema"),
                    "macro_context": macro_ctx,
                    "perme_threshold_overlay": LAST_RUN_SUMMARY.get("perme_threshold_overlay"),
                })
                _audit_signal_decision(
                    tkr,
                    {"action": "WAIT", "reason": rag_reason, "signal": res.get("signal"), "rvol": res.get("rvol")},
                    score, pillars, live, _scan_source(tkr, pending_scan, ema_retry_scan), market_date, run_id,
                )
                continue

        decision = port.consider_buy(
            res, dry_run=not live, regime=entry_regime,
            pending=pending, reserved_cash=reserved_cash, gear_packet=gear_packet,
        )
        decision.setdefault("score", score)
        decision.setdefault("rvol", res.get("rvol"))
        decision.setdefault("signal", res.get("signal", ""))
        decision.setdefault("analyst_rating", res.get("analyst_rating"))
        decision.setdefault("analyst_insight", res.get("analyst_insight"))
        decision.setdefault("fundamentals", res.get("fundamentals"))
        decision.setdefault("indicator_info", res.get("indicator_info"))
        decision.setdefault("atr_info", res.get("atr_info"))
        decision.setdefault("sentiment_info", res.get("sentiment_info"))
        decision.setdefault("insider_activity", res.get("insider_activity"))
        decision.setdefault("macro_context", decision.get("macro_context") or macro_ctx)
        decision.setdefault("earnings_context", res.get("earnings_context"))
        decision.setdefault("earnings_note", decision.get("earnings_note") or ((res.get("earnings_context") or {}).get("earnings_momentum") or {}).get("earnings_momentum_note") or ((res.get("earnings_context") or {}).get("earnings_miss") or {}).get("earnings_miss_note") or ((res.get("earnings_context") or {}).get("note") if (res.get("earnings_context") or {}).get("unknown") else None))
        decision.setdefault("fda_calendar", decision.get("fda_calendar") or res.get("fda_calendar"))
        decision.setdefault("fda_note", decision.get("fda_note") or ((decision.get("fda_calendar") or {}).get("tag") if isinstance(decision.get("fda_calendar"), dict) else None))
        act = decision["action"]
        _audit_signal_decision(tkr, decision, score, pillars, live, _scan_source(tkr, pending_scan, ema_retry_scan), market_date, run_id)
        if act == "BUY":
            _attach_live_signal_price(decision, tkr)
        high_candidates.append({
            "ticker": tkr.upper(),
            "score": score,
            "pillars": pillars,
            "signal": res.get("signal", ""),
            "action": act,
            "reason": decision.get("reason", ""),
            "entry": decision.get("entry"),
            "stop": decision.get("stop"),
            "target": decision.get("target"),
            "cost": decision.get("cost"),
            "shares": decision.get("shares"),
            "rvol": res.get("rvol"),
            "live_price": decision.get("live_price"),
            "price": decision.get("price"),
            "pct_over_ema": decision.get("pct_over_ema"),
            "analyst_rating": decision.get("analyst_rating"),
            "analyst_insight": decision.get("analyst_insight"),
            "fundamentals": decision.get("fundamentals"),
            "indicator_info": decision.get("indicator_info"),
            "atr_info": decision.get("atr_info"),
            "sentiment_info": decision.get("sentiment_info"),
            "insider_activity": decision.get("insider_activity"),
            "macro_context": decision.get("macro_context"),
            "earnings_context": decision.get("earnings_context"),
            "earnings_note": decision.get("earnings_note"),
            "earnings_blackout": decision.get("earnings_blackout"),
            "fda_calendar": decision.get("fda_calendar"),
            "fda_note": decision.get("fda_note"),
            "fda_blackout": decision.get("fda_blackout"),
            "hysteresis_state": res.get("hysteresis_state"),
            "raw_score": res.get("raw_score"),
            "raw_pillars": res.get("raw_pillars"),
            "final_advisory_action": act,
        })
        if act == "BUY":
            buys.append(decision)
            pending.append(tkr.upper())
            reserved_cash += decision["cost"]
            print(f"  BUY   {tkr:<6} {decision['shares']} sh @ {decision['entry']} "
                  f"(stop {decision['stop']}, {decision['risk_pct']:.1f}% risk, "
                  f"${decision['cost']:,.0f}) — {decision['reason']}")
        elif act == "WAIT":
            watch.append(tkr.upper())
            prefix = "⏳" if "WAITING FOR PULLBACK" in str(decision.get("reason", "")) else "wait"
            print(f"  {prefix} {decision['reason']}")
        elif act == "BLOCK":
            print(f"  block {tkr:<6} ({score}) {decision['reason']}")
        elif act == "SKIP" and str(decision.get("reason", "")).startswith("TOO EXTENDED"):
            print(f"  🚀 {decision['reason']}")
        else:
            print(f"  {act.lower():<5} {tkr:<6} ({score}) {decision['reason']}")

    _timing_log("ticker_loop", "end", ticker_loop_start, extra=f"processed={idx} scanned={scanned_count} candidates_final={len(candidates)}")

    fda_scan_context = _load_fda_scan_context(candidates)
    for _row in high_candidates:
        _attach_fda_metadata(_row, fda_scan_context)
    LAST_RUN_SUMMARY["fda_scan_stats"] = fda_scan_context.get("stats", {})

    LAST_RUN_SUMMARY.update({
        "candidates": candidates,
        "scanned_count": scanned_count,
        "high_candidates": high_candidates,
        "watch_2": sorted(set(watch_2)),
        "catalysts": catalysts,
        "sector_sweep_triggers": sector_sweep_triggers,
        "scan_errors": scan_errors,
        "expired_pullbacks": expired_pullbacks,
        "pending_pullbacks": atlas_db.get_pending_pullbacks(status="WAITING"),
        "buys": buys,
        "result": "ACTION" if (buys or sells) else "DO NOTHING",
    })

    # --- PERSIST SCAN RESULT TO HANDOFF (so pre-market brief stays live) ---
    if live:
        try:
            import datetime as _dt
            _today = current_et_market_date_str()
            _buy_syms = [b.get("ticker", b.get("symbol", "")) for b in buys]
            _buy_syms = [s.upper() for s in _buy_syms if s]
            _watch_syms = [t.upper() for t in (pending + watch)]  # approved-but-not-bought + scanned
            _existing = atlas_db.get_handoff(_today) or {}
            _handoff = {
                "date": _today,
                "BUY": sorted(set(_buy_syms)),
                "WATCH": sorted(set((_existing.get("WATCH") or []) + _watch_syms)),
                "last_scan": _dt.datetime.now().isoformat(),
            }
            atlas_db.update_handoff(_today, _handoff)
            LAST_RUN_SUMMARY["handoff"] = _handoff
            print(f"  [handoff] saved {len(_handoff['BUY'])} BUY / {len(_handoff['WATCH'])} WATCH for {_today}")
        except Exception as _e:
            LAST_RUN_SUMMARY["handoff_error"] = str(_e)
            print(f"  [handoff] persist skipped: {_e}")
    else:
        print("  [handoff] DRY-RUN: skipping handoff persistence")
    # ------------------------------------------------------------------------------

    _finish(live, sells, buys)
    return LAST_RUN_SUMMARY


def _finish(live, sells, buys):
    _hdr("SUMMARY")
    print(f"  Sells executed : {len(sells)}" if live else f"  Sells planned  : {len(sells)}")
    print(f"  Buys executed  : {len(buys)}" if live else f"  Buys planned   : {len(buys)}")
    post = acct.get_account_summary(price_lookup=port._price_lookup)
    print(f"  Cash now       : ${post['cash']:,.2f}")
    print(f"  Equity now     : ${post['equity']:,.2f}")
    if not live:
        print(THIN)
        print("  This was a DRY-RUN. Re-run with --live to execute.")
    print(LINE + "\n")


def _register_value(parts, key, default=None):
    prefix = key + "="
    for part in parts:
        if str(part).startswith(prefix):
            return str(part).split("=", 1)[1]
    return default


def handle_register(argv):
    """Register a user-confirmed broker fill.

    Usage: atlas_manage.py register TICKER buy qty=N price=P fees=F ref=REF
    If a PENDING_FILL row exists for the ticker, it is confirmed into OPEN.
    Otherwise a new OPEN trade is created for manual broker registrations.
    """
    if len(argv) < 4:
        raise SystemExit("Usage: atlas_manage.py register TICKER buy qty=N price=P fees=F ref=REF")
    ticker = argv[2].upper()
    side = argv[3].lower()
    if side != "buy":
        raise SystemExit("Only 'buy' register is supported here")
    qty_raw = _register_value(argv[4:], "qty")
    price_raw = _register_value(argv[4:], "price")
    if qty_raw is None or price_raw is None:
        raise SystemExit("register requires qty=N and price=P")
    qty = float(qty_raw)
    price = float(str(price_raw).replace("$", ""))
    fees = float(str(_register_value(argv[4:], "fees", "0")).replace("$", ""))
    ref = _register_value(argv[4:], "ref", "")
    pending = [r for r in atlas_db.get_pending_fill_trades() if str(r.get("ticker", "")).upper() == ticker]
    if pending:
        trade = atlas_db.confirm_trade_fill(pending[0]["id"], qty, price, fees, ref)
        print(f"REGISTERED {ticker}: PENDING_FILL #{pending[0]['id']} -> OPEN, qty={qty}, price=${price:.2f}, fees=${fees:.2f}, ref={ref}")
        return {"registered": True, "mode": "confirmed_pending", "trade": trade}
    trade_id = atlas_db.open_trade(
        ticker, price, qty, fees=fees, status="OPEN",
        notes=f"Manual broker registration ref {ref}" if ref else "Manual broker registration",
    )
    conn = atlas_db.get_connection(); cur = conn.cursor()
    atlas_db._append_cash_ledger(cur, -(qty * price + fees), f"Manual broker fill {ticker} {ref}: {qty} sh @ {price} plus fees {fees}")
    conn.commit(); conn.close()
    print(f"REGISTERED {ticker}: new OPEN trade #{trade_id}, qty={qty}, price=${price:.2f}, fees=${fees:.2f}, ref={ref}")
    return {"registered": True, "mode": "manual_open", "trade_id": trade_id}


def main():
    if len(sys.argv) > 1 and sys.argv[1].lower() == "register":
        handle_register(sys.argv)
        return
    p = argparse.ArgumentParser(description="Atlas v2 daily portfolio manager")
    p.add_argument("tickers", nargs="*", help="Optional explicit tickers to scan")
    p.add_argument("--file", help="Path to a watchlist file (one/many tickers per line)")
    p.add_argument("--live", action="store_true", help="Execute orders (default is dry-run)")
    p.add_argument("--exits-only", action="store_true", help="Only run the exit engine")
    p.add_argument("--json", action="store_true", help="Also dump machine-readable JSON")
    p.add_argument("--lock-stop", type=int, help="Lock one OPEN trade stop against automatic trailing by trade id")
    p.add_argument("--unlock-stop", type=int, help="Unlock one OPEN trade stop so automatic trailing can resume by trade id")
    args = p.parse_args()
    if args.lock_stop and args.unlock_stop:
        raise SystemExit("Use only one of --lock-stop or --unlock-stop")
    if args.lock_stop:
        atlas_db.init_db()
        changed = atlas_db.set_manual_stop_lock(args.lock_stop, True)
        trade = atlas_db.get_trade(args.lock_stop)
        print(f"LOCK_STOP trade_id={args.lock_stop} changed={changed} trade={json.dumps(trade, default=str, sort_keys=True)}")
        return
    if args.unlock_stop:
        atlas_db.init_db()
        changed = atlas_db.set_manual_stop_lock(args.unlock_stop, False)
        trade = atlas_db.get_trade(args.unlock_stop)
        print(f"UNLOCK_STOP trade_id={args.unlock_stop} changed={changed} trade={json.dumps(trade, default=str, sort_keys=True)}")
        return
    summary = run(args)
    if args.json:
        print(json.dumps(summary, default=str))


if __name__ == "__main__":
    main()
