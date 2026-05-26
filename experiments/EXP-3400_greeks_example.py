"""
EXP-3400: Greeks Integration Example

Demonstrates how to use GreeksProvider for delta-based strike selection
in iron condor strategies.

This is an EXAMPLE showing the integration pattern. Real experiments
can adapt this for their specific use cases.

Example use case: Select 30Δ strikes for iron condor short puts
"""
import logging
from datetime import datetime

import pandas as pd

from compass.greeks_provider import GreeksProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def find_delta_strike(
    greeks_df: pd.DataFrame,
    target_delta: float,
    tolerance: float = 0.05
) -> dict:
    """
    Find the strike closest to a target delta.
    
    Args:
        greeks_df: DataFrame with columns [strike, delta, ...]
        target_delta: Target delta value (e.g., 0.30 for 30Δ)
        tolerance: Maximum acceptable deviation from target
        
    Returns:
        Dict with strike, actual_delta, and quality metrics
    """
    if greeks_df.empty:
        return None
    
    # Calculate absolute deviation from target
    greeks_df = greeks_df.copy()
    greeks_df["delta_abs"] = greeks_df["delta"].abs()
    greeks_df["deviation"] = (greeks_df["delta_abs"] - target_delta).abs()
    
    # Find best match
    best = greeks_df.loc[greeks_df["deviation"].idxmin()]
    
    if best["deviation"] > tolerance:
        logger.warning(
            f"Best match delta {best['delta']:.3f} exceeds tolerance "
            f"({best['deviation']:.3f} > {tolerance})"
        )
    
    return {
        "strike": best["strike"],
        "actual_delta": best["delta"],
        "deviation": best["deviation"],
        "bid": best.get("bid"),
        "ask": best.get("ask"),
    }


def example_iron_condor_strike_selection():
    """
    Example: Select strikes for SPY iron condor using Greeks.
    
    Strategy: 30Δ short put / 20Δ long put
    """
    logger.info("=== EXP-3400: Greeks Integration Example ===")
    
    # Initialize provider
    provider = GreeksProvider()
    
    # Parameters
    ticker = "SPY"
    expiration = "2024-03-15"
    trade_date = "2024-03-01"
    
    # Query Greeks for candidate strikes
    # For real strategies, get strikes from DataProvider.get_available_strikes()
    candidate_strikes = [490.0, 495.0, 500.0, 505.0, 510.0]
    
    logger.info(f"Querying Greeks for {ticker} {expiration} on {trade_date}")
    logger.info(f"Candidate strikes: {candidate_strikes}")
    
    greeks = provider.get_greeks(
        ticker=ticker,
        expiration=expiration,
        strikes=candidate_strikes,
        option_type="P",
        date=trade_date,
        interval="60min"
    )
    
    if greeks is None:
        logger.error("Failed to retrieve Greeks data")
        return
    
    logger.info(f"Retrieved Greeks for {len(greeks)} data points")
    
    # Use most recent timestamp (market close)
    latest_time = greeks["timestamp"].max()
    greeks_latest = greeks[greeks["timestamp"] == latest_time]
    
    logger.info(f"Using Greeks from {latest_time}")
    logger.info("\nAvailable strikes and deltas:")
    for _, row in greeks_latest.iterrows():
        logger.info(
            f"  {row['strike']:>6.1f}P: Δ={row['delta']:>6.3f}, "
            f"bid={row['bid']:>5.2f}, ask={row['ask']:>5.2f}"
        )
    
    # Find 30Δ strike for short put
    short_strike = find_delta_strike(greeks_latest, target_delta=0.30)
    
    if short_strike is None:
        logger.error("Could not find suitable short strike")
        return
    
    logger.info(f"\n✓ Selected SHORT strike: {short_strike['strike']}P")
    logger.info(f"  Actual delta: {short_strike['actual_delta']:.3f}")
    logger.info(f"  Bid/Ask: {short_strike['bid']:.2f}/{short_strike['ask']:.2f}")
    
    # Find 20Δ strike for long put
    long_strike = find_delta_strike(greeks_latest, target_delta=0.20)
    
    if long_strike is None:
        logger.error("Could not find suitable long strike")
        return
    
    logger.info(f"\n✓ Selected LONG strike: {long_strike['strike']}P")
    logger.info(f"  Actual delta: {long_strike['actual_delta']:.3f}")
    logger.info(f"  Bid/Ask: {long_strike['bid']:.2f}/{long_strike['ask']:.2f}")
    
    # Calculate spread properties
    spread_width = short_strike["strike"] - long_strike["strike"]
    logger.info(f"\n=== Iron Condor Put Spread ===")
    logger.info(f"Short: {short_strike['strike']}P @ 30Δ")
    logger.info(f"Long:  {long_strike['strike']}P @ 20Δ")
    logger.info(f"Width: ${spread_width:.2f}")
    
    return {
        "short_strike": short_strike,
        "long_strike": long_strike,
        "spread_width": spread_width,
    }


def example_analyze_greeks_distribution():
    """
    Example: Analyze Greeks distribution across strike range.
    
    Useful for understanding volatility smile, skew effects, etc.
    """
    logger.info("\n=== Greeks Distribution Analysis ===")
    
    provider = GreeksProvider()
    
    # Query wider strike range
    strikes = [490.0, 495.0, 500.0, 505.0, 510.0, 515.0, 520.0]
    
    greeks = provider.get_greeks(
        ticker="SPY",
        expiration="2024-03-15",
        strikes=strikes,
        option_type="P",
        date="2024-03-01"
    )
    
    if greeks is None:
        logger.error("Failed to retrieve Greeks data")
        return
    
    # Use latest timestamp
    latest = greeks[greeks["timestamp"] == greeks["timestamp"].max()]
    
    logger.info("\nGreeks by strike:")
    logger.info(
        f"{'Strike':>7} | {'Delta':>7} | {'Gamma':>7} | "
        f"{'Theta':>7} | {'Vega':>7}"
    )
    logger.info("-" * 50)
    
    for _, row in latest.sort_values("strike").iterrows():
        logger.info(
            f"{row['strike']:>7.1f} | "
            f"{row['delta']:>7.3f} | "
            f"{row['gamma']:>7.4f} | "
            f"{row['theta']:>7.3f} | "
            f"{row['vega']:>7.3f}"
        )
    
    # Calculate gamma skew
    gamma_mean = latest["gamma"].mean()
    gamma_std = latest["gamma"].std()
    
    logger.info(f"\nGamma distribution:")
    logger.info(f"  Mean: {gamma_mean:.4f}")
    logger.info(f"  Std:  {gamma_std:.4f}")
    
    return latest


def main():
    """Run all examples."""
    try:
        # Example 1: Strike selection
        result = example_iron_condor_strike_selection()
        
        if result:
            logger.info("\n✓ Strike selection completed successfully")
        
        # Example 2: Distribution analysis
        distribution = example_analyze_greeks_distribution()
        
        if distribution is not None:
            logger.info("\n✓ Distribution analysis completed successfully")
        
        logger.info("\n=== EXP-3400 Complete ===")
        
    except Exception as e:
        logger.error(f"Example failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
