"""
Greeks Provider - CBOE Athena Integration

Provides option Greeks (delta, gamma, theta, vega) from CBOE Athena.

This is a SEPARATE interface from DataProvider to maintain clean separation
between pricing (IronVault) and Greeks (CBOE).

Usage:
    provider = GreeksProvider()
    greeks = provider.get_greeks(
        ticker="SPY",
        expiration="2024-03-15",
        strikes=[500.0, 505.0, 510.0],
        option_type="P",
        date="2024-03-01"
    )

Rule Zero: This ONLY provides Greeks, never prices. IronVault remains the
source of truth for all entry/exit pricing.
"""
import logging
from typing import List, Optional

import pandas as pd

from compass.cboe_client import CBOEAthenaClient

logger = logging.getLogger(__name__)


class GreeksProvider:
    """Opt-in provider for option Greeks from CBOE Athena."""

    def __init__(self):
        """Initialize Greeks provider with CBOE Athena client."""
        self.client = CBOEAthenaClient()
        logger.info("GreeksProvider initialized with CBOE Athena client")

    def get_greeks(
        self,
        ticker: str,
        expiration: str,
        strikes: List[float],
        option_type: str,
        date: str,
        interval: str = "60min"
    ) -> Optional[pd.DataFrame]:
        """
        Get Greeks for multiple strikes at a specific date.

        Args:
            ticker: Underlying ticker (e.g., "SPY", "SPX")
            expiration: Option expiration date (YYYY-MM-DD format)
            strikes: List of strikes to query
            option_type: "C" for calls, "P" for puts
            date: Query date (YYYY-MM-DD format)
            interval: Data interval ("1min", "5min", "15min", "60min")

        Returns:
            DataFrame with columns:
                strike, delta, gamma, theta, vega, timestamp, bid, ask
            Returns None if data unavailable or error occurs.

        Note:
            - Queries CBOE Athena directly (no cache per Carlos)
            - Logs bytes scanned for cost tracking
            - Handles errors gracefully (returns None, doesn't crash)
        """
        if not strikes:
            logger.warning("No strikes provided to get_greeks()")
            return None

        # Convert date to start/end range (query full day)
        start_date = f"{date} 00:00:00"
        end_date = f"{date} 23:59:59"

        all_data = []

        for strike in strikes:
            try:
                logger.debug(
                    f"Querying Greeks: {ticker} {expiration} {strike}{option_type} @ {date}"
                )
                
                df = self.client.query_greeks(
                    ticker=ticker,
                    expiration=expiration,
                    strike=strike,
                    option_type=option_type,
                    start_date=start_date,
                    end_date=end_date,
                    interval=interval
                )

                if df.empty:
                    logger.warning(
                        f"No Greeks data found for {ticker} {strike}{option_type} @ {date}"
                    )
                    continue

                # Add strike column
                df["strike"] = strike
                all_data.append(df)

            except Exception as e:
                logger.error(
                    f"Error querying Greeks for {ticker} {strike}{option_type}: {e}",
                    exc_info=True
                )
                # Continue with other strikes even if one fails
                continue

        if not all_data:
            logger.warning(
                f"No Greeks data retrieved for any strikes: {ticker} {expiration} @ {date}"
            )
            return None

        # Concatenate all strikes
        result = pd.concat(all_data, ignore_index=True)

        # Reorder columns for clarity
        columns = ["strike", "timestamp", "delta", "gamma", "theta", "vega", "bid", "ask"]
        # Keep only columns that exist
        columns = [c for c in columns if c in result.columns]
        result = result[columns]

        logger.info(
            f"Retrieved Greeks for {len(strikes)} strikes: "
            f"{len(result)} total data points"
        )

        return result

    def get_greeks_single_strike(
        self,
        ticker: str,
        expiration: str,
        strike: float,
        option_type: str,
        date: str,
        interval: str = "60min"
    ) -> Optional[pd.DataFrame]:
        """
        Get Greeks for a single strike (convenience wrapper).

        Returns:
            DataFrame with columns: timestamp, delta, gamma, theta, vega, bid, ask
            Returns None if data unavailable.
        """
        result = self.get_greeks(
            ticker=ticker,
            expiration=expiration,
            strikes=[strike],
            option_type=option_type,
            date=date,
            interval=interval
        )

        if result is None:
            return None

        # Drop strike column since it's redundant for single strike
        if "strike" in result.columns:
            result = result.drop(columns=["strike"])

        return result
