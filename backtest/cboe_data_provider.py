"""
CBOE DataProvider for SPX option backtesting.

Uses CBOE's Athena dataset for:
  - OHLC candles (bid/ask for fills)
  - Greeks (delta/gamma/theta/vega)
  - Volume and underlying price

Key differences from IronVault (HistoricalOptionsData):
  - CBOE uses ^SPX ticker (with caret)
  - 60-minute bars (not daily) - need aggregation
  - Direct AWS Athena queries (no SQLite cache)
  - Built-in Greeks (no separate GreeksProvider needed)

Cost control:
  - No caching (per Carlos)
  - Partition pruning by year/month/day
  - Batch queries where possible
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from compass.cboe_client import CBOEAthenaClient

logger = logging.getLogger(__name__)


class CBOEDataProvider:
    """
    DataProvider implementation for SPX using CBOE Athena data.
    
    Implements same interface as HistoricalOptionsData for drop-in compatibility.
    """
    
    def __init__(self, database: str = None, output_bucket: str = None):
        """
        Initialize CBOE data provider.
        
        Args:
            database: Athena database name (default: "cboe")
            output_bucket: S3 bucket for query results (e.g., "s3://cboe-athena-results/")
        """
        self.client = CBOEAthenaClient(database=database, output_bucket=output_bucket)
        self._ticker_map = {
            "SPX": "^SPX",  # CBOE uses ^SPX
            "^SPX": "^SPX",
        }
    
    def _normalize_ticker(self, ticker: str) -> str:
        """Convert SPX → ^SPX for CBOE queries."""
        return self._ticker_map.get(ticker.upper(), ticker)
    
    def get_spread_prices(
        self,
        ticker: str,
        expiration: datetime | str,
        short_strike: float,
        long_strike: float,
        option_type: str,
        date: datetime | str,
    ) -> Optional[Dict]:
        """
        Get spread prices for a specific date (compatible with HistoricalOptionsData).
        
        Returns:
            Dict with keys: short_close, long_close, spread_value
            None if data unavailable
        """
        cboe_ticker = self._normalize_ticker(ticker)
        
        # Normalize inputs
        if isinstance(expiration, datetime):
            exp_str = expiration.strftime("%Y-%m-%d")
        else:
            exp_str = expiration
        
        if isinstance(date, datetime):
            date_str = date.strftime("%Y-%m-%d")
        else:
            date_str = date
        
        # Query both legs
        try:
            short_data = self._get_option_data(
                ticker=cboe_ticker,
                strike=short_strike,
                option_type=option_type,
                expiration=exp_str,
                start_date=date_str,
                end_date=date_str,
            )
            
            long_data = self._get_option_data(
                ticker=cboe_ticker,
                strike=long_strike,
                option_type=option_type,
                expiration=exp_str,
                start_date=date_str,
                end_date=date_str,
            )
            
            if short_data.empty or long_data.empty:
                logger.warning(
                    "Missing data for %s %s spread %s/%s on %s",
                    ticker, option_type, short_strike, long_strike, date_str
                )
                return None
            
            # Use last bar of the day (closest to market close)
            short_price = (short_data.iloc[-1]["bid"] + short_data.iloc[-1]["ask"]) / 2.0
            long_price = (long_data.iloc[-1]["bid"] + long_data.iloc[-1]["ask"]) / 2.0
            
            return {
                "short_close": short_price,
                "long_close": long_price,
                "spread_value": short_price - long_price,  # credit = short - long
                "short_bid": short_data.iloc[-1]["bid"],
                "short_ask": short_data.iloc[-1]["ask"],
                "long_bid": long_data.iloc[-1]["bid"],
                "long_ask": long_data.iloc[-1]["ask"],
            }
        
        except Exception as e:
            logger.error("Error fetching spread prices: %s", e, exc_info=True)
            return None
    
    def _get_option_data(
        self,
        ticker: str,
        strike: float,
        option_type: str,
        expiration: str,
        start_date: str,
        end_date: str,
        interval: str = "60min",
    ) -> pd.DataFrame:
        """
        Get OHLC + Greeks for a specific option contract.
        
        Returns DataFrame with: timestamp, bid, ask, delta, gamma, theta, vega, volume, underlying_price
        """
        return self.client.query_greeks(
            ticker=ticker,
            expiration=expiration,
            strike=strike,
            option_type=option_type,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )
    
    def get_available_strikes(
        self,
        ticker: str,
        expiration: str,
        as_of_date: str,
        option_type: str = "P",
    ) -> List[float]:
        """
        Get available strikes for a given expiration on a specific date.
        
        Args:
            ticker: SPX (will be converted to ^SPX)
            expiration: YYYY-MM-DD format
            as_of_date: YYYY-MM-DD format
            option_type: "P" or "C"
        
        Returns:
            List of strike prices (sorted)
        """
        cboe_ticker = self._normalize_ticker(ticker)
        
        # Query distinct strikes from CBOE
        try:
            # Extract date components for partition pruning
            if isinstance(as_of_date, datetime):
                date_dt = as_of_date
            else:
                date_dt = datetime.strptime(as_of_date.split()[0], "%Y-%m-%d")
            
            if isinstance(expiration, datetime):
                exp_dt = expiration
                expiration = expiration.strftime("%Y-%m-%d")
            else:
                exp_dt = datetime.strptime(expiration.split()[0], "%Y-%m-%d")
            
            query = f"""
            SELECT DISTINCT strike
            FROM cboe_60min_option_candles
            WHERE year = '{date_dt.year:04d}'
              AND month = '{date_dt.month:02d}'
              AND day = '{date_dt.day:02d}'
              AND symbol = '{cboe_ticker}'
              AND expiration = date '{expiration}'
              AND option_type = '{option_type}'
            ORDER BY strike
            """
            
            df = self.client._execute_query(query)
            
            if df.empty:
                logger.warning(
                    "No strikes found for %s %s %s on %s",
                    ticker, option_type, expiration, as_of_date
                )
                return []
            
            return [float(x) for x in df["strike"].tolist()]
        
        except Exception as e:
            logger.error("Error fetching available strikes: %s", e, exc_info=True)
            return []
    
    def get_expirations(
        self,
        ticker: str,
        as_of_date: datetime,
        min_dte: int,
        max_dte: int,
    ) -> List[str]:
        """
        Get available expirations within DTE window.
        
        Args:
            ticker: SPX (will be converted to ^SPX)
            as_of_date: Reference date
            min_dte: Minimum days to expiration
            max_dte: Maximum days to expiration
        
        Returns:
            List of expiration dates in YYYY-MM-DD format (sorted)
        """
        cboe_ticker = self._normalize_ticker(ticker)
        
        try:
            date_str = as_of_date.strftime("%Y-%m-%d")
            date_dt = datetime.strptime(date_str, "%Y-%m-%d")
            
            # Calculate date range for query
            min_exp = date_dt + timedelta(days=min_dte)
            max_exp = date_dt + timedelta(days=max_dte)
            
            query = f"""
            SELECT DISTINCT expiration
            FROM cboe_60min_option_candles
            WHERE year = '{date_dt.year:04d}'
              AND month = '{date_dt.month:02d}'
              AND day = '{date_dt.day:02d}'
              AND symbol = '{cboe_ticker}'
              AND expiration >= date '{min_exp.strftime("%Y-%m-%d")}'
              AND expiration <= date '{max_exp.strftime("%Y-%m-%d")}'
            ORDER BY expiration
            """
            
            df = self.client._execute_query(query)
            
            if df.empty:
                logger.warning(
                    "No expirations found for %s between %d-%d DTE on %s",
                    ticker, min_dte, max_dte, date_str
                )
                return []
            
            return df["expiration"].tolist()
        
        except Exception as e:
            logger.error("Error fetching expirations: %s", e, exc_info=True)
            return []
    
    def get_greeks(
        self,
        ticker: str,
        strike: float,
        option_type: str,
        expiration: str,
        date: str,
    ) -> Optional[Dict[str, float]]:
        """
        Get Greeks for a specific option contract on a specific date.
        
        Returns:
            Dict with keys: delta, gamma, theta, vega
            None if data unavailable
        """
        cboe_ticker = self._normalize_ticker(ticker)
        
        try:
            df = self._get_option_data(
                ticker=cboe_ticker,
                strike=strike,
                option_type=option_type,
                expiration=expiration,
                start_date=date,
                end_date=date,
            )
            
            if df.empty:
                return None
            
            # Use last bar of the day
            row = df.iloc[-1]
            
            return {
                "delta": float(row["delta"]) if pd.notna(row["delta"]) else None,
                "gamma": float(row["gamma"]) if pd.notna(row["gamma"]) else None,
                "theta": float(row["theta"]) if pd.notna(row["theta"]) else None,
                "vega": float(row["vega"]) if pd.notna(row["vega"]) else None,
            }
        
        except Exception as e:
            logger.error("Error fetching Greeks: %s", e, exc_info=True)
            return None
    
    def get_underlying_price(
        self,
        ticker: str,
        date: datetime | str,
    ) -> Optional[float]:
        """
        Get underlying price for SPX on a specific date.
        
        Uses the underlying_price field from CBOE option data.
        """
        cboe_ticker = self._normalize_ticker(ticker)
        
        if isinstance(date, datetime):
            date_str = date.strftime("%Y-%m-%d")
        else:
            date_str = date
        
        try:
            date_dt = datetime.strptime(date_str.split()[0], "%Y-%m-%d")
            
            # Query any option contract to get underlying price
            query = f"""
            SELECT underlying_price
            FROM cboe_60min_option_candles
            WHERE year = '{date_dt.year:04d}'
              AND month = '{date_dt.month:02d}'
              AND day = '{date_dt.day:02d}'
              AND symbol = '{cboe_ticker}'
            LIMIT 1
            """
            
            df = self.client._execute_query(query)
            
            if df.empty or pd.isna(df.iloc[0]["underlying_price"]):
                return None
            
            return float(df.iloc[0]["underlying_price"])
        
        except Exception as e:
            logger.error("Error fetching underlying price: %s", e, exc_info=True)
            return None
