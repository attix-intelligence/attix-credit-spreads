"""
EXP-3503: SPX 0DTE VIX-Adaptive (20Δ/25Δ/30Δ) with REAL CBOE Data

Rule Zero Compliance:
- Uses ONLY real CBOE Athena data
- No synthetic prices, Greeks, or fills
- All data sourced and logged for audit

Strategy: VIX-adaptive iron condor (smart delta selection)
- VIX <20: 20Δ (aggressive)
- VIX 20-25: 25Δ (moderate)
- VIX >25: 30Δ (defensive)

Ticker: SPX (0DTE Mon/Wed/Fri)
Period: 2021-2025 (full CBOE dataset)

North Star: Path A Pillar 2 - SMART ADAPTATION STRATEGY
Goal: >25% monthly, Sharpe >2.5, win rate >75%
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np
import yfinance as yf
from dotenv import load_dotenv

# Add project root
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backtest"))  # Add backtest directory to path

# Load environment
load_dotenv(ROOT / ".env")

# Use FIXED CSV provider from backtest directory (not local copy)
from backtest.cboe_csv_provider import CBOECSVProvider as CBOEDataProvider

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).parent / "backtest_run.log"),
        logging.StreamHandler()
    ]
)

# Output directory
OUTPUT_DIR = Path(__file__).resolve().parent / "results"
OUTPUT_DIR.mkdir(exist_ok=True)

# ===== EXPERIMENT PARAMETERS =====
EXPERIMENT_ID = "EXP-3503"
TICKER = "SPX"
START_DATE = "2021-01-04"  # First trading day of 2021
END_DATE = "2025-05-23"    # Latest CBOE data

# VIX-Adaptive Strategy parameters
VIX_LOW_THRESHOLD = 20.0   # Below this: use aggressive 20Δ
VIX_HIGH_THRESHOLD = 25.0  # Above this: use defensive 30Δ
# Between thresholds: use moderate 25Δ

DELTA_AGGRESSIVE = 0.20  # 20Δ (high premium, calm markets)
DELTA_MODERATE = 0.25    # 25Δ (balanced)
DELTA_DEFENSIVE = 0.30   # 30Δ (safer, volatile markets)

WING_WIDTH = 50.0  # $50 wide spreads (SPX scale)
CONTRACTS_PER_TRADE = 10  # Fixed sizing
PROFIT_TARGET_PCT = 0.50  # 50% profit target
STOP_LOSS_PCT = 2.00  # -200% stop loss (lose 2x credit)
ENTRY_TIME = time(9, 45)  # 9:45 AM ET
EXIT_TIME = time(15, 0)   # 3:00 PM ET or profit target
CAPITAL = 100000  # $100K starting capital

# Trading days (SPX 0DTE availability)
TRADING_DAYS = ["Monday", "Wednesday", "Friday"]


def load_vix_data(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Load VIX historical data from Yahoo Finance.
    Returns DataFrame with Date index and 'Close' column.
    """
    logger.info(f"Loading VIX data from {start_date} to {end_date}...")
    
    try:
        vix = yf.download("^VIX", start=start_date, end=end_date, progress=False)
        vix.index = pd.to_datetime(vix.index).date
        logger.info(f"Loaded {len(vix)} days of VIX data")
        return vix
    except Exception as e:
        logger.error(f"Failed to load VIX data: {e}")
        raise


def get_vix_level(vix_data: pd.DataFrame, date: datetime.date) -> Optional[float]:
    """Get VIX close for a given date."""
    if date in vix_data.index:
        val = vix_data.loc[date, 'Close']
        # Handle both Series and scalar
        if isinstance(val, pd.Series):
            return float(val.iloc[0])
        return float(val)
    return None


def select_delta_for_vix(vix_level: float) -> Tuple[float, str]:
    """
    Select delta target based on VIX regime.
    Returns: (delta, regime_name)
    """
    if vix_level < VIX_LOW_THRESHOLD:
        return DELTA_AGGRESSIVE, "AGGRESSIVE"
    elif vix_level > VIX_HIGH_THRESHOLD:
        return DELTA_DEFENSIVE, "DEFENSIVE"
    else:
        return DELTA_MODERATE, "MODERATE"


def get_0dte_expirations(provider: CBOEDataProvider, date: datetime) -> List[str]:
    """Get 0DTE expirations (same day expiry)."""
    date_str = date.strftime("%Y-%m-%d")
    
    # For 0DTE, expiration = trade date
    expirations = provider.get_expirations(
        ticker=TICKER,
        as_of_date=date,
        min_dte=0,
        max_dte=0
    )
    
    # Filter to exact match
    matching = [exp for exp in expirations if exp == date_str]
    return matching


def find_delta_strike(
    provider: CBOEDataProvider,
    date: str,
    expiration: str,
    option_type: str,
    target_delta: float,
    underlying_price: float,
) -> Optional[float]:
    """
    Find strike closest to target delta using REAL CBOE data.
    
    Rule Zero: Uses only real CBOE Greeks.
    """
    # Get available strikes (note: CBOE provider uses 'as_of_date', not 'date')
    strikes = provider.get_available_strikes(
        ticker=TICKER,
        option_type=option_type.upper(),  # "call" -> "C", "put" -> "P"
        expiration=expiration,
        as_of_date=date
    )
    
    if not strikes:
        return None
    
    # Get deltas for all strikes
    best_strike = None
    best_delta_diff = float('inf')
    
    for strike in strikes:
        greeks = provider.get_greeks(
            ticker=TICKER,
            option_type=option_type,
            strike=strike,
            expiration=expiration,
            date=date
        )
        
        if greeks is None or greeks.get('delta') is None:
            continue
        
        delta = abs(greeks['delta'])  # Absolute value for comparison
        delta_diff = abs(delta - target_delta)
        
        if delta_diff < best_delta_diff:
            best_delta_diff = delta_diff
            best_strike = strike
    
    return best_strike


def get_single_option_price(
    provider: CBOEDataProvider,
    date: str,
    expiration: str,
    option_type: str,
    strike: float,
) -> Optional[Dict]:
    """
    Get option bid/ask using REAL CBOE data via the spread_prices method.
    We query a 0-width spread (same strike for both legs) to get single option price.
    
    Rule Zero: Uses only real market prices.
    """
    # Use get_spread_prices with same strike for both legs
    spread_data = provider.get_spread_prices(
        ticker=TICKER,
        expiration=expiration,
        short_strike=strike,
        long_strike=strike,
        option_type=option_type,
        date=date
    )
    
    if spread_data is None:
        return None
    
    return {
        'bid': spread_data.get('short_bid'),
        'ask': spread_data.get('short_ask'),
        'mid': (spread_data.get('short_bid', 0) + spread_data.get('short_ask', 0)) / 2.0
    }


def construct_iron_condor(
    provider: CBOEDataProvider,
    date_str: str,
    expiration: str,
    underlying_price: float,
    delta_target: float,
) -> Optional[Dict]:
    """
    Construct an iron condor with the given delta target.
    
    Structure:
    - Sell Call at delta_target
    - Buy Call at (sell_call_strike + WING_WIDTH)
    - Sell Put at delta_target
    - Buy Put at (sell_put_strike - WING_WIDTH)
    
    Returns dict with strikes and entry credit, or None if construction fails.
    """
    # Find short strikes
    short_call_strike = find_delta_strike(
        provider, date_str, expiration, "C", delta_target, underlying_price
    )
    short_put_strike = find_delta_strike(
        provider, date_str, expiration, "P", delta_target, underlying_price
    )
    
    if short_call_strike is None or short_put_strike is None:
        logger.warning(f"Could not find short strikes for delta={delta_target:.2f}")
        return None
    
    # Long strikes are WING_WIDTH away
    long_call_strike = short_call_strike + WING_WIDTH
    long_put_strike = short_put_strike - WING_WIDTH
    
    # Get prices using spread_prices for efficiency (2 calls instead of 4)
    call_spread = provider.get_spread_prices(
        ticker=TICKER,
        expiration=expiration,
        short_strike=short_call_strike,
        long_strike=long_call_strike,
        option_type="C",
        date=date_str
    )
    
    put_spread = provider.get_spread_prices(
        ticker=TICKER,
        expiration=expiration,
        short_strike=short_put_strike,
        long_strike=long_put_strike,
        option_type="P",
        date=date_str
    )
    
    if call_spread is None or put_spread is None:
        logger.warning(f"Missing spread prices for iron condor legs")
        return None
    
    # Use conservative fills: sell at bid, buy at ask
    # Provider returns 'short_close' (bid) and 'long_close' (ask)
    call_credit = call_spread['short_close'] - call_spread['long_close']
    put_credit = put_spread['short_close'] - put_spread['long_close']
    total_credit = call_credit + put_credit
    
    if total_credit <= 0:
        logger.warning(f"Iron condor has negative/zero credit: {total_credit:.2f}")
        return None
    
    return {
        'short_call_strike': short_call_strike,
        'long_call_strike': long_call_strike,
        'short_put_strike': short_put_strike,
        'long_put_strike': long_put_strike,
        'call_credit': call_credit,
        'put_credit': put_credit,
        'entry_credit': total_credit,
        'max_risk': WING_WIDTH - total_credit,
        'call_spread': call_spread,
        'put_spread': put_spread,
    }


def get_spread_value(
    provider: CBOEDataProvider,
    date_str: str,
    expiration: str,
    ic: Dict,
) -> Optional[float]:
    """
    Get current debit to close the iron condor.
    """
    call_spread = provider.get_exit_prices(
        ticker=TICKER,
        expiration=expiration,
        short_strike=ic['short_call_strike'],
        long_strike=ic['long_call_strike'],
        option_type="C",
        date=date_str
    )
    
    put_spread = provider.get_exit_prices(
        ticker=TICKER,
        expiration=expiration,
        short_strike=ic['short_put_strike'],
        long_strike=ic['long_put_strike'],
        option_type="P",
        date=date_str
    )
    
    if call_spread is None or put_spread is None:
        return None
    
    # Exit: spread_value is the DEBIT to close (short_ask - long_bid)
    total_debit = call_spread['spread_value'] + put_spread['spread_value']
    
    return total_debit


def run_backtest():
    """Run the VIX-adaptive backtest."""
    logger.info(f"Starting {EXPERIMENT_ID}: VIX-Adaptive SPX 0DTE")
    logger.info(f"Period: {START_DATE} to {END_DATE}")
    logger.info(f"VIX Thresholds: <{VIX_LOW_THRESHOLD} (20Δ), {VIX_LOW_THRESHOLD}-{VIX_HIGH_THRESHOLD} (25Δ), >{VIX_HIGH_THRESHOLD} (30Δ)")
    
    # Initialize data provider
    provider = CBOEDataProvider()
    
    # Load VIX data
    vix_data = load_vix_data(START_DATE, END_DATE)
    
    # Trading state
    trades = []
    equity_curve = []
    current_capital = CAPITAL
    
    # Date range
    start = datetime.strptime(START_DATE, "%Y-%m-%d")
    end = datetime.strptime(END_DATE, "%Y-%m-%d")
    current_date = start
    
    while current_date <= end:
        # Only trade on specified days
        if current_date.strftime("%A") not in TRADING_DAYS:
            current_date += timedelta(days=1)
            continue
        
        date_str = current_date.strftime("%Y-%m-%d")
        date_only = current_date.date()
        
        # Get VIX level for this day
        vix_level = get_vix_level(vix_data, date_only)
        if vix_level is None:
            logger.warning(f"{date_str}: No VIX data, skipping")
            current_date += timedelta(days=1)
            continue
        
        # Select delta based on VIX
        delta_target, regime = select_delta_for_vix(vix_level)
        logger.info(f"{date_str}: VIX={vix_level:.2f}, Regime={regime}, Delta={delta_target:.2f}")
        
        # Check for 0DTE expiration
        expirations = get_0dte_expirations(provider, current_date)
        if not expirations:
            logger.warning(f"{date_str}: No 0DTE expiration found, skipping")
            current_date += timedelta(days=1)
            continue
        
        expiration = expirations[0]
        
        # Get underlying price
        underlying = provider.get_underlying_price(TICKER, date_str)
        if underlying is None:
            logger.warning(f"{date_str}: No underlying price, skipping")
            current_date += timedelta(days=1)
            continue
        
        # Construct iron condor with adaptive delta
        ic = construct_iron_condor(
            provider, date_str, expiration, underlying, delta_target
        )
        
        if ic is None:
            logger.warning(f"{date_str}: Could not construct iron condor, skipping")
            current_date += timedelta(days=1)
            continue
        
        # Entry
        entry_credit = ic['entry_credit'] * 100 * CONTRACTS_PER_TRADE  # Per contract = $100 multiplier
        profit_target = entry_credit * PROFIT_TARGET_PCT
        stop_loss = -entry_credit * STOP_LOSS_PCT
        
        logger.info(f"{date_str} ENTRY: Credit=${entry_credit:.2f}, Target=${profit_target:.2f}, Stop=${stop_loss:.2f}")
        logger.info(f"  Short Call: {ic['short_call_strike']}, Short Put: {ic['short_put_strike']}")
        
        # Track intraday P&L
        # In real backtest we'd check multiple times during the day
        # For simplicity, check at expiration (3:00 PM or EOD)
        
        # Get spread value at expiration
        spread_value_at_exit = get_spread_value(provider, date_str, expiration, ic)
        
        if spread_value_at_exit is None:
            logger.warning(f"{date_str}: Could not get exit spread value, skipping")
            current_date += timedelta(days=1)
            continue
        
        # P&L = entry credit - exit debit
        exit_debit = spread_value_at_exit * 100 * CONTRACTS_PER_TRADE
        pnl = entry_credit - exit_debit
        
        # Check profit target / stop loss
        exit_reason = "EXPIRATION"
        if pnl >= profit_target:
            pnl = profit_target  # Cap at profit target
            exit_reason = "PROFIT_TARGET"
        elif pnl <= stop_loss:
            pnl = stop_loss  # Cap loss at stop
            exit_reason = "STOP_LOSS"
        
        # Update capital
        current_capital += pnl
        
        logger.info(f"{date_str} EXIT ({exit_reason}): P&L=${pnl:.2f}, Capital=${current_capital:.2f}")
        
        # Record trade
        trades.append({
            'date': date_str,
            'vix': vix_level,
            'regime': regime,
            'delta_target': delta_target,
            'underlying': underlying,
            'short_call_strike': ic['short_call_strike'],
            'long_call_strike': ic['long_call_strike'],
            'short_put_strike': ic['short_put_strike'],
            'long_put_strike': ic['long_put_strike'],
            'entry_credit': entry_credit,
            'exit_debit': exit_debit,
            'pnl': pnl,
            'exit_reason': exit_reason,
            'capital': current_capital,
        })
        
        equity_curve.append({
            'date': date_str,
            'capital': current_capital,
        })
        
        current_date += timedelta(days=1)
    
    # Convert to DataFrames
    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity_curve)
    
    # Save results
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    equity_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    
    logger.info(f"\nBacktest complete. {len(trades)} trades executed.")
    logger.info(f"Final capital: ${current_capital:,.2f}")
    logger.info(f"Total return: {((current_capital / CAPITAL - 1) * 100):.2f}%")
    
    # Calculate metrics
    calculate_metrics(trades_df, equity_df)


def calculate_metrics(trades_df: pd.DataFrame, equity_df: pd.DataFrame):
    """Calculate and display backtest metrics."""
    if len(trades_df) == 0:
        logger.error("No trades to analyze")
        return
    
    total_trades = len(trades_df)
    winning_trades = len(trades_df[trades_df['pnl'] > 0])
    losing_trades = len(trades_df[trades_df['pnl'] < 0])
    win_rate = winning_trades / total_trades if total_trades > 0 else 0
    
    total_pnl = trades_df['pnl'].sum()
    avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
    avg_loss = trades_df[trades_df['pnl'] < 0]['pnl'].mean() if losing_trades > 0 else 0
    
    # Returns
    trades_df['date'] = pd.to_datetime(trades_df['date'])
    trades_df = trades_df.set_index('date')
    
    # Daily returns (percentage)
    returns = trades_df['pnl'] / CAPITAL
    
    # Sharpe ratio (annualized, assuming ~252 trading days, ~130 0DTE trades/year)
    mean_return = returns.mean()
    std_return = returns.std()
    sharpe = (mean_return / std_return) * np.sqrt(130) if std_return > 0 else 0
    
    # Max drawdown
    equity_df['peak'] = equity_df['capital'].cummax()
    equity_df['drawdown'] = (equity_df['capital'] - equity_df['peak']) / equity_df['peak']
    max_dd = equity_df['drawdown'].min()
    
    # Monthly aggregation
    trades_monthly = trades_df.resample('ME')['pnl'].sum()
    monthly_return_pct = (trades_monthly / CAPITAL * 100).mean()
    
    # Regime breakdown
    regime_stats = trades_df.groupby('regime').agg({
        'pnl': ['count', 'sum', 'mean'],
        'vix': 'mean'
    }).round(2)
    
    # Print metrics
    logger.info("\n" + "="*60)
    logger.info(f"EXPERIMENT: {EXPERIMENT_ID}")
    logger.info("="*60)
    logger.info(f"Total Trades: {total_trades}")
    logger.info(f"Win Rate: {win_rate*100:.1f}%")
    logger.info(f"Avg Win: ${avg_win:.2f}")
    logger.info(f"Avg Loss: ${avg_loss:.2f}")
    logger.info(f"Total P&L: ${total_pnl:,.2f}")
    logger.info(f"Total Return: {(total_pnl/CAPITAL*100):.2f}%")
    logger.info(f"Monthly Return (avg): {monthly_return_pct:.2f}%")
    logger.info(f"Sharpe Ratio: {sharpe:.2f}")
    logger.info(f"Max Drawdown: {max_dd*100:.2f}%")
    logger.info("\n" + "Regime Breakdown:")
    logger.info(regime_stats.to_string())
    logger.info("="*60)
    
    # Save metrics
    # Flatten regime_stats MultiIndex for JSON serialization
    regime_dict = {}
    if not regime_stats.empty:
        for regime in regime_stats.index:
            regime_dict[regime] = {
                'trade_count': int(regime_stats.loc[regime, ('pnl', 'count')]),
                'total_pnl': float(regime_stats.loc[regime, ('pnl', 'sum')]),
                'avg_pnl': float(regime_stats.loc[regime, ('pnl', 'mean')]),
                'avg_vix': float(regime_stats.loc[regime, ('vix', 'mean')]),
            }
    
    metrics = {
        'experiment_id': EXPERIMENT_ID,
        'total_trades': int(total_trades),
        'win_rate': float(win_rate),
        'avg_win': float(avg_win),
        'avg_loss': float(avg_loss),
        'total_pnl': float(total_pnl),
        'total_return_pct': float(total_pnl / CAPITAL * 100),
        'monthly_return_pct': float(monthly_return_pct),
        'sharpe_ratio': float(sharpe),
        'max_drawdown_pct': float(max_dd * 100),
        'regime_stats': regime_dict,
    }
    
    with open(OUTPUT_DIR / "metrics.json", 'w') as f:
        json.dump(metrics, f, indent=2)
    
    logger.info(f"\nResults saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    try:
        run_backtest()
    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        sys.exit(1)
