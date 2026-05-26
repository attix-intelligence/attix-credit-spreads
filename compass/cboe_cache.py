"""
CBOE Data Cache (DuckDB)

Local cache to avoid repeated Athena queries ($5/TB adds up fast).
Stores Greeks + bid/ask data in DuckDB for instant retrieval.
"""
import logging
import os
from datetime import datetime
from typing import Optional

import duckdb
import pandas as pd

from compass.cboe_client import CBOEAthenaClient

logger = logging.getLogger(__name__)


class CBOECache:
    """DuckDB-backed cache for CBOE options data."""
    
    def __init__(self, cache_path: str = None, client: CBOEAthenaClient = None):
        # Default to shared/data/cboe_cache.duckdb
        if cache_path is None:
            shared_data_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), 
                "shared", 
                "data"
            )
            os.makedirs(shared_data_dir, exist_ok=True)
            cache_path = os.path.join(shared_data_dir, "cboe_cache.duckdb")
        
        self.cache_path = cache_path
        self.client = client or CBOEAthenaClient()
        
        # DuckDB connection (auto-creates DB file)
        self.conn = duckdb.connect(self.cache_path)
        self._init_schema()
    
    def _init_schema(self):
        """Create cache table if not exists."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS greeks (
                ticker VARCHAR,
                expiration DATE,
                strike DOUBLE,
                option_type VARCHAR,
                timestamp TIMESTAMP,
                bid DOUBLE,
                ask DOUBLE,
                delta DOUBLE,
                gamma DOUBLE,
                theta DOUBLE,
                vega DOUBLE,
                volume BIGINT,
                underlying_price DOUBLE,
                PRIMARY KEY (ticker, expiration, strike, option_type, timestamp)
            )
        """)
    
    def get_greeks(
        self,
        ticker: str,
        expiration: str,
        strike: float,
        option_type: str,
        start_date: str,
        end_date: str,
        interval: str = "60min",
    ) -> pd.DataFrame:
        """
        Get Greeks from cache. On miss, fetch from Athena and cache.
        """
        # Check cache - convert expiration string to date for comparison
        from datetime import datetime
        exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
        
        # Handle both "YYYY-MM-DD" and "YYYY-MM-DD HH:MM:SS" formats
        if ' ' not in start_date:
            start_dt = datetime.fromisoformat(f"{start_date}T00:00:00")
            end_dt = datetime.fromisoformat(f"{end_date}T23:59:59")
        else:
            start_dt = datetime.fromisoformat(start_date.replace(' ', 'T'))
            end_dt = datetime.fromisoformat(end_date.replace(' ', 'T'))
        
        query = """
        SELECT * FROM greeks
        WHERE ticker = ?
          AND expiration = ?
          AND strike = ?
          AND option_type = ?
          AND timestamp BETWEEN ? AND ?
        ORDER BY timestamp
        """
        
        cached = self.conn.execute(
            query,
            [ticker, exp_date, strike, option_type, start_dt, end_dt]
        ).fetchdf()
        
        if not cached.empty:
            logger.debug(f"CBOE cache hit: {ticker} {expiration} {strike}{option_type}")
            return cached
        
        # Cache miss — fetch from Athena
        logger.info(f"CBOE cache miss: fetching from Athena for {ticker} {expiration} {strike}{option_type}")
        
        df = self.client.query_greeks(
            ticker, expiration, strike, option_type, start_date, end_date, interval
        )
        
        if df.empty:
            logger.warning(f"Athena returned no data for {ticker} {expiration} {strike}{option_type}")
            return df
        
        # Insert into cache - reorder columns to match schema
        df_insert = df[[
            "timestamp", "bid", "ask", "delta", "gamma", "theta", "vega", 
            "volume", "underlying_price"
        ]].copy()
        df_insert["ticker"] = ticker
        df_insert["expiration"] = exp_date  # Use converted date
        df_insert["strike"] = strike
        df_insert["option_type"] = option_type
        
        # Reorder to match table schema
        df_insert = df_insert[[
            "ticker", "expiration", "strike", "option_type", "timestamp",
            "bid", "ask", "delta", "gamma", "theta", "vega", "volume", "underlying_price"
        ]]
        
        self.conn.execute("INSERT INTO greeks SELECT * FROM df_insert")
        self.conn.commit()
        
        logger.info(f"Cached {len(df)} rows for {ticker} {expiration} {strike}{option_type}")
        return df
    
    def coverage_report(self) -> dict:
        """Return cache statistics."""
        stats = self.conn.execute("""
            SELECT
                ticker,
                COUNT(DISTINCT expiration) as expirations,
                COUNT(*) as rows,
                MIN(timestamp) as earliest,
                MAX(timestamp) as latest
            FROM greeks
            GROUP BY ticker
        """).fetchdf()
        
        return stats.to_dict("records")
