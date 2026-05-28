# TradeAlgo Daily Snapshot API

Integration notes for `shared/tradealgo_client.py` and `shared/tradealgo_darkflow.py`.

## Endpoint

```
GET  https://presentation.tradealgo.com/reports/snapshot
POST https://presentation.tradealgo.com/reports/snapshot   # triggers a server-side refresh
```

Headers required on both verbs:

| Header             | Value                                  |
|--------------------|----------------------------------------|
| `x-api-key`        | `$TRADEALGO_API_KEY` (prod key)        |
| `x-auth-provider`  | `apikey`                               |
| `user-agent`       | `Mozilla/5.0 ...` (any browser-ish UA) |

`TRADEALGO_API_KEY` must be set via the environment — it is NOT committed to
`.env`. Set it in the deploy environment (Railway / shell) before any code
path that fetches live data.

## Wire format reality vs vendor docs

The vendor's documentation claims the response is `application/zip`. **It is
not.** Both `GET` and `POST` actually return `application/json`:

* `POST /reports/snapshot` → ~45 byte ack: `{"status":"ok","files":31,"sizeBytes":679638}`
* `GET  /reports/snapshot` → ~3 MB JSON dict keyed by the archive's module
  paths (e.g. `"movement/darkflow-large.json": {...}`).

`TradeAlgoClient` therefore treats the response as a flat JSON bundle, NOT as
a zip stream. If the server ever switches back to zip we'd see
`content-type: application/zip` and the client raises `DataFetchError("not JSON")`
fail-closed; never fabricate (per Rule Zero).

## Cache layout

```
data/tradealgo/
  └── 2026-05-27/
        └── snapshot.json        # full bundle, ~3 MB
```

Writes are atomic (`*.tmp` → `rename`). The snapshot date is inferred from the
`live-options/snapshot.json` (or first `movement/darkflow-*.json` options block)
embedded ISO timestamp; falls back to today's UTC date if dateless.

`fetch_snapshot()` returns the cached bundle when one exists for today's UTC
date unless `force_refresh=True`.

## Public surface

```python
from shared.tradealgo_client import TradeAlgoClient
from shared.tradealgo_darkflow import (
    parse_movement_darkflow, darkflow_zscores, top_darkflow,
    parse_historical_darkflow,
)

# 1. fetch (or read cache)
client = TradeAlgoClient()                      # picks up TRADEALGO_API_KEY
snap = client.fetch_snapshot()                  # cached-today shortcut
snap = client.fetch_snapshot(force_refresh=True)  # bypass cache
snap = TradeAlgoClient.from_cache("2026-05-27") # offline

# 2. parse dark-flow movers
records = parse_movement_darkflow(snap)         # {ticker: DarkFlowRecord}
zs = darkflow_zscores(records)                  # {ticker: composite_z or None}
top = top_darkflow(records, n=10, side="up", sort_by="dollar_value")

# 3. rolling history
events = parse_historical_darkflow(snap)        # flat list of flagging events
```

### `DarkFlowRecord`

Frozen dataclass with the fields most callers need: `ticker`, `side`
(`"up"|"down"`), `cap_bucket` (`"small"|"medium"|"large"`), `multiplier`,
`dollar_value`, `perf`, `market_cap`, `last_price`, `flow_sentiment`,
`call_flow`, `put_to_call`, `call_total_prem`, `put_total_prem`,
`ats_dollar_volume_pct`.

JSON ships `multiplier`, `dollar_value`, and `market_cap` as **strings** — the
parser coerces them. Records failing core coercion are silently dropped.

### `darkflow_zscores(records)`

Cross-sectional intensity z-score across the current bundle (typically ~60
records — both sides, all three cap buckets). The composite is the arithmetic
mean of:

* z(`multiplier`)
* z(`log(dollar_value)`)             — log-transform because values are heavy-tailed
* z(`ats_dollar_volume_pct`)

Returns `None` for tickers with fewer than 2 valid components. The score is
**unsigned by side** — direction lives on `DarkFlowRecord.side`. Callers that
want a sign-aware composite can fold it in themselves.

## Flow-signal integration

`compass.signals.flow_proxy.compute_flow_signal` accepts an optional
`darkflow_z` parameter. When provided it is appended to `components_z` and
averaged into the composite alongside the existing Polygon-derived features
(`oi_total`, `vol_total`, `put_call_ratio`, `vol_oi_ratio`, `large_prints_$`).

When `darkflow_z=None` (the default) the composite math is unchanged — this
preserves the current live-trading paths (EXP-3303b / 3309 / 3311) until a
backtested weight vector justifies promoting dark-flow into the live signal.

Typical wiring:

```python
records = parse_movement_darkflow(snap)
zs = darkflow_zscores(records)
darkflow_z = zs.get(ticker)  # may be None

result = compute_flow_signal(
    ticker=ticker, as_of=as_of, provider=provider,
    darkflow_z=darkflow_z,
)
```

## Demo

```bash
python3 scripts/tradealgo_daily_demo.py                       # most recent cache
python3 scripts/tradealgo_daily_demo.py --date 2026-05-27     # specific date
python3 scripts/tradealgo_daily_demo.py --fetch               # force network fetch
python3 scripts/tradealgo_daily_demo.py -n 20 --side down     # 20 trending_down
```

Sample output (real `2026-05-27` snapshot):

```
TradeAlgo Daily Snapshot — 2026-05-27
  movement/ records: 60  (parsed across 3 cap buckets)
  top 10 by dollar_value — side=up

   #  Ticker  Cap     Side   Mult        Dollar Vol  Sentiment  ATS % avg   Perf %  DarkflowZ
  ---------------------------------------------------------------------------------------------------
   1  META    large   up     1.96  $  6,903,451,023      0.792       98.1    +4.26     +0.557
   2  IREN    large   up     2.19  $  2,703,254,930      0.683      109.5    +9.61     +0.443
   3  APP     large   up     2.26  $  2,587,178,066      0.812      113.2    +9.03     +0.457
   4  ASTS    large   up     1.53  $  2,255,512,352      0.789       76.5    +4.19     +0.211
   5  ONDS    medium  up     1.70  $    542,864,142      0.862       85.0    +8.11     -0.015
   6  CIFR    medium  up     1.98  $    431,796,547      0.455       99.2    +8.78     +0.026
   7  GM      large   up     2.08  $    390,563,400      0.821      104.1    +3.72     +0.035
   8  TSCO    large   up     2.07  $    305,605,921      0.718      103.6    +2.94     -0.015
   9  NIO     large   up     1.35  $    245,753,621      0.796       67.3   +10.27     -0.274
  10  CLF     medium  up     2.33  $    198,971,012      0.945      116.7    +7.58     -0.020
```

## Retry / error model

* `_MAX_RETRIES=3` with backoff `(1, 2, 4)` seconds on `429` / `5xx` / transport errors.
* `4xx` other than `429` raises `DataFetchError` immediately.
* Non-JSON or non-dict top-level response raises `DataFetchError`.
* On permanent failure the snapshot is NOT written; callers must handle the
  exception (fail-closed; never fabricate values, per `CLAUDE.md` Rule Zero).

## Bundle schema (31 modules)

The full archive ships these module paths — only the ones currently parsed
are listed here:

| Path                                              | Parser                           |
|---------------------------------------------------|----------------------------------|
| `movement/darkflow-large.json`                    | `parse_movement_darkflow`        |
| `movement/darkflow-medium.json`                   | `parse_movement_darkflow`        |
| `movement/darkflow-small.json`                    | `parse_movement_darkflow`        |
| `historical-darkflow/daily-darkflow-up.json`      | `parse_historical_darkflow`      |
| `historical-darkflow/daily-darkflow-down.json`    | `parse_historical_darkflow`      |
| `live-options/snapshot.json`                      | (unused; only mined for `date`)  |
| `dashboard/*`, `option-chain/*`, `scanner/*`, `swing-trades/*` | not yet parsed       |

## Known deferrals

* **No cron yet.** Daily 4:35 PM ET wiring in `main.py` is intentionally
  unhooked until live signal-weight changes are backtested.
* **No `.env` mutation.** `TRADEALGO_API_KEY` must be set in the deploy
  environment — never committed.
* **Composite reweighting is opt-in.** `flow_proxy.compute_flow_signal`
  treats `darkflow_z` as `None` by default; promoting it into the live
  signal requires a weight vector backed by backtest evidence.
