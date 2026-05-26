# CBOE Complete Dataset - Quick Start Guide

## 📁 Dataset Location

```
data/cboe_complete/
├── spx/
│   ├── 0dte/
│   ├── 1dte/
│   ├── 2dte/
│   ├── 3dte/
│   ├── 5dte/
│   ├── 7dte/
│   ├── 14dte/
│   └── 30dte/
├── spy/
└── qqq/
```

Each file: `{YYYY}-{MM}.csv.gz` (gzip-compressed CSV)

---

## 📊 Data Schema

| Column | Type | Description |
|--------|------|-------------|
| `ticker` | str | Underlying symbol (^SPX, SPY, QQQ) |
| `expiration` | date | Option expiration date |
| `strike` | float | Strike price |
| `option_type` | str | "C" (call) or "P" (put) |
| `timestamp` | datetime | 60-minute bar timestamp |
| `open`, `high`, `low`, `close` | float | Option price OHLC |
| `bid_open`, `bid_high`, `bid_low`, `bid_close` | float | Bid price OHLC |
| `ask_open`, `ask_high`, `ask_low`, `ask_close` | float | Ask price OHLC |
| `delta`, `gamma`, `theta`, `vega`, `rho` | float | Option Greeks |
| `iv` | float | Implied volatility (0-1 scale) |
| `volume` | int | Trade volume |
| `open_interest` | int | Open interest |
| `underlying_price` | float | Underlying price at bar time |

---

## 🚀 Usage Examples

### 1. Load a Single Month

```python
import pandas as pd

# Load SPX 0DTE for January 2024
df = pd.read_csv("data/cboe_complete/spx/0dte/2024-01.csv.gz", compression="gzip")

print(f"Rows: {len(df):,}")
print(df.head())
```

### 2. Find 30Δ Strikes for a Specific Day

```python
# Filter for a specific date and expiration
target_date = "2024-01-05"
df_day = df[df["timestamp"].str.startswith(target_date)]

# Puts with delta near -0.30
puts_30d = df_day[
    (df_day["option_type"] == "P") &
    (df_day["delta"] >= -0.35) &
    (df_day["delta"] <= -0.25)
]

print(f"30Δ puts on {target_date}:")
print(puts_30d[["strike", "delta", "bid_close", "ask_close"]])
```

### 3. Get Fill Price for Iron Condor

```python
# Define iron condor legs (example: 30Δ puts, 20Δ calls)
short_put_strike = 4650
long_put_strike = 4625
short_call_strike = 4850
long_call_strike = 4875
expiration = "2024-01-05"

# Get prices at 10:00 AM
entry_time = "2024-01-05 10:00"

# Filter for entry conditions
entry_data = df[
    (df["timestamp"] == entry_time) &
    (df["expiration"] == expiration)
]

# Calculate spread values (credit = bid for short, ask for long)
short_put_bid = entry_data[
    (entry_data["strike"] == short_put_strike) & (entry_data["option_type"] == "P")
]["bid_close"].values[0]

long_put_ask = entry_data[
    (entry_data["strike"] == long_put_strike) & (entry_data["option_type"] == "P")
]["ask_close"].values[0]

put_spread_credit = short_put_bid - long_put_ask

# (Repeat for call spread)
```

### 4. Load All Months for a Ticker/DTE

```python
from pathlib import Path
import pandas as pd

# Load all SPX 0DTE data
data_dir = Path("data/cboe_complete/spx/0dte")
all_files = sorted(data_dir.glob("*.csv.gz"))

dfs = []
for file in all_files:
    df = pd.read_csv(file, compression="gzip")
    dfs.append(df)

full_df = pd.concat(dfs, ignore_index=True)
print(f"Total rows: {len(full_df):,}")
```

### 5. Compute Greeks-Based Strike Selection

```python
# Find strike closest to 30Δ for a specific date/expiration
target_delta = -0.30
tolerance = 0.05

candidates = df[
    (df["timestamp"] == "2024-01-05 10:00") &
    (df["expiration"] == "2024-01-05") &
    (df["option_type"] == "P") &
    (df["delta"] >= target_delta - tolerance) &
    (df["delta"] <= target_delta + tolerance)
]

# Pick closest to target
candidates["delta_diff"] = (candidates["delta"] - target_delta).abs()
best_strike = candidates.loc[candidates["delta_diff"].idxmin()]

print(f"Best 30Δ strike: {best_strike['strike']} (actual Δ: {best_strike['delta']:.3f})")
```

---

## 📈 Integration with Backtest Framework

### Option A: Direct File Access

```python
class LocalCBOEDataProvider:
    """Load CBOE data from local files."""
    
    def __init__(self, data_dir="data/cboe_complete"):
        self.data_dir = Path(data_dir)
    
    def get_spread_prices(self, ticker, expiration, short_strike, long_strike, option_type, date):
        # Extract year-month from date
        ym = date.strftime("%Y-%m")
        
        # Determine DTE
        dte = (expiration - date).days
        dte_bucket = self._find_dte_bucket(dte)
        
        # Load file
        file_path = self.data_dir / ticker.lower() / f"{dte_bucket}dte" / f"{ym}.csv.gz"
        
        if not file_path.exists():
            return None
        
        df = pd.read_csv(file_path, compression="gzip")
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["expiration"] = pd.to_datetime(df["expiration"])
        
        # Filter for target date/expiration
        mask = (
            (df["expiration"] == expiration) &
            (df["timestamp"].dt.date == date.date()) &
            (df["option_type"] == option_type)
        )
        
        day_data = df[mask]
        
        # Get short and long leg prices (use last bar of day)
        short_data = day_data[day_data["strike"] == short_strike].iloc[-1]
        long_data = day_data[day_data["strike"] == long_strike].iloc[-1]
        
        return {
            "short_close": (short_data["bid_close"] + short_data["ask_close"]) / 2,
            "long_close": (long_data["bid_close"] + long_data["ask_close"]) / 2,
            "spread_value": short_data["bid_close"] - long_data["ask_close"],  # Credit
        }
    
    def _find_dte_bucket(self, dte):
        """Map actual DTE to bucket."""
        buckets = [0, 1, 2, 3, 5, 7, 14, 30]
        return min(buckets, key=lambda x: abs(x - dte))
```

### Option B: Hybrid (Local + Athena Fallback)

```python
class HybridCBOEProvider:
    """Try local files first, fallback to Athena."""
    
    def __init__(self, local_dir="data/cboe_complete"):
        self.local_provider = LocalCBOEDataProvider(local_dir)
        self.athena_provider = CBOEDataProvider()
    
    def get_spread_prices(self, *args, **kwargs):
        # Try local first
        result = self.local_provider.get_spread_prices(*args, **kwargs)
        
        if result is not None:
            return result
        
        # Fallback to Athena
        return self.athena_provider.get_spread_prices(*args, **kwargs)
```

---

## 🎯 Common Queries

### Find Available Strikes for a Date

```python
# Load day's data
df_day = df[df["timestamp"].str.startswith("2024-01-05")]

# Get unique strikes for puts expiring same day
strikes = df_day[
    (df_day["expiration"] == "2024-01-05") &
    (df_day["option_type"] == "P")
]["strike"].unique()

print(f"Available strikes: {sorted(strikes)}")
```

### Check Data Coverage for a Period

```python
from pathlib import Path

data_dir = Path("data/cboe_complete/spx/0dte")
months = sorted([f.stem for f in data_dir.glob("*.csv.gz")])

print(f"SPX 0DTE coverage: {months[0]} to {months[-1]}")
print(f"Total months: {len(months)}")
```

### Calculate Monthly P&L from Trades

```python
# Load all 2024 data
files_2024 = Path("data/cboe_complete/spx/0dte").glob("2024-*.csv.gz")
dfs = [pd.read_csv(f, compression="gzip") for f in files_2024]
df_2024 = pd.concat(dfs, ignore_index=True)

# (Join with your trade log to calculate fills and P&L)
```

---

## 🔧 Utilities

### Decompress a Single File (For Inspection)

```bash
gunzip -c data/cboe_complete/spx/0dte/2024-01.csv.gz > /tmp/spx_0dte_2024-01.csv
head /tmp/spx_0dte_2024-01.csv
```

### Count Total Rows Across All Files

```bash
find data/cboe_complete -name "*.csv.gz" -exec zcat {} \; | wc -l
```

### Search for Specific Contract

```bash
# Find all occurrences of SPX 4700 put expiring 2024-01-05
zgrep "^SPX,2024-01-05,4700.0,P" data/cboe_complete/spx/0dte/2024-01.csv.gz
```

---

## ⚠️ Important Notes

### 1. Timestamp is 60-Minute Bars
- Data is aggregated into 60-minute OHLC bars
- For more precise fills, interpolate or use bid/ask at bar close
- Market open: 09:30 ET, Close: 16:00 ET

### 2. SPX 0DTE Coverage
- **Before May 2022:** No data (0DTE didn't exist)
- **May 2022 - 2023:** Mon/Wed/Fri only (3× weekly)
- **2024+:** Daily (Mon-Fri)

### 3. Delta Sign Convention
- **Calls:** Positive delta (0 to +1)
- **Puts:** Negative delta (-1 to 0)

### 4. Bid/Ask for Realistic Fills
- **Buying (long):** Pay ask
- **Selling (short):** Receive bid
- **Spread credit:** `short_bid - long_ask`

### 5. Greeks Caveats
- Greeks are model-based (not exchange-calculated)
- May have outliers (validate before use)
- IV is in decimal form (0.15 = 15%)

---

## 🐛 Troubleshooting

### File Not Found
**Problem:** `FileNotFoundError` when loading a file

**Solution:** Check coverage matrix in `data/cboe_download_catalog.json`. Some months may not have data (e.g., SPX 0DTE before May 2022).

### Memory Error
**Problem:** `MemoryError` when loading large files

**Solution:** Use `chunksize` parameter:
```python
for chunk in pd.read_csv(file, compression="gzip", chunksize=10000):
    process(chunk)
```

### Invalid Delta Values
**Problem:** Delta outside expected range

**Solution:** Filter for reasonable values:
```python
df = df[(df["delta"] >= -1) & (df["delta"] <= 1)]
```

---

## 📚 Additional Resources

- **CBOE SPX Options:** https://www.cboe.com/spx
- **Pandas CSV Docs:** https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html
- **Options Greeks Primer:** https://www.cboe.com/education/greeks

---

**Last updated:** 2026-05-25
**Dataset version:** 2020-2025 complete
