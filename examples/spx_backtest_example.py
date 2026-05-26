"""
Example: SPX Credit Spread Backtest using CBOE DataProvider

This example demonstrates:
1. Setting up HybridDataProvider for SPX (CBOE) and SPY (IronVault)
2. Running a backtest on SPX using real CBOE option data
3. Analyzing Greeks for risk management
4. Comparing SPX vs SPY performance

Requirements:
  - AWS credentials configured (Athena access)
  - IronVault SQLite cache for SPY comparison (optional)

Usage:
  python examples/spx_backtest_example.py
"""
import logging
import os
from datetime import datetime

from backtest import Backtester
from backtest.hybrid_data_provider import HybridDataProvider
from backtest.historical_data import HistoricalOptionsData

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Run SPX backtest example."""
    
    # Check AWS credentials
    if not os.getenv("ATHENA_OUTPUT_BUCKET"):
        logger.error("ATHENA_OUTPUT_BUCKET not set. Please configure AWS credentials.")
        logger.info("export ATHENA_OUTPUT_BUCKET=s3://your-bucket/")
        return
    
    # Setup data providers
    logger.info("Setting up data providers...")
    
    # IronVault for SPY/QQQ (optional - only if you want to compare)
    ironvault = None
    if os.path.exists("data/polygon_cache.db"):
        ironvault = HistoricalOptionsData(db_path="data/polygon_cache.db")
        logger.info("IronVault loaded from data/polygon_cache.db")
    else:
        logger.warning("IronVault cache not found - SPY comparison will be skipped")
    
    # Hybrid provider (auto-routes SPX → CBOE, SPY → IronVault)
    provider = HybridDataProvider(
        ironvault_data=ironvault,
        cboe_database=os.getenv("ATHENA_DATABASE", "cboe"),
        cboe_output_bucket=os.getenv("ATHENA_OUTPUT_BUCKET"),
    )
    
    # Backtest configuration
    config = {
        'backtest': {
            'starting_capital': 100000,
            'ticker': 'SPX',  # ← Uses CBOE DataProvider
            'start_date': '2024-01-01',
            'end_date': '2024-03-31',  # Q1 2024 for quick test
        },
        'strategy': {
            'strategy_type': 'credit_spread',
            'credit_threshold_pct': 1.0,  # Min 1% credit
            'spread_width': 50,            # 50-point spread
            'target_dte': 45,              # 45 days to expiration
            'otm_pct': 0.05,               # 5% OTM short strike
        },
        'risk': {
            'max_risk_per_trade': 2.0,     # Max 2% portfolio risk per trade
        }
    }
    
    # Run backtest
    logger.info("Running SPX backtest (Q1 2024)...")
    logger.info("This will query CBOE data from Athena - may take a few minutes...")
    
    backtester = Backtester(config, historical_data=provider)
    results = backtester.run()
    
    # Display results
    print("\n" + "="*60)
    print("SPX CREDIT SPREAD BACKTEST RESULTS (Q1 2024)")
    print("="*60)
    print(f"Total Return:       {results['total_return']:>8.2%}")
    print(f"Win Rate:           {results['win_rate']:>8.2%}")
    print(f"Max Drawdown:       {results['max_drawdown']:>8.2%}")
    print(f"Sharpe Ratio:       {results.get('sharpe', 0):>8.2f}")
    print(f"Total Trades:       {results['total_trades']:>8d}")
    print(f"Winning Trades:     {results['winning_trades']:>8d}")
    print(f"Losing Trades:      {results['losing_trades']:>8d}")
    print(f"Final Capital:      ${results['final_capital']:>8,.2f}")
    print("="*60)
    
    # Greeks analysis example
    logger.info("\nQuerying Greeks for current SPX options...")
    
    try:
        greeks = provider.get_greeks(
            ticker="SPX",
            strike=5200,
            option_type="P",
            expiration="2024-03-15",
            date="2024-03-01"
        )
        
        if greeks:
            print("\nSPX 5200P Greeks (March 15, 2024 expiry, as of March 1):")
            print(f"  Delta: {greeks['delta']:>8.4f}")
            print(f"  Gamma: {greeks['gamma']:>8.6f}")
            print(f"  Theta: {greeks['theta']:>8.4f}")
            print(f"  Vega:  {greeks['vega']:>8.4f}")
    except Exception as e:
        logger.warning(f"Greeks query failed: {e}")
    
    # Compare SPX vs SPY (if IronVault is available)
    if ironvault:
        logger.info("\nComparing SPX (CBOE) vs SPY (IronVault)...")
        
        config_spy = {**config}
        config_spy['backtest']['ticker'] = 'SPY'
        config_spy['strategy']['spread_width'] = 5  # SPY uses 5-point spreads
        
        backtester_spy = Backtester(config_spy, historical_data=provider)
        results_spy = backtester_spy.run()
        
        print("\n" + "="*60)
        print("SPX vs SPY COMPARISON")
        print("="*60)
        print(f"{'Metric':<20} {'SPX':>15} {'SPY':>15}")
        print("-"*60)
        print(f"{'Total Return':<20} {results['total_return']:>14.2%} {results_spy['total_return']:>14.2%}")
        print(f"{'Win Rate':<20} {results['win_rate']:>14.2%} {results_spy['win_rate']:>14.2%}")
        print(f"{'Max Drawdown':<20} {results['max_drawdown']:>14.2%} {results_spy['max_drawdown']:>14.2%}")
        print(f"{'Sharpe Ratio':<20} {results.get('sharpe', 0):>14.2f} {results_spy.get('sharpe', 0):>14.2f}")
        print(f"{'Total Trades':<20} {results['total_trades']:>15d} {results_spy['total_trades']:>15d}")
        print("="*60)
    
    logger.info("\n✅ Backtest complete!")


if __name__ == "__main__":
    main()
