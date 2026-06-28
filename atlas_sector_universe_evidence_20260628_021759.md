# Atlas Sector Catalyst / Universe Evidence — 2026-06-28

Prof.

This file contains the evidence that should have been sent as an attachment instead of a long Telegram message.

## 1. Does Atlas dynamically expand the ticker universe based on a sector catalyst?

**Answer: Yes — not in `market_scout.py`; yes through `atlas_manage.py` calling sector-sweep helpers.**

Evidence that `market_scout.py` has no sector catalyst / peer expansion code:

```text
search_files market_scout.py pattern="sector_sweep|sector catalyst|peer|gic"
total_count: 0
```

Relevant dynamic expansion in `/Users/yasser/scripts/atlas_manage.py`:

```python
464|        sector_sweep_start = time.perf_counter()
465|        _timing_log("sector_sweep_trigger", "start", ticker=tkr)
466|        try:
467|            sweep_meta = port.sector_catalyst_sweep_trigger(res)
468|            _timing_log("sector_sweep_trigger", "end", sector_sweep_start, tkr, extra=f"peers={len((sweep_meta or {}).get('peers') or []) if isinstance(sweep_meta, dict) else 0}")
469|        except Exception as e:
470|            sweep_meta = None
471|            _timing_log("sector_sweep_trigger", "end", sector_sweep_start, tkr, extra=f"error={str(e)[:80]}")
472|            scan_errors.append({"ticker": tkr.upper(), "error": f"sector catalyst sweep trigger failed: {e}"})
473|        if isinstance(sweep_meta, dict) and sweep_meta.get("peers"):
474|            sector_sweep_triggers.append({
475|                "ticker": tkr.upper(),
476|                "move_pct": sweep_meta.get("move_pct"),
477|                "rvol": sweep_meta.get("rvol"),
478|                "catalyst": sweep_meta.get("catalyst"),
479|                "peer_count": sweep_meta.get("peer_count"),
480|                "classification": sweep_meta.get("classification"),
481|            })
482|            queued = set(candidates)
483|            added_peers = []
484|            for peer in sweep_meta.get("peers") or []:
485|                peer = str(peer or "").upper()
486|                if not peer or peer == tkr.upper():
487|                    continue
488|                sector_sweep_context.setdefault(peer, sweep_meta)
489|                if peer in queued:
490|                    if peer in processed_scan and peer not in sector_sweep_requeued:
491|                        candidates.append(peer)
492|                        sector_sweep_requeued.add(peer)
493|                        added_peers.append(peer)
494|                    continue
495|                candidates.append(peer)
496|                queued.add(peer)
497|                added_peers.append(peer)
498|            if added_peers:
499|                cls = sweep_meta.get("classification") or {}
500|                label = cls.get("gic_subindustry") or cls.get("industry") or cls.get("sic_description") or "peer group"
501|                print(f"  🧲 SECTOR SWEEP {tkr:<6} +{sweep_meta.get('move_pct'):.1f}% RVOL {sweep_meta.get('rvol'):.1f}x — queued {len(added_peers)} {label} peers")
```

Minimal related sector peer evidence from `/Users/yasser/scripts/atlas_portfolio.py`:

```python
1246|def _sector_sweep_curated_gics_industry_peers(gic_industry):
1247|    if str(gic_industry or "").strip().lower() != "semiconductors & semiconductor equipment":
1248|        return []
1249|    return [
1250|        "NVDA", "AMD", "AVGO", "QCOM", "MU", "MRVL", "ON", "STM", "TSM", "ASML", "AMAT", "LRCX",
1251|        "KLAC", "TER", "UCTT", "MKSI", "MXL", "ALGM", "ENTG", "ONTO", "NVMI", "AEIS", "ACLS", "COHU",
1252|        "VECO", "ICHR", "FORM", "AMKR", "LSCC", "MPWR", "RMBS", "SMTC", "DIOD", "POWI", "CRUS", "WOLF",
1253|    ]
```

Minimal trigger evidence from `/Users/yasser/scripts/atlas_portfolio.py`:

```python
1303|def sector_catalyst_sweep_trigger(signal_result, now=None):
1304|    ticker = str((signal_result or {}).get("ticker") or "").upper()
1305|    if not ticker or not _sector_sweep_window_open(now=now):
1306|        return None
1307|    metrics = _sector_sweep_snapshot_metrics(ticker)
1308|    move_pct = metrics.get("move_pct")
1309|    rvol = metrics.get("rvol")
1310|    if move_pct is None or float(move_pct) <= SECTOR_SWEEP_TRIGGER_MOVE_PCT:
1311|        return None
1312|    if rvol is None or float(rvol) <= SECTOR_SWEEP_TRIGGER_RVOL:
1313|        return None
1314|    catalyst_ok, catalyst_note = _recent_benzinga_catalyst(ticker, now=now)
1315|    if not catalyst_ok:
1316|        return None
1317|    meta = sector_catalyst_sweep_peers(ticker)
1318|    meta.update({
1319|        "move_pct": round(float(move_pct), 2),
1320|        "rvol": round(float(rvol), 2),
1321|        "catalyst": catalyst_note,
1322|        "entry_type": "SECTOR_CATALYST_SWEEP",
1323|    })
1324|    return meta if meta.get("peers") else None
```

## 2. What is the exact source of the ~90–100 ticker universe Atlas scans?

**Answer: Dynamic fetch from `market_scout.discover_tickers()` capped at 80, then expanded with DB pending pullbacks, EMA retries, and open holdings. The hardcoded list is fallback only.**

Evidence in `/Users/yasser/scripts/atlas_manage.py`:

```python
57|# Default universe if the user passes no tickers. Kept small & liquid; the
58|# scout normally supplies the real candidates, but this gives a sane default.
59|DEFAULT_UNIVERSE = [
60|    "NVDA", "AMD", "AVGO", "SMCI", "MU",
61|    "AAPL", "MSFT", "GOOGL", "META", "AMZN",
62|    "TSLA", "NFLX", "PLTR", "SNOW", "CRWD",
63|    "LLY", "JPM", "COIN", "ORCL", "NOW",
64|]
```

```python
109|def load_candidates(args):
110|    if args.tickers:
111|        return [t.upper() for t in args.tickers]
112|    if args.file and os.path.exists(args.file):
113|        with open(args.file) as f:
114|            toks = []
115|            for line in f:
116|                line = line.split("#", 1)[0].strip()
117|                if line:
118|                    toks += [p.strip().upper() for p in line.replace(",", " ").split()]
119|            return [t for t in toks if t]
120|    # Default: reuse the SAME news-driven discovery the scout uses, so the
121|    # daily manager scans exactly the universe market_scout.py would. Falls
122|    # back to the built-in liquid list if the scout isn't importable.
123|    try:
124|        from market_scout import discover_tickers
125|        found = discover_tickers()
126|        if found:
127|            return [t.upper() for t in found]
128|    except Exception:
129|        pass
130|    return list(DEFAULT_UNIVERSE)
```

```python
316|    candidates = load_candidates(args)
317|    pending_rows = atlas_db.get_pending_pullbacks(status="WAITING")
318|    pending_scan = [r.get("ticker", "").upper() for r in pending_rows if r.get("ticker")]
319|    ema_retry_rows = atlas_db.get_ema_retry_candidates(status="WAITING")
320|    ema_retry_scan = [r.get("ticker", "").upper() for r in ema_retry_rows if r.get("ticker")]
321|    held_scan = [r.get("ticker", "").upper() for r in atlas_db.get_trades(status="OPEN") if r.get("ticker")]
322|    candidates = list(dict.fromkeys(pending_scan + ema_retry_scan + held_scan + [t.upper() for t in candidates]))
323|    _hdr(f"SCAN & ENTRIES  ({len(candidates)} candidates)")
```

Evidence in `/Users/yasser/scripts/market_scout.py` showing dynamic sources and final cap:

```python
494|def discover_tickers():
495|    # Use Benzinga to find stocks with breaking news today
496|    benzinga_key = os.environ.get("BENZINGA_API_KEY")
497|    catalyst_order = []
498|    earnings_order = []
499|    large_cap_quality_order = []
500|    mover_order = []
501|    volume_order = []
502|    rs_order = []
503|    momentum_order = []
```

```python
514|    if benzinga_key:
515|        url = "https://api.benzinga.com/api/v2/news"
516|        params = {
517|            "token": benzinga_key,
518|            "dateFrom": datetime.date.today().strftime('%Y-%m-%d'),
519|            "pageSize": 50,
520|            "sort": "created",
521|            "sortDir": "desc",
522|        }
523|        try:
524|            response = _audit_get(url, params=params, headers={"Accept": "application/json"})
525|            if response.status_code == 200:
526|                for item in response.json():
527|                    for stock in item.get("stocks", []):
528|                        if stock.get("name"):
529|                            _add_to_bucket(catalyst_order, stock["name"])
530|        except Exception as e:
531|            print(f"[market_scout] Benzinga discovery failed: {e}")
```

```python
533|    # Earnings calendar: previous trading day through next 3 trading days.
534|    try:
535|        for sym in discover_earnings_calendar(limit=20):
536|            _add_to_bucket(earnings_order, sym)
537|    except Exception as e:
538|        print(f"[market_scout] earnings calendar discovery failed: {e}")
```

```python
540|    # Large-cap quality: liquid US mega/large caps without a same-day momentum requirement.
541|    try:
542|        for sym in discover_large_cap_quality(limit=40):
543|            _add_to_bucket(large_cap_quality_order, sym)
544|    except Exception as e:
545|        print(f"[market_scout] large-cap quality discovery failed: {e}")
```

```python
547|    # --- Top movers feed: gainers + most-active (price >= $5), so breakout/volume leaders are always surfaced ---
548|    if MASSIVE_API_KEY:
549|        try:
550|            mr = _audit_get(
551|                f"{MASSIVE_BASE}/v2/snapshot/locale/us/markets/stocks/gainers",
552|                params={"apiKey": MASSIVE_API_KEY},
553|                headers={"Accept": "application/json"},
554|                timeout=10,
555|            )
556|            if mr.status_code == 200:
557|                for t in (mr.json().get("tickers") or [])[:15]:
558|                    sym = (t.get("ticker") or "").upper()
559|                    price = (t.get("day") or {}).get("c") or 0
560|                    if sym and price >= 5:
561|                        _add_to_bucket(mover_order, sym)
562|        except Exception as e:
563|            print(f"[market_scout] gainers feed failed: {e}")
```

```python
567|        try:
568|            mr = _audit_get(
569|                f"{MASSIVE_BASE}/v2/snapshot/locale/us/markets/stocks/tickers",
570|                params={"apiKey": MASSIVE_API_KEY},
571|                headers={"Accept": "application/json"},
572|                timeout=10,
573|            )
574|            if mr.status_code == 200:
575|                volume_rows = []
576|                for t in (mr.json().get("tickers") or []):
577|                    sym = (t.get("ticker") or "").upper()
578|                    day = t.get("day") or {}
579|                    prev = t.get("prevDay") or {}
580|                    last = t.get("lastTrade") or {}
581|                    price = day.get("c") or last.get("p") or prev.get("c") or 0
582|                    volume = day.get("v") or day.get("volume") or prev.get("v") or prev.get("volume") or 0
583|                    if sym and price and float(price) >= 5 and volume:
584|                        volume_rows.append((float(volume), t))
585|                for _volume, t in sorted(volume_rows, key=lambda item: item[0], reverse=True)[:50]:
586|                    sym = (t.get("ticker") or "").upper()
587|                    _add_to_bucket(volume_order, sym)
588|        except Exception as e:
589|            print(f"[market_scout] most-active snapshot failed: {e}")
```

```python
591|    # RS leaders: multi-day outperformers vs SPY
592|    try:
593|        rs_leaders = discover_rs_leaders(top_n=RS_TOP_N)
594|        for sym in rs_leaders:
595|            if _is_tradeable_equity(sym):
596|                _add_to_bucket(rs_order, sym)
597|    except Exception:
598|        pass
```

```python
600|    # EODHD screener: fresh liquid/moving US names, fed into the SAME normal engine scan.
601|    if EODHD_API_KEY:
602|        try:
603|            import json as _json
604|            filters = [["refund_1d_p", ">", 3], ["avgvol_200d", ">", 1000000], ["exchange", "=", "US"], ["market_capitalization", ">", 300000000]]
605|            sr = _audit_get(
606|                "https://eodhd.com/api/screener",
607|                params={"api_token": EODHD_API_KEY, "fmt": "json", "filters": _json.dumps(filters), "limit": 50, "sort": "refund_1d_p.desc"},
608|                headers={"Accept": "application/json"}, timeout=10,
609|            )
610|            if sr.status_code == 200:
611|                for row in (sr.json().get("data") or [])[:50]:
612|                    sym = (row.get("code") or "").upper()
613|                    price = row.get("adjusted_close") or 0
614|                    if sym and price and float(price) >= 5:
615|                        _add_to_bucket(momentum_order, sym)
616|        except Exception as e:
617|            print(f"[market_scout] EODHD screener failed: {e}")
```

```python
619|    # Fallback high-liquidity universe if no discovery feeds return names (e.g. weekend/pre-market)
620|    if not any((catalyst_order, earnings_order, large_cap_quality_order, mover_order, volume_order, rs_order, momentum_order)):
621|        fallback = {"NVDA", "TSLA", "AAPL", "AMD", "MSFT", "META", "AMZN", "GOOGL", "NFLX", "SMCI", "PLTR", "COIN"}
622|        for sym in fallback:
623|            _add_to_bucket(catalyst_order, sym)
```

```python
636|    full_order = _dedupe_ordered(catalyst_order, earnings_order, large_cap_quality_order, mover_order, volume_order, rs_order, momentum_order)
637|    capped_order = _dedupe_ordered(
638|        catalyst_order[:20],
639|        earnings_order[:20],
640|        large_cap_quality_order[:30],
641|        mover_order[:20],
642|        volume_order[:20],
643|        rs_order[:10],
644|        momentum_order[:10],
645|    )
646|    final_order = capped_order[:80] if len(full_order) > 80 else full_order[:80]
647|    global _LAST_DISCOVERY_BUCKETS
648|    _LAST_DISCOVERY_BUCKETS = {
649|        "catalyst": list(catalyst_order),
650|        "earnings": list(earnings_order),
651|        "large_cap_quality": list(large_cap_quality_order),
652|        "movers": list(mover_order),
653|        "volume": list(volume_order),
654|        "rs": list(rs_order),
655|        "momentum": list(momentum_order),
656|        "final": list(final_order),
657|    }
658|    return final_order
```

## 3. On June 26, were KLAC, TER, UCTT, MXL, MKSI, or ALGM anywhere in the scan universe — watchlist, pending_pullbacks, or signals table?

**Answer: Yes.**

### Exact command requested

```bash
sqlite3 /Users/yasser/scripts/atlas.db "SELECT ticker, COUNT(*) FROM signals WHERE ticker IN ('KLAC','TER','UCTT','MXL','MKSI','ALGM') GROUP BY ticker;"
```

Output:

```text
ALGM|13
KLAC|4
MKSI|13
MXL|1
TER|2
UCTT|1
```

### Watchlist evidence for `2026-06-26`

```bash
sqlite3 /Users/yasser/scripts/atlas.db "SELECT h.date, j.value FROM handoff h, json_each(h.data, '$.WATCH') j WHERE h.date='2026-06-26' AND j.value IN ('KLAC','TER','UCTT','MXL','MKSI','ALGM') ORDER BY j.value;"
```

Output:

```text
2026-06-26|ALGM
2026-06-26|KLAC
2026-06-26|MKSI
2026-06-26|MXL
2026-06-26|TER
2026-06-26|UCTT
```

### Pending pullbacks evidence

```bash
sqlite3 /Users/yasser/scripts/atlas.db "SELECT ticker, status, COUNT(*) FROM pending_pullbacks WHERE ticker IN ('KLAC','TER','UCTT','MXL','MKSI','ALGM') GROUP BY ticker, status ORDER BY ticker, status;"
```

Output:

```text
ALGM|WAITING|1
MKSI|WAITING|1
```
