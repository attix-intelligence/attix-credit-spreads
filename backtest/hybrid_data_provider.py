"""
Hybrid DataProvider - Auto-routing based on ticker.

Routes to the correct DataProvider implementation:
  - SPX → CBOEDataProvider (Athena)
  - SPY, QQQ, etc. → HistoricalOptionsData (IronVault SQLite)

Backward compatible: existing experiments work unchanged.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class HybridDataProvider:
    """
    Router that automatically selects the correct DataProvider based on ticker.
    
    Usage:
        # In backtester initialization:
        from backtest.hybrid_data_provider import HybridDataProvider
        
        provider = HybridDataProvider(
            ironvault_data=historical_data,  # existing HistoricalOptionsData
            cboe_database="cboe",
            cboe_output_bucket="s3://cboe-athena-results/"
        )
        
        # Backtester uses provider.get_spread_prices() as usual
        # SPX → CBOE, SPY → IronVault (automatic)
    """
    
    def __init__(
        self,
        ironvault_data=None,
        cboe_database: str = None,
        cboe_output_bucket: str = None,
    ):
        """
        Initialize hybrid provider.
        
        Args:
            ironvault_data: HistoricalOptionsData instance for SPY/QQQ/etc
            cboe_database: Athena database name for CBOE (default: "cboe")
            cboe_output_bucket: S3 bucket for CBOE query results
        """
        self.ironvault_data = ironvault_data
        
        # Lazy-load CBOE provider (only if SPX is queried)
        self._cboe_provider = None
        self._cboe_database = cboe_database
        self._cboe_output_bucket = cboe_output_bucket
        
        # Ticker routing table
        self._cboe_tickers = {"SPX", "^SPX", "SPXW"}  # SPX and related tickers
    
    def _get_cboe_provider(self):
        """Lazy-load CBOE provider on first SPX query."""
        if self._cboe_provider is None:
            from backtest.cboe_data_provider import CBOEDataProvider
            
            logger.info("Initializing CBOE DataProvider for SPX")
            self._cboe_provider = CBOEDataProvider(
                database=self._cboe_database,
                output_bucket=self._cboe_output_bucket,
            )
        return self._cboe_provider
    
    def _route_ticker(self, ticker: str):
        """Return appropriate provider for ticker."""
        ticker_upper = ticker.upper()
        
        if ticker_upper in self._cboe_tickers:
            return self._get_cboe_provider()
        else:
            if self.ironvault_data is None:
                raise ValueError(
                    f"No IronVault data provider configured for ticker {ticker}. "
                    f"Only SPX is available via CBOE."
                )
            return self.ironvault_data
    
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
        Get spread prices - auto-routes to correct provider.
        
        Returns:
            Dict with keys: short_close, long_close, spread_value
            None if data unavailable
        """
        provider = self._route_ticker(ticker)
        return provider.get_spread_prices(
            ticker=ticker,
            expiration=expiration,
            short_strike=short_strike,
            long_strike=long_strike,
            option_type=option_type,
            date=date,
        )
    
    def get_available_strikes(
        self,
        ticker: str,
        expiration: str,
        as_of_date: str,
        option_type: str = "P",
    ) -> List[float]:
        """Get available strikes - auto-routes to correct provider."""
        provider = self._route_ticker(ticker)
        return provider.get_available_strikes(
            ticker=ticker,
            expiration=expiration,
            as_of_date=as_of_date,
            option_type=option_type,
        )
    
    def get_expirations(
        self,
        ticker: str,
        as_of_date: datetime,
        min_dte: int,
        max_dte: int,
    ) -> List[str]:
        """Get available expirations - auto-routes to correct provider."""
        provider = self._route_ticker(ticker)
        return provider.get_expirations(
            ticker=ticker,
            as_of_date=as_of_date,
            min_dte=min_dte,
            max_dte=max_dte,
        )
    
    def get_greeks(
        self,
        ticker: str,
        strike: float,
        option_type: str,
        expiration: str,
        date: str,
    ) -> Optional[Dict[str, float]]:
        """
        Get Greeks for a specific option contract.
        
        Only available for SPX (CBOE). Returns None for other tickers.
        """
        provider = self._route_ticker(ticker)
        
        # Check if provider has get_greeks method (CBOE does, IronVault doesn't)
        if hasattr(provider, "get_greeks"):
            return provider.get_greeks(
                ticker=ticker,
                strike=strike,
                option_type=option_type,
                expiration=expiration,
                date=date,
            )
        else:
            logger.debug("Greeks not available for ticker %s (IronVault provider)", ticker)
            return None
    
    def get_underlying_price(
        self,
        ticker: str,
        date: datetime | str,
    ) -> Optional[float]:
        """Get underlying price - auto-routes to correct provider."""
        provider = self._route_ticker(ticker)
        
        # Check if provider has get_underlying_price method
        if hasattr(provider, "get_underlying_price"):
            return provider.get_underlying_price(ticker=ticker, date=date)
        else:
            return None
