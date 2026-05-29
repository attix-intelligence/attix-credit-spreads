# V8A Flush — code handoff for cc1 (Railway deploy, before 09:30 ET 2026-05-29)

Two artifacts on this branch (`v8a-flush-handoff`):
1. `scripts/v8a_flush.py` — Railway-portable flush (subcommands `close` / `verify` / `flip-guard`), dry-run validated.
2. `experiments/registry.json` — **champion-disable**: `EXP-V8A status:active→paused` (separate commit; deploy this before 09:30 ET).

Fold these into your Railway build. Notes below are the exact tested logic.

## Champion-disable (deploy first, before 09:30)
`status:paused` makes `manager.active()` (filters `status=="active"`) skip V8A → the worker does
not spawn the V8A scanner → **no Champion entry at 09:30** and no position-monitor race with the flush.
Re-activate (`status:active`) at the 09:40 flip together with the VRP toggle, then restart the worker.

## close_spread — exact invocation (tested)
`AlpacaProvider.close_spread(ticker, short_strike, long_strike, expiration, spread_type, contracts, limit_price)`
buys-to-close the short leg + sells-to-close the long leg as **one atomic MLEG** order.

For the current live position (SPY 735/723 ×32, exp 2026-06-12):
```python
prov.close_spread(
    ticker="SPY",
    short_strike=735.0,        # SHORT leg (the sold higher put)
    long_strike=723.0,         # LONG leg (the bought lower put)
    expiration="2026-06-12",
    spread_type="bull_put",    # "call" in the string => call legs; else put
    contracts=32,
    limit_price=net_debit,     # marketable limit, see below
)
```
**Prefer the generic path in `scripts/v8a_flush.py::cmd_close`** — it reads live positions, groups
each (expiry, type) vertical, and derives short/long/contracts at run time. That way it also closes
a *fresh* spread if one slipped through, and uses live 09:33 marks (not stale after-hours marks).

## Marketable-limit logic (tested)
Closing a credit spread = buying it back at a **net debit**. Pad mid slightly to guarantee fill:
```python
net_debit = round(short_leg_mark - long_leg_mark + FLUSH_LIMIT_BUFFER, 2)   # buffer default 0.10
# marks = each leg's current_price from /v2/positions, read live at 09:33
```
Dry-run today produced `limit_debit = 1.04` (short 1.93 − long 0.99 + 0.10). Recomputed live at run.

## Railway wiring
- Creds: script reads env `ALPACA_API_KEY_EXPV8A` / `ALPACA_API_SECRET_EXPV8A` (already on attix-worker
  per `/api/v1/health`), falling back to `.env.expv8a` locally.
- Audit log: `$RAILWAY_VOLUME_MOUNT_PATH/v8a_flush_audit.log`.
- **`close` only places orders with `FLUSH_LIVE=1`** (dry-run otherwise). Idempotent (flat→no-op).
- Schedule as **one-shot** jobs today (EDT = UTC−4): `09:33/13:33 close` (FLUSH_LIVE=1) ·
  `09:35/13:35 verify` · `09:40/13:40 flip-guard && <PR-E flip cmd>`.

## Dependencies cc1 must close
- **Telegram on attix-worker**: `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` must be set, else halt/fail
  paging is silent (empty locally).
- **09:40 flip**: `flip-guard` only GATES (flat + PR-E#78 merged + healthy). The actual flip
  (`dry_run:false` toggle + re-activate V8A `status:active` + worker restart) is PR-E's wiring — chain
  it after `flip-guard` returns exit 0.
- PR #66 (fills-based reconciler) still OPEN → close-fill PnL attribution is a follow-up.
