#!/usr/bin/env python3
"""EXP-P0B Tradier fill-quality probe scheduler (prereg: experiments/EXP-P0B-fill-probes/PREREG.md).

Cron-driven one-shot phases (crash-resilient; every invocation re-reads state
from the probe DB and the broker):

    enter --slot A|B     10:15 / 13:45 ET — place the slot's probe entry (fixed
                         rotation, NOT a strategy signal). Entries are placed
                         ONCE and never modified (no-chase rule).
    poll                 every 15 min — record entry order status (time-to-fill).
    cancel-unfilled      15:15 ET — cancel entries still open; record as unfilled.
    flatten              15:30 ET — buy-to-close filled probes; close orders may
                         reprice (cancel+resubmit ladder) until flat; deadline 15:45.
    eod-check            16:15 ET — kill-criterion check: anything unfilled-and-
                         unflattened on the broker record HALTS probes.
    preview [--fixture]  dry-run: print the exact executor POST bodies for a date
                         without any network submission (recording fake HTTP).
    status               print DB summary.

Gates checked before ANY submission: config `enabled`, halt flag, RTH,
`live_submit` (engine-parity dry-run), 1-lot assertion, underlier whitelist,
daily order caps, idempotency (DB + tag).

Suggested crontab (ET box; DO NOT install before Maximus's explicit go):
    15 10 * * 1-5  cd <repo> && python scripts/p0b_probe_scheduler.py enter --slot A
    45 13 * * 1-5  cd <repo> && python scripts/p0b_probe_scheduler.py enter --slot B
    */15 10-15 * * 1-5  cd <repo> && python scripts/p0b_probe_scheduler.py poll
    15 15 * * 1-5  cd <repo> && python scripts/p0b_probe_scheduler.py cancel-unfilled
    30 15 * * 1-5  cd <repo> && python scripts/p0b_probe_scheduler.py flatten
    15 16 * * 1-5  cd <repo> && python scripts/p0b_probe_scheduler.py eod-check
    45 16 * * 1-5  cd <repo> && python scripts/p0b_reconcile.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time as time_mod
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from execution.market_hours import is_rth_now  # noqa: E402
from scripts.p0b_common import (  # noqa: E402
    SLOTS, P0BConfigError, SpreadQuote, alert, assert_probe_invariants,
    build_close_intent, build_entry_intent, build_sink, entries_today, et_cutoff,
    is_halted, limit_credit_for_level, load_config, now_et, open_db,
    orders_today, probe_tag, record_order, rotation_cell, set_halt,
)

logger = logging.getLogger("p0b.scheduler")

DEFAULT_CONFIG = REPO_ROOT / "configs" / "probe_p0b_tradier.yaml"

TERMINAL_UNFILLED = {"canceled", "cancelled", "rejected", "expired", "error"}


# ── market data ───────────────────────────────────────────────────────────────

def _tradier_provider(cfg: Dict[str, Any]):
    import os
    from strategy.tradier_provider import TradierProvider
    token_env = cfg["data"]["tradier"]["token_env"]
    token = os.environ.get(token_env, "")
    if not token:
        raise P0BConfigError(f"{token_env} not set — cannot fetch NBBO")
    return TradierProvider(token, sandbox=bool(cfg["data"]["tradier"].get("sandbox", False)))


def select_spread(cfg: Dict[str, Any], provider: Any, underlier: str,
                  ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Pick expiry/strikes per prereg §2.2 and return leg NBBOs.
    Returns (spec, None) or (None, skip_reason)."""
    p = cfg["probe"]
    q = provider.get_quote(underlier)
    spot = float(q.get("last") or q.get("close") or 0)
    if spot <= 0:
        return None, "no underlier quote"

    today = now_et().date()
    expirations = provider.get_expirations(underlier) or []
    def dte(e: str) -> int:
        return (date.fromisoformat(e) - today).days
    in_window = [e for e in expirations if p["min_dte"] <= dte(e) <= p["max_dte"]]
    if not in_window:
        return None, f"no expiration in [{p['min_dte']},{p['max_dte']}] DTE"
    expiration = min(in_window, key=lambda e: abs(dte(e) - p["target_dte"]))

    chain = provider.get_options_chain(underlier, expiration)
    if chain is None or len(chain) == 0:
        return None, "empty chain"
    puts = chain[chain["type"] == "put"]
    if len(puts) == 0:
        return None, "no puts in chain"

    target_short = spot * (1 - float(p["otm_pct"]))
    strikes = sorted(puts["strike"].unique())
    short_strike = min(strikes, key=lambda s: abs(s - target_short))
    width = float(p["widths"][underlier])
    target_long = short_strike - width
    long_candidates = [s for s in strikes if width * 0.5 <= short_strike - s <= width * 1.5]
    if not long_candidates:
        return None, f"no long strike near {target_long:g}"
    long_strike = min(long_candidates, key=lambda s: abs(s - target_long))

    def leg_nbbo(strike: float) -> Optional[Tuple[float, float]]:
        rows = puts[puts["strike"] == strike]
        if len(rows) == 0:
            return None
        r = rows.iloc[0]
        return float(r["bid"]), float(r["ask"])

    sb = leg_nbbo(short_strike)
    lb = leg_nbbo(long_strike)
    if sb is None or lb is None:
        return None, "leg NBBO missing (zero-quote filtered)"
    quote = SpreadQuote(short_bid=sb[0], short_ask=sb[1], long_bid=lb[0], long_ask=lb[1])
    if not quote.valid():
        return None, f"invalid/crossed NBBO {quote}"
    if quote.natural_credit < 0.01:
        return None, f"no marketable credit (natural={quote.natural_credit:.2f})"

    return {
        "underlier": underlier, "spot": spot, "expiration": expiration,
        "short_strike": float(short_strike), "long_strike": float(long_strike),
        "width": float(short_strike - long_strike), "quote": quote,
    }, None


# ── phase: enter ──────────────────────────────────────────────────────────────

def phase_enter(cfg: Dict[str, Any], conn, slot: str, *, force_date: Optional[date] = None) -> int:
    trade_date = force_date or now_et().date()
    tag = probe_tag(trade_date, slot)

    # Gate stack — every one logged with its reason.
    if not cfg.get("enabled", False):
        logger.error("[gate] enabled=false in config — probe schedule is not armed. Exiting.")
        return 2
    halted = is_halted(conn)
    if halted:
        logger.error("[gate] HALTED: %s — no submissions.", halted)
        return 2
    if trade_date.isoformat() in [str(d) for d in cfg["probe"].get("skip_dates", [])]:
        logger.info("[gate] %s is a configured skip date (half-day). Skipping slot %s.", trade_date, slot)
        return 0
    if not is_rth_now():
        logger.info("[gate] outside RTH — skipping slot %s.", slot)
        return 0
    if conn.execute("SELECT 1 FROM probes WHERE probe_id=?", (tag,)).fetchone():
        logger.info("[gate] idempotency: probe %s already exists. Nothing to do.", tag)
        return 0
    if entries_today(conn, trade_date) >= cfg["risk"]["max_entries_per_day"]:
        logger.error("[gate] daily entry cap reached — refusing.")
        return 2
    if orders_today(conn, trade_date) >= cfg["risk"]["max_orders_per_day"]:
        logger.error("[gate] daily order cap reached — refusing.")
        return 2
    total = conn.execute("SELECT COUNT(*) c FROM probes WHERE entry_status != 'skipped'").fetchone()["c"]
    if total >= cfg["probe"]["max_probes"]:
        logger.info("[gate] max_probes=%d reached — run complete, no more entries.", cfg["probe"]["max_probes"])
        return 0

    underlier, level = rotation_cell(cfg, trade_date, slot)
    logger.info("probe %s: cell = %s @ %s", tag, underlier, level)

    provider = _tradier_provider(cfg)
    spec, skip = select_spread(cfg, provider, underlier)
    if skip:
        logger.warning("probe %s SKIPPED: %s", tag, skip)
        conn.execute(
            "INSERT INTO probes(probe_id,trade_date,slot,underlier,level,entry_status,skip_reason) "
            "VALUES(?,?,?,?,?,'skipped',?)", (tag, trade_date.isoformat(), slot, underlier, level, skip))
        conn.commit()
        return 0

    q: SpreadQuote = spec["quote"]
    limit_credit = limit_credit_for_level(q, level)
    if limit_credit < 0.01:
        conn.execute(
            "INSERT INTO probes(probe_id,trade_date,slot,underlier,level,entry_status,skip_reason) "
            "VALUES(?,?,?,?,?,'skipped',?)",
            (tag, trade_date.isoformat(), slot, underlier, level, f"limit<{0.01} at {level}"))
        conn.commit()
        return 0

    intent = build_entry_intent(tag, underlier, spec["expiration"],
                                spec["short_strike"], spec["long_strike"], limit_credit, level)
    assert_probe_invariants(intent)  # belt-and-suspenders (also inside build)

    # live_submit gate — engine-parity dry-run semantics.
    import os
    live_submit = bool(cfg.get("live_submit", False)) or \
        os.environ.get("LIVE_SUBMIT", "").lower() in ("1", "true", "yes", "on")
    if not live_submit:
        logger.warning(
            "[DRY RUN — live_submit=false]: would submit %s %s bull_put %g/%g exp %s x1 "
            "limit_credit=%.2f (level=%s, mid=%.2f natural=%.2f qs=%.2f)",
            tag, underlier, spec["short_strike"], spec["long_strike"], spec["expiration"],
            limit_credit, level, q.mid_credit_raw, q.natural_credit, q.quoted_spread)
        return 0

    sink = build_sink(cfg)
    resp = sink.submit(intent)
    status = str(resp.get("status", "error"))
    order_id = str(resp.get("order_id") or resp.get("broker_order_id") or "")
    from compass.live.vrp_sinks import stream_client_order_id
    idem = stream_client_order_id(intent)

    conn.execute(
        "INSERT INTO probes(probe_id,trade_date,slot,underlier,level,expiration,"
        "short_strike,long_strike,width,spot_at_placement,short_bid,short_ask,long_bid,long_ask,"
        "mid_credit,natural_credit,quoted_spread,limit_credit,placed_at,"
        "entry_order_id,entry_idempotency_key,entry_status) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (tag, trade_date.isoformat(), slot, underlier, level, spec["expiration"],
         spec["short_strike"], spec["long_strike"], spec["width"], spec["spot"],
         q.short_bid, q.short_ask, q.long_bid, q.long_ask,
         round(q.mid_credit_raw, 4), q.natural_credit, q.quoted_spread, limit_credit,
         now_et().isoformat(), order_id, idem,
         "open" if status == "submitted" else "rejected"))
    record_order(conn, order_id=order_id, probe_id=tag, kind="entry", idempotency_key=idem,
                 payload={"intent": intent.__dict__, "legs": [l.__dict__ for l in intent.legs]},
                 response=resp, status=status)

    if status != "submitted":
        logger.error("probe %s entry REJECTED by sink/executor: %s", tag, resp.get("message"))
        alert(f"⚠️ P0B probe {tag} entry rejected: {resp.get('message')}")
    else:
        logger.info("probe %s entry submitted: order_id=%s limit=%.2f", tag, order_id, limit_credit)
    return 0


# ── phase: poll ───────────────────────────────────────────────────────────────

def _classify(raw: Any) -> Tuple[str, Optional[float]]:
    """(status, avg_fill_price) from a get_order_status payload, defensively."""
    d = raw if isinstance(raw, dict) else {}
    for key in ("order_status", "status", "state"):
        s = str(d.get(key, "")).lower()
        if s:
            break
    fill = d.get("average_fill_price") or d.get("avg_fill_price")
    try:
        fill = float(fill) if fill is not None else None
    except (TypeError, ValueError):
        fill = None
    if s in ("filled", "executed") or (d.get("filled_quantity") in (1, "1") and s not in TERMINAL_UNFILLED):
        return "filled", fill
    if s in TERMINAL_UNFILLED:
        return "canceled", fill
    return "open", fill


def phase_poll(cfg: Dict[str, Any], conn) -> int:
    trade_date = now_et().date().isoformat()
    rows = conn.execute(
        "SELECT probe_id, entry_order_id FROM probes "
        "WHERE trade_date=? AND entry_status='open' AND entry_order_id != ''", (trade_date,)).fetchall()
    if not rows:
        return 0
    sink = build_sink(cfg)
    for r in rows:
        try:
            raw = sink.get_order_status(r["entry_order_id"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("poll %s failed: %s", r["probe_id"], exc)
            continue
        status, fill = _classify(raw)
        conn.execute("INSERT INTO status_polls(probe_id,order_id,polled_at,raw,order_status) VALUES(?,?,?,?,?)",
                     (r["probe_id"], r["entry_order_id"], now_et().isoformat(),
                      json.dumps(raw, default=str), status))
        if status == "filled":
            conn.execute("UPDATE probes SET entry_status='filled', entry_filled_at=?, entry_fill_credit=? "
                         "WHERE probe_id=?", (now_et().isoformat(), fill, r["probe_id"]))
            logger.info("probe %s FILLED at %s", r["probe_id"], fill)
        elif status == "canceled":
            conn.execute("UPDATE probes SET entry_status='canceled', canceled_at=? WHERE probe_id=?",
                         (now_et().isoformat(), r["probe_id"]))
        conn.commit()
    return 0


# ── phase: cancel-unfilled ────────────────────────────────────────────────────

def phase_cancel_unfilled(cfg: Dict[str, Any], conn) -> int:
    phase_poll(cfg, conn)  # refresh statuses first
    trade_date = now_et().date().isoformat()
    rows = conn.execute(
        "SELECT probe_id, entry_order_id, entry_idempotency_key FROM probes "
        "WHERE trade_date=? AND entry_status='open'", (trade_date,)).fetchall()
    if not rows:
        logger.info("cancel-unfilled: nothing open.")
        return 0
    sink = build_sink(cfg)
    for r in rows:
        try:
            resp = sink.cancel_order(r["entry_order_id"])
        except Exception as exc:  # noqa: BLE001
            logger.error("cancel %s FAILED: %s", r["probe_id"], exc)
            alert(f"⚠️ P0B cancel failed for {r['probe_id']} — will re-verify at EOD check")
            continue
        record_order(conn, order_id=r["entry_order_id"], probe_id=r["probe_id"], kind="cancel",
                     idempotency_key=r["entry_idempotency_key"], payload={}, response=resp,
                     status=str(resp.get("status", "")) if isinstance(resp, dict) else "sent")
        conn.execute("UPDATE probes SET entry_status='canceled', canceled_at=? WHERE probe_id=?",
                     (now_et().isoformat(), r["probe_id"]))
        conn.commit()
        logger.info("probe %s: unfilled entry canceled at cutoff (recorded as unfilled observation).",
                    r["probe_id"])
    phase_poll(cfg, conn)  # catch fills that raced the cancel
    return 0


# ── phase: flatten ────────────────────────────────────────────────────────────

def _close_debit_marketable(cfg: Dict[str, Any], probe) -> Optional[float]:
    """Marketable close debit from live NBBO (buy short back at ask, sell long at bid)."""
    provider = _tradier_provider(cfg)
    chain = provider.get_options_chain(probe["underlier"], probe["expiration"])
    if chain is None or len(chain) == 0:
        return None
    puts = chain[chain["type"] == "put"]
    def nbbo(strike):
        rows = puts[puts["strike"] == strike]
        return (float(rows.iloc[0]["bid"]), float(rows.iloc[0]["ask"])) if len(rows) else None
    s, l = nbbo(probe["short_strike"]), nbbo(probe["long_strike"])
    if not s or not l:
        return None
    return max(0.01, round(s[1] - l[0], 2))


def phase_flatten(cfg: Dict[str, Any], conn) -> int:
    phase_poll(cfg, conn)
    trade_date = now_et().date().isoformat()
    rows = conn.execute(
        "SELECT * FROM probes WHERE trade_date=? AND entry_status='filled' AND flat_confirmed_at IS NULL",
        (trade_date,)).fetchall()
    if not rows:
        logger.info("flatten: no filled probes to close.")
        return 0

    sink = build_sink(cfg)
    deadline = et_cutoff(cfg, "flatten_deadline_et")
    p = cfg["probe"]

    for r in rows:
        probe = dict(r)
        entry = build_entry_intent(probe["probe_id"], probe["underlier"], probe["expiration"],
                                   probe["short_strike"], probe["long_strike"],
                                   max(0.01, probe["limit_credit"] or 0.01), probe["level"])
        attempt = int(probe["close_attempts"] or 0)
        current_order: Optional[str] = None
        while now_et() < deadline:
            attempt += 1
            debit = _close_debit_marketable(cfg, probe)
            if debit is not None:
                debit = round(debit + p["close_reprice_step"] * (attempt - 1), 2)
            close_intent = build_close_intent(entry, attempt)
            resp = sink.submit_close(close_intent, net_debit=debit)  # debit None -> market
            order_id = str(resp.get("order_id") or resp.get("broker_order_id") or "")
            record_order(conn, order_id=order_id, probe_id=probe["probe_id"], kind="close",
                         idempotency_key=str(resp.get("client_order_id", "")),
                         payload={"attempt": attempt, "net_debit": debit}, response=resp,
                         status=str(resp.get("status", "error")))
            conn.execute("UPDATE probes SET close_order_id=?, close_attempts=? WHERE probe_id=?",
                         (order_id, attempt, probe["probe_id"]))
            conn.commit()
            if resp.get("status") != "submitted":
                logger.error("close attempt %d for %s rejected: %s", attempt,
                             probe["probe_id"], resp.get("message"))
                time_mod.sleep(15)
                continue
            current_order = order_id
            wait_until = min(deadline, now_et() + timedelta(
                seconds=p["close_reprice_after_s"] if attempt == 1 else p["close_reprice_every_s"]))
            filled = False
            while now_et() < wait_until:
                time_mod.sleep(10)
                try:
                    status, fill = _classify(sink.get_order_status(current_order))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("close poll failed: %s", exc)
                    continue
                if status == "filled":
                    conn.execute(
                        "UPDATE probes SET close_filled_at=?, close_fill_debit=?, flat_confirmed_at=? "
                        "WHERE probe_id=?",
                        (now_et().isoformat(), fill, now_et().isoformat(), probe["probe_id"]))
                    conn.commit()
                    logger.info("probe %s FLAT (close filled at %s, attempt %d)",
                                probe["probe_id"], fill, attempt)
                    filled = True
                    break
            if filled:
                break
            # ladder: cancel and resubmit 1c through (closing orders may chase — prereg §2.2)
            try:
                sink.cancel_order(current_order)
            except Exception as exc:  # noqa: BLE001
                logger.warning("close cancel failed (may have filled): %s", exc)
            phase_poll(cfg, conn)
        else:
            logger.critical("probe %s NOT FLAT at deadline — eod-check will halt.", probe["probe_id"])
            alert(f"🛑 P0B probe {probe['probe_id']} not flat at 15:45 deadline")
    return 0


# ── phase: eod-check (the kill criterion) ─────────────────────────────────────

def phase_eod_check(cfg: Dict[str, Any], conn) -> int:
    phase_poll(cfg, conn)
    trade_date = now_et().date().isoformat()
    problems = []

    rows = conn.execute("SELECT * FROM probes WHERE trade_date=?", (trade_date,)).fetchall()
    for r in rows:
        if r["entry_status"] == "open":
            problems.append(f"{r['probe_id']}: entry order still open after cancel cutoff")
        if r["entry_status"] == "filled" and not r["flat_confirmed_at"]:
            problems.append(f"{r['probe_id']}: FILLED AND NOT FLATTENED")

    # Broker-side verification: no probe-matching open positions, ever.
    try:
        sink = build_sink(cfg)
        positions = sink.get_positions() or []
        legs = conn.execute(
            "SELECT probe_id, underlier, expiration, short_strike, long_strike FROM probes "
            "WHERE entry_status='filled'").fetchall()
        for pos in positions:
            psym = str(pos.get("symbol", pos.get("occ_symbol", "")))
            for lg in legs:
                for strike in (lg["short_strike"], lg["long_strike"]):
                    exp = (lg["expiration"] or "").replace("-", "")[2:]
                    if lg["underlier"] in psym and exp and exp in psym \
                            and f"{int(round(strike * 1000)):08d}" in psym:
                        if lg["probe_id"] not in [p.split(":")[0] for p in problems]:
                            problems.append(f"{lg['probe_id']}: broker still shows position {psym}")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"broker position check FAILED: {exc}")

    # Budget guards (prereg §6.5) — estimates until reconcile ingests commissions.
    est = conn.execute(
        "SELECT COALESCE(SUM((COALESCE(entry_fill_credit,0)-COALESCE(close_fill_debit,0))*100),0) pnl, "
        "COUNT(*) filled FROM probes WHERE entry_status='filled' AND close_fill_debit IS NOT NULL"
    ).fetchone()
    commissions_est = est["filled"] * 4 * 0.65
    pnl_net_est = est["pnl"] - commissions_est
    if pnl_net_est < cfg["risk"]["budget_pnl_halt_usd"]:
        problems.append(f"budget kill: cumulative est. net P&L {pnl_net_est:.2f} "
                        f"< {cfg['risk']['budget_pnl_halt_usd']}")

    if problems:
        for pr in problems:
            logger.critical("[EOD-CHECK] %s", pr)
        set_halt(conn, "EOD check failed: " + " | ".join(problems))
        return 1
    logger.info("[EOD-CHECK] clean: %d probes today, cumulative est. net P&L %.2f", len(rows), pnl_net_est)
    return 0


# ── phase: preview (dry-run order bodies, zero network submission) ───────────

class _RecordingHttp:
    """requests-like stub: serves CSRF, records writes, submits nothing."""
    def __init__(self):
        self.writes = []

    def request(self, method, url, **kw):
        class R:
            status_code = 200
            def __init__(self, payload): self._p = payload
            def json(self): return self._p
            @property
            def text(self): return json.dumps(self._p)
        if method == "GET" and url.endswith("/auth/csrf-token"):
            return R({"csrf_token": "preview-token"})
        if method != "GET":
            self.writes.append({"method": method, "url": url, "json": kw.get("json")})
            return R({"status": "submitted", "order_id": "PREVIEW-ONLY",
                      "broker_order_id": "PREVIEW-ONLY"})
        return R({})


def phase_preview(cfg: Dict[str, Any], conn, *, for_date: Optional[date], fixture: Optional[Path]) -> int:
    from compass.live.executor_order_sink import ExecutorClient, ExecutorOrderSink

    d = for_date or _next_trading_day(now_et().date())
    fixture_data = json.loads(fixture.read_text()) if fixture else None
    rec = _RecordingHttp()
    client = ExecutorClient(cfg["tradier_live"]["base_url"] and "https://executor.preview.invalid",
                            "preview-key", http=rec)
    sink = ExecutorOrderSink(client, account_id=cfg["tradier_live"]["account_id"],
                             account_type=cfg["tradier_live"]["account_type"],
                             source_model=cfg.get("executor", {}).get("source_model", "p0b_probe"))

    print(f"\n=== EXP-P0B DRY-RUN ORDER PREVIEW — trade date {d} (no network submission) ===")
    print(f"account: {sink.account_id} ({sink.account_type})  source_model: {sink.source_model}")
    for slot in SLOTS:
        underlier, level = rotation_cell(cfg, d, slot)
        tag = probe_tag(d, slot)
        spec = skip = None
        if fixture_data and underlier in fixture_data:
            f = fixture_data[underlier]
            q = SpreadQuote(**f["nbbo"])
            spec = {"underlier": underlier, "spot": f["spot"], "expiration": f["expiration"],
                    "short_strike": f["short_strike"], "long_strike": f["long_strike"],
                    "width": f["short_strike"] - f["long_strike"], "quote": q}
        else:
            try:
                spec, skip = select_spread(cfg, _tradier_provider(cfg), underlier)
            except Exception as exc:  # noqa: BLE001
                skip = f"live quotes unavailable ({exc})"
        print(f"\n--- slot {slot} @ {cfg['probe']['slots'][slot]} ET → cell ({underlier}, {level}), tag {tag}")
        if skip or spec is None:
            print(f"    SKIP: {skip}")
            continue
        q = spec["quote"]
        limit_credit = limit_credit_for_level(q, level)
        print(f"    NBBO: short {q.short_bid}/{q.short_ask}  long {q.long_bid}/{q.long_ask}"
              f"  → mid {q.mid_credit_raw:.3f}  natural {q.natural_credit:.2f}"
              f"  quoted_spread {q.quoted_spread:.2f}  → limit_credit {limit_credit:.2f}")
        intent = build_entry_intent(tag, underlier, spec["expiration"],
                                    spec["short_strike"], spec["long_strike"], limit_credit, level)
        sink.submit(intent)  # captured by _RecordingHttp — never leaves this process
        body = rec.writes[-1]
        print(f"    POST {body['url']}")
        print("    " + json.dumps(body["json"], indent=4).replace("\n", "\n    "))
    print(f"\n(entries rest until {cfg['probe']['entry_cancel_et']} ET, filled probes close "
          f"{cfg['probe']['flatten_start_et']}–{cfg['probe']['flatten_deadline_et']} ET; "
          f"gates: enabled={cfg.get('enabled')} live_submit={cfg.get('live_submit')})")
    return 0


def _next_trading_day(d: date) -> date:
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


# ── phase: status ─────────────────────────────────────────────────────────────

def phase_status(cfg: Dict[str, Any], conn) -> int:
    total = conn.execute("SELECT COUNT(*) c FROM probes WHERE entry_status!='skipped'").fetchone()["c"]
    by = conn.execute("SELECT underlier, level, entry_status, COUNT(*) c FROM probes "
                      "GROUP BY 1,2,3 ORDER BY 1,2,3").fetchall()
    halted = is_halted(conn)
    print(f"EXP-P0B: {total} probes recorded (target ≥{cfg['probe']['min_probes']}, "
          f"max {cfg['probe']['max_probes']}); halted={halted or 'no'}")
    for r in by:
        print(f"  {r['underlier']:>4} {r['level']:<13} {r['entry_status']:<9} {r['c']}")
    return 0


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", choices=["enter", "poll", "cancel-unfilled", "flatten",
                                      "eod-check", "preview", "status"])
    ap.add_argument("--slot", choices=list(SLOTS))
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--date", help="YYYY-MM-DD (preview only)")
    ap.add_argument("--fixture", help="JSON NBBO fixture for preview when market data is unavailable")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = load_config(args.config)
    fh = logging.FileHandler(REPO_ROOT / cfg["logging"]["file"], encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(fh)

    conn = open_db(cfg)
    try:
        if args.phase == "enter":
            if not args.slot:
                ap.error("enter requires --slot")
            return phase_enter(cfg, conn, args.slot)
        if args.phase == "poll":
            return phase_poll(cfg, conn)
        if args.phase == "cancel-unfilled":
            return phase_cancel_unfilled(cfg, conn)
        if args.phase == "flatten":
            return phase_flatten(cfg, conn)
        if args.phase == "eod-check":
            return phase_eod_check(cfg, conn)
        if args.phase == "preview":
            return phase_preview(cfg, conn,
                                 for_date=date.fromisoformat(args.date) if args.date else None,
                                 fixture=Path(args.fixture) if args.fixture else None)
        if args.phase == "status":
            return phase_status(cfg, conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
