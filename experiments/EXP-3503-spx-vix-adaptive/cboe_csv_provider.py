"""
Fast CSV-based CBOE data provider for backtesting.

Uses pre-downloaded CBOE CSV files instead of Athena queries.
100x faster than Athena for backtesting.
"""
from __future__ import annotations

import gzip
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class CBOECSVProvider:
    """
    Fast local CSV-based CBOE data provider.
    Compatible with CBOEDataProvider interface.
    """
    
    def __init__(self, data_dir: str = None):
        """
        Initialize CSV provider.
        
        Args:
            data_dir: Path to CBOE CSV data (default: ../../data/cboe_complete/spx/0dte/)
        """
        if data_dir is None:
            # Default to 0DTE data
            data_dir = Path(__file__).parent.parent.parent / "data" / "cboe_complete" / "spx" / "0dte"
        
        self.data_dir = Path(data_dir)
        if not self.data_dir.exists():
            raise ValueError(f"Data directory not found: {self.data_dir}")
        
        # Cache for loaded monthly data
        self._monthly_cache = {}
        
        logger.info(f"Initialized CSV provider with data dir: {self.data_dir}")
    
    def _load_month_data(self, year: int, month: int) -> pd.DataFrame:
        """Load and cache data for a specific month."""
        key = (year, month)
        
        if key in self._monthly_cache:
            return self._monthly_cache[key]
        
        # Find matching file
        pattern = f"{year:04d}-{month:02d}.csv.csv.gz"
        file_path = self.data_dir / pattern
        
        if not file_path.exists():
            logger.warning(f"No data file found for {year}-{month:02d}")
            return pd.DataFrame()
        
        # Load gzipped CSV
        logger.debug(f"Loading {file_path.name}...")
        df = pd.read_csv(file_path, compression='gzip')
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Cache it
        self._monthly_cache[key] = df
        
        return df
    
    def _get_data_for_date(self, date: str) -> pd.DataFrame:
        """Get all data for a specific date."""
        dt = datetime.strptime(date, "%Y-%m-%d")
        
        # Load month data
        df = self._load_month_data(dt.year, dt.month)
        
        if df.empty:
            return df
        
        # Filter to specific date
        df_date = df[df['timestamp'].dt.date == dt.date()].copy()
        
        return df_date
    
    def get_expirations(
        self,
        ticker: str,
        as_of_date: datetime,
        min_dte: int,
        max_dte: int,
    ) -> List[str]:
        """Get available expirations within DTE window."""
        date_str = as_of_date.strftime("%Y-%m-%d")
        df = self._get_data_for_date(date_str)
        
        if df.empty:
            return []
        
        # Get unique expirations
        expirations = df['expiration'].unique()
        
        # Filter by DTE
        result = []
        for exp in expirations:
            exp_date = datetime.strptime(exp, "%Y-%m-%d")
            dte = (exp_date.date() - as_of_date.date()).days
            
            if min_dte <= dte <= max_dte:
                result.append(exp)
        
        return sorted(result)
    
    def get_available_strikes(
        self,
        ticker: str,
        expiration: str,
        as_of_date: str,
        option_type: str = "P",
    ) -> List[float]:
        """Get available strikes for a given expiration on a specific date."""
        df = self._get_data_for_date(as_of_date)
        
        if df.empty:
            return []
        
        # Filter to expiration and option type
        mask = (df['expiration'] == expiration) & (df['option_type'] == option_type)
        strikes = df.loc[mask, 'strike'].unique()
        
        return sorted([float(s) for s in strikes])
    
    def get_greeks(
        self,
        ticker: str,
        strike: float,
        option_type: str,
        expiration: str,
        date: str,
    ) -> Optional[Dict[str, float]]:
        """Get Greeks for a specific option contract on a specific date."""
        df = self._get_data_for_date(date)
        
        if df.empty:
            return None
        
        # Filter to specific contract
        mask = (
            (df['expiration'] == expiration) &
            (df['strike'] == strike) &
            (df['option_type'] == option_type)
        )
        
        contract_data = df.loc[mask]
        
        if contract_data.empty:
            return None
        
        # Use last bar of the day (closest to market close / entry time)
        row = contract_data.iloc[-1]
        
        return {
            "delta": float(row["delta"]) if pd.notna(row["delta"]) else None,
            "gamma": float(row["gamma"]) if pd.notna(row["gamma"]) else None,
            "theta": float(row["theta"]) if pd.notna(row["theta"]) else None,
            "vega": float(row["vega"]) if pd.notna(row["vega"]) else None,
        }
    
    def get_spread_prices(
        self,
        ticker: str,
        expiration: str,
        short_strike: float,
        long_strike: float,
        option_type: str,
        date: str,
    ) -> Optional[Dict]:
        """Get spread prices for a specific date."""
        df = self._get_data_for_date(date)
        
        if df.empty:
            return None
        
        # Get short leg
        short_mask = (
            (df['expiration'] == expiration) &
            (df['strike'] == short_strike) &
            (df['option_type'] == option_type)
        )
        short_data = df.loc[short_mask]
        
        # Get long leg
        long_mask = (
            (df['expiration'] == expiration) &
            (df['strike'] == long_strike) &
            (df['option_type'] == option_type)
        )
        long_data = df.loc[long_mask]
        
        if short_data.empty or long_data.empty:
            logger.warning(
                f"Missing data for {option_type} spread {short_strike}/{long_strike} on {date}"
            )
            return None
        
        # Use last bar of the day
        short_row = short_data.iloc[-1]
        long_row = long_data.iloc[-1]
        
        # Return bid/ask for both legs
        return {
            "short_bid": float(short_row["bid_close"]),
            "short_ask": float(short_row["ask_close"]),
            "short_close": (float(short_row["bid_close"]) + float(short_row["ask_close"])) / 2.0,
            "long_bid": float(long_row["bid_close"]),
            "long_ask": float(long_row["ask_close"]),
            "long_close": (float(long_row["bid_close"]) + float(long_row["ask_close"])) / 2.0,
            "spread_value": (
                (float(short_row["bid_close"]) + float(short_row["ask_close"])) / 2.0 -
                (float(long_row["bid_close"]) + float(long_row["ask_close"])) / 2.0
            ),
        }
    
    def get_underlying_price(
        self,
        ticker: str,
        date: str,
    ) -> Optional[float]:
        """Get underlying price for SPX on a specific date."""
        df = self._get_data_for_date(date)
        
        if df.empty:
            return None
        
        # Get underlying price from any row (it's the same for all options)
        underlying = df.iloc[0]['underlying_price']
        
        if pd.isna(underlying):
            return None
        
        return float(underlying)
