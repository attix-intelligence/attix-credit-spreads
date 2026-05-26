"""
Bulk download CBOE SPX 0DTE data for fast backtesting.

Downloads all SPX 0DTE option data for 2023-2024:
- All strikes for Mon/Wed/Fri expirations
- Greeks (delta/gamma/theta/vega)
- Bid/ask spreads
- Stores in local DuckDB for offline access

Estimated runtime: 2 hours
Estimated cost: $5 in Athena queries
One-time operation per date range.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from compass.cboe_client import CBOEAthenaClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

CACHE_DB = ROOT / "shared" / "data" / "cboe_cache.duckdb"
CACHE_DB.parent.mkdir(parents=True, exist_ok=True)


def bulk_download_0dte_data(start_date: str, end_date: str):
    """Bulk download all SPX 0DTE data for date range."""
    
    logger.info("="*70)
    logger.info("CBOE SPX 0DTE DATA CACHE BUILDER")
    logger.info(f"Period: {start_date} to {end_date}")
    logger.info(f"Cache: {CACHE_DB}")
    logger.info("="*70)
    
    client = CBOEAthenaClient()
    
    # Generate Mon/Wed/Fri dates
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    
    trading_days = []
    current = start_dt
    while current <= end_dt:
        if current.strftime("%A") in ["Monday", "Wednesday", "Friday"]:
            trading_days.append(current)
        current += timedelta(days=1)
    
    logger.info(f"Total 0DTE days to download: {len(trading_days)}")
    
    # Connect to cache database
    con = duckdb.connect(str(CACHE_DB))
    
    # Create table
    con.execute("""
        CREATE TABLE IF NOT EXISTS spx_0dte_options (
            date DATE,
            expiration DATE,
            strike DOUBLE,
            option_type VARCHAR,
            delta DOUBLE,
            gamma DOUBLE,
            theta DOUBLE,
            vega DOUBLE,
            bid DOUBLE,
            ask DOUBLE,
            volume INTEGER,
            open_interest INTEGER,
            PRIMARY KEY (date, expiration, strike, option_type)
        )
    """)
    
    logger.info("Cache table ready")
    
    # Download each day
    for i, trade_date in enumerate(trading_days):
        date_str = trade_date.strftime("%Y-%m-%d")
        
        logger.info(f"\n[{i+1}/{len(trading_days)}] Downloading {date_str}...")
        
        # Query all options for this 0DTE
        year = trade_date.year
        month = trade_date.month
        day = trade_date.day
        
        query = f"""
        SELECT
            date '{date_str}' as date,
            expiration,
            strike,
            option_type,
            delta,
            gamma,
            theta,
            vega,
            bid_close as bid,
            ask_close as ask,
            trade_volume as volume,
            open_interest
        FROM cboe_60min_option_candles
        WHERE year = '{year:04d}'
          AND month = '{month:02d}'
          AND day = '{day:02d}'
          AND symbol = '^SPX'
          AND expiration = date '{date_str}'
          AND quote_timestamp >= timestamp '{date_str} 09:30:00'
          AND quote_timestamp <= timestamp '{date_str} 16:00:00'
        """
        
        try:
            df = client._execute_query(query)
            
            if df.empty:
                logger.warning(f"  No data for {date_str}")
                continue
            
            # Insert into cache
            con.execute("INSERT OR REPLACE INTO spx_0dte_options SELECT * FROM df")
            
            logger.info(f"  ✓ Cached {len(df)} rows")
            
        except Exception as e:
            logger.error(f"  ✗ Error: {e}")
            continue
        
        # Progress report every 20 days
        if (i + 1) % 20 == 0:
            count = con.execute("SELECT COUNT(*) FROM spx_0dte_options").fetchone()[0]
            logger.info(f"\nProgress: {i+1}/{len(trading_days)} days | Total rows: {count:,}\n")
    
    # Final stats
    count = con.execute("SELECT COUNT(*) FROM spx_0dte_options").fetchone()[0]
    dates = con.execute("SELECT COUNT(DISTINCT date) FROM spx_0dte_options").fetchone()[0]
    strikes = con.execute("SELECT COUNT(DISTINCT strike) FROM spx_0dte_options").fetchone()[0]
    
    logger.info("="*70)
    logger.info("CACHE BUILD COMPLETE")
    logger.info(f"  Total rows: {count:,}")
    logger.info(f"  Unique dates: {dates}")
    logger.info(f"  Unique strikes: {strikes}")
    logger.info(f"  Cache file: {CACHE_DB}")
    logger.info(f"  Size: {CACHE_DB.stat().st_size / 1024 / 1024:.1f} MB")
    logger.info("="*70)
    
    con.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Cache CBOE SPX 0DTE data")
    parser.add_argument("--start", default="2023-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2024-12-31", help="End date (YYYY-MM-DD)")
    
    args = parser.parse_args()
    
    bulk_download_0dte_data(args.start, args.end)
