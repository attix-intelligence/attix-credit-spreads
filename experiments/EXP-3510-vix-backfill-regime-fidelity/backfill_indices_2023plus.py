#!/usr/bin/env python3
"""EXP-3510 step 1 — extend data/historical_indices.sqlite past 2023-02-13.

Same method and schema as scripts/bootstrap_indices_history.py (the one-time
Yahoo bootstrap that populated 2019-06-03..2023-02-13), extended forward:
fetch ^VIX / ^VIX3M / ^GSPC daily bars from Yahoo Finance for
2023-02-14..2026-07-01 and INSERT OR IGNORE into the existing table.

Real vendor data only (Rule Zero) — no interpolation, no synthesis. Idempotent.
A timestamped backup of the sqlite is taken before writing.

Run:  .venv/bin/python experiments/EXP-3510-vix-backfill-regime-fidelity/backfill_indices_2023plus.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "data" / "historical_indices.sqlite"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

TICKERS = [("^VIX", "I:VIX"), ("^VIX3M", "I:VIX3M"), ("^GSPC", "I:SPX")]
START = "2023-02-14"
END = "2026-07-02"  # yfinance end is exclusive → last bar 2026-07-01


def main() -> None:
    backup = DB.with_suffix(f".sqlite.bak-exp3510")
    if not backup.exists():
        shutil.copy2(DB, backup)
        print(f"backup -> {backup}")

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    report = {"generated": datetime.utcnow().isoformat(), "start": START, "end_exclusive": END,
              "source": "Yahoo Finance daily bars via yfinance (same as scripts/bootstrap_indices_history.py)",
              "tickers": {}}

    for yahoo, canonical in TICKERS:
        df = yf.download(yahoo, start=START, end=END, progress=False, auto_adjust=False)
        if df.empty:
            print(f"ERROR: no data for {yahoo}", file=sys.stderr)
            report["tickers"][canonical] = {"rows_fetched": 0, "error": "empty"}
            continue
        if hasattr(df.columns, "get_level_values") and df.columns.nlevels > 1:
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        inserted = 0
        for ts, row in df.iterrows():
            cur.execute(
                "INSERT OR IGNORE INTO historical_indices "
                "(ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                (canonical, ts.date().isoformat(), float(row["Open"]), float(row["High"]),
                 float(row["Low"]), float(row["Close"]), float(row.get("Volume", 0) or 0)),
            )
            inserted += cur.rowcount
        conn.commit()
        lo, hi, n = cur.execute(
            "SELECT MIN(date), MAX(date), COUNT(*) FROM historical_indices WHERE ticker=?",
            (canonical,),
        ).fetchone()
        report["tickers"][canonical] = {
            "rows_fetched": int(len(df)), "rows_inserted": int(inserted),
            "table_range": [lo, hi], "table_rows": int(n),
        }
        print(f"{canonical}: fetched {len(df)}, inserted {inserted}, table now {lo}..{hi} ({n} rows)")

    conn.close()
    with open(OUT / "backfill_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(f"wrote {OUT/'backfill_report.json'}")


if __name__ == "__main__":
    main()
