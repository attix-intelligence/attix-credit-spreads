#!/usr/bin/env python3
"""EXP-P0B daily reconciliation — probe state DB vs broker records (prereg §7).

Runs after the close (suggested 16:45 ET cron). Pulls from the executor REST
service (the same audited account APIs used in the broker-verified fleet
review): order status per recorded order id, open positions, and — where the
executor exposes it — /v1/portfolio/trades for commissions + a phantom-order
scan (any probe-tagged broker order missing from the DB).

ANY mismatch sets the halt flag (kill criterion #4); the scheduler refuses all
submissions while halted. Output:
    experiments/EXP-P0B-fill-probes/reconciliation/<date>.json
    experiments/EXP-P0B-fill-probes/RECON_LOG.md   (one line per day)
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.p0b_common import (  # noqa: E402
    TAG_PREFIX, build_sink, executor_get, is_halted, load_config, now_et, open_db, set_halt,
)

logger = logging.getLogger("p0b.reconcile")

RECON_DIR = REPO_ROOT / "experiments" / "EXP-P0B-fill-probes" / "reconciliation"
RECON_LOG = REPO_ROOT / "experiments" / "EXP-P0B-fill-probes" / "RECON_LOG.md"


def _is_probe_tagged(obj: Dict[str, Any]) -> bool:
    blob = json.dumps(obj, default=str)
    return TAG_PREFIX in blob


def reconcile(cfg: Dict[str, Any], conn) -> Dict[str, Any]:
    today = now_et().date().isoformat()
    mismatches: List[str] = []
    warnings: List[str] = []

    sink = build_sink(cfg)

    # 1 · Every DB order must be terminal and agree with the broker record.
    orders = conn.execute(
        "SELECT DISTINCT o.order_id, o.probe_id, o.kind, p.entry_status, p.flat_confirmed_at "
        "FROM orders o JOIN probes p ON p.probe_id = o.probe_id "
        "WHERE o.order_id != '' AND o.order_id != 'PREVIEW-ONLY'").fetchall()
    broker_orders: Dict[str, Any] = {}
    for r in orders:
        try:
            raw = sink.get_order_status(r["order_id"])
            broker_orders[r["order_id"]] = raw
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"status fetch failed for {r['order_id']} ({r['probe_id']}): {exc}")
            continue
        d = raw if isinstance(raw, dict) else {}
        st = str(d.get("order_status") or d.get("status") or "").lower()
        if st in ("open", "pending", "submitted", "partially_filled", "accepted", ""):
            mismatches.append(f"{r['probe_id']}: order {r['order_id']} ({r['kind']}) "
                              f"non-terminal on broker: {st or 'unknown'}")
        qty = d.get("quantity") or d.get("contracts")
        if qty not in (None, 1, "1", 1.0):
            mismatches.append(f"{r['probe_id']}: order {r['order_id']} broker qty={qty} != 1 "
                              "(1-LOT HARD CAP breach on the broker record)")

    # 2 · No probe-related open positions on the broker.
    try:
        positions = sink.get_positions() or []
    except Exception as exc:  # noqa: BLE001
        positions = []
        mismatches.append(f"positions fetch FAILED: {exc}")
    filled = conn.execute(
        "SELECT probe_id, underlier, expiration, short_strike, long_strike FROM probes "
        "WHERE entry_status='filled'").fetchall()
    for pos in positions:
        psym = str(pos.get("symbol", pos.get("occ_symbol", "")))
        for lg in filled:
            exp = (lg["expiration"] or "").replace("-", "")[2:]
            for strike in (lg["short_strike"], lg["long_strike"]):
                if lg["underlier"] in psym and exp and exp in psym \
                        and f"{int(round(strike * 1000)):08d}" in psym:
                    mismatches.append(f"{lg['probe_id']}: open broker position {psym} after EOD")

    # 3 · Phantom scan + commissions via /v1/portfolio/trades (best-effort:
    # the endpoint shape follows the IBKR-assessment tooling; absence is a
    # warning, not a pass).
    commissions_total = None
    try:
        trades = executor_get("/v1/portfolio/trades",
                              {"account_id": cfg["tradier_live"]["account_id"]})
        tlist = trades if isinstance(trades, list) else \
            trades.get("trades") or trades.get("data") or []
        probe_trades = [t for t in tlist if _is_probe_tagged(t)]
        known_ids = {r["order_id"] for r in orders}
        commissions_total = 0.0
        for t in probe_trades:
            oid = str(t.get("broker_order_id") or t.get("order_id") or "")
            if oid and oid not in known_ids:
                mismatches.append(f"PHANTOM probe-tagged broker trade not in DB: {oid}")
            c = t.get("commission")
            if c is not None:
                try:
                    commissions_total += abs(float(c))
                except (TypeError, ValueError):
                    pass
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"trades endpoint unavailable — phantom scan skipped: {exc}")

    # 4 · Budget guard with broker commissions where available (prereg §6.5).
    pnl = conn.execute(
        "SELECT COALESCE(SUM((COALESCE(entry_fill_credit,0)-COALESCE(close_fill_debit,0))*100),0) g, "
        "COUNT(*) n FROM probes WHERE entry_status='filled'").fetchone()
    commissions = commissions_total if commissions_total is not None else pnl["n"] * 4 * 0.65
    net = pnl["g"] - commissions
    slippage_paid = conn.execute(
        "SELECT COALESCE(SUM((mid_credit - entry_fill_credit)*100),0) s FROM probes "
        "WHERE entry_status='filled' AND entry_fill_credit IS NOT NULL").fetchone()["s"]
    friction = commissions + max(0.0, slippage_paid)
    if friction > cfg["risk"]["budget_friction_halt_usd"]:
        mismatches.append(f"budget kill: cumulative friction ${friction:.2f} "
                          f"> ${cfg['risk']['budget_friction_halt_usd']}")
    if net < cfg["risk"]["budget_pnl_halt_usd"]:
        mismatches.append(f"budget kill: cumulative net P&L ${net:.2f} "
                          f"< ${cfg['risk']['budget_pnl_halt_usd']}")

    report = {
        "date": today,
        "generated_at": now_et().isoformat(),
        "orders_checked": len(orders),
        "open_positions_checked": len(positions),
        "mismatches": mismatches,
        "warnings": warnings,
        "cumulative": {"gross_pnl": pnl["g"], "commissions": commissions,
                       "net_pnl": net, "friction_est": friction,
                       "commissions_source": "broker" if commissions_total is not None else "estimate"},
        "verdict": "MISMATCH-HALT" if mismatches else "OK",
        "already_halted": is_halted(conn),
    }
    return report


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(REPO_ROOT / "configs" / "probe_p0b_tradier.yaml"))
    args = ap.parse_args()

    cfg = load_config(args.config)
    conn = open_db(cfg)
    try:
        report = reconcile(cfg, conn)
        RECON_DIR.mkdir(parents=True, exist_ok=True)
        out = RECON_DIR / f"{report['date']}.json"
        out.write_text(json.dumps(report, indent=2, default=str))
        line = (f"- {report['date']} — **{report['verdict']}** · orders {report['orders_checked']} · "
                f"net ${report['cumulative']['net_pnl']:.2f} · friction ${report['cumulative']['friction_est']:.2f}"
                f"{' · ' + '; '.join(report['mismatches']) if report['mismatches'] else ''}\n")
        with open(RECON_LOG, "a") as fh:
            fh.write(line)
        logger.info("reconciliation written: %s (%s)", out, report["verdict"])
        if report["mismatches"]:
            set_halt(conn, "reconciliation mismatch: " + " | ".join(report["mismatches"]))
            return 1
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
