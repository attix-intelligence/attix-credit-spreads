# SPX 0DTE Backtests - Quick Start Guide

**If you want to run the backtests RIGHT NOW, follow these steps.**

---

## ⚡ Fast Track (3 hours total)

### Step 1: Bulk Download Data (2 hours)

```bash
cd /home/node/.openclaw/workspace/pilotai-credit-spreads

# Download all SPX 0DTE data for 2023-2024
python3 scripts/cache_cboe_spx_0dte.py --start 2023-01-01 --end 2024-12-31
```

**What this does:**
- Queries CBOE Athena for all SPX 0DTE options (Mon/Wed/Fri)
- Downloads Greeks (delta/gamma/theta/vega)
- Downloads bid/ask spreads
- Stores in local DuckDB cache
- **One-time operation**, data persists

**Expected output:**
```
[INFO] CBOE SPX 0DTE DATA CACHE BUILDER
[INFO] Total 0DTE days to download: 312
[INFO] [1/312] Downloading 2023-01-03...
[INFO]   ✓ Cached 15,840 rows
...
[INFO] CACHE BUILD COMPLETE
[INFO]   Total rows: 4,934,400
[INFO]   Cache file: shared/data/cboe_cache.duckdb
```

### Step 2: Run All 5 Backtests (1 hour)

```bash
# Run all experiments from cached data
python3 scripts/run_spx_0dte_backtests.py --use-cache
```

**What this does:**
- Runs EXP-3500 (30Δ baseline)
- Runs EXP-3501 (20Δ aggressive)
- Runs EXP-3502 (15Δ extreme)
- Runs EXP-3503 (VIX-adaptive)
- Runs EXP-3504 (XLK IV filter)
- Generates consolidated report

**Expected output:**
```
[INFO] SPX 0DTE BACKTEST SUITE - RULE ZERO COMPLIANT
[INFO] Starting EXP-3500: 30Δ Baseline
[INFO] EXP-3500 COMPLETE:
[INFO]   Trades: 245
[INFO]   Win rate: 87.8%
[INFO]   Total return: +34.5%
[INFO]   Sharpe ratio: 2.14
[INFO] 🏆 WINNER: EXP-3503 - VIX-Adaptive
```

### Step 3: View Results

```bash
# Open consolidated report in browser
open experiments/EXP-3500-series-results/CONSOLIDATED_REPORT.html

# Or view JSON results
cat experiments/EXP-3500-series-results/EXP-3500_results.json
```

---

## 🐌 Slow Track (17 days, not recommended)

If you want to skip caching and query Athena live for every trade:

```bash
# Run without cache (SLOW!)
python3 scripts/run_spx_0dte_backtests.py

# This will take 17 days to complete
# Use only if you want pure real-time queries
```

---

## 🧪 Validation Track (5 hours)

Test with just 1 month of data first:

```bash
# Run January 2023 only (20 trading days)
python3 scripts/run_spx_0dte_backtests.py --start 2023-01-01 --end 2023-01-31

# Review results, then decide on full run
```

---

## Troubleshooting

### Error: "AWS credentials not found"

```bash
# Verify .env file exists and has credentials
cat /home/node/.openclaw/workspace/pilotai-credit-spreads/.env

# Should show:
# AWS_ACCESS_KEY_ID=AKIA...
# AWS_SECRET_ACCESS_KEY=...
# AWS_DEFAULT_REGION=ap-southeast-1
```

### Error: "Athena query failed"

```bash
# Test CBOE connection
python3 -c "
from dotenv import load_dotenv
load_dotenv('.env')
from backtest.cboe_data_provider import CBOEDataProvider
provider = CBOEDataProvider()
print('✓ Connection OK')
"
```

### Cache file missing

```bash
# Check if cache exists
ls -lh shared/data/cboe_cache.duckdb

# If missing, run Step 1 again
python3 scripts/cache_cboe_spx_0dte.py --start 2023-01-01 --end 2024-12-31
```

---

## Expected Results

After completion, you'll have:

1. **5 experiment result files:**
   - `EXP-3500_results.json`
   - `EXP-3501_results.json`
   - `EXP-3502_results.json`
   - `EXP-3503_results.json`
   - `EXP-3504_results.json`

2. **Consolidated report:**
   - `CONSOLIDATED_RESULTS.json`
   - `CONSOLIDATED_REPORT.html`

3. **Winner identification:**
   - Strategy with highest Sharpe ratio
   - Performance metrics comparison
   - Paper trading config ready

---

## Cost

| Item | Amount |
|------|--------|
| Bulk download (Step 1) | ~$5 |
| Backtests (Step 2) | $0 (cached) |
| **TOTAL** | **$5** |

---

## Questions?

**Check documentation:**
- `CBOE_VERIFICATION_REPORT.md` - Technical details
- `STATUS_REPORT.html` - Visual dashboard
- `EXECUTIVE_SUMMARY.md` - High-level overview

**Or ask Carlos/Maximus.**

---

**Ready? Start with Step 1 above. ⚡**
