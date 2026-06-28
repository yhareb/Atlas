# M3 Post-Update Atlas Verification

## 1. launchctl list | grep atlas
```text
-	0	com.atlas.audit.retention
-	0	com.atlas.preopen.check
-	0	com.atlas.vaultsync
-	0	com.atlas.intraday
-	0	com.atlas.macro.premarket
1291	0	ai.hermes.gateway-atlasops
-	0	com.atlas.premarket.gaps
-	0	com.atlas.hermesgdrivebackup
1295	0	ai.hermes.gateway-atlas
-	0	com.atlas.macro.postmarket
-	0	com.atlas.premarket
-	0	com.atlas.audit.report
-	0	com.atlas.premarket.report
-	0	com.atlas.daily
```

## 2. py_compile
```text
py_compile exit=0
```

## 3. DB counts
```text
10
6566
27
```

## 4. hermes -p atlas status
```text

┌─────────────────────────────────────────────────────────┐
│                 ⚕ Hermes Agent Status                  │
└─────────────────────────────────────────────────────────┘

◆ Environment
  Project:      /Users/yasser/.hermes/hermes-agent
  Python:       3.11.15
  .env file:    ✓ exists
  Model:        gpt-5.5
  Provider:     OpenAI API

◆ API Keys
  OpenRouter    ✗ (not set)
  OpenAI        ✓ sk-p...hQoA
  Google / Gemini  ✗ (not set)
  DeepSeek      ✗ (not set)
  xAI / Grok    ✗ (not set)
  NVIDIA NIM    ✗ (not set)
  Z.AI / GLM    ✗ (not set)
  Kimi          ✗ (not set)
  StepFun Step Plan  ✗ (not set)
  MiniMax       ✗ (not set)
  MiniMax-CN    ✗ (not set)
  Firecrawl     ✗ (not set)
  Tavily        ✗ (not set)
  Browser Use   ✗ (not set)
  Browserbase   ✗ (not set)
  FAL           ✗ (not set)
  ElevenLabs    ✗ (not set)
  GitHub        ✗ (not set)
  Anthropic     ✗ (not set)

◆ Auth Providers
  Nous Portal   ✗ not logged in (run: hermes portal)
  OpenAI Codex  ✗ not logged in (run: hermes model)
    Auth file:  /Users/yasser/.hermes/profiles/atlas/auth.json
    Error:      No Codex credentials stored. Run `hermes auth` to authenticate.
  Qwen OAuth    ✗ not logged in (run: qwen auth qwen-oauth)
    Auth file:  /Users/yasser/.qwen/oauth_creds.json
    Error:      Qwen CLI credentials not found. Run 'qwen auth qwen-oauth' first.
  MiniMax OAuth  ✗ not logged in (run: hermes auth add minimax-oauth)
  xAI OAuth     ✗ not logged in (run: hermes auth add xai-oauth)
    Auth file:  /Users/yasser/.hermes/profiles/atlas/auth.json
    Error:      No xAI OAuth credentials stored. Select xAI Grok OAuth (SuperGrok / Premium+) in `hermes model`.

◆ API-Key Providers
  Z.AI / GLM       ✗ not configured (run: hermes model)
  Kimi / Moonshot  ✗ not configured (run: hermes model)
  StepFun Step Plan ✗ not configured (run: hermes model)
  MiniMax          ✗ not configured (run: hermes model)
  MiniMax (China)  ✗ not configured (run: hermes model)

◆ Terminal Backend
  Backend:      local
  Sudo:         ✗ disabled

◆ Messaging Platforms
  Telegram      ✓ configured (home: 8014591917)
  Discord       ✗ not configured
  WhatsApp      ✗ not configured
  Signal        ✗ not configured
  Slack         ✗ not configured
  Email         ✗ not configured
  SMS           ✗ not configured
  DingTalk      ✗ not configured
  Feishu        ✗ not configured
  WeCom         ✗ not configured
  WeCom Callback  ✗ not configured
  Weixin        ✗ not configured
  BlueBubbles   ✗ not configured
  QQBot         ✗ not configured
  Yuanbao       ✗ not configured

◆ Gateway Service
  Status:       ✓ running
  Manager:      launchd
  PID(s):       1295

◆ Scheduled Jobs
  Jobs:         5 active, 5 total

◆ Sessions
  Active:       1 session(s)

────────────────────────────────────────────────────────────
  Run 'hermes doctor' for detailed diagnostics
  Run 'hermes setup' to configure

```

## 5. python3 /Users/yasser/scripts/atlas_intraday.py --force --dry-run
```text
/Users/yasser/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(

[2026-06-28 21:22:30] Atlas intraday loop starting...
[intraday] market-hours gate bypassed by --force: outside market hours — weekend (Sun 2026-06-28 13:22 EDT)
[intraday] dry-run: start status telegram suppressed
[intraday] report-first mode: sector sweep peer enrichment deferred until after Telegram report
[intraday] signal high-water before scan id=6584
====================================================================
  ATLAS v2 DAILY MANAGER   2026-06-28 21:22
  Mode: DRY-RUN — no writes
====================================================================

====================================================================
  ACCOUNT
====================================================================
  Cash available : $22,472.74
  Open invested  : $6,582.61
  Realized P&L   : $9.94
  Equity (MTM)   : $29,125.74

====================================================================
  EXITS  (evaluated before any new buys)
====================================================================
  HOLD  SYNA   persisted decision stop; gain -0.44R; 2d open
  HOLD  INTC   persisted decision stop; gain -0.13R; 3d open
  HOLD  LRCX   peak +2R reached -> stop locked at +1R; gain +966.85R; 4d open

====================================================================
  REGIME GATE
====================================================================
  RISK-ON  : ⚠️ WEAK — cautious (half size); SPY 728.99 < 50SMA 734.35
  MACRO LLM: ⚠️ CAUTION: broad market/semis pressure
  MACRO    : ⚠️ Fed/CPI day — cautious (Fed Kashkari Speech, Fed Williams Speech)

====================================================================
  SCAN & ENTRIES  (94 candidates)
====================================================================
[TIMING] 2026-06-28T21:25:10 section=ticker_loop event=start candidates=94
[TIMING] 2026-06-28T21:25:10 section=pillar_checks_parallel event=start tickers=94 workers=8
[TIMING] 2026-06-28T21:25:10 section=pillar_checks event=start ticker=MU
[TIMING] 2026-06-28T21:25:10 section=pillar_checks event=start ticker=CGEM
[TIMING] 2026-06-28T21:25:10 section=pillar_checks event=start ticker=CAT
[TIMING] 2026-06-28T21:25:10 section=pillar_checks event=start ticker=ELVN
[TIMING] 2026-06-28T21:25:10 section=pillar_checks event=start ticker=EWTX
[TIMING] 2026-06-28T21:25:10 section=pillar_checks event=start ticker=AAL
[TIMING] 2026-06-28T21:25:10 section=pillar_checks event=start ticker=SLDB
[TIMING] 2026-06-28T21:25:10 section=pillar_checks event=start ticker=JNJ
[TIMING] 2026-06-28T21:25:16 section=pillar_checks event=end ticker=SLDB elapsed=5.493s
[TIMING] 2026-06-28T21:25:16 section=pillar_checks event=start ticker=AMAT
[TIMING] 2026-06-28T21:25:16 section=pillar_checks event=end ticker=MU elapsed=6.179s
[TIMING] 2026-06-28T21:25:16 section=pillar_checks event=start ticker=BAC
[TIMING] 2026-06-28T21:25:16 section=pillar_checks event=end ticker=JNJ elapsed=6.338s
[TIMING] 2026-06-28T21:25:16 section=pillar_checks event=start ticker=RL
[TIMING] 2026-06-28T21:25:17 section=pillar_checks event=end ticker=AAL elapsed=6.736s
[TIMING] 2026-06-28T21:25:17 section=pillar_checks event=start ticker=CWAN
[TIMING] 2026-06-28T21:25:22 section=pillar_checks event=end ticker=AMAT elapsed=6.267s
[TIMING] 2026-06-28T21:25:22 section=pillar_checks event=start ticker=MRK
[TIMING] 2026-06-28T21:25:22 section=pillar_checks event=end ticker=ELVN elapsed=12.314s
[TIMING] 2026-06-28T21:25:22 section=pillar_checks event=start ticker=GLW
[TIMING] 2026-06-28T21:25:23 section=pillar_checks event=end ticker=EWTX elapsed=12.654s
[TIMING] 2026-06-28T21:25:23 section=pillar_checks event=start ticker=MKSI
[TIMING] 2026-06-28T21:25:24 section=pillar_checks event=end ticker=BAC elapsed=8.140s
[TIMING] 2026-06-28T21:25:24 section=pillar_checks event=start ticker=ALGM
[TIMING] 2026-06-28T21:25:25 section=pillar_checks event=end ticker=RL elapsed=8.861s
[TIMING] 2026-06-28T21:25:25 section=pillar_checks event=start ticker=KLIC
[TIMING] 2026-06-28T21:25:26 section=pillar_checks event=end ticker=CGEM elapsed=15.717s
[TIMING] 2026-06-28T21:25:26 section=pillar_checks event=start ticker=TGT
[TIMING] 2026-06-28T21:25:27 section=pillar_checks event=end ticker=CAT elapsed=17.382s
[TIMING] 2026-06-28T21:25:27 section=pillar_checks event=start ticker=KO
[intraday] dry-run: interim telegram suppressed
[TIMING] 2026-06-28T21:25:30 section=pillar_checks event=end ticker=CWAN elapsed=13.481s
[TIMING] 2026-06-28T21:25:30 section=pillar_checks event=start ticker=SYNA
[TIMING] 2026-06-28T21:25:31 section=pillar_checks event=end ticker=MRK elapsed=9.080s
[TIMING] 2026-06-28T21:25:31 section=pillar_checks event=start ticker=INTC
[TIMING] 2026-06-28T21:25:33 section=pillar_checks event=end ticker=TGT elapsed=7.046s
[TIMING] 2026-06-28T21:25:33 section=pillar_checks event=start ticker=LRCX
[TIMING] 2026-06-28T21:25:34 section=pillar_checks event=end ticker=KLIC elapsed=8.709s
[TIMING] 2026-06-28T21:25:34 section=pillar_checks event=start ticker=AAPL
[TIMING] 2026-06-28T21:25:36 section=pillar_checks event=end ticker=ALGM elapsed=11.661s
[TIMING] 2026-06-28T21:25:36 section=pillar_checks event=start ticker=DIS
[TIMING] 2026-06-28T21:25:36 section=pillar_checks event=end ticker=INTC elapsed=5.315s
[TIMING] 2026-06-28T21:25:36 section=pillar_checks event=start ticker=TSLA
[TIMING] 2026-06-28T21:25:37 section=pillar_checks event=end ticker=MKSI elapsed=14.082s
[TIMING] 2026-06-28T21:25:37 section=pillar_checks event=start ticker=JPM
[TIMING] 2026-06-28T21:25:38 section=pillar_checks event=end ticker=GLW elapsed=15.355s
[TIMING] 2026-06-28T21:25:38 section=pillar_checks event=start ticker=STZ
[TIMING] 2026-06-28T21:25:39 section=pillar_checks event=end ticker=SYNA elapsed=8.197s
[TIMING] 2026-06-28T21:25:39 section=pillar_checks event=start ticker=NKE
[TIMING] 2026-06-28T21:25:40 section=pillar_checks event=end ticker=KO elapsed=12.361s
[TIMING] 2026-06-28T21:25:40 section=pillar_checks event=start ticker=FDS
[TIMING] 2026-06-28T21:25:41 section=pillar_checks event=end ticker=AAPL elapsed=7.157s
[TIMING] 2026-06-28T21:25:41 section=pillar_checks event=start ticker=AVAV
[TIMING] 2026-06-28T21:25:41 section=pillar_checks event=end ticker=LRCX elapsed=8.318s
[TIMING] 2026-06-28T21:25:41 section=pillar_checks event=start ticker=CULP
[TIMING] 2026-06-28T21:25:42 section=pillar_checks event=end ticker=CULP elapsed=1.052s
[TIMING] 2026-06-28T21:25:42 section=pillar_checks event=start ticker=CNVS
[TIMING] 2026-06-28T21:25:43 section=pillar_checks event=end ticker=CNVS elapsed=0.862s
[TIMING] 2026-06-28T21:25:43 section=pillar_checks event=start ticker=XAIR
[TIMING] 2026-06-28T21:25:43 section=pillar_checks event=end ticker=DIS elapsed=7.357s
[TIMING] 2026-06-28T21:25:43 section=pillar_checks event=start ticker=APOG
[TIMING] 2026-06-28T21:25:44 section=pillar_checks event=end ticker=TSLA elapsed=7.342s
[TIMING] 2026-06-28T21:25:44 section=pillar_checks event=start ticker=GBX
[TIMING] 2026-06-28T21:25:44 section=pillar_checks event=end ticker=XAIR elapsed=0.850s
[TIMING] 2026-06-28T21:25:44 section=pillar_checks event=start ticker=BSET
[TIMING] 2026-06-28T21:25:45 section=pillar_checks event=end ticker=BSET elapsed=0.842s
[TIMING] 2026-06-28T21:25:45 section=pillar_checks event=start ticker=MSM
[TIMING] 2026-06-28T21:25:45 section=pillar_checks event=end ticker=NKE elapsed=6.348s
[TIMING] 2026-06-28T21:25:45 section=pillar_checks event=start ticker=UNF
[TIMING] 2026-06-28T21:25:46 section=pillar_checks event=end ticker=STZ elapsed=7.766s
[TIMING] 2026-06-28T21:25:46 section=pillar_checks event=start ticker=GIS
[TIMING] 2026-06-28T21:25:47 section=pillar_checks event=end ticker=JPM elapsed=9.988s
[TIMING] 2026-06-28T21:25:47 section=pillar_checks event=start ticker=FC
[TIMING] 2026-06-28T21:25:48 section=pillar_checks event=end ticker=FC elapsed=1.096s
[TIMING] 2026-06-28T21:25:48 section=pillar_checks event=start ticker=PRGS
[TIMING] 2026-06-28T21:25:48 section=pillar_checks event=end ticker=FDS elapsed=8.078s
[TIMING] 2026-06-28T21:25:48 section=pillar_checks event=start ticker=CNXC
[TIMING] 2026-06-28T21:25:49 section=pillar_checks event=end ticker=GBX elapsed=5.629s
[TIMING] 2026-06-28T21:25:49 section=pillar_checks event=start ticker=NVDA
[TIMING] 2026-06-28T21:25:50 section=pillar_checks event=end ticker=APOG elapsed=6.748s
[TIMING] 2026-06-28T21:25:50 section=pillar_checks event=start ticker=GOOGL
[TIMING] 2026-06-28T21:25:50 section=pillar_checks event=end ticker=MSM elapsed=5.649s
[TIMING] 2026-06-28T21:25:50 section=pillar_checks event=start ticker=GOOG
[TIMING] 2026-06-28T21:25:51 section=pillar_checks event=end ticker=AVAV elapsed=9.426s
[TIMING] 2026-06-28T21:25:51 section=pillar_checks event=start ticker=MSFT
[TIMING] 2026-06-28T21:25:51 section=pillar_checks event=end ticker=UNF elapsed=6.282s
[TIMING] 2026-06-28T21:25:51 section=pillar_checks event=start ticker=AMZN
[TIMING] 2026-06-28T21:25:51 section=pillar_checks event=end ticker=GIS elapsed=5.784s
[TIMING] 2026-06-28T21:25:51 section=pillar_checks event=start ticker=TSM
[TIMING] 2026-06-28T21:25:53 section=pillar_checks event=end ticker=PRGS elapsed=5.554s
[TIMING] 2026-06-28T21:25:53 section=pillar_checks event=start ticker=AVGO
[TIMING] 2026-06-28T21:25:54 section=pillar_checks event=end ticker=CNXC elapsed=6.014s
[TIMING] 2026-06-28T21:25:54 section=pillar_checks event=start ticker=META
[TIMING] 2026-06-28T21:25:55 section=pillar_checks event=end ticker=NVDA elapsed=6.064s
[TIMING] 2026-06-28T21:25:55 section=pillar_checks event=start ticker=WMT
[TIMING] 2026-06-28T21:25:59 section=pillar_checks event=end ticker=GOOG elapsed=8.478s
[TIMING] 2026-06-28T21:25:59 section=pillar_checks event=start ticker=AMD
[TIMING] 2026-06-28T21:25:59 section=pillar_checks event=end ticker=AMZN elapsed=7.820s
[TIMING] 2026-06-28T21:25:59 section=pillar_checks event=start ticker=V
[TIMING] 2026-06-28T21:25:59 section=pillar_checks event=end ticker=GOOGL elapsed=9.087s
[TIMING] 2026-06-28T21:25:59 section=pillar_checks event=start ticker=XOM
[TIMING] 2026-06-28T21:26:00 section=pillar_checks event=end ticker=TSM elapsed=8.218s
[TIMING] 2026-06-28T21:26:00 section=pillar_checks event=start ticker=CSCO
[TIMING] 2026-06-28T21:26:00 section=pillar_checks event=end ticker=MSFT elapsed=9.199s
[TIMING] 2026-06-28T21:26:00 section=pillar_checks event=start ticker=ABBV
[TIMING] 2026-06-28T21:26:00 section=pillar_checks event=end ticker=AVGO elapsed=6.348s
[TIMING] 2026-06-28T21:26:00 section=pillar_checks event=start ticker=ORCL
[TIMING] 2026-06-28T21:26:00 section=pillar_checks event=end ticker=META elapsed=6.258s
[TIMING] 2026-06-28T21:26:00 section=pillar_checks event=start ticker=UNH
[TIMING] 2026-06-28T21:26:01 section=pillar_checks event=end ticker=WMT elapsed=5.854s
[TIMING] 2026-06-28T21:26:01 section=pillar_checks event=start ticker=GE
[TIMING] 2026-06-28T21:26:05 section=pillar_checks event=end ticker=AMD elapsed=6.266s
[TIMING] 2026-06-28T21:26:05 section=pillar_checks event=start ticker=ARM
[TIMING] 2026-06-28T21:26:06 section=pillar_checks event=end ticker=ORCL elapsed=5.861s
[TIMING] 2026-06-28T21:26:06 section=pillar_checks event=start ticker=PG
[TIMING] 2026-06-28T21:26:06 section=pillar_checks event=end ticker=XOM elapsed=7.030s
[TIMING] 2026-06-28T21:26:06 section=pillar_checks event=start ticker=CVX
[TIMING] 2026-06-28T21:26:08 section=pillar_checks event=end ticker=V elapsed=8.622s
[TIMING] 2026-06-28T21:26:08 section=pillar_checks event=start ticker=MIC
[TIMING] 2026-06-28T21:26:08 section=pillar_checks event=end ticker=MIC elapsed=0.847s
[TIMING] 2026-06-28T21:26:08 section=pillar_checks event=start ticker=SDOT
[TIMING] 2026-06-28T21:26:10 section=pillar_checks event=end ticker=GE elapsed=8.988s
[TIMING] 2026-06-28T21:26:10 section=pillar_checks event=start ticker=GOGL
[TIMING] 2026-06-28T21:26:11 section=pillar_checks event=end ticker=UNH elapsed=10.792s
[TIMING] 2026-06-28T21:26:11 section=pillar_checks event=start ticker=PCLA
[TIMING] 2026-06-28T21:26:11 section=pillar_checks event=end ticker=CSCO elapsed=11.458s
[TIMING] 2026-06-28T21:26:11 section=pillar_checks event=start ticker=WSHP
[TIMING] 2026-06-28T21:26:12 section=pillar_checks event=end ticker=ABBV elapsed=11.835s
[TIMING] 2026-06-28T21:26:12 section=pillar_checks event=start ticker=NVC
[TIMING] 2026-06-28T21:26:12 section=pillar_checks event=end ticker=WSHP elapsed=0.809s
[TIMING] 2026-06-28T21:26:12 section=pillar_checks event=start ticker=CDE
[TIMING] 2026-06-28T21:26:12 section=pillar_checks event=end ticker=PCLA elapsed=1.085s
[TIMING] 2026-06-28T21:26:12 section=pillar_checks event=start ticker=NOK
[TIMING] 2026-06-28T21:26:12 section=pillar_checks event=end ticker=PG elapsed=6.431s
[TIMING] 2026-06-28T21:26:12 section=pillar_checks event=start ticker=SPCX
[TIMING] 2026-06-28T21:26:13 section=pillar_checks event=end ticker=NVC elapsed=1.042s
[TIMING] 2026-06-28T21:26:13 section=pillar_checks event=start ticker=ONDS
[TIMING] 2026-06-28T21:26:13 section=pillar_checks event=end ticker=CVX elapsed=6.756s
[TIMING] 2026-06-28T21:26:13 section=pillar_checks event=start ticker=KEEL
[TIMING] 2026-06-28T21:26:14 section=pillar_checks event=end ticker=SDOT elapsed=5.938s
[TIMING] 2026-06-28T21:26:14 section=pillar_checks event=start ticker=HL
[TIMING] 2026-06-28T21:26:15 section=pillar_checks event=end ticker=ARM elapsed=10.021s
[TIMING] 2026-06-28T21:26:15 section=pillar_checks event=start ticker=SOFI
[TIMING] 2026-06-28T21:26:20 section=pillar_checks event=end ticker=ONDS elapsed=7.126s
[TIMING] 2026-06-28T21:26:20 section=pillar_checks event=start ticker=T
[TIMING] 2026-06-28T21:26:20 section=pillar_checks event=end ticker=GOGL elapsed=10.017s
[TIMING] 2026-06-28T21:26:20 section=pillar_checks event=start ticker=NWL
[TIMING] 2026-06-28T21:26:20 section=pillar_checks event=end ticker=NOK elapsed=8.118s
[TIMING] 2026-06-28T21:26:20 section=pillar_checks event=start ticker=WEN
[TIMING] 2026-06-28T21:26:20 section=pillar_checks event=end ticker=SPCX elapsed=8.331s
[TIMING] 2026-06-28T21:26:20 section=pillar_checks event=start ticker=NFLX
[TIMING] 2026-06-28T21:26:20 section=pillar_checks event=end ticker=HL elapsed=6.089s
[TIMING] 2026-06-28T21:26:20 section=pillar_checks event=start ticker=HON
[TIMING] 2026-06-28T21:26:21 section=pillar_checks event=end ticker=SOFI elapsed=5.474s
[TIMING] 2026-06-28T21:26:21 section=pillar_checks event=start ticker=DFTX
[TIMING] 2026-06-28T21:26:23 section=pillar_checks event=end ticker=KEEL elapsed=9.977s
[TIMING] 2026-06-28T21:26:23 section=pillar_checks event=start ticker=BLZE
[TIMING] 2026-06-28T21:26:24 section=pillar_checks event=end ticker=CDE elapsed=11.774s
[TIMING] 2026-06-28T21:26:24 section=pillar_checks event=start ticker=SLS
[TIMING] 2026-06-28T21:26:28 section=pillar_checks event=end ticker=NWL elapsed=8.197s
[TIMING] 2026-06-28T21:26:28 section=pillar_checks event=start ticker=LILAK
[TIMING] 2026-06-28T21:26:29 section=pillar_checks event=end ticker=T elapsed=8.799s
[TIMING] 2026-06-28T21:26:29 section=pillar_checks event=start ticker=ABSI
[TIMING] 2026-06-28T21:26:29 section=pillar_checks event=end ticker=NFLX elapsed=8.155s
[TIMING] 2026-06-28T21:26:29 section=pillar_checks event=start ticker=APGE
[TIMING] 2026-06-28T21:26:29 section=pillar_checks event=end ticker=WEN elapsed=8.814s
[TIMING] 2026-06-28T21:26:29 section=pillar_checks event=start ticker=ZURA
[TIMING] 2026-06-28T21:26:29 section=pillar_checks event=end ticker=DFTX elapsed=8.334s
[TIMING] 2026-06-28T21:26:29 section=pillar_checks event=start ticker=GRPN
[TIMING] 2026-06-28T21:26:30 section=pillar_checks event=end ticker=SLS elapsed=6.688s
[TIMING] 2026-06-28T21:26:30 section=pillar_checks event=start ticker=HELP
[TIMING] 2026-06-28T21:26:35 section=pillar_checks event=end ticker=BLZE elapsed=12.016s
[TIMING] 2026-06-28T21:26:35 section=pillar_checks event=start ticker=FCEL
[TIMING] 2026-06-28T21:26:35 section=pillar_checks event=end ticker=LILAK elapsed=7.102s
[TIMING] 2026-06-28T21:26:35 section=pillar_checks event=start ticker=LCID
[TIMING] 2026-06-28T21:26:35 section=pillar_checks event=end ticker=ZURA elapsed=6.461s
[TIMING] 2026-06-28T21:26:35 section=pillar_checks event=start ticker=ATAI
[TIMING] 2026-06-28T21:26:36 section=pillar_checks event=end ticker=GRPN elapsed=6.749s
[TIMING] 2026-06-28T21:26:36 section=pillar_checks event=start ticker=SPT
[TIMING] 2026-06-28T21:26:36 section=pillar_checks event=end ticker=HON elapsed=15.771s
[TIMING] 2026-06-28T21:26:36 section=pillar_checks event=start ticker=GENI
[TIMING] 2026-06-28T21:26:38 section=pillar_checks event=end ticker=HELP elapsed=7.799s
[TIMING] 2026-06-28T21:26:42 section=pillar_checks event=end ticker=GENI elapsed=5.535s
[TIMING] 2026-06-28T21:26:42 section=pillar_checks event=end ticker=APGE elapsed=13.759s
[TIMING] 2026-06-28T21:26:44 section=pillar_checks event=end ticker=ABSI elapsed=15.191s
[TIMING] 2026-06-28T21:26:44 section=pillar_checks event=end ticker=LCID elapsed=8.361s
[TIMING] 2026-06-28T21:26:44 section=pillar_checks event=end ticker=FCEL elapsed=8.929s
[TIMING] 2026-06-28T21:26:46 section=pillar_checks event=end ticker=ATAI elapsed=10.943s
[TIMING] 2026-06-28T21:26:46 section=pillar_checks event=end ticker=SPT elapsed=10.704s
[TIMING] 2026-06-28T21:26:46 section=pillar_checks_parallel event=end elapsed=96.365s tickers=94 workers=8
[TIMING] 2026-06-28T21:26:46 section=ticker event=start ticker=MU idx=1/94
[TIMING] 2026-06-28T21:26:46 section=pending_pullback event=start ticker=MU
[TIMING] 2026-06-28T21:26:50 section=pending_pullback event=end ticker=MU elapsed=3.757s
  ⏳ WAITING FOR PULLBACK — MU (3/4 Pillars): price $113.35 = +3.9% over 10-EMA. Limit armed at $105.80 (3-day window).
[TIMING] 2026-06-28T21:26:50 section=ticker event=start ticker=CGEM idx=2/94
[TIMING] 2026-06-28T21:26:50 section=pending_pullback event=start ticker=CGEM
[TIMING] 2026-06-28T21:26:53 section=pending_pullback event=end ticker=CGEM elapsed=3.276s
  ⏳ WAITING FOR PULLBACK — CGEM (3/4 Pillars): price $18.04 = +8.9% over 10-EMA. Limit armed at $15.20 (3-day window).
[TIMING] 2026-06-28T21:26:54 section=ticker event=start ticker=CAT idx=3/94
[TIMING] 2026-06-28T21:26:54 section=pending_pullback event=start ticker=CAT
[TIMING] 2026-06-28T21:26:57 section=pending_pullback event=end ticker=CAT elapsed=3.722s
  ⏳ WAITING FOR PULLBACK — CAT (3/4 Pillars): price $999.81 = +1.7% over 10-EMA. Limit armed at $961.93 (3-day window).
[TIMING] 2026-06-28T21:26:57 section=ticker event=start ticker=ELVN idx=4/94
[TIMING] 2026-06-28T21:26:57 section=pending_pullback event=start ticker=ELVN
[TIMING] 2026-06-28T21:27:01 section=pending_pullback event=end ticker=ELVN elapsed=3.528s
  ⏳ WAITING FOR PULLBACK — ELVN (3/4 Pillars): price $50.00 = +8.4% over 10-EMA. Limit armed at $44.79 (3-day window).
[TIMING] 2026-06-28T21:27:01 section=ticker event=start ticker=EWTX idx=5/94
[TIMING] 2026-06-28T21:27:01 section=pending_pullback event=start ticker=EWTX
[TIMING] 2026-06-28T21:27:03 section=pending_pullback event=end ticker=EWTX elapsed=1.863s
  ⏳ WAITING FOR PULLBACK — EWTX (3/4 Pillars): price $41.46 = +7.5% over 10-EMA. Limit armed at $36.84 (3-day window).
[TIMING] 2026-06-28T21:27:03 section=ticker event=start ticker=AAL idx=6/94
[TIMING] 2026-06-28T21:27:03 section=pending_pullback event=start ticker=AAL
[TIMING] 2026-06-28T21:27:05 section=pending_pullback event=end ticker=AAL elapsed=1.861s
  ⏳ WAITING FOR PULLBACK — AAL (3/4 Pillars): price $17.85 = +8.9% over 10-EMA. Limit armed at $15.79 (3-day window).
[TIMING] 2026-06-28T21:27:05 section=ticker event=start ticker=SLDB idx=7/94
[TIMING] 2026-06-28T21:27:05 section=pending_pullback event=start ticker=SLDB
[TIMING] 2026-06-28T21:27:06 section=pending_pullback event=end ticker=SLDB elapsed=1.883s
  ⏳ WAITING FOR PULLBACK — SLDB (3/4 Pillars): price $9.29 = +11.2% over 10-EMA. Limit armed at $8.01 (3-day window).
[TIMING] 2026-06-28T21:27:06 section=ticker event=start ticker=JNJ idx=8/94
[TIMING] 2026-06-28T21:27:06 section=pending_pullback event=start ticker=JNJ
[TIMING] 2026-06-28T21:27:10 section=pending_pullback event=end ticker=JNJ elapsed=3.359s
  ⏳ WAITING FOR PULLBACK — JNJ (3/4 Pillars): price $254.61 = +5.9% over 10-EMA. Limit armed at $238.39 (3-day window).
[TIMING] 2026-06-28T21:27:10 section=ticker event=start ticker=AMAT idx=9/94
[TIMING] 2026-06-28T21:27:10 section=pending_pullback event=start ticker=AMAT
[TIMING] 2026-06-28T21:27:14 section=pending_pullback event=end ticker=AMAT elapsed=4.012s
  ⏳ WAITING FOR PULLBACK — AMAT (3/4 Pillars): price $627.25 = +4.7% over 10-EMA. Limit armed at $587.24 (3-day window).
[TIMING] 2026-06-28T21:27:14 section=ticker event=start ticker=BAC idx=10/94
[TIMING] 2026-06-28T21:27:14 section=pending_pullback event=start ticker=BAC
[TIMING] 2026-06-28T21:27:19 section=pending_pullback event=end ticker=BAC elapsed=4.754s
  ⏳ WAITING FOR PULLBACK — BAC (3/4 Pillars): price $57.93 = +1.7% over 10-EMA. Limit armed at $57.02 (3-day window).
[TIMING] 2026-06-28T21:27:19 section=ticker event=start ticker=RL idx=11/94
[TIMING] 2026-06-28T21:27:19 section=pending_pullback event=start ticker=RL
[TIMING] 2026-06-28T21:27:23 section=pending_pullback event=end ticker=RL elapsed=4.023s
  ⏳ WAITING FOR PULLBACK — RL (3/4 Pillars): price $411.16 = +1.4% over 10-EMA. Limit armed at $407.11 (3-day window).
[TIMING] 2026-06-28T21:27:23 section=ticker event=start ticker=CWAN idx=12/94
[TIMING] 2026-06-28T21:27:23 section=pending_pullback event=start ticker=CWAN
[TIMING] 2026-06-28T21:27:27 section=pending_pullback event=end ticker=CWAN elapsed=4.011s
  ⏳ WAITING FOR PULLBACK — CWAN (3/4 Pillars): price $24.55 = +0.5% over 10-EMA. Limit armed at $24.54 (3-day window).
[TIMING] 2026-06-28T21:27:27 section=ticker event=start ticker=MRK idx=13/94
[TIMING] 2026-06-28T21:27:27 section=pending_pullback event=start ticker=MRK
[TIMING] 2026-06-28T21:27:30 section=pending_pullback event=end ticker=MRK elapsed=3.723s
  ⏳ WAITING FOR PULLBACK — MRK (3/4 Pillars): price $127.53 = +5.6% over 10-EMA. Limit armed at $119.39 (3-day window).
[TIMING] 2026-06-28T21:27:30 section=ticker event=start ticker=GLW idx=14/94
[TIMING] 2026-06-28T21:27:30 section=pending_pullback event=start ticker=GLW
[TIMING] 2026-06-28T21:27:35 section=pending_pullback event=end ticker=GLW elapsed=4.598s
  ⏳ WAITING FOR PULLBACK — GLW (3/4 Pillars): price $220.28 = +8.7% over 10-EMA. Limit armed at $199.06 (3-day window).
[TIMING] 2026-06-28T21:27:35 section=ticker event=start ticker=MKSI idx=15/94
[TIMING] 2026-06-28T21:27:35 section=pending_pullback event=start ticker=MKSI
[TIMING] 2026-06-28T21:27:39 section=pending_pullback event=end ticker=MKSI elapsed=3.918s
  ⏳ WAITING FOR PULLBACK — MKSI (4/4 Pillars): price $388.61 = +1.6% over 10-EMA. Limit armed at $381.34 (3-day window).
[TIMING] 2026-06-28T21:27:39 section=ticker event=start ticker=ALGM idx=16/94
[TIMING] 2026-06-28T21:27:39 section=pending_pullback event=start ticker=ALGM
[TIMING] 2026-06-28T21:27:43 section=pending_pullback event=end ticker=ALGM elapsed=3.760s
  ⏳ WAITING FOR PULLBACK — ALGM (3/4 Pillars): price $56.82 = +1.5% over 10-EMA. Limit armed at $55.54 (3-day window).
[TIMING] 2026-06-28T21:27:43 section=ticker event=start ticker=KLIC idx=17/94
[TIMING] 2026-06-28T21:27:43 section=pending_pullback event=start ticker=KLIC
[TIMING] 2026-06-28T21:27:47 section=pending_pullback event=end ticker=KLIC elapsed=3.934s
  ⏳ WAITING FOR PULLBACK — KLIC (4/4 Pillars): price $121.01 = +-0.4% over 10-EMA. Limit armed at $120.68 (3-day window).
[TIMING] 2026-06-28T21:27:47 section=ticker event=start ticker=TGT idx=18/94
[TIMING] 2026-06-28T21:27:47 section=pending_pullback event=start ticker=TGT
[TIMING] 2026-06-28T21:27:50 section=pending_pullback event=end ticker=TGT elapsed=3.418s
  ⏳ WAITING FOR PULLBACK — TGT (3/4 Pillars): price $140.21 = +3.9% over 10-EMA. Limit armed at $135.72 (3-day window).
[TIMING] 2026-06-28T21:27:50 section=ticker event=start ticker=KO idx=19/94
[TIMING] 2026-06-28T21:27:50 section=pending_pullback event=start ticker=KO
[TIMING] 2026-06-28T21:27:54 section=pending_pullback event=end ticker=KO elapsed=3.708s
  ⏳ WAITING FOR PULLBACK — KO (3/4 Pillars): price $82.43 = +2.0% over 10-EMA. Limit armed at $81.19 (3-day window).
[TIMING] 2026-06-28T21:27:54 section=ticker event=start ticker=SYNA idx=20/94
[TIMING] 2026-06-28T21:27:54 section=pending_pullback event=start ticker=SYNA
[TIMING] 2026-06-28T21:27:54 section=pending_pullback event=end ticker=SYNA elapsed=0.001s
[TIMING] 2026-06-28T21:27:54 section=analyst_ratings_check event=start ticker=SYNA
[TIMING] 2026-06-28T21:27:54 section=analyst_ratings_check event=end ticker=SYNA elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:27:54 section=news_catalyst_check event=start ticker=SYNA
[TIMING] 2026-06-28T21:27:54 section=news_catalyst_check event=end ticker=SYNA elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:27:54 section=sector_sweep_trigger event=start ticker=SYNA
[TIMING] 2026-06-28T21:27:54 section=sector_sweep_trigger event=end ticker=SYNA elapsed=0.000s peers=0
  block SYNA   (3/4 Pillars) Already holding SYNA
[TIMING] 2026-06-28T21:27:54 section=ticker event=start ticker=INTC idx=21/94
[TIMING] 2026-06-28T21:27:54 section=pending_pullback event=start ticker=INTC
[TIMING] 2026-06-28T21:27:54 section=pending_pullback event=end ticker=INTC elapsed=0.001s
[TIMING] 2026-06-28T21:27:54 section=analyst_ratings_check event=start ticker=INTC
[TIMING] 2026-06-28T21:27:54 section=analyst_ratings_check event=end ticker=INTC elapsed=0.000s rating={'firm': 'Goldman Sachs', 'analyst': 'James Schneider', 'benzinga_analyst_id': '586e48c7351b9b00018beef7', 'benzinga_firm_id': '57f832a96b87f600016fa34f', 'rating': 'neutral', 'rating_action': 'initiates_coverage_on', 'price_target': 150.0, 'adjusted_price_target': 150.0, 'previous_price_target': None, 'price_percent_change': None, 'date': '2026-06-25', 'pt_raised': False, 'analyst_quality': {'benzinga_firm_id': '57f832a96b87f600016fa34f', 'benzinga_id': '586e48c7351b9b00018beef7', 'firm_match': True, 'firm_name': 'Goldman Sachs', 'full_name': 'James Schneider', 'overall_avg_return': 61.03, 'overall_success_rate': 53.01, 'smart_score': 76.01, 'summary': None, 'top_analyst': False, 'total_ratings': 83.0}, 'top_analyst_backed': False, 'note': 'Initiates Coverage On by Goldman Sachs → PT $150'}
[TIMING] 2026-06-28T21:27:54 section=news_catalyst_check event=start ticker=INTC
[TIMING] 2026-06-28T21:27:54 section=news_catalyst_check event=end ticker=INTC elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:27:54 section=sector_sweep_trigger event=start ticker=INTC
[TIMING] 2026-06-28T21:27:54 section=sector_sweep_trigger event=end ticker=INTC elapsed=0.000s peers=0
  skip  INTC   ⚪ WATCH  (2/4 Pillars)
[TIMING] 2026-06-28T21:27:54 section=ticker event=start ticker=LRCX idx=22/94
[TIMING] 2026-06-28T21:27:54 section=pending_pullback event=start ticker=LRCX
[TIMING] 2026-06-28T21:27:54 section=pending_pullback event=end ticker=LRCX elapsed=0.001s
[TIMING] 2026-06-28T21:27:54 section=analyst_ratings_check event=start ticker=LRCX
[TIMING] 2026-06-28T21:27:54 section=analyst_ratings_check event=end ticker=LRCX elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:27:54 section=news_catalyst_check event=start ticker=LRCX
[TIMING] 2026-06-28T21:27:54 section=news_catalyst_check event=end ticker=LRCX elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:27:54 section=sector_sweep_trigger event=start ticker=LRCX
[TIMING] 2026-06-28T21:27:54 section=sector_sweep_trigger event=end ticker=LRCX elapsed=0.000s peers=0
  skip  LRCX   ⚪ WATCH  (2/4 Pillars)
[TIMING] 2026-06-28T21:27:54 section=ticker event=start ticker=AAPL idx=23/94
[TIMING] 2026-06-28T21:27:54 section=pending_pullback event=start ticker=AAPL
[TIMING] 2026-06-28T21:27:54 section=pending_pullback event=end ticker=AAPL elapsed=0.001s
[TIMING] 2026-06-28T21:27:54 section=analyst_ratings_check event=start ticker=AAPL
[TIMING] 2026-06-28T21:27:54 section=analyst_ratings_check event=end ticker=AAPL elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:27:54 section=news_catalyst_check event=start ticker=AAPL
[TIMING] 2026-06-28T21:27:54 section=news_catalyst_check event=end ticker=AAPL elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:27:54 section=sector_sweep_trigger event=start ticker=AAPL
[TIMING] 2026-06-28T21:27:54 section=sector_sweep_trigger event=end ticker=AAPL elapsed=0.000s peers=0
  skip  AAPL   🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:27:54 section=ticker event=start ticker=DIS idx=24/94
[TIMING] 2026-06-28T21:27:54 section=pending_pullback event=start ticker=DIS
[TIMING] 2026-06-28T21:27:54 section=pending_pullback event=end ticker=DIS elapsed=0.001s
[TIMING] 2026-06-28T21:27:54 section=analyst_ratings_check event=start ticker=DIS
[TIMING] 2026-06-28T21:27:54 section=analyst_ratings_check event=end ticker=DIS elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:27:54 section=news_catalyst_check event=start ticker=DIS
[TIMING] 2026-06-28T21:27:54 section=news_catalyst_check event=end ticker=DIS elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:27:54 section=sector_sweep_trigger event=start ticker=DIS
[TIMING] 2026-06-28T21:27:54 section=sector_sweep_trigger event=end ticker=DIS elapsed=0.000s peers=0
  skip  DIS    🔴 AVOID  (0/4 Pillars)
[TIMING] 2026-06-28T21:27:54 section=ticker event=start ticker=TSLA idx=25/94
[TIMING] 2026-06-28T21:27:54 section=pending_pullback event=start ticker=TSLA
[TIMING] 2026-06-28T21:27:54 section=pending_pullback event=end ticker=TSLA elapsed=0.001s
[TIMING] 2026-06-28T21:27:54 section=analyst_ratings_check event=start ticker=TSLA
[TIMING] 2026-06-28T21:27:54 section=analyst_ratings_check event=end ticker=TSLA elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:27:54 section=news_catalyst_check event=start ticker=TSLA
[TIMING] 2026-06-28T21:27:54 section=news_catalyst_check event=end ticker=TSLA elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:27:54 section=sector_sweep_trigger event=start ticker=TSLA
[TIMING] 2026-06-28T21:27:54 section=sector_sweep_trigger event=end ticker=TSLA elapsed=0.000s peers=0
  skip  TSLA   🔴 AVOID  (0/4 Pillars)
[TIMING] 2026-06-28T21:27:54 section=ticker event=start ticker=JPM idx=26/94
[TIMING] 2026-06-28T21:27:54 section=pending_pullback event=start ticker=JPM
[TIMING] 2026-06-28T21:27:54 section=pending_pullback event=end ticker=JPM elapsed=0.001s
[TIMING] 2026-06-28T21:27:54 section=analyst_ratings_check event=start ticker=JPM
[TIMING] 2026-06-28T21:27:54 section=analyst_ratings_check event=end ticker=JPM elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:27:54 section=news_catalyst_check event=start ticker=JPM
[TIMING] 2026-06-28T21:27:54 section=news_catalyst_check event=end ticker=JPM elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:27:54 section=sector_sweep_trigger event=start ticker=JPM
[TIMING] 2026-06-28T21:27:54 section=sector_sweep_trigger event=end ticker=JPM elapsed=0.000s peers=0
[TIMING] 2026-06-28T21:28:01 section=live_price_fetch event=start ticker=JPM
[TIMING] 2026-06-28T21:28:01 section=live_price_fetch event=end ticker=JPM elapsed=0.000s price=yes
  BUY   JPM    12 sh @ 329.17 (stop 317.21, 0.5% risk, $3,950) — Pulled back to 10-EMA 327.89 (close 329.17)
[TIMING] 2026-06-28T21:28:01 section=ticker event=start ticker=STZ idx=27/94
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=start ticker=STZ
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=end ticker=STZ elapsed=0.001s
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=start ticker=STZ
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=end ticker=STZ elapsed=0.000s rating={'firm': 'TD Cowen', 'analyst': 'Seamus Cassidy', 'benzinga_analyst_id': '6a3eb415f11bb700014a9611', 'benzinga_firm_id': '57f832aa6b87f600016fa359', 'rating': 'buy', 'rating_action': 'assumes', 'price_target': 174.0, 'adjusted_price_target': 174.0, 'previous_price_target': None, 'price_percent_change': None, 'date': '2026-06-26', 'pt_raised': False, 'analyst_quality': None, 'top_analyst_backed': False, 'note': 'Assumes by TD Cowen → PT $174'}
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=start ticker=STZ
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=end ticker=STZ elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=start ticker=STZ
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=end ticker=STZ elapsed=0.000s peers=0
  skip  STZ    🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:01 section=ticker event=start ticker=NKE idx=28/94
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=start ticker=NKE
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=end ticker=NKE elapsed=0.001s
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=start ticker=NKE
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=end ticker=NKE elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=start ticker=NKE
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=end ticker=NKE elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=start ticker=NKE
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=end ticker=NKE elapsed=0.000s peers=0
  skip  NKE    🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:01 section=ticker event=start ticker=FDS idx=29/94
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=start ticker=FDS
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=end ticker=FDS elapsed=0.001s
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=start ticker=FDS
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=end ticker=FDS elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=start ticker=FDS
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=end ticker=FDS elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=start ticker=FDS
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=end ticker=FDS elapsed=0.000s peers=0
  skip  FDS    ⚪ WATCH  (2/4 Pillars)
[TIMING] 2026-06-28T21:28:01 section=ticker event=start ticker=AVAV idx=30/94
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=start ticker=AVAV
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=end ticker=AVAV elapsed=0.001s
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=start ticker=AVAV
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=end ticker=AVAV elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=start ticker=AVAV
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=end ticker=AVAV elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=start ticker=AVAV
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=end ticker=AVAV elapsed=0.000s peers=0
  skip  AVAV   🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:01 section=ticker event=start ticker=CULP idx=31/94
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=start ticker=CULP
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=end ticker=CULP elapsed=0.001s
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=start ticker=CULP
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=end ticker=CULP elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=start ticker=CULP
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=end ticker=CULP elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=start ticker=CULP
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=end ticker=CULP elapsed=0.000s peers=0
  skip  CULP     (0)
[TIMING] 2026-06-28T21:28:01 section=ticker event=start ticker=CNVS idx=32/94
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=start ticker=CNVS
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=end ticker=CNVS elapsed=0.001s
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=start ticker=CNVS
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=end ticker=CNVS elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=start ticker=CNVS
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=end ticker=CNVS elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=start ticker=CNVS
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=end ticker=CNVS elapsed=0.000s peers=0
  skip  CNVS     (0)
[TIMING] 2026-06-28T21:28:01 section=ticker event=start ticker=XAIR idx=33/94
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=start ticker=XAIR
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=end ticker=XAIR elapsed=0.001s
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=start ticker=XAIR
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=end ticker=XAIR elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=start ticker=XAIR
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=end ticker=XAIR elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=start ticker=XAIR
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=end ticker=XAIR elapsed=0.000s peers=0
  skip  XAIR     (0)
[TIMING] 2026-06-28T21:28:01 section=ticker event=start ticker=APOG idx=34/94
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=start ticker=APOG
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=end ticker=APOG elapsed=0.001s
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=start ticker=APOG
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=end ticker=APOG elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=start ticker=APOG
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=end ticker=APOG elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=start ticker=APOG
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=end ticker=APOG elapsed=0.000s peers=0
  block APOG   (2/4 Pillars) ⛔ EARNINGS in 0d — no new entry
[TIMING] 2026-06-28T21:28:01 section=ticker event=start ticker=GBX idx=35/94
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=start ticker=GBX
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=end ticker=GBX elapsed=0.001s
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=start ticker=GBX
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=end ticker=GBX elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=start ticker=GBX
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=end ticker=GBX elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=start ticker=GBX
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=end ticker=GBX elapsed=0.000s peers=0
  skip  GBX    🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:01 section=ticker event=start ticker=BSET idx=36/94
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=start ticker=BSET
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=end ticker=BSET elapsed=0.001s
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=start ticker=BSET
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=end ticker=BSET elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=start ticker=BSET
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=end ticker=BSET elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=start ticker=BSET
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=end ticker=BSET elapsed=0.000s peers=0
  skip  BSET     (0)
[TIMING] 2026-06-28T21:28:01 section=ticker event=start ticker=MSM idx=37/94
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=start ticker=MSM
[TIMING] 2026-06-28T21:28:01 section=pending_pullback event=end ticker=MSM elapsed=0.001s
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=start ticker=MSM
[TIMING] 2026-06-28T21:28:01 section=analyst_ratings_check event=end ticker=MSM elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=start ticker=MSM
[TIMING] 2026-06-28T21:28:01 section=news_catalyst_check event=end ticker=MSM elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=start ticker=MSM
[TIMING] 2026-06-28T21:28:01 section=sector_sweep_trigger event=end ticker=MSM elapsed=0.000s peers=0
[TIMING] 2026-06-28T21:28:04 section=live_price_fetch event=start ticker=MSM
[TIMING] 2026-06-28T21:28:04 section=live_price_fetch event=end ticker=MSM elapsed=0.000s price=yes
  BUY   MSM    31 sh @ 118.18 (stop 113.61, 0.5% risk, $3,664) — Pulled back to 10-EMA 117.02 (close 118.18)
[TIMING] 2026-06-28T21:28:04 section=ticker event=start ticker=UNF idx=38/94
[TIMING] 2026-06-28T21:28:04 section=pending_pullback event=start ticker=UNF
[TIMING] 2026-06-28T21:28:04 section=pending_pullback event=end ticker=UNF elapsed=0.001s
[TIMING] 2026-06-28T21:28:04 section=analyst_ratings_check event=start ticker=UNF
[TIMING] 2026-06-28T21:28:04 section=analyst_ratings_check event=end ticker=UNF elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:04 section=news_catalyst_check event=start ticker=UNF
[TIMING] 2026-06-28T21:28:04 section=news_catalyst_check event=end ticker=UNF elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:04 section=sector_sweep_trigger event=start ticker=UNF
[TIMING] 2026-06-28T21:28:04 section=sector_sweep_trigger event=end ticker=UNF elapsed=0.000s peers=0
[TIMING] 2026-06-28T21:28:07 section=live_price_fetch event=start ticker=UNF
[TIMING] 2026-06-28T21:28:07 section=live_price_fetch event=end ticker=UNF elapsed=0.000s price=yes
  BUY   UNF    15 sh @ 266.07 (stop 256.51, 0.5% risk, $3,991) — Pulled back to 10-EMA 263.98 (close 266.07)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=GIS idx=39/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=GIS
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=GIS elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=GIS
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=GIS elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=GIS
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=GIS elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=GIS
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=GIS elapsed=0.000s peers=0
  skip  GIS    🔴 AVOID  (0/4 Pillars)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=FC idx=40/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=FC
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=FC elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=FC
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=FC elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=FC
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=FC elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=FC
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=FC elapsed=0.000s peers=0
  skip  FC       (0)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=PRGS idx=41/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=PRGS
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=PRGS elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=PRGS
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=PRGS elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=PRGS
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=PRGS elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=PRGS
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=PRGS elapsed=0.000s peers=0
  skip  PRGS   🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=CNXC idx=42/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=CNXC
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=CNXC elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=CNXC
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=CNXC elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=CNXC
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=CNXC elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=CNXC
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=CNXC elapsed=0.000s peers=0
  skip  CNXC   🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=NVDA idx=43/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=NVDA
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=NVDA elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=NVDA
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=NVDA elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=NVDA
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=NVDA elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=NVDA
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=NVDA elapsed=0.000s peers=0
  skip  NVDA   🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=GOOGL idx=44/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=GOOGL
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=GOOGL elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=GOOGL
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=GOOGL elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=GOOGL
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=GOOGL elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=GOOGL
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=GOOGL elapsed=0.000s peers=0
  skip  GOOGL  🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=GOOG idx=45/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=GOOG
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=GOOG elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=GOOG
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=GOOG elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=GOOG
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=GOOG elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=GOOG
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=GOOG elapsed=0.000s peers=0
  skip  GOOG   🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=MSFT idx=46/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=MSFT
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=MSFT elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=MSFT
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=MSFT elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=MSFT
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=MSFT elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=MSFT
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=MSFT elapsed=0.000s peers=0
  skip  MSFT   🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=AMZN idx=47/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=AMZN
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=AMZN elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=AMZN
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=AMZN elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=AMZN
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=AMZN elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=AMZN
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=AMZN elapsed=0.000s peers=0
  skip  AMZN   🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=TSM idx=48/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=TSM
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=TSM elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=TSM
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=TSM elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=TSM
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=TSM elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=TSM
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=TSM elapsed=0.000s peers=0
  skip  TSM    ⚪ WATCH  (2/4 Pillars)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=AVGO idx=49/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=AVGO
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=AVGO elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=AVGO
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=AVGO elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=AVGO
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=AVGO elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=AVGO
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=AVGO elapsed=0.000s peers=0
  skip  AVGO   🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=META idx=50/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=META
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=META elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=META
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=META elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=META
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=META elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=META
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=META elapsed=0.000s peers=0
  skip  META   🔴 AVOID  (0/4 Pillars)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=WMT idx=51/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=WMT
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=WMT elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=WMT
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=WMT elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=WMT
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=WMT elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=WMT
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=WMT elapsed=0.000s peers=0
  skip  WMT    ⚪ WATCH  (2/4 Pillars)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=AMD idx=52/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=AMD
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=AMD elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=AMD
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=AMD elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=AMD
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=AMD elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=AMD
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=AMD elapsed=0.000s peers=0
  skip  AMD    🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=V idx=53/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=V
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=V elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=V
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=V elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=V
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=V elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=V
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=V elapsed=0.000s peers=0
  skip  V      🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=XOM idx=54/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=XOM
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=XOM elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=XOM
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=XOM elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=XOM
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=XOM elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=XOM
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=XOM elapsed=0.000s peers=0
  skip  XOM    🔴 AVOID  (0/4 Pillars)
[TIMING] 2026-06-28T21:28:07 section=ticker event=start ticker=CSCO idx=55/94
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=start ticker=CSCO
[TIMING] 2026-06-28T21:28:07 section=pending_pullback event=end ticker=CSCO elapsed=0.001s
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=start ticker=CSCO
[TIMING] 2026-06-28T21:28:07 section=analyst_ratings_check event=end ticker=CSCO elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=start ticker=CSCO
[TIMING] 2026-06-28T21:28:07 section=news_catalyst_check event=end ticker=CSCO elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=start ticker=CSCO
[TIMING] 2026-06-28T21:28:07 section=sector_sweep_trigger event=end ticker=CSCO elapsed=0.000s peers=0
[TIMING] 2026-06-28T21:28:10 section=live_price_fetch event=start ticker=CSCO
[TIMING] 2026-06-28T21:28:10 section=live_price_fetch event=end ticker=CSCO elapsed=0.000s price=yes
  BUY   CSCO   25 sh @ 113.6 (stop 107.84, 0.5% risk, $2,840) — Pulled back to 10-EMA 118.97 (close 113.60)
[TIMING] 2026-06-28T21:28:10 section=ticker event=start ticker=ABBV idx=56/94
[TIMING] 2026-06-28T21:28:10 section=pending_pullback event=start ticker=ABBV
[TIMING] 2026-06-28T21:28:10 section=pending_pullback event=end ticker=ABBV elapsed=0.001s
[TIMING] 2026-06-28T21:28:10 section=analyst_ratings_check event=start ticker=ABBV
[TIMING] 2026-06-28T21:28:10 section=analyst_ratings_check event=end ticker=ABBV elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:10 section=news_catalyst_check event=start ticker=ABBV
[TIMING] 2026-06-28T21:28:10 section=news_catalyst_check event=end ticker=ABBV elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:10 section=sector_sweep_trigger event=start ticker=ABBV
[TIMING] 2026-06-28T21:28:10 section=sector_sweep_trigger event=end ticker=ABBV elapsed=0.000s peers=0
[TIMING] 2026-06-28T21:28:15 section=live_price_fetch event=start ticker=ABBV
[TIMING] 2026-06-28T21:28:15 section=live_price_fetch event=end ticker=ABBV elapsed=0.000s price=yes
  BUY   ABBV   16 sh @ 253.0 (stop 243.97, 0.5% risk, $4,048) — Gap-Up Breakout Entry: gap +4.1%, volume 8.9x 30D, sentiment +0.97; opening-range stop below $245.20
[TIMING] 2026-06-28T21:28:15 section=ticker event=start ticker=ORCL idx=57/94
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=start ticker=ORCL
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=end ticker=ORCL elapsed=0.001s
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=start ticker=ORCL
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=end ticker=ORCL elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=start ticker=ORCL
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=end ticker=ORCL elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=start ticker=ORCL
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=end ticker=ORCL elapsed=0.000s peers=0
  skip  ORCL   🔴 AVOID  (0/4 Pillars)
[TIMING] 2026-06-28T21:28:15 section=ticker event=start ticker=UNH idx=58/94
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=start ticker=UNH
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=end ticker=UNH elapsed=0.001s
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=start ticker=UNH
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=end ticker=UNH elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=start ticker=UNH
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=end ticker=UNH elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=start ticker=UNH
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=end ticker=UNH elapsed=0.000s peers=0
  skip  UNH    ⚪ WATCH  (2/4 Pillars)
[TIMING] 2026-06-28T21:28:15 section=ticker event=start ticker=GE idx=59/94
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=start ticker=GE
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=end ticker=GE elapsed=0.001s
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=start ticker=GE
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=end ticker=GE elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=start ticker=GE
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=end ticker=GE elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=start ticker=GE
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=end ticker=GE elapsed=0.000s peers=0
  skip  GE     ⚪ WATCH  (2/4 Pillars)
[TIMING] 2026-06-28T21:28:15 section=ticker event=start ticker=ARM idx=60/94
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=start ticker=ARM
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=end ticker=ARM elapsed=0.001s
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=start ticker=ARM
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=end ticker=ARM elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=start ticker=ARM
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=end ticker=ARM elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=start ticker=ARM
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=end ticker=ARM elapsed=0.000s peers=0
  skip  ARM    ⚪ WATCH  (2/4 Pillars)
[TIMING] 2026-06-28T21:28:15 section=ticker event=start ticker=PG idx=61/94
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=start ticker=PG
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=end ticker=PG elapsed=0.001s
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=start ticker=PG
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=end ticker=PG elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=start ticker=PG
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=end ticker=PG elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=start ticker=PG
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=end ticker=PG elapsed=0.000s peers=0
  skip  PG     🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:15 section=ticker event=start ticker=CVX idx=62/94
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=start ticker=CVX
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=end ticker=CVX elapsed=0.001s
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=start ticker=CVX
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=end ticker=CVX elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=start ticker=CVX
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=end ticker=CVX elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=start ticker=CVX
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=end ticker=CVX elapsed=0.000s peers=0
  skip  CVX    🔴 AVOID  (0/4 Pillars)
[TIMING] 2026-06-28T21:28:15 section=ticker event=start ticker=MIC idx=63/94
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=start ticker=MIC
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=end ticker=MIC elapsed=0.001s
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=start ticker=MIC
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=end ticker=MIC elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=start ticker=MIC
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=end ticker=MIC elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=start ticker=MIC
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=end ticker=MIC elapsed=0.000s peers=0
  skip  MIC      (0)
[TIMING] 2026-06-28T21:28:15 section=ticker event=start ticker=SDOT idx=64/94
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=start ticker=SDOT
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=end ticker=SDOT elapsed=0.001s
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=start ticker=SDOT
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=end ticker=SDOT elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=start ticker=SDOT
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=end ticker=SDOT elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=start ticker=SDOT
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=end ticker=SDOT elapsed=0.000s peers=0
  skip  SDOT   ⚪ WATCH  (2/4 Pillars)
[TIMING] 2026-06-28T21:28:15 section=ticker event=start ticker=GOGL idx=65/94
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=start ticker=GOGL
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=end ticker=GOGL elapsed=0.001s
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=start ticker=GOGL
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=end ticker=GOGL elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=start ticker=GOGL
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=end ticker=GOGL elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=start ticker=GOGL
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=end ticker=GOGL elapsed=0.000s peers=0
  skip  GOGL   🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:15 section=ticker event=start ticker=PCLA idx=66/94
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=start ticker=PCLA
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=end ticker=PCLA elapsed=0.001s
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=start ticker=PCLA
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=end ticker=PCLA elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=start ticker=PCLA
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=end ticker=PCLA elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=start ticker=PCLA
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=end ticker=PCLA elapsed=0.000s peers=0
  skip  PCLA     (0)
[TIMING] 2026-06-28T21:28:15 section=ticker event=start ticker=WSHP idx=67/94
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=start ticker=WSHP
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=end ticker=WSHP elapsed=0.001s
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=start ticker=WSHP
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=end ticker=WSHP elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=start ticker=WSHP
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=end ticker=WSHP elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=start ticker=WSHP
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=end ticker=WSHP elapsed=0.000s peers=0
  skip  WSHP     (0)
[TIMING] 2026-06-28T21:28:15 section=ticker event=start ticker=NVC idx=68/94
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=start ticker=NVC
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=end ticker=NVC elapsed=0.001s
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=start ticker=NVC
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=end ticker=NVC elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=start ticker=NVC
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=end ticker=NVC elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=start ticker=NVC
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=end ticker=NVC elapsed=0.000s peers=0
  skip  NVC      (0)
[TIMING] 2026-06-28T21:28:15 section=ticker event=start ticker=CDE idx=69/94
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=start ticker=CDE
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=end ticker=CDE elapsed=0.001s
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=start ticker=CDE
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=end ticker=CDE elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=start ticker=CDE
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=end ticker=CDE elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=start ticker=CDE
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=end ticker=CDE elapsed=0.000s peers=0
  skip  CDE    ⚪ WATCH  (2/4 Pillars)
[TIMING] 2026-06-28T21:28:15 section=ticker event=start ticker=NOK idx=70/94
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=start ticker=NOK
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=end ticker=NOK elapsed=0.001s
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=start ticker=NOK
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=end ticker=NOK elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=start ticker=NOK
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=end ticker=NOK elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=start ticker=NOK
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=end ticker=NOK elapsed=0.000s peers=0
  skip  NOK    🔴 AVOID  (0/4 Pillars)
[TIMING] 2026-06-28T21:28:15 section=ticker event=start ticker=SPCX idx=71/94
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=start ticker=SPCX
[TIMING] 2026-06-28T21:28:15 section=pending_pullback event=end ticker=SPCX elapsed=0.001s
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=start ticker=SPCX
[TIMING] 2026-06-28T21:28:15 section=analyst_ratings_check event=end ticker=SPCX elapsed=0.000s rating={'firm': 'Argus Research', 'analyst': '', 'benzinga_analyst_id': '', 'benzinga_firm_id': '57f832aa6b87f600016fa36a', 'rating': 'hold', 'rating_action': 'initiates_coverage_on', 'price_target': None, 'adjusted_price_target': None, 'previous_price_target': None, 'price_percent_change': None, 'date': '2026-06-26', 'pt_raised': False, 'analyst_quality': None, 'top_analyst_backed': False, 'note': 'Initiates Coverage On by Argus Research → PT N/A'}
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=start ticker=SPCX
[TIMING] 2026-06-28T21:28:15 section=news_catalyst_check event=end ticker=SPCX elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=start ticker=SPCX
[TIMING] 2026-06-28T21:28:15 section=sector_sweep_trigger event=end ticker=SPCX elapsed=0.000s peers=0
[TIMING] 2026-06-28T21:28:18 section=live_price_fetch event=start ticker=SPCX
[TIMING] 2026-06-28T21:28:18 section=live_price_fetch event=end ticker=SPCX elapsed=0.000s price=yes
  BUY   SPCX   3 sh @ 152.77 (stop 115.44, 0.5% risk, $458) — Pulled back to 10-EMA 170.35 (close 152.77)
[TIMING] 2026-06-28T21:28:18 section=ticker event=start ticker=ONDS idx=72/94
[TIMING] 2026-06-28T21:28:18 section=pending_pullback event=start ticker=ONDS
[TIMING] 2026-06-28T21:28:18 section=pending_pullback event=end ticker=ONDS elapsed=0.001s
[TIMING] 2026-06-28T21:28:18 section=analyst_ratings_check event=start ticker=ONDS
[TIMING] 2026-06-28T21:28:18 section=analyst_ratings_check event=end ticker=ONDS elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:18 section=news_catalyst_check event=start ticker=ONDS
[TIMING] 2026-06-28T21:28:18 section=news_catalyst_check event=end ticker=ONDS elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:18 section=sector_sweep_trigger event=start ticker=ONDS
[TIMING] 2026-06-28T21:28:18 section=sector_sweep_trigger event=end ticker=ONDS elapsed=0.000s peers=0
  skip  ONDS   ⚪ WATCH  (2/4 Pillars)
[TIMING] 2026-06-28T21:28:18 section=ticker event=start ticker=KEEL idx=73/94
[TIMING] 2026-06-28T21:28:18 section=pending_pullback event=start ticker=KEEL
[TIMING] 2026-06-28T21:28:18 section=pending_pullback event=end ticker=KEEL elapsed=0.001s
[TIMING] 2026-06-28T21:28:18 section=analyst_ratings_check event=start ticker=KEEL
[TIMING] 2026-06-28T21:28:18 section=analyst_ratings_check event=end ticker=KEEL elapsed=0.000s rating={'firm': 'Citizens', 'analyst': 'Greg P. Miller', 'benzinga_analyst_id': '6891ff12ce665b00013ae12b', 'benzinga_firm_id': '57f832aa6b87f600016fa36e', 'rating': 'market outperform', 'rating_action': 'initiates_coverage_on', 'price_target': 10.0, 'adjusted_price_target': 10.0, 'previous_price_target': None, 'price_percent_change': None, 'date': '2026-06-24', 'pt_raised': False, 'analyst_quality': {'benzinga_firm_id': '57f832aa6b87f600016fa36e', 'benzinga_id': '6891ff12ce665b00013ae12b', 'firm_match': True, 'firm_name': 'Citizens', 'full_name': 'Greg P. Miller', 'overall_avg_return': 17.41, 'overall_success_rate': 64.29, 'smart_score': 64.17, 'summary': None, 'top_analyst': False, 'total_ratings': 14.0}, 'top_analyst_backed': False, 'note': 'Initiates Coverage On by Citizens → PT $10'}
[TIMING] 2026-06-28T21:28:18 section=news_catalyst_check event=start ticker=KEEL
[TIMING] 2026-06-28T21:28:18 section=news_catalyst_check event=end ticker=KEEL elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:18 section=sector_sweep_trigger event=start ticker=KEEL
[TIMING] 2026-06-28T21:28:18 section=sector_sweep_trigger event=end ticker=KEEL elapsed=0.000s peers=0
  skip  KEEL   ⚪ WATCH  (2/4 Pillars)
[TIMING] 2026-06-28T21:28:18 section=ticker event=start ticker=HL idx=74/94
[TIMING] 2026-06-28T21:28:18 section=pending_pullback event=start ticker=HL
[TIMING] 2026-06-28T21:28:18 section=pending_pullback event=end ticker=HL elapsed=0.001s
[TIMING] 2026-06-28T21:28:18 section=analyst_ratings_check event=start ticker=HL
[TIMING] 2026-06-28T21:28:18 section=analyst_ratings_check event=end ticker=HL elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:18 section=news_catalyst_check event=start ticker=HL
[TIMING] 2026-06-28T21:28:18 section=news_catalyst_check event=end ticker=HL elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:18 section=sector_sweep_trigger event=start ticker=HL
[TIMING] 2026-06-28T21:28:18 section=sector_sweep_trigger event=end ticker=HL elapsed=0.000s peers=0
  skip  HL     🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:18 section=ticker event=start ticker=SOFI idx=75/94
[TIMING] 2026-06-28T21:28:18 section=pending_pullback event=start ticker=SOFI
[TIMING] 2026-06-28T21:28:18 section=pending_pullback event=end ticker=SOFI elapsed=0.001s
[TIMING] 2026-06-28T21:28:18 section=analyst_ratings_check event=start ticker=SOFI
[TIMING] 2026-06-28T21:28:18 section=analyst_ratings_check event=end ticker=SOFI elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:18 section=news_catalyst_check event=start ticker=SOFI
[TIMING] 2026-06-28T21:28:18 section=news_catalyst_check event=end ticker=SOFI elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:18 section=sector_sweep_trigger event=start ticker=SOFI
[TIMING] 2026-06-28T21:28:18 section=sector_sweep_trigger event=end ticker=SOFI elapsed=0.000s peers=0
  skip  SOFI   🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:18 section=ticker event=start ticker=T idx=76/94
[TIMING] 2026-06-28T21:28:18 section=pending_pullback event=start ticker=T
[TIMING] 2026-06-28T21:28:18 section=pending_pullback event=end ticker=T elapsed=0.001s
[TIMING] 2026-06-28T21:28:18 section=analyst_ratings_check event=start ticker=T
[TIMING] 2026-06-28T21:28:18 section=analyst_ratings_check event=end ticker=T elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:18 section=news_catalyst_check event=start ticker=T
[TIMING] 2026-06-28T21:28:18 section=news_catalyst_check event=end ticker=T elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:18 section=sector_sweep_trigger event=start ticker=T
[TIMING] 2026-06-28T21:28:18 section=sector_sweep_trigger event=end ticker=T elapsed=0.000s peers=0
  skip  T      🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:18 section=ticker event=start ticker=NWL idx=77/94
[TIMING] 2026-06-28T21:28:18 section=pending_pullback event=start ticker=NWL
[TIMING] 2026-06-28T21:28:18 section=pending_pullback event=end ticker=NWL elapsed=0.001s
[TIMING] 2026-06-28T21:28:18 section=analyst_ratings_check event=start ticker=NWL
[TIMING] 2026-06-28T21:28:18 section=analyst_ratings_check event=end ticker=NWL elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:18 section=news_catalyst_check event=start ticker=NWL
[TIMING] 2026-06-28T21:28:18 section=news_catalyst_check event=end ticker=NWL elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:18 section=sector_sweep_trigger event=start ticker=NWL
[TIMING] 2026-06-28T21:28:18 section=sector_sweep_trigger event=end ticker=NWL elapsed=0.000s peers=0
  skip  NWL    🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:18 section=ticker event=start ticker=WEN idx=78/94
[TIMING] 2026-06-28T21:28:18 section=pending_pullback event=start ticker=WEN
[TIMING] 2026-06-28T21:28:18 section=pending_pullback event=end ticker=WEN elapsed=0.001s
[TIMING] 2026-06-28T21:28:18 section=analyst_ratings_check event=start ticker=WEN
[TIMING] 2026-06-28T21:28:18 section=analyst_ratings_check event=end ticker=WEN elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:18 section=news_catalyst_check event=start ticker=WEN
[TIMING] 2026-06-28T21:28:18 section=news_catalyst_check event=end ticker=WEN elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:18 section=sector_sweep_trigger event=start ticker=WEN
[TIMING] 2026-06-28T21:28:18 section=sector_sweep_trigger event=end ticker=WEN elapsed=0.000s peers=0
[TIMING] 2026-06-28T21:28:20 section=live_price_fetch event=start ticker=WEN
[TIMING] 2026-06-28T21:28:21 section=live_price_fetch event=end ticker=WEN elapsed=0.873s price=yes
  BUY   WEN    373 sh @ 7.8 (stop 7.41, 0.5% risk, $2,909) — CATALYST OVERRIDE Entry: score 2/4 Pillars, RVOL 4.50, gap +6.4%, sentiment +0.93; half-size, 5% stop
[TIMING] 2026-06-28T21:28:21 section=ticker event=start ticker=NFLX idx=79/94
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=start ticker=NFLX
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=end ticker=NFLX elapsed=0.002s
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=start ticker=NFLX
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=end ticker=NFLX elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=start ticker=NFLX
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=end ticker=NFLX elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=start ticker=NFLX
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=end ticker=NFLX elapsed=0.000s peers=0
  skip  NFLX   🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:21 section=ticker event=start ticker=HON idx=80/94
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=start ticker=HON
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=end ticker=HON elapsed=0.001s
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=start ticker=HON
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=end ticker=HON elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=start ticker=HON
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=end ticker=HON elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=start ticker=HON
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=end ticker=HON elapsed=0.000s peers=0
  block HON    (3/4 Pillars) Max positions reached (10)
[TIMING] 2026-06-28T21:28:21 section=ticker event=start ticker=DFTX idx=81/94
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=start ticker=DFTX
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=end ticker=DFTX elapsed=0.001s
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=start ticker=DFTX
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=end ticker=DFTX elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=start ticker=DFTX
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=end ticker=DFTX elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=start ticker=DFTX
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=end ticker=DFTX elapsed=0.000s peers=0
  skip  DFTX   ⚪ WATCH  (2/4 Pillars)
[TIMING] 2026-06-28T21:28:21 section=ticker event=start ticker=BLZE idx=82/94
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=start ticker=BLZE
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=end ticker=BLZE elapsed=0.001s
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=start ticker=BLZE
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=end ticker=BLZE elapsed=0.000s rating={'firm': 'Craig-Hallum', 'analyst': 'Jeff Van Rhee', 'benzinga_analyst_id': '591479b9290fa7000138e4bb', 'benzinga_firm_id': '606c62f26538960001891011', 'rating': 'buy', 'rating_action': 'upgrades', 'price_target': 16.0, 'adjusted_price_target': 16.0, 'previous_price_target': 6.5, 'price_percent_change': 146.14999389648438, 'date': '2026-06-23', 'pt_raised': True, 'analyst_quality': {'benzinga_firm_id': '606c62f26538960001891011', 'benzinga_id': '591479b9290fa7000138e4bb', 'firm_match': True, 'firm_name': 'Craig-Hallum', 'full_name': 'Jeff Van Rhee', 'overall_avg_return': 18.75, 'overall_success_rate': 57.41, 'smart_score': 68.58, 'summary': None, 'top_analyst': False, 'total_ratings': 54.0}, 'top_analyst_backed': False, 'note': 'Upgrades by Craig-Hallum → PT $16 (PT raised)'}
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=start ticker=BLZE
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=end ticker=BLZE elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=start ticker=BLZE
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=end ticker=BLZE elapsed=0.000s peers=0
  block BLZE   (3/4 Pillars) Max positions reached (10)
[TIMING] 2026-06-28T21:28:21 section=ticker event=start ticker=SLS idx=83/94
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=start ticker=SLS
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=end ticker=SLS elapsed=0.001s
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=start ticker=SLS
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=end ticker=SLS elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=start ticker=SLS
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=end ticker=SLS elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=start ticker=SLS
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=end ticker=SLS elapsed=0.000s peers=0
  block SLS    (4/4 Pillars) Max positions reached (10)
[TIMING] 2026-06-28T21:28:21 section=ticker event=start ticker=LILAK idx=84/94
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=start ticker=LILAK
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=end ticker=LILAK elapsed=0.001s
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=start ticker=LILAK
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=end ticker=LILAK elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=start ticker=LILAK
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=end ticker=LILAK elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=start ticker=LILAK
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=end ticker=LILAK elapsed=0.000s peers=0
  skip  LILAK  🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:21 section=ticker event=start ticker=ABSI idx=85/94
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=start ticker=ABSI
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=end ticker=ABSI elapsed=0.001s
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=start ticker=ABSI
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=end ticker=ABSI elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=start ticker=ABSI
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=end ticker=ABSI elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=start ticker=ABSI
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=end ticker=ABSI elapsed=0.000s peers=0
  block ABSI   (3/4 Pillars) Max positions reached (10)
[TIMING] 2026-06-28T21:28:21 section=ticker event=start ticker=APGE idx=86/94
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=start ticker=APGE
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=end ticker=APGE elapsed=0.001s
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=start ticker=APGE
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=end ticker=APGE elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=start ticker=APGE
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=end ticker=APGE elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=start ticker=APGE
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=end ticker=APGE elapsed=0.000s peers=0
  block APGE   (3/4 Pillars) Max positions reached (10)
[TIMING] 2026-06-28T21:28:21 section=ticker event=start ticker=ZURA idx=87/94
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=start ticker=ZURA
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=end ticker=ZURA elapsed=0.001s
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=start ticker=ZURA
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=end ticker=ZURA elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=start ticker=ZURA
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=end ticker=ZURA elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=start ticker=ZURA
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=end ticker=ZURA elapsed=0.000s peers=0
  skip  ZURA   🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:21 section=ticker event=start ticker=GRPN idx=88/94
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=start ticker=GRPN
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=end ticker=GRPN elapsed=0.001s
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=start ticker=GRPN
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=end ticker=GRPN elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=start ticker=GRPN
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=end ticker=GRPN elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=start ticker=GRPN
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=end ticker=GRPN elapsed=0.000s peers=0
  skip  GRPN   🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:21 section=ticker event=start ticker=HELP idx=89/94
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=start ticker=HELP
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=end ticker=HELP elapsed=0.001s
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=start ticker=HELP
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=end ticker=HELP elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=start ticker=HELP
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=end ticker=HELP elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=start ticker=HELP
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=end ticker=HELP elapsed=0.000s peers=0
  skip  HELP   ⚪ WATCH  (2/4 Pillars)
[TIMING] 2026-06-28T21:28:21 section=ticker event=start ticker=FCEL idx=90/94
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=start ticker=FCEL
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=end ticker=FCEL elapsed=0.001s
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=start ticker=FCEL
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=end ticker=FCEL elapsed=0.000s rating={'firm': 'Jefferies', 'analyst': 'Dushyant Ailani', 'benzinga_analyst_id': '635001642cec4c00018c23d3', 'benzinga_firm_id': '6065ca27a93f970001f2c7fe', 'rating': 'buy', 'rating_action': 'upgrades', 'price_target': 24.0, 'adjusted_price_target': 24.0, 'previous_price_target': 16.0, 'price_percent_change': 50.0, 'date': '2026-06-26', 'pt_raised': True, 'analyst_quality': {'benzinga_firm_id': '6065ca27a93f970001f2c7fe', 'benzinga_id': '635001642cec4c00018c23d3', 'firm_match': True, 'firm_name': 'Jefferies', 'full_name': 'Dushyant Ailani', 'overall_avg_return': -29.62, 'overall_success_rate': 50.0, 'smart_score': 37.08, 'summary': None, 'top_analyst': False, 'total_ratings': 16.0}, 'top_analyst_backed': False, 'note': 'Upgrades by Jefferies → PT $24 (PT raised)'}
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=start ticker=FCEL
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=end ticker=FCEL elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=start ticker=FCEL
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=end ticker=FCEL elapsed=0.000s peers=0
  block FCEL   (3/4 Pillars) Max positions reached (10)
[TIMING] 2026-06-28T21:28:21 section=ticker event=start ticker=LCID idx=91/94
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=start ticker=LCID
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=end ticker=LCID elapsed=0.001s
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=start ticker=LCID
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=end ticker=LCID elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=start ticker=LCID
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=end ticker=LCID elapsed=0.000s catalyst=no
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=start ticker=LCID
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=end ticker=LCID elapsed=0.000s peers=0
  skip  LCID   🔴 AVOID  (1/4 Pillars)
[TIMING] 2026-06-28T21:28:21 section=ticker event=start ticker=ATAI idx=92/94
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=start ticker=ATAI
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=end ticker=ATAI elapsed=0.001s
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=start ticker=ATAI
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=end ticker=ATAI elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=start ticker=ATAI
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=end ticker=ATAI elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=start ticker=ATAI
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=end ticker=ATAI elapsed=0.000s peers=0
  skip  ATAI   ⚪ WATCH  (2/4 Pillars)
[TIMING] 2026-06-28T21:28:21 section=ticker event=start ticker=SPT idx=93/94
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=start ticker=SPT
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=end ticker=SPT elapsed=0.001s
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=start ticker=SPT
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=end ticker=SPT elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=start ticker=SPT
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=end ticker=SPT elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=start ticker=SPT
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=end ticker=SPT elapsed=0.000s peers=0
  block SPT    (2/4 Pillars) Max positions reached (10)
[TIMING] 2026-06-28T21:28:21 section=ticker event=start ticker=GENI idx=94/94
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=start ticker=GENI
[TIMING] 2026-06-28T21:28:21 section=pending_pullback event=end ticker=GENI elapsed=0.001s
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=start ticker=GENI
[TIMING] 2026-06-28T21:28:21 section=analyst_ratings_check event=end ticker=GENI elapsed=0.000s rating=none
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=start ticker=GENI
[TIMING] 2026-06-28T21:28:21 section=news_catalyst_check event=end ticker=GENI elapsed=0.000s catalyst=yes
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=start ticker=GENI
[TIMING] 2026-06-28T21:28:21 section=sector_sweep_trigger event=end ticker=GENI elapsed=0.000s peers=0
  skip  GENI   ⚪ WATCH  (2/4 Pillars)
[TIMING] 2026-06-28T21:28:21 section=ticker_loop event=end elapsed=190.631s processed=94 scanned=75 candidates_final=94
  [handoff] saved 7 BUY / 76 WATCH for 2026-06-26

====================================================================
  SUMMARY
====================================================================
  Sells planned  : 0
  Buys planned   : 7
  Cash now       : $22,472.74
  Equity now     : $29,125.74
--------------------------------------------------------------------
  This was a DRY-RUN. Re-run with --live to execute.
====================================================================

Errors/Warnings: [2026-06-28T17:25:18+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:18+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:19+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:19+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:22+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:23+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:23+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:25+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:26+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:26+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:28+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:31+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:31+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:33+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:34+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:36+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:37+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:37+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:39+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:39+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:40+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:41+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:42+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:44+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:44+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:45+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:46+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:47+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:48+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:50+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:51+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:51+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:51+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:52+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:52+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:54+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:54+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:56+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:25:59+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:00+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:00+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:01+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:01+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:01+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:02+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:02+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:05+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:06+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:07+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:08+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:11+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:11+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:12+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:12+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:12+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:13+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:15+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:16+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:20+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:20+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:21+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:22+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:22+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:22+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:23+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:24+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:29+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:29+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:29+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:30+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:30+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:31+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:36+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:36+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:37+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:37+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:37+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:38+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:42+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:43+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:44+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:44+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:45+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:47+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}
[2026-06-28T17:26:48+00:00] vault_client: pushed signal {'signals': 1} synced={'signals': 1, 'positions': 0, 'handoff': 0, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}

Result: ACTION - 7 BUY(S), 0 SELL(S). See Vault.
[2026-06-28T17:28:22+00:00] vault_client: pushed handoff {'handoff': 1} synced={'signals': 0, 'positions': 0, 'handoff': 1, 'trades': 0, 'cash': 0, 'decisions': 0, 'documents': 0, 'thesis': 0, 'valueSnapshots': 0}

[intraday] telegram report body begin
🦅 ATLAS INTRADAY — 1:28 PM ET
📡 🟢 RISK-ON · SPY $728.99 · ⚠️ Fed/CPI day — cautious · 🧠 CAUTION: broad market/semis pressure
💰 Equity $29,126 · Cash $22,473 · 3 positions

━━━ ACTIONS ━━━
🛒 BUY (30)
   • AAL (American Airlines Group) — $18 · stop $17 · target $22 · 4/4 Pillars · 0.5% risk
   • ELVN (Enliven Therapeutics) — $50 · stop $44 · target $63 · 4/4 Pillars · 0.5% risk
   • JNJ (Johnson & Johnson) — $255 · stop $246 · target $318 · 4/4 Pillars · 0.5% risk
   • MRK (Merck) — $129 · stop $124 · target $161 · 4/4 Pillars · 0.5% risk
   • RL (Ralph Lauren) — $411 · stop $391 · target $514 · 4/4 Pillars · 0.5% risk
   • SLS (SELLAS Life Sciences Group) — $12 · stop $11 · target $15 · 4/4 Pillars · 0.5% risk
   • ABBV (AbbVie) — $253 · stop $243 · target $317 · 3/4 Pillars · 0.5% risk
   • ABSI (Absci) — $11 · stop $9 · target $14 · 3/4 Pillars · 0.5% risk
   • ALGM (Allegro MicroSystems) — $58 · stop $51 · target $72 · 3/4 Pillars · 0.5% risk
   • AMAT (Applied Materials) — $627 · stop $558 · target $784 · 3/4 Pillars · 0.5% risk
   • APGE (Apogee Therapeutics) — $133 · stop $123 · target $166 · 3/4 Pillars · 0.5% risk
   • BAC (Bank of America) — $58 · stop $56 · target $72 · 3/4 Pillars · 0.5% risk
   • BLZE (Backblaze) — $15 · stop $13 · target $18 · 3/4 Pillars · 0.5% risk
   • CAT (Caterpillar) — $997 · stop $934 · target $1,247 · 3/4 Pillars · 0.5% risk
   • CGEM (Cullinan Therapeutics) — $18 · stop $16 · target $23 · 3/4 Pillars · 0.5% risk
   • CSCO (Cisco Systems) — $114 · stop $108 · target $142 · 3/4 Pillars · 0.5% risk
   • CWAN (Clearwater Analytics) — $25 · stop $24 · target $31 · 3/4 Pillars · 0.5% risk
   • EWTX (Edgewise Therapeutics) — $41 · stop $37 · target $52 · 3/4 Pillars · 0.5% risk
   • FCEL (FuelCell Energy Inc NEW) — $24 · stop $19 · target $30 · 3/4 Pillars · 0.5% risk
   • GLW (Corning) — $221 · stop $196 · target $276 · 3/4 Pillars · 0.5% risk
   • HON (Honeywell International) — $232 · stop $221 · target $290 · 3/4 Pillars · 0.5% risk
   • JPM (JPMorgan Chase) — $329 · stop $317 · target $411 · 3/4 Pillars · 0.5% risk
   • KLIC (Kulicke & Soffa Industries) — $125 · stop $112 · target $157 · 3/4 Pillars · 0.5% risk
   • KO (Coca-Cola) — $83 · stop $80 · target $103 · 3/4 Pillars · 0.5% risk
   • MKSI (Mks) — $389 · stop $349 · target $486 · 3/4 Pillars · 0.5% risk
   • MSM (MSC Industrial Direct) — $118 · stop $114 · target $148 · 3/4 Pillars · 0.5% risk
   • SPCX (SpaceX) — $153 · stop $116 · target $192 · 3/4 Pillars · 0.5% risk
   • SYNA (Synaptics) — $121 · stop $106 · target $151 · 3/4 Pillars · 0.5% risk
   • TGT (Target) — $140 · stop $134 · target $175 · 3/4 Pillars · 0.5% risk
   • UNF (Unifirst) — $266 · stop $257 · target $333 · 3/4 Pillars · 0.5% risk
💰 SELL: none — holding all

━━━ ⏳ PENDING ENTRIES (0) ━━━
✅ none

━━━ 💼 HOLDING (3) ━━━

🔴 SYNA (Synaptics) ~$845  $126.44 → $120.70  −5% (−$40)
   🛑 $113.35  🎯 $156.61

🔴 INTC (Intel) ~$893  $129.78 → $127.62  −2% (−$15)
   🛑 $113.02  🎯 $162.25

🟢 LRCX (Lam Research) ~$4,915  $368.39 → $378.06  +3% (+$126)
   🛑 $368.40  🎯 $446.95

━━━ 🚀 GAP-UP BREAKOUTS (0) ━━━

✅ none

━━━ 📈 INTRADAY BREAKOUTS (0) ━━━

✅ none

━━━ 🎣 WAITING FOR DIP (19) ━━━

🔸 MU (Micron Technology) buy $105.80 · now $113.35 (+4%)
   3/4 · ✅ fundamentals 56% · 📉 RSI 59 · 📈 MACD+ · ⚠️ momentum weak

🔸 CGEM (Cullinan Therapeutics) buy $15.20 · now $18.04 (+9%)
   3/4 · ⚠️ weak/no earnings · 📉 RSI 67 · 📈 MACD+ · 🟢 +0.7

🔸 CAT (Caterpillar) buy $961.93 · now $999.81 (+2%)
   3/4 · ✅ fundamentals 13% · 📉 RSI 63 · 📈 MACD+ · ⚠️ momentum weak · 🟢 +0.8

🔸 ELVN (Enliven Therapeutics) buy $44.79 · now $50.00 (+8%)
   3/4 · ⚠️ weak/no earnings · 📉 RSI 67 · 📈 MACD+ · 🟢 +1.0

🔸 EWTX (Edgewise Therapeutics) buy $36.84 · now $41.46 (+8%)
   3/4 · ⚠️ weak/no earnings · 📉 RSI 65 · 📈 MACD+ · 🟢 +0.2

🔸 AAL (American Airlines Group) buy $15.79 · now $17.85 (+9%)
   3/4 · fundamentals 0% · 📉 RSI 76 · 📈 MACD+ · ⚠️ momentum weak · 🔴 -0.0

🔸 SLDB (Solid Biosciences) buy $8.01 · now $9.29 (+11%)
   3/4 · ⚠️ weak/no earnings · 📉 RSI 70 · 📈 MACD+ · ⚠️ momentum weak · 🟢 +0.0

🔸 JNJ (Johnson & Johnson) buy $238.39 · now $254.61 (+6%)
   3/4 · ✅ fundamentals · 📉 RSI 65 · 📈 MACD+ · 🟢 +1.0

🔸 AMAT (Applied Materials) buy $587.24 · now $627.25 (+5%)
   3/4 · ✅ fundamentals 29% · 📉 RSI 69 · 📈 MACD+ · ⚠️ momentum weak · 🟢 +0.9

🔸 BAC (Bank of America) buy $57.02 · now $57.93 (+2%)
   3/4 · ✅ fundamentals 27% · 📉 RSI 75 · 📈 MACD+ · ⚠️ momentum weak · 🟢 +0.9

🔸 RL (Ralph Lauren) buy $407.11 · now $411.16 (+1%)
   3/4 · ✅ fundamentals 12% · 📉 RSI 65 · 📈 MACD+ · ⚠️ momentum weak · 🟢 +1.0

🔸 CWAN (Clearwater Analytics) buy $24.54 · now $24.55 (+0%)
   3/4 · ⚠️ weak/no earnings · 📉 RSI 68 · 📈 MACD+

🔸 MRK (Merck) buy $119.39 · now $127.53 (+6%)
   3/4 · ✅ fundamentals 14% · 📉 RSI 64 · 📈 MACD+ · 🟢 +0.5

🔸 GLW (Corning) buy $199.06 · now $220.28 (+9%)
   3/4 · ✅ fundamentals 12% · 📉 RSI 64 · 📈 MACD+ · 🟢 +0.9

🔸 MKSI (Mks) buy $381.34 · now $388.61 (+2%)
   4/4 · ✅ fundamentals · 📉 RSI 67 · 📈 MACD+ · 🟢 +1.0

🔸 ALGM (Allegro MicroSystems) buy $55.54 · now $56.82 (+2%)
   3/4 · ⚠️ weak/no earnings · 📉 RSI 63 · 📈 MACD+ · 🟢 +1.0

🔸 KLIC (Kulicke & Soffa Industries) buy $120.68 · now $121.01 (+0%)
   4/4 · ✅ fundamentals · 📉 RSI 74 · 📈 MACD+ · ⚠️ momentum weak · 🟢 +1.0

🔸 TGT (Target) buy $135.72 · now $140.21 (+4%)
   3/4 · ✅ fundamentals 3% · 📉 RSI 66 · 📈 MACD+ · 🟢 +1.0

🔸 KO (Coca-Cola) buy $81.19 · now $82.43 (+2%)
   3/4 · ✅ fundamentals 27% · 📉 RSI 61 · 📈 MACD+ · 🟢 +0.8


━━━ 🚦 TOO HOT (0) ━━━
none

━━━ 👀 WATCHING (16) ━━━

1. ARM (Arm Holdings)
2. ATAI (AtaiBeckley)
3. CDE (Coeur Mining)
4. DFTX (Definium Therapeutics)
5. FDS (Factset Research Systems)
6. GE (GE Aerospace)
7. GENI (Genius Sports)
8. HELP (Cybin)
9. INTC (Intel)
10. KEEL (Keel Infrastructure)
11. LRCX (Lam Research)
12. ONDS (Ondas)
13. SDOT (Sadot Group)
14. TSM (Taiwan Semiconductor)
15. UNH (UnitedHealth Group)
16. WMT (Walmart)
[intraday] telegram report body end
[intraday] dry-run: final telegram send suppressed
atlas_intraday dry-run exit=0
```

## 6. Direct Telegram reachability probe via atlas_intraday.send_telegram
```text
/Users/yasser/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
[atlas] telegram chunk 1 attempt 1 failed: Telegram HTTP 403: {"ok":false,"error_code":403,"description":"Forbidden: the bot can't send messages to the bot"}; retrying in 2s
[atlas] telegram chunk 1 attempt 2 failed: Telegram HTTP 403: {"ok":false,"error_code":403,"description":"Forbidden: the bot can't send messages to the bot"}; retrying in 5s
[atlas] telegram failed after 3 attempts for chunk 1: Telegram HTTP 403: {"ok":false,"error_code":403,"description":"Forbidden: the bot can't send messages to the bot"}
SEND_RETURNED: False
```

## 7. Clean-env Telegram reachability probe via atlas_intraday.send_telegram

```text
/Users/yasser/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
CHAT_ID_loaded_len 10
CHAT_ID_loaded_tail 9320
[atlas] telegram chunk 1 attempt 1 failed: Telegram HTTP 403: {"ok":false,"error_code":403,"description":"Forbidden: the bot can't send messages to the bot"}; retrying in 2s
[atlas] telegram chunk 1 attempt 2 failed: Telegram HTTP 403: {"ok":false,"error_code":403,"description":"Forbidden: the bot can't send messages to the bot"}; retrying in 5s
[atlas] telegram failed after 3 attempts for chunk 1: Telegram HTTP 403: {"ok":false,"error_code":403,"description":"Forbidden: the bot can't send messages to the bot"}
SEND_RETURNED: False
```

## 8. Session-env Telegram reachability probe via atlas_intraday.send_telegram

```text
/Users/yasser/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
CHAT_ID_loaded_len 10
CHAT_ID_loaded_tail 1917
[atlas] telegram chunk 1 attempt 1 failed: Telegram HTTP 403: {"ok":false,"error_code":403,"description":"Forbidden: the bot can't send messages to the bot"}; retrying in 2s
[atlas] telegram chunk 1 attempt 2 failed: Telegram HTTP 403: {"ok":false,"error_code":403,"description":"Forbidden: the bot can't send messages to the bot"}; retrying in 5s
[atlas] telegram failed after 3 attempts for chunk 1: HTTPSConnectionPool(host='api.telegram.org', port=443): Read timed out. (read timeout=5)
SEND_RETURNED: False
```
