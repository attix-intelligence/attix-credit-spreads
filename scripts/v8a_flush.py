#!/usr/bin/env python3
"""V8A flush sequence — RAILWAY-PORTABLE (runs inside attix-worker).

Subcommands (wire each as a one-shot scheduled job on attix-worker):
  close       09:33 ET — cancel orders + close ALL option verticals (LIVE only with FLUSH_LIVE=1)
  verify      09:35 ET — assert flat (0 positions, 0 orders); exit 1 + page if not
  flip-guard  09:40 ET — GO/HALT gate (flat + PR-E merged + prod healthy). Exit 0=GO, 1=HALT.
                         Does NOT apply the toggle itself — chain: `flip-guard && <PR-E flip cmd>`

Portability vs the local versions:
  * creds from env ALPACA_API_KEY_EXPV8A / ALPACA_API_SECRET_EXPV8A (Railway per-exp vars),
    falling back to <repo>/.env.expv8a for local dry-runs.
  * repo root auto-detected (no hardcoded /Users path).
  * audit log -> $RAILWAY_VOLUME_MOUNT_PATH/v8a_flush_audit.log (persists on the volume).
  * Telegram from env TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (must be set on attix-worker).
"""
import os
import re
import sys
import json
import logging
from datetime import date
from pathlib import Path

# --- repo root: walk up until we find strategy/alpaca_provider.py ---
_here = Path(__file__).resolve()
ROOT = next((p for p in [_here, *_here.parents] if (p / "strategy" / "alpaca_provider.py").exists()), None)
if ROOT is None:
    ROOT = Path(os.environ.get("REPO_ROOT", os.getcwd()))
sys.path.insert(0, str(ROOT))

_vol = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or str(ROOT / "data")
os.makedirs(_vol, exist_ok=True)
_logpath = os.path.join(_vol, "v8a_flush_audit.log")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(_logpath), logging.StreamHandler()])
log = logging.getLogger("v8a-flush")

LIVE = os.environ.get("FLUSH_LIVE") == "1"
LIMIT_BUFFER = float(os.environ.get("FLUSH_LIMIT_BUFFER", "0.10"))
PR_E = int(os.environ.get("PR_E_NUMBER", "78"))
OCC = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


def _creds():
    k = os.environ.get("ALPACA_API_KEY_EXPV8A")
    s = os.environ.get("ALPACA_API_SECRET_EXPV8A")
    if k and s:
        return k, s, os.environ.get("ALPACA_PAPER", "true").lower() != "false"
    from dotenv import dotenv_values  # local fallback
    cfg = dotenv_values(str(ROOT / ".env.expv8a"))
    return cfg["ALPACA_API_KEY"], cfg["ALPACA_API_SECRET"], cfg.get("ALPACA_PAPER", "true").lower() != "false"


def _provider():
    from strategy.alpaca_provider import AlpacaProvider
    k, s, paper = _creds()
    return AlpacaProvider(api_key=k, api_secret=s, paper=paper)


def alert(msg):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not tok or not chat:
        log.error("ALERT (telegram UNCONFIGURED on this host): %s", msg)
        return
    import urllib.request, urllib.parse
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            data=urllib.parse.urlencode({"chat_id": chat, "text": msg, "parse_mode": "HTML"}).encode()), timeout=15)
        log.info("ALERT delivered")
    except Exception as e:  # noqa: BLE001
        log.error("ALERT delivery FAILED: %s | %s", e, msg)


def _parse(sym):
    m = OCC.match(sym or "")
    if not m:
        return None
    ymd = m.group(2)
    return {"ticker": m.group(1), "expiration": f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}",
            "cp": "call" if m.group(3) == "C" else "put", "strike": int(m.group(4)) / 1000.0}


def cmd_close():
    log.info("=== FLUSH close | mode=%s ===", "LIVE" if LIVE else "DRY-RUN")
    prov = _provider()
    pos = prov.get_positions()
    acct = prov.get_account()
    log.info("acct=%s equity=%.2f cash=%.2f positions=%d", acct["account_number"], acct["equity"], acct["cash"], len(pos))
    if not pos:
        log.info("IDEMPOTENT NO-OP: already flat."); return 0
    if prov.get_orders(status="open", limit=100):
        log.warning("working order(s) already present — possible in-flight close; proceeding with care")
    groups = {}
    for p in pos:
        info = _parse(p["symbol"])
        if not info:
            log.error("unparseable position %s — manual review", p["symbol"]); alert(f"🚨 V8A flush: unparseable {p['symbol']}"); return 1
        info.update(qty=int(p["qty"]), mark=float(p["current_price"]))
        groups.setdefault((info["expiration"], info["cp"]), []).append(info)
    rc = 0
    for (expiry, cp), grp in groups.items():
        shorts = [g for g in grp if g["qty"] < 0]; longs = [g for g in grp if g["qty"] > 0]
        if len(shorts) == 1 and len(longs) == 1:
            s, lng = shorts[0], longs[0]; n = abs(s["qty"])
            debit = round(s["mark"] - lng["mark"] + LIMIT_BUFFER, 2)
            stype = "bear_call" if cp == "call" else "bull_put"
            log.info("close %s %s exp=%s short=%.0f long=%.0f n=%d limit_debit=%.2f", s["ticker"], stype, expiry, s["strike"], lng["strike"], n, debit)
            if not LIVE:
                log.info("DRY-RUN: would close_spread(...)"); continue
            res = prov.close_spread(s["ticker"], s["strike"], lng["strike"], expiry, stype, n, debit)
            log.info("result: %s", json.dumps(res))
            if res.get("status") != "submitted":
                rc = 1; alert(f"🚨 V8A flush close FAILED {s['ticker']} {expiry}: {res.get('message')}")
        else:
            log.error("non-vertical group exp=%s %s shorts=%d longs=%d — manual", expiry, cp, len(shorts), len(longs))
            rc = 1; alert(f"🚨 V8A flush: unexpected shape exp={expiry} {cp}")
    log.info("=== FLUSH close done rc=%d ===", rc)
    return rc


def cmd_verify():
    prov = _provider()
    pos = prov.get_positions(); orders = prov.get_orders(status="open", limit=100); acct = prov.get_account()
    flat = not pos and not orders
    log.info("VERIFY positions=%d orders=%d equity=%.2f cash=%.2f flat=%s", len(pos), len(orders), acct["equity"], acct["cash"], flat)
    for p in pos:
        log.warning("  REMAINING %s qty=%s upl=%s", p["symbol"], p["qty"], p["unrealized_pl"])
    if not flat:
        alert(f"🚨 V8A NOT FLAT at verify: {len(pos)} pos / {len(orders)} orders — FLIP BLOCKED"); return 1
    log.info("✅ FLAT — equity≈cash=%.2f (Champion-era end marker)", acct["equity"]); return 0


def cmd_flip_guard():
    import subprocess
    prov = _provider()
    npos = len(prov.get_positions()); norders = len(prov.get_orders(status="open", limit=100))
    flat = npos == 0 and norders == 0
    try:
        out = subprocess.check_output(["gh", "pr", "view", str(PR_E), "--repo",
                                       "attix-intelligence/attix-credit-spreads", "--json", "state,mergedAt"], text=True, timeout=30)
        d = json.loads(out); merged = d.get("state") == "MERGED" and bool(d.get("mergedAt"))
    except Exception as e:  # noqa: BLE001
        merged, d = False, {"error": str(e)}
    import urllib.request
    try:
        with urllib.request.urlopen("https://attix-production.up.railway.app/api/v1/health", timeout=20) as r:
            healthy = json.load(r).get("status") == "ok"
    except Exception:  # noqa: BLE001
        healthy = False
    log.info("FLIP-GUARD flat=%s (pos=%d orders=%d) PR-E#%d merged=%s healthy=%s", flat, npos, norders, PR_E, merged, healthy)
    if not (flat and merged and healthy):
        reasons = []
        if not flat: reasons.append(f"NOT FLAT ({npos} pos/{norders} ord)")
        if not merged: reasons.append(f"PR-E#{PR_E} not merged ({d})")
        if not healthy: reasons.append("prod health not ok")
        alert("🛑 V8A FLIP HALTED — " + "; ".join(reasons)); return 1
    log.info("✅ FLIP-GUARD GO — chain the PR-E flip cmd next (dry_run:false + re-activate V8A). MANUAL: confirm Railway deployed #%d.", PR_E)
    return 0


if __name__ == "__main__":
    cmds = {"close": cmd_close, "verify": cmd_verify, "flip-guard": cmd_flip_guard}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("usage: v8a_flush.py {close|verify|flip-guard}"); sys.exit(2)
    try:
        sys.exit(cmds[sys.argv[1]]())
    except Exception as e:  # noqa: BLE001
        log.exception("CRASH: %s", e); alert(f"🚨 V8A flush '{sys.argv[1]}' CRASHED: {e}"); sys.exit(2)
